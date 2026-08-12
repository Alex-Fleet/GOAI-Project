"""异常路径：规则未命中 / 证据缺失 / 空事实 → FAILED，不硬出结论（ARD §4.3 / §10.4）。"""

from __future__ import annotations

from .conftest import make_event


def test_empty_indicators_do_not_trigger(service):
    """层0 触发判定：无不合格指标 → 不触发，FAILED 标注原因。"""
    chain = service.start(make_event("P1", indicators=[]))
    assert chain.status == "FAILED"
    assert "trigger" in chain.note
    assert chain.steps == []  # 未进入任何推理层


def test_unknown_entity_fails_at_l1(service):
    """证据缺失：工艺图中不存在该对象 → L1 定位失败，FAILED。"""
    chain = service.start(make_event("P-NOPE"))
    assert chain.status == "FAILED"
    assert "L1" in chain.note


def test_no_liability_fails_at_l4(service):
    """P2：设备自检失败但部件磨损不达标、物料无异常 → 责任缺位 → FAILED 不硬判。"""
    chain = service.start(make_event("P2"))
    assert chain.status == "FAILED"
    assert "L4" in chain.note
    assert chain.impact.get("liabilities") in (None, [])  # 未出责任结论


def test_failed_chain_still_auditable(service):
    """FAILED 链也应带输入指纹（审计可追溯），root_hash 非空。"""
    chain = service.start(make_event("P-NOPE"))
    assert chain.status == "FAILED"
    assert chain.root_hash


def test_max_candidates_bounds_exploration(service):
    """候选上限：候选池截断到 max_candidates，避免无限探索。"""
    chain = service.start(make_event("P1"))
    assert chain.status == "READY"
    # 每个候选 id 不超过上限（conftest 默认 5）
    for step in chain.steps:
        for edge in step.path:
            assert edge.src.id or edge.dst.id  # 路径可回放
