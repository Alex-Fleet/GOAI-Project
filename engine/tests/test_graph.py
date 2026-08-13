"""知识层 Ladybug 图查询测试：forward/backward 方向还原 + 关系表缺失兜底。"""

from __future__ import annotations

from engine.contracts import NodeRef


def test_query_forward_returns_true_direction(graph):
    """forward：P1 -(HAS_PROCESS)-> S1 -(AT_EQUIPMENT)-> DMC-50H。"""
    edges = graph.query(NodeRef("Product", "P1"), "HAS_PROCESS", "forward")
    assert [e.dst.id for e in edges] == ["S1"]
    assert all(e.src.id == "P1" for e in edges)


def test_query_backward_returns_true_direction(graph):
    """backward 必须还原真实图方向：S1 -> DMC-50H（而非反向的 DMC-50H -> S1）。

    边轨迹语义 = 可回放的真实边（src -(rel)-> dst）；backward 只是查询方向，
    返回的 EdgeRef 仍是真实方向，否则推理核沿图验证会把回溯路径当成假边拒绝。
    """
    edges = graph.query(NodeRef("Equipment", "DMC-50H"), "AT_EQUIPMENT", "backward")
    assert len(edges) == 1
    e = edges[0]
    assert e.src.label == "Process" and e.src.id == "S1"
    assert e.dst.label == "Equipment" and e.dst.id == "DMC-50H"
    assert e.rel == "AT_EQUIPMENT"

    # 可继续沿真实方向向上回溯（检索兜底的反向工艺回溯依赖此语义）
    hp = graph.query(e.src, "HAS_PROCESS", "backward")
    assert hp and hp[0].src.id == "P1" and hp[0].dst.id == "S1"


def test_query_missing_rel_table_returns_empty(graph):
    """关系表未建（知识不完整）→ 空列表而非崩溃。"""
    assert graph.query(NodeRef("Product", "P1"), "NOT_A_TABLE", "forward") == []
