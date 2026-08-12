"""Agent loop：7 步 pipeline 编排 + 每层「提议 → 把关」小循环（ARD §4.2 / §4.3）。

编排规则：
- 每层候选 = 确定性图遍历（layers）+（可选）LLM 提议（nlu.propose，P0 关闭）；
- 把关 = 推理核 verify（图验证 + 属性规则判定），通过才进 TraceChain；
- 候选耗尽 → 换判断点（L3 换下一个设备）→ 两路都无 → FAILED，不硬出结论；
- 审计横切：每层结论实时写哈希链，篡改即失效。
"""

from __future__ import annotations

import uuid
from typing import Any

from ..contracts import (
    EvidenceEvent,
    NodeRef,
    Proposal,
    TraceChain,
    TraceStep,
    Verdict,
)
from .infer import InferenceKernel, Rule
from .layers import (
    assess_impact,
    build_actions,
    evidence_of,
    explore_l1,
    explore_l3,
    explore_supplier,
)
from .nlu import NluSide


class Failure(Exception):
    """流程失败：无候选 / 证据缺失 / 规则未命中（ARD §4.3 → FAILED，不硬出结论）。"""

    def __init__(self, layer: str, reason: str):
        super().__init__(f"{layer}: {reason}")
        self.layer = layer
        self.reason = reason


class TracingLoop:
    """一次事故的 7 步推理链编排。"""

    def __init__(
        self,
        kernel: InferenceKernel,
        nlu: NluSide,
        graph,
        business,
        audit,
        layer_rules: dict[str, list[Rule]],
        max_candidates: int = 5,
    ):
        self._kernel = kernel
        self._nlu = nlu
        self._graph = graph
        self._business = business
        self._audit = audit
        self._rules = layer_rules
        self._max_candidates = max_candidates

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    def run(self, event: EvidenceEvent) -> TraceChain:
        chain = TraceChain(id=uuid.uuid4().hex, trigger=event)
        self._audit.begin(event)  # 输入指纹（哈希链锚点）
        if not event.failed_indicators:  # 层0 触发判定：无不合格指标不触发
            chain.status = "FAILED"
            chain.note = "trigger: 无不合格指标（不触发）"
            chain.root_hash = self._audit.root()
            return chain
        try:
            self._trace(chain, event)
            chain.status = "READY"
        except Failure as f:
            chain.status = "FAILED"
            chain.note = f"{f.layer}: {f.reason}"
        chain.root_hash = self._audit.root()
        return chain

    # ------------------------------------------------------------------
    # 7 步链
    # ------------------------------------------------------------------

    def _trace(self, chain: TraceChain, event: EvidenceEvent) -> None:
        # ---- 层1 工艺图定位 ----
        devices, materials, all_basis = explore_l1(event, self._graph)
        verdict_l1 = Verdict("locate_process_flow", len(devices), 1, ">=", bool(devices))
        self._commit(chain, TraceStep("L1", all_basis, verdict_l1, [event.raw_ref]))
        if not devices and not materials:
            raise Failure("L1", "工艺图未定位到该对象（无工序/设备/外购件）")

        # ---- 层2 判断点（排除法：设备路 + 物料路都溯）----
        eq_pool = self._verify_pool(devices, "L2", self._rules.get("L2_equipment", []))
        mat_pool = self._verify_pool(materials, "L2", self._rules.get("L2_material", []))
        for proposal, v in eq_pool:
            self._commit(chain, TraceStep("L2", proposal.basis, v, evidence_of(proposal.candidate)))
        for proposal, v in mat_pool:
            self._commit(chain, TraceStep("L2", proposal.basis, v, evidence_of(proposal.candidate)))
        if not eq_pool and not mat_pool:
            raise Failure("L2", "判断点无候选通过（设备自检与物料异常均未命中）")

        # ---- 层3 设备内部（换判断点：逐个设备下钻，第一个有通过部件的设备成交）----
        comp_pool: list[tuple[Proposal, Verdict]] = []
        for proposal, _v in eq_pool:
            comps = explore_l3(proposal.candidate, self._graph)
            pool = self._verify_pool(comps, "L3", self._rules.get("L3", []))
            if pool:
                comp_pool = pool
                cp, cv = pool[0]
                self._commit(chain, TraceStep("L3", cp.basis, cv, evidence_of(cp.candidate)))
                break  # 换判断点成功；其余设备不再深挖（二楼可扩展收集全部）
        # 物料方向无"内部"层：物料本身即判断对象，直接进层4责任

        # ---- 层4 责任归属（部件方向 + 物料方向 → 供应商 + 条款）----
        base_comp = comp_pool[0][0].candidate if comp_pool else None
        base_mat = mat_pool[0][0].candidate if mat_pool else None
        liabilities: list[NodeRef] = []
        for base, rel in ((base_comp, "SUPPLIED_BY"), (base_mat, "SUPPLIED_MATERIAL")):
            if base is None:
                continue
            sups = explore_supplier(base, rel, self._graph)
            for cand, v, _clause in self._l4_verify(sups):
                self._commit(chain, TraceStep("L4", cand.basis, v, evidence_of(cand.node)))
                liabilities.append(cand.node)
        if not liabilities:
            raise Failure("L4", "责任归属无候选通过（无供应商条款覆盖该故障）")

        # ---- 波及前推 ----
        chain.impact = assess_impact(liabilities, self._business, event)

        # ---- 处置建议 ----
        eq_node = eq_pool[0][0].candidate if eq_pool else None
        chain.actions = build_actions(eq_node, liabilities, chain.impact)

    # ------------------------------------------------------------------
    # 每层「提议 → 把关」小循环
    # ------------------------------------------------------------------

    def _verify_pool(
        self, candidates: list, layer: str, rules: list[Rule]
    ) -> list[tuple[Proposal, Verdict]]:
        """候选池逐一过把关（图验证 + 属性判定），返回通过的 (proposal, verdict)。"""
        passed: list[tuple[Proposal, Verdict]] = []
        for i, cand in enumerate(candidates[: self._max_candidates]):
            proposal = Proposal(
                id=f"{layer}-{i}",
                layer=layer,
                candidate=cand.node,
                hypothesis=f"{layer} 候选 {cand.node}",
                basis=cand.basis,
            )
            verdict = self._kernel.verify(proposal, rules)
            if verdict and verdict.passed:
                passed.append((proposal, verdict))
        return passed

    def _l4_verify(self, supplier_cands: list) -> list[tuple[Any, Verdict, NodeRef]]:
        """层4 专用把关：供应商可达（basis 真实）+ 条款规则命中（判定 Clause 节点）。"""
        clause_rules = self._rules.get("L4", [])
        out: list[tuple[Any, Verdict, NodeRef]] = []
        for cand in supplier_cands[: self._max_candidates]:
            if not self._kernel.validate_basis(cand.basis):
                continue
            clause = (
                cand.basis[-1].dst if cand.basis and cand.basis[-1].rel == "SUBJECT_TO" else None
            )
            if clause is None:
                continue  # 供应商无条款 → 责任不成立（不硬判）
            for rule in clause_rules:
                v = self._kernel.judge(clause, rule)
                if v.passed:
                    out.append((cand, v, clause))
                    break
        return out

    def _commit(self, chain: TraceChain, step: TraceStep) -> None:
        """结论实时三写：进链 + 审计哈希 + 人话解释（聊天窗流式）。"""
        chain.steps.append(step)
        self._audit.append(step)
        chain.narrative.append(self._nlu.explain(step))
