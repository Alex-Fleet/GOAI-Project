"""符号侧推理核 = 裁判（ARD §4.2 / P1：AI proposes, Logic disposes）。

裁判职责：
  1. 沿图验证——LLM 提议的依据轨迹（basis）必须真实存在于图上（防编理由）；
  2. 属性判定——对候选节点应用知识层规则（读属性 + 操作符比较）。

推理核不知道任何行业/设备知识，只消费 GraphStore 契约与规则集。
P0 阶段候选由确定性图遍历生成（layers.py），LLM 提议启用后同样走本裁判。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contracts import EdgeRef, GraphStore, NodeRef, Proposal, Verdict


@dataclass
class Rule:
    """属性规则（知识层）：对 node_label 节点读 attr，与 threshold 按 operator 比较。"""

    rule_id: str
    node_label: str
    attr: str
    operator: str  # >= | <= | > | < | == | != | contains | in
    threshold: Any

    def __post_init__(self) -> None:
        if self.operator not in RuleEngine.OPERATORS:
            raise ValueError(f"未知操作符 {self.operator!r}，允许: {sorted(RuleEngine.OPERATORS)}")


class RuleEngine:
    """属性规则判定（读节点属性 + 操作符比较）。"""

    OPERATORS = {">=", "<=", ">", "<", "==", "!=", "contains", "in"}

    def judge(self, node: NodeRef, rule: Rule) -> Verdict:
        observed = node.props.get(rule.attr)
        passed = self._compare(observed, rule.operator, rule.threshold)
        return Verdict(rule.rule_id, observed, rule.threshold, rule.operator, passed)

    def _compare(self, observed: Any, op: str, threshold: Any) -> bool:
        try:
            if op == ">=":
                return observed >= threshold
            if op == "<=":
                return observed <= threshold
            if op == ">":
                return observed > threshold
            if op == "<":
                return observed < threshold
            if op == "==":
                return observed == threshold
            if op == "!=":
                return observed != threshold
            if op == "contains":
                return threshold in observed
            if op == "in":
                return observed in threshold
        except (TypeError, ValueError):
            return False  # 属性缺失（None）或类型不匹配 → 不通过 → 换候选/FAILED
        return False


class InferenceKernel:
    """推理核：沿图验证 + 属性判定。"""

    def __init__(self, graph: GraphStore, rules: list[Rule] | None = None):
        self._graph = graph
        self._rules = list(rules or [])
        self._engine = RuleEngine()

    def verify(self, proposal: Proposal, rules: list[Rule] | None = None) -> Verdict | None:
        """把关一个提议。通过：proposal.status=verified 并返回末条通过 Verdict；否则 rejected 返回 None。"""
        # 1. 沿图验证：依据轨迹必须真实（防 LLM 编理由）
        if not self._validate_basis(proposal.basis):
            proposal.status = "rejected"
            return None
        # 2. 属性判定：候选 label 匹配的规则全部通过才算 verified
        applied = rules if rules is not None else self._match_rules(proposal.candidate)
        if not applied:
            # 无规则可判定：仅凭图可达不足以成结论 → 不通过（避免硬出结论）
            proposal.status = "rejected"
            return None
        last: Verdict | None = None
        for rule in applied:
            last = self._engine.judge(proposal.candidate, rule)
            if not last.passed:
                proposal.status = "rejected"
                proposal.verdict = last
                return last  # 返回未通过的判定（供审计/解释）
        proposal.status = "verified"
        proposal.verdict = last
        return last

    # ---- 供层逻辑使用的公开原语 ----

    def judge(self, node: NodeRef, rule: Rule) -> Verdict:
        """对单个节点应用规则（层逻辑自管判定对象时用，如条款判定）。"""
        return self._engine.judge(node, rule)

    def validate_basis(self, basis: list[EdgeRef]) -> bool:
        """公开的沿图验证：依据轨迹是否真实存在于图上。"""
        return self._validate_basis(basis)

    # ---- 内部 ----

    def _match_rules(self, node: NodeRef) -> list[Rule]:
        return [r for r in self._rules if r.node_label == node.label]

    def _validate_basis(self, basis: list[EdgeRef]) -> bool:
        """逐边验证 basis 在图上真实存在。空 basis 视为无依据 → 不通过。"""
        if not basis:
            return False
        for e in basis:
            found = self._graph.query(e.src, e.rel, "forward")
            if not any(ed.dst == e.dst for ed in found):
                return False
        return True
