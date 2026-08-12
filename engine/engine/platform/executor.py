"""执行层：人确认后的动作落库（ARD §5 / §6.2）。

职责边界（防膨胀）：不自主决策——只执行已被标记 approved 的动作；
决策在 Agent（建议）+ 人（确认）。执行结果写回业务层，可追溯。
"""

from __future__ import annotations

from ..contracts import Action, BusinessStore, ExecutionReport


class Executor:
    """把「人已确认」的处置动作落库到业务层，产出执行报告。"""

    def __init__(self, business: BusinessStore):
        self._business = business

    def execute(self, chain_id: str, actions: list[Action]) -> ExecutionReport:
        applied: list[Action] = []
        failed: list[Action] = []
        for a in actions:
            if not a.approved:  # 未经确认的动作一律不执行（防御）
                failed.append(a)
                continue
            result = self._business.apply([a])[0]
            if result.ok:
                a.result = result.message
                applied.append(a)
            else:
                failed.append(a)
        summary = f"{len(applied)} applied, {len(failed)} failed"
        return ExecutionReport(chain_id, applied, failed, summary)
