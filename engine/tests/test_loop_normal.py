"""正常路径：一次事故 7 步链全走通（ARD §10.4 模拟事实测试集-正常）。"""

from __future__ import annotations

from .conftest import make_event


def test_normal_chain_reaches_ready(service):
    """P1：设备自检失败 → 部件磨损命中 → 供应商条款覆盖 → READY。"""
    chain = service.start(make_event("P1"))
    assert chain.status == "READY"
    assert chain.note == ""

    layers = [s.layer for s in chain.steps]
    assert "L1" in layers and "L2" in layers and "L3" in layers and "L4" in layers

    # 每层结论 = 决策三件套：路径（可回放）+ 判定 + 依据
    for step in chain.steps:
        assert step.path, f"{step.layer} 缺少路径"
        assert step.verdict is not None, f"{step.layer} 缺少判定"
        assert step.evidence_refs, f"{step.layer} 缺少依据引用"


def test_liability_and_impact(service):
    chain = service.start(make_event("P1"))
    # 责任方：SUP-A（部件供应商，条款 CL-1 覆盖）
    assert chain.impact["liabilities"] == ["SUP-A"]
    # 波及：contract-1 关联的成品与订单
    assert chain.impact["affected_products"] == ["P-1", "P-2"]
    assert chain.impact["orders"] == ["ORD-1"]
    assert chain.impact["contracts"] == ["contract-1"]


def test_disposal_actions(service):
    """处置建议：冻结波及批次 + 停机检修设备 + 向责任供应商索赔。"""
    chain = service.start(make_event("P1"))
    types = {a.action_type for a in chain.actions}
    assert {"freeze", "halt", "claim"} <= types
    claim = next(a for a in chain.actions if a.action_type == "claim")
    assert claim.target_ref == "SUP-A"
    # 未经确认：approved 应为 False
    assert all(a.approved is False for a in chain.actions)


def test_narrative_is_human_readable(service):
    """聊天窗流式内容 = 每步人话解释，引用推理核已产出的判定。"""
    chain = service.start(make_event("P1"))
    assert len(chain.narrative) == len(chain.steps)
    for text in chain.narrative:
        assert text.strip(), "narrative 出现空串"
    # L1 是定位，其余层是规则判定
    assert any("判定规则" in t for t in chain.narrative)


def test_exclusion_both_ways(service):
    """排除法：设备路与物料路都评估——本案例设备自检失败成立、物料无异常。"""
    chain = service.start(make_event("P1"))
    l2_steps = [s for s in chain.steps if s.layer == "L2"]
    assert l2_steps, "L2 应有判断点结论"
    # 设备路成立（self_check_failed=True）
    assert any(s.verdict and s.verdict.rule_id == "equipment_self_check" for s in l2_steps)
    # 物料路未成立（anomaly=False）→ 不产生物料方向的 L2 结论
    assert all(not (s.verdict and s.verdict.rule_id == "material_anomaly") for s in l2_steps)
