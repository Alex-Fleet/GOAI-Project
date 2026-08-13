"""检索兜底（ARD §5 检索两路接入推理）：图遍历定位不到对象 → 知识检索第二路补候选。

安全线验证：检索只是起点，候选 basis 必须真实存在于图上——伪造/缺失均被推理核拒绝，
不因检索而绕过「依据必须真实存在」。
"""

from __future__ import annotations

from engine import InferenceKernel, NluSide, TracingLoop, TracingService
from engine.agent.layers import Candidate
from engine.contracts import EdgeRef, NodeRef
from engine.platform.executor import Executor

from .conftest import MOCK_LAYER_RULES, make_event


class StubRetriever:
    """测试用检索器：固定返回候选列表（模拟二层知识检索的定位结果）。"""

    def __init__(self, candidates: list[Candidate]):
        self._candidates = candidates

    def retrieve(self, event) -> list[Candidate]:
        return self._candidates


def _service_with(graph, business, audit, retriever) -> TracingService:
    nlu = NluSide()
    kernel = InferenceKernel(graph, rules=[])
    loop = TracingLoop(kernel, nlu, graph, business, audit, MOCK_LAYER_RULES, retriever=retriever)
    executor = Executor(business)
    return TracingService(loop, nlu, executor, audit)


def _device_candidate(graph) -> list[Candidate]:
    """DMC-50H 及其真实工艺路径 basis（P1 → S1 → DMC-50H）。"""
    hp = graph.query(NodeRef("Product", "P1"), "HAS_PROCESS", "forward")[0]
    ae = graph.query(hp.dst, "AT_EQUIPMENT", "forward")[0]
    return [Candidate(NodeRef("Equipment", "DMC-50H"), [hp, ae])]


def test_l1_fallback_via_retriever_reaches_ready(graph, business, audit):
    """P-NOPE 图遍历定位不到 → 检索兜底命中 DMC-50H → 7 步链走通 READY。"""
    svc = _service_with(graph, business, audit, StubRetriever(_device_candidate(graph)))
    chain = svc.start(make_event("P-NOPE"))
    assert chain.status == "READY"
    # 聊天窗体现检索兜底发生（人话可读、可审计）
    assert any("知识检索兜底命中候选" in t for t in chain.narrative)
    # 兜底候选走正常把关 → 责任结论与正常路径一致
    assert chain.impact["liabilities"] == ["SUP-A"]
    # 候选节点带图上属性快照，规则判定读到值（self_check_failed=true 通过）
    l2 = [s for s in chain.steps if s.layer == "L2"]
    assert any(s.verdict and s.verdict.rule_id == "equipment_self_check" for s in l2)


def test_retriever_candidate_missing_in_graph_is_dropped(graph, business, audit):
    """检索候选在图上不存在（无据）→ 丢弃 → L1 仍 FAILED，不硬出结论。"""
    retriever = StubRetriever([Candidate(NodeRef("Equipment", "FAKE-01"), [])])
    svc = _service_with(graph, business, audit, retriever)
    chain = svc.start(make_event("P-NOPE"))
    assert chain.status == "FAILED"
    assert "L1" in chain.note


def test_retriever_fake_basis_rejected(graph, business, audit):
    """检索候选 basis 伪造（图上不存在该边）→ 推理核拒绝 → L2 无候选 FAILED。

    关键安全线：检索不能编造依据——basis 不过沿图验证，候选即使被定位也不成立。
    """
    fake_edge = EdgeRef(NodeRef("Product", "P1"), "HAS_PROCESS", NodeRef("Process", "NOPE"))
    retriever = StubRetriever([Candidate(NodeRef("Equipment", "DMC-50H"), [fake_edge])])
    svc = _service_with(graph, business, audit, retriever)
    chain = svc.start(make_event("P-NOPE"))
    assert chain.status == "FAILED"
    assert "L2" in chain.note  # L1 定位到候选（图上有该节点），但 L2 把关拒绝伪造依据


def test_empty_retriever_falls_back_to_failed(graph, business, audit):
    """检索器返回空 → 与未注入一致：L1 定位失败 FAILED。"""
    svc = _service_with(graph, business, audit, StubRetriever([]))
    chain = svc.start(make_event("P-NOPE"))
    assert chain.status == "FAILED"
    assert "L1" in chain.note
