"""服务层：TracingService——对外 API 的聚合器（ARD §6.2）。

职责边界：唯一对外入口，聚合 Agent（loop）+ 平台（业务/执行/审计）；
不包含推理逻辑（推理在 Agent 层），不直接触碰平台内部。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from ..agent.loop import TracingLoop
from ..agent.nlu import NluSide
from ..contracts import (
    EvidenceEvent,
    ExecutionReport,
    TraceChain,
)


def to_dict(obj: Any) -> Any:
    """递归把契约数据类序列化为纯 dict（供 JSON / SSE）。"""
    if is_dataclass(obj):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


class TracingService:
    """对外聚合器：start / list_events / confirm。"""

    def __init__(self, loop: TracingLoop, nlu: NluSide, executor, audit):
        self._loop = loop
        self._nlu = nlu
        self._executor = executor
        self._audit = audit
        self._events: list[EvidenceEvent] = []
        self._chains: dict[str, TraceChain] = {}

    # ---- 事故处理 ----

    def start(self, event: EvidenceEvent) -> TraceChain:
        """新事故：跑完整 7 步链，返回 TraceChain（含逐层结论 + 哈希根指纹）。"""
        chain = self._loop.run(event)
        self._events.append(event)
        self._chains[chain.id] = chain
        return chain

    def list_events(self) -> list[EvidenceEvent]:
        return list(self._events)

    def get_chain(self, chain_id: str) -> TraceChain:
        if chain_id not in self._chains:
            raise KeyError(f"未知事故链: {chain_id}")
        return self._chains[chain_id]

    def confirm(self, chain_id: str, action_ids: list[str]) -> ExecutionReport:
        """人确认处置动作 → 执行层落库（不确认的动作不执行）。"""
        chain = self.get_chain(chain_id)
        if chain.status != "READY":
            raise ValueError(f"当前状态 {chain.status} 不允许确认（须为 READY）")
        selected = [a for a in chain.actions if a.id in action_ids]
        unknown = set(action_ids) - {a.id for a in chain.actions}
        if unknown:
            raise ValueError(f"未知动作 id: {sorted(unknown)}")
        for a in selected:
            a.approved = True
        report = self._executor.execute(chain_id, selected)
        chain.status = "EXECUTED"
        return report

    def verify_chain(self, chain: TraceChain) -> bool:
        """独立重算校验哈希链（可回放、防篡改）。"""
        return self._audit.verify(chain.root_hash)
