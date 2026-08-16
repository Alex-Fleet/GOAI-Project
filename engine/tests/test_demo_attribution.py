"""二楼 demo 层测试：归因器 + 知识建图（不依赖真实数据文件）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demo.attribution import Attributor, SignalStats
from demo.kb_build import build_graph, chunk_knowledge
from engine.contracts import NodeRef


def test_attribution_aircut_material_short():
    """空切 + 来料偏轻 → 锁定来料尺寸不足（demo 主线）。"""
    sig = SignalStats(curr6_mean=0.07, load6_mean=1.84, curr6_peak=5.3)
    res = Attributor(material_weight=0.5385).attribute("111501", sig)
    assert res.symptom == "air_cut"
    assert res.locked == "material_short"
    assert res.is_anomaly


def test_attribution_overload_clamping():
    """过载 + 来料在合格线内 → 排除来料过大 → 锁定夹持。"""
    sig = SignalStats(curr6_mean=4.30, load6_mean=6.20, curr6_peak=18.5)
    res = Attributor(material_weight=0.6212).attribute("114402", sig)
    assert res.symptom == "overload"
    assert res.locked == "clamping_error"


def test_attribution_normal_no_lock():
    """工艺信号正常 → 不判异常、不归因。"""
    sig = SignalStats(curr6_mean=2.44, load6_mean=4.13, curr6_peak=9.0)
    res = Attributor(material_weight=0.569).attribute("100101", sig)
    assert res.symptom == "normal"
    assert res.locked is None
    assert not res.is_anomaly


def test_attribution_aircut_normal_weight_unresolved():
    """空切但来料重量正常 → 无法归因（不硬出结论）。"""
    sig = SignalStats(curr6_mean=0.3, load6_mean=2.0, curr6_peak=5.0)
    res = Attributor(material_weight=0.575).attribute("111101", sig)
    assert res.symptom == "air_cut"
    assert res.locked is None  # 来料正常 → 非来料短；对刀无信号证据 → 不锁定


def test_kb_graph_causal_fork():
    """知识图：空切 Symptom CAUSES 多个候选 Fault（候选分叉）。"""
    g = build_graph(":memory:")
    sym = g.get_node(NodeRef("Symptom", "SYM-AIRCUT"))
    causes = g.query(sym, "CAUSES", "forward")
    assert [e.dst.id for e in causes] == ["F-MAT-SHORT", "F-CLAMP", "F-TOOL"]


def test_kb_graph_liability_chain():
    """知识图：来料尺寸不足 → 表面粗糙缺陷；供应链责任链完整。"""
    g = build_graph(":memory:")
    fault = g.get_node(NodeRef("Fault", "F-MAT-SHORT"))
    affects = [e.dst.id for e in g.query(fault, "AFFECTS", "forward")]
    assert "D-SURFACE" in affects  # 来料短 → 表面粗糙
    sup = g.get_node(NodeRef("Supplier", "SUP-B"))
    clauses = g.query(sup, "SUBJECT_TO", "forward")
    assert clauses and clauses[0].dst.id == "CL-2"


def test_knowledge_chunker_tree():
    """知识文档切块：title_path 记录树层级（文档 → 树）。"""
    chunks = chunk_knowledge()
    assert chunks
    # 至少出现因果知识的树路径（文档 / 章节 / 子章节）
    paths = [" / ".join(c.title_path) for c in chunks]
    assert any("causal_knowledge" in p and "空切症状与候选原因" in p for p in paths)
