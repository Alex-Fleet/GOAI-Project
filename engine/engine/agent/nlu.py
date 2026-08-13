"""神经侧 LLM/VLM 三职责（ARD §4.1）：NLU 解析 / 探索提议 / 人话表达。

边界（ARD P1）：一切提议必须经推理核把关验证后才能进入 TraceChain；
LLM 不得直接产出决策结论；聊天窗输出必须引用推理核已产出的 TraceStep。

P0 阶段不接真实 LLM（D4 待启用）：propose 默认关闭，推理核用确定性候选枚举兜底；
explain 用模板把 TraceStep 转人话（供左栏聊天窗流式输出）。
"""

from __future__ import annotations

from ..contracts import EvidenceEvent, Proposal, TraceStep

_LAYER_LABELS = {
    "L1": "工艺图定位",
    "L2": "设备判断点",
    "L3": "设备内部",
    "L4": "责任归属",
    "impact": "波及前推",
}


class NluSide:
    """神经侧三职责实现。P0：parse 直接包装已结构化输入，propose 关闭，explain 模板。"""

    def __init__(self, propose_enabled: bool = False):
        self._propose_enabled = propose_enabled

    # ---- NLU：非结构化输入 → 结构化事实 ----

    def parse(self, raw: dict) -> EvidenceEvent:
        """P0：把（已结构化的）原始输入包装为 EvidenceEvent。

        真实 NLU（质检报告文本/图片/信号 → 事实）是接入适配器能力之一（ARD §4.1），
        二楼实例化时替换此方法，契约不变。
        """
        if not isinstance(raw, dict):
            raise TypeError(f"raw must be a dict, got {type(raw)!r}")
        missing = [k for k in ("entity_ref", "ts") if k not in raw]
        if missing:
            raise ValueError(f"raw 缺少必填字段: {missing}")
        return EvidenceEvent(
            entity_ref=str(raw["entity_ref"]),
            entity_type=str(raw.get("entity_type", "product")),
            ts=float(raw["ts"]),
            failed_indicators=list(raw.get("failed_indicators", [])),
            raw_ref=str(raw.get("raw_ref", "")),
        )

    # ---- 探索提议（P0 关闭）----

    def propose(
        self, layer: str, candidates_hint: list[Proposal] | None = None
    ) -> list[Proposal] | None:
        """LLM 看图提议下钻方向/候选。P0 未启用返回 None（推理核确定性探索兜底）。

        启用后：LLM 读图（候选的 basis）产出 Proposal(pending)，由推理核把关。
        """
        if not self._propose_enabled:
            return None
        return candidates_hint  # 占位：真实 LLM 调用在二楼实例化时接入

    # ---- 人话表达：把推理步骤说成人话（聊天窗流式）----

    def explain(self, step: TraceStep) -> str:
        """把一条已把关的 TraceStep 转人话。只引用推理核已产出的内容，不编造。"""
        layer = _LAYER_LABELS.get(step.layer, step.layer)
        verdict = step.verdict
        head = f"【{layer}】"
        if verdict is None:
            return f"{head}完成定位（图遍历 {len(step.path)} 步）。"
        if isinstance(verdict.observed, bool):
            obs = "是" if verdict.observed else "否"
            thr = "是" if verdict.threshold else "否"
        else:
            obs, thr = verdict.observed, verdict.threshold
        mark = "通过" if verdict.passed else "未通过"
        return f"{head}判定规则 `{verdict.rule_id}`：observed={obs}，threshold={thr}，{mark}。"

    def explain_retrieval(self, event: EvidenceEvent, refs: list) -> str:
        """层1 检索兜底的人话：图遍历定位不到 → 知识检索定位到候选（只报事实，不编造）。"""
        names = "、".join(f"{r.label} {r.id}" for r in refs)
        return f"【工艺图定位】图遍历未定位到对象 {event.entity_ref!r}，知识检索兜底命中候选：{names}。"
