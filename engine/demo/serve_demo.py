"""GOAI Demo 服务：三事故溯源演示（真实 CiP-DMD 数据 + 真实推理链 + 归因）。

组装：
- 一楼 TracingLoop 跑检测链（L1 定位 → L2 盲推检出 → L3 部件 → L4 责任）
- 二楼 Attributor 跑归因（空切/过载 → 候选原因 → 证据排除 → 锁定根因）
- 真实样本数据（SampleLoader）喂信号/质检/来料重量

API：
- GET  /samples        → demo 三事故样本元信息
- POST /start          → {part_id} 跑完整链（检测 + 归因），返回 TraceChain
- GET  /chains/{id}    → 推理链
- GET  /stream/{id}    → SSE 人话叙事（聊天窗）

用法：python -m demo.serve_demo  （默认 8800；CIPDMD_DATA 指定数据目录）
"""

from __future__ import annotations

import json
import time
import uuid

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from engine import (
    InferenceKernel,
    NluSide,
    Rule,
    SQLiteAudit,
    SQLiteBusinessStore,
    TracingLoop,
    TracingService,
)
from engine.contracts import EvidenceEvent, NodeRef, TraceStep, Verdict
from engine.service.tracing import to_dict

from . import tbox
from .attribution import Attributor, SignalStats
from .data_loader import SampleLoader
from .kb_build import build_graph, set_equipment_signal, set_material_weight
from .llm_service import LLMService

# 根因 → 责任链（归属供应商 + 条款）
ROOT_CAUSE_LIABILITY = {
    "material_short": ("RM1", "SUPPLIED_MATERIAL", "SUP-B", "CL-2"),
    "clamping_error": ("SP1", "SUPPLIED_BY", "SUP-A", "CL-1"),
}

# 一楼检测链规则（二楼实例化）
LAYER_RULES = {
    "L2_equipment": [Rule("face_milling_anomalous", "Equipment", "face_milling_anomalous", "==", True)],
    "L2_material": [Rule("material_anomaly", "Material", "anomaly", "==", True)],
    "L3": [Rule("component_wear", "Component", "wear_level", ">=", 2.8)],
    "L4": [Rule("clause_covers", "Clause", "covers", "==", True)],
}

DEMO_NAMES = {
    "1": "来料缺陷事故",
    "2": "设备夹持事故",
    "3": "杂项异常事故",
}


class DemoServe:
    """组装完整 demo 服务。"""

    def __init__(self, data_dir: str = "/tmp/cipdmd"):
        self.graph = build_graph(":memory:")
        self.loader = SampleLoader(data_dir)
        self._llm = LLMService()
        self._build_loop()
        self._attributors: dict[str, Attributor] = {}

    def _build_loop(self) -> None:
        business = SQLiteBusinessStore(":memory:")
        business.upsert("contract-1", "contract", {"supplier": "SUP-A", "orders": ["ORD-1"], "products": ["P-1"]})
        business.upsert("contract-2", "contract", {"supplier": "SUP-B", "orders": ["ORD-2"], "products": ["P-1"]})
        self._business = business
        audit = SQLiteAudit(":memory:")
        nlu = NluSide()
        kernel = InferenceKernel(self.graph, rules=[])
        # max_candidates 放宽：深度本体下 DMC-50H 直接子部件 6 个（5 子系统 + 轴承 SP1），
        # 默认 5 会截断排第 6 的 SP1。L3 需对所有部件判定。
        loop = TracingLoop(kernel, nlu, self.graph, business, audit, LAYER_RULES, max_candidates=20)
        self._service = TracingService(loop, nlu, _NoopExecutor(), audit)

    # ---- 样本 ----

    def samples_meta(self) -> list[dict]:
        """demo 三事故样本元信息（供前端事故选择）。"""
        out = []
        for s in self.loader.pick_demo_samples():
            sig = s["signal"]
            w = s["saw_weight"]
            official = {"0": "正常", "1": "来料短", "2": "夹持", "3": "杂项"}.get(s["official_anomaly"], "?")
            symptom = tbox.classify_signal(sig.curr6_mean, sig.load6_mean, sig.curr6_peak) if sig else "?"
            out.append({
                "part_id": s["part_id"],
                "official_anomaly": s["official_anomaly"],
                "official_name": official,
                "surface_roughness": float(s["quality"].get("surface_roughness", 0) or 0),
                "saw_weight": w,
                "signal": {"curr6_mean": sig.curr6_mean, "load6_mean": sig.load6_mean, "curr6_peak": sig.curr6_peak} if sig else None,
                "symptom": symptom,
            })
        return out

    # ---- 推理 ----

    def run_accident(self, part_id: str, use_llm: bool = True) -> dict:
        """跑一个事故：检测链 + 归因，返回 TraceChain dict。

        use_llm=False：跳过 LLM 提议/人话（批量分析用确定性快速归因）。
        """
        sample = self.loader.full_sample(part_id)
        sig = sample["signal"]
        w = sample["saw_weight"]
        if sig is None:
            return {"error": f"样本 {part_id} 无工艺信号数据"}
        symptom = tbox.classify_signal(sig.curr6_mean, sig.load6_mean, sig.curr6_peak)
        anomalous = symptom != tbox.SYMPTOM_NORMAL
        # 真实观测写图（ABox 个体断言）
        set_equipment_signal(self.graph, sig, anomalous, symptom)
        below = bool(w is not None and w < tbox.MATERIAL_WEIGHT_BASELINE)
        set_material_weight(self.graph, w if w is not None else 0.569, below)

        # 一楼检测链
        event = EvidenceEvent(
            entity_ref="P1", entity_type="part", ts=0,
            failed_indicators=["surface_roughness"],
            raw_ref=f"cip-dmd://cylinder_bottom/{part_id}",
        )
        chain = self._service.start(event)

        # 二楼归因：LLM 提议候选（图约束）+ ABox 证据排除
        attributor = Attributor(material_weight=w if w is not None else 0.569)
        allowed = tbox.SYMPTOM_CAUSES.get(symptom, [])
        signal_desc = f"端面铣削电流均值 {sig.curr6_mean:.2f}（正常 1.49~3.39），负载 {sig.load6_mean:.2f}，峰值 {sig.curr6_peak:.1f}"
        if use_llm and self._llm.enabled and allowed:
            allowed = self._llm.propose_causes(
                tbox.SYMPTOM_NAMES.get(symptom, symptom), signal_desc, allowed
            )
        res = attributor.attribute(part_id, sig, candidates=allowed)
        self._attach_attribution(chain, res, sample, sig, use_llm=use_llm)
        # 状态跟随一楼推理核：检出且归因锁定 → READY；无法归因 → 保留 FAILED（诚实边界）
        return to_dict(chain)

    # ---- 批量分析 ----

    def pick_batch(self, per_type: int = 3) -> list[str]:
        """挑一批混合样本：异常类型挑质检不合格件（SR>2.5）+ 正常挑合格件。"""
        out = []
        for a in ["1", "2", "3"]:
            picked = []
            for pid in self.loader.sample_ids(a):
                if len(picked) >= per_type:
                    break
                s = self.loader.full_sample(pid)
                sr = float(s["quality"].get("surface_roughness", 0) or 0)
                if sr > 2.5 and s["signal"] is not None:
                    picked.append(pid)
            out.extend(picked)
        # 正常对照（合格件）
        picked = []
        for pid in self.loader.sample_ids("0"):
            if len(picked) >= 3:
                break
            s = self.loader.full_sample(pid)
            sr = float(s["quality"].get("surface_roughness", 0) or 0)
            if sr <= 2.5 and s["signal"] is not None:
                picked.append(pid)
        out.extend(picked)
        return out

    def analyze_batch(self, part_ids: list[str] | None = None, all_samples: bool = False) -> list[dict]:
        """批量分析：哪些不合格（质检 SR 超标）→ 什么问题（归因）→ 追责谁。

        all_samples=True：分析全部质检不合格异常样本 + 正常对照（展示系统从大批数据归因）。
        """
        if all_samples:
            part_ids = []
            for a in ["1", "2", "3"]:
                for pid in self.loader.sample_ids(a):
                    s = self.loader.full_sample(pid)
                    sr = float(s["quality"].get("surface_roughness", 0) or 0)
                    if sr > 2.5 and s["signal"] is not None:
                        part_ids.append(pid)
            n = 0
            for pid in self.loader.sample_ids("0"):
                if n >= 10:
                    break
                s = self.loader.full_sample(pid)
                sr = float(s["quality"].get("surface_roughness", 0) or 0)
                if sr <= 2.5 and s["signal"] is not None:
                    part_ids.append(pid)
                    n += 1
        elif not part_ids:
            part_ids = self.pick_batch()
        rows = []
        for pid in part_ids:
            sample = self.loader.full_sample(pid)
            sr = float(sample["quality"].get("surface_roughness", 0) or 0)
            if sr <= 2.5:  # 质检合格 → 不触发事故
                rows.append({
                    "part_id": pid,
                    "official_anomaly": sample["official_anomaly"],
                    "official_name": sample["official_anomaly"],
                    "surface_roughness": sr, "symptom": "normal",
                    "locked": None, "liability": [], "status": "PASS",
                })
                continue
            sig = sample["signal"]
            if sig is None:
                rows.append({
                    "part_id": pid,
                    "official_anomaly": sample["official_anomaly"],
                    "official_name": sample["official_anomaly"],
                    "surface_roughness": sr, "symptom": "无信号",
                    "locked": None, "liability": [], "status": "NO_DATA",
                })
                continue
            chain = self.run_accident(pid, use_llm=False)
            rows.append(self._summarize(chain, sample))
        return rows

    @staticmethod
    def _summarize(chain: dict, sample: dict) -> dict:
        """从完整链提取批量汇总行。"""
        attr = next((s for s in chain.get("steps", []) if s["layer"] == "L2-attribution"), None)
        v = attr["verdict"] if attr else None
        locked = str(v["threshold"]) if v and v["passed"] else None
        names = {"material_short": "来料尺寸不足", "clamping_error": "工件夹持不平"}
        sr = sample["quality"].get("surface_roughness")
        return {
            "part_id": sample["part_id"],
            "official_anomaly": sample["official_anomaly"],
            "official_name": sample["official_anomaly"],
            "surface_roughness": float(sr) if sr else None,
            "symptom": v["observed"] if v else "normal",
            "locked": names.get(locked, locked) if locked else None,
            "liability": list(chain.get("impact", {}).get("liabilities", [])),
            "status": chain.get("status", ""),
            "chain_id": chain.get("id", ""),
        }

    def _attach_attribution(self, chain, res, sample, sig: SignalStats, use_llm: bool = True) -> None:
        """归因结论挂链 + 根因责任修正 + 人话叙事（LLM 增强，失败/批量用模板兜底）。"""
        locked = res.locked
        v = Verdict(
            rule_id="attribute_root_cause",
            observed=res.symptom,
            threshold=locked or "unresolved",
            operator="==",
            passed=locked is not None,
        )
        chain.steps.append(TraceStep("L2-attribution", [], v, [f"cip-dmd://cylinder_bottom/{sample['part_id']}"]))
        # 归因人话
        sr = float(sample["quality"].get("surface_roughness", 0) or 0)
        w = sample["saw_weight"]
        lo_c, hi_c = tbox.CURR6_WINDOW
        lines = [f"【归因】质检表面粗糙度 {sr:.2f}（上限 2.5）触发，下钻 DMC-50H 端面铣削信号。"]
        if res.symptom != tbox.SYMPTOM_NORMAL:
            lines.append(
                f"信号判据：电流均值 {sig.curr6_mean:.2f}（正常窗口 {lo_c:.2f}~{hi_c:.2f}），"
                f"判定为{tbox.SYMPTOM_NAMES[res.symptom]}。"
            )
            lines.append(f"候选原因：{'、'.join(tbox.FAULT_NAMES[c] for c in res.candidates)}。")
            for f, why in res.excluded.items():
                lines.append(f"排除 {tbox.FAULT_NAMES[f]}：{why}。")
            if locked:
                lines.append(f"证据排除后锁定根因：{tbox.FAULT_NAMES[locked]}。")
                if locked == "material_short" and w is not None:
                    lines.append(
                        f"来料锯切重量 {w:.3f} kg，质检合格线内（≥0.495）但明显低于正常基线（0.569）"
                        f"——质检盲区，靠工艺信号暴露。"
                    )
                # 根因责任修正：责任跟随根因
                self._attach_root_liability(chain, locked, lines)
            else:
                lines.append("所有候选证据均不充分——不硬出结论。")
        else:
            lines.append("工艺信号在正常窗口内，未检出加工异常——无法归因，不硬出结论。")
        template_text = "".join(lines)
        if use_llm and self._llm.enabled:
            context = "\n".join([
                f"质检触发：气缸底 {sample['part_id']} 表面粗糙度 {sr:.2f}（上限 2.5）",
                f"工艺信号：端面铣削电流均值 {sig.curr6_mean:.2f}（正常 1.49~3.39），判定为{tbox.SYMPTOM_NAMES.get(res.symptom, res.symptom)}",
                f"候选根因：{'、'.join(tbox.FAULT_NAMES.get(c, c) for c in res.candidates)}",
                f"证据排除：{('；'.join(f'{tbox.FAULT_NAMES.get(f, f)}：{why}' for f, why in res.excluded.items())) or '无'}",
                f"锁定根因：{tbox.FAULT_NAMES.get(locked, '无法归因') if locked else '无法归因'}",
                f"责任方：{chain.impact.get('liabilities', [])}",
                f"来料证据：锯切重量 {w:.3f} kg（质检合格线内 0.495~0.641，正常基线 0.569）" if w else "来料证据：无",
            ])
            llm_text = self._llm.explain(context)
            if llm_text:
                chain.narrative.append(llm_text)
                return
        chain.narrative.append(template_text)

    def _attach_root_liability(self, chain, locked, lines) -> None:
        """根因 → 责任供应商 + 条款（沿图验证），重定向 impact/actions。"""
        spec = ROOT_CAUSE_LIABILITY.get(locked)
        if spec is None:
            return
        base_id, rel, supplier_id, clause_id = spec
        # 沿图找供应商 + 条款，验证条款覆盖
        base = self.graph.get_node(NodeRef("Component" if base_id == "SP1" else "Material", base_id))
        if base is None:
            return
        for se in self.graph.query(base, rel, "forward"):
            if se.dst.id != supplier_id:
                continue
            for ce in self.graph.query(se.dst, "SUBJECT_TO", "forward"):
                if ce.dst.id != clause_id:
                    continue
                clause = self.graph.get_node(ce.dst)
                covers = clause.props.get("covers", False)
                verdict = Verdict("clause_covers", covers, True, "==", bool(covers))
                chain.steps.append(
                    TraceStep("L4-root-cause", [se, ce], verdict, [f"graph://Supplier/{supplier_id}"])
                )
                lines.append(f"根因责任：沿供应关系定位到 {supplier_id}，条款 {clause_id} 覆盖索赔。")
                # 重定向 impact/actions 到根因供应商
                from engine.agent.layers import assess_impact
                from engine.contracts import Action

                supplier_node = NodeRef("Supplier", supplier_id)
                chain.impact = assess_impact([supplier_node], self._business, chain.trigger)
                chain.actions = [
                    Action(
                        id=f"a-{uuid.uuid4().hex[:8]}",
                        action_type="freeze",
                        target_ref="P-1",
                        description="冻结受影响批次/产品 P-1",
                    ),
                    Action(
                        id=f"a-{uuid.uuid4().hex[:8]}",
                        action_type="claim",
                        target_ref=supplier_id,
                        description=f"依据条款 {clause_id} 向供应商 {supplier_id} 索赔",
                    ),
                ]
                # 业务闭环：违约金测算（供应商 → 合同(违约金率) → 订单(金额)）
                penalty = self._calc_penalty(supplier_id)
                if penalty is not None:
                    chain.impact["penalty"] = penalty
                    lines.append(
                        f"违约金测算：依据合同 {penalty['contract']}（违约金率 {penalty['rate']}），"
                        f"订单金额 {penalty['amount']:.0f} 元 → 追偿 {penalty['value']:.0f} 元。"
                    )
                chain.impact["root_hash"] = chain.root_hash
                return

    def _calc_penalty(self, supplier_id: str) -> dict | None:
        """违约金 = 合同违约金率 × 订单金额（沿业务层本体：Supplier→Contract→PurchaseOrder）。"""
        supplier = NodeRef("Supplier", supplier_id)
        for hc in self.graph.query(supplier, "HAS_CONTRACT", "forward"):
            ct = self.graph.get_node(hc.dst)
            if ct is None:
                continue
            rate = float(ct.props.get("penalty_rate", 0) or 0)
            for co in self.graph.query(hc.dst, "COVERS_ORDER", "forward"):
                od = self.graph.get_node(co.dst)
                if od is None:
                    continue
                amount = float(od.props.get("amount", 0) or 0)
                return {
                    "supplier": supplier_id,
                    "contract": hc.dst.id,
                    "rate": rate,
                    "amount": amount,
                    "value": round(amount * rate, 2),
                }
        return None


class _NoopExecutor:
    """demo 不真实执行处置，占位（返回空执行报告，符合一楼契约）。"""

    def execute(self, chain_id: str, actions):
        from engine.contracts import ExecutionReport

        applied = [a for a in actions if a.approved]
        return ExecutionReport(
            chain_id=chain_id,
            applied=applied,
            failed=[],
            summary=f"demo 沙盘：已执行 {len(applied)} 条处置动作",
        )


def build_app(data_dir: str = "/tmp/cipdmd") -> FastAPI:
    serve = DemoServe(data_dir)

    app = FastAPI(title="GOAI 分层溯源 Demo", version="0.2.1")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/samples")
    def samples() -> list[dict]:
        return serve.samples_meta()

    @app.get("/ontology")
    def ontology() -> dict:
        from .kb_build import export_ontology

        return export_ontology()

    @app.post("/analyze_batch")
    def analyze_batch(payload: dict) -> list[dict]:
        part_ids = payload.get("part_ids") or None
        all_samples = bool(payload.get("all", False))
        return serve.analyze_batch(part_ids, all_samples=all_samples)

    @app.post("/start")
    def start(payload: dict) -> dict:
        part_id = str(payload.get("part_id", ""))
        if not part_id:
            return {"error": "缺少 part_id"}
        return serve.run_accident(part_id, use_llm=bool(payload.get("use_llm", True)))

    @app.post("/chat")
    def chat(payload: dict) -> dict:
        """Agent 对话框问答（LLM 基于系统知识回答）。"""
        question = str(payload.get("question", "")).strip()
        if not question:
            return {"error": "缺少问题"}
        if not serve._llm.enabled:
            return {"error": "未配置 DEEPSEEK_API_KEY，问答不可用"}
        context = (
            "你是 GOAI 跨层溯源 Agent 的问答助手。系统对 CiP-DMD 气动缸气缸底制造数据做跨层溯源："
            "质检触发（表面粗糙度）→ 工艺图定位 → 设备盲推（端面铣削电流/负载信号）→ 归因（候选根因排除）"
            "→ 责任（供应商/合同/违约金）。回答要专业、简洁、基于工业常识与系统机制，不确定时明说。"
        )
        answer = serve._llm.ask(question, context)
        if answer is None:
            return {"error": "问答失败"}
        return {"answer": answer}

    @app.post("/nlu_parse")
    def nlu_parse(payload: dict) -> dict:
        """NLU：DeepSeek 把自然语言事故报告解析为结构化事件。"""
        text = str(payload.get("text", "")).strip()
        if not text:
            return {"error": "缺少事故报告文本"}
        if not serve._llm.enabled:
            return {"error": "未配置 DEEPSEEK_API_KEY，NLU 解析不可用"}
        parsed = serve._llm.parse_accident(text)
        if parsed is None:
            return {"error": "NLU 解析失败"}
        return parsed

    @app.get("/chains/{chain_id}")
    def get_chain(chain_id: str) -> dict:
        try:
            return to_dict(serve._service.get_chain(chain_id))
        except KeyError:
            return {"error": "未知事故链"}

    @app.post("/confirm")
    def confirm(payload: dict) -> dict:
        chain_id = str(payload.get("chain_id", ""))
        action_ids = list(payload.get("action_ids", []))
        try:
            report = serve._service.confirm(chain_id, action_ids)
            return to_dict(report)
        except (KeyError, ValueError) as e:
            return {"error": str(e)}

    @app.get("/stream/{chain_id}")
    def stream(chain_id: str) -> StreamingResponse:
        try:
            chain = serve._service.get_chain(chain_id)
        except KeyError as e:
            return StreamingResponse(json.dumps({"error": str(e)}), media_type="application/json")

        def gen():
            for text in chain.narrative:
                payload = json.dumps({"type": "narrative", "text": text}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                time.sleep(0.05)
            payload = json.dumps({"type": "done", "status": chain.status}, ensure_ascii=False)
            yield f"data: {payload}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8800)
