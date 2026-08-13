"""共享 fixture：模拟图数据 / 模拟业务数据 / 模拟规则 / 组装服务。

一楼用模拟事实驱动测试（ARD §8）：不依赖任何真实工厂数据。
图里放两个产品：P1 走正常命中路径；P2 走"部件未命中 → 责任缺位 FAILED"路径。
"""

from __future__ import annotations

import pytest

from engine import (
    InferenceKernel,
    LadybugGraphStore,
    NluSide,
    Rule,
    SQLiteAudit,
    SQLiteBusinessStore,
    TracingLoop,
    TracingService,
    default_schema,
)
from engine.contracts import EvidenceEvent
from engine.platform.executor import Executor
from tests.helpers import StubEmbedder

# 模拟知识库规则（一楼可独立跑；二楼替换为行业规则）
MOCK_LAYER_RULES = {
    "L2_equipment": [Rule("equipment_self_check", "Equipment", "self_check_failed", "==", True)],
    "L2_material": [Rule("material_anomaly", "Material", "anomaly", "==", True)],
    "L3": [Rule("component_wear", "Component", "wear_level", ">=", 2.8)],
    "L4": [Rule("clause_covers", "Clause", "covers", "==", True)],
}

_GRAPH_NODES = """
CREATE (:Product {id:'P1', name:'product-1'})
CREATE (:Process {id:'S1', name:'milling'})
CREATE (:Equipment {id:'DMC-50H', model:'DMC 50H', self_check_failed:true})
CREATE (:Material {id:'M1', name:'steel', anomaly:false})
CREATE (:Component {id:'C1', name:'spindle-bearing', wear_level:3.5})
CREATE (:Supplier {id:'SUP-A', name:'Acme'})
CREATE (:Clause {id:'CL-1', name:'warranty', covers:true})
CREATE (:Clause {id:'CL-2', name:'warranty', covers:false})
CREATE (:Product {id:'P2', name:'product-2'})
CREATE (:Process {id:'S2', name:'grinding'})
CREATE (:Equipment {id:'E2', model:'GR-200', self_check_failed:true})
CREATE (:Material {id:'M2', name:'alloy', anomaly:false})
CREATE (:Component {id:'C2', name:'feed-screw', wear_level:0.5})
CREATE (:Supplier {id:'SUP-B', name:'Beta'})
CREATE (:Clause {id:'CL-3', name:'warranty', covers:true})
"""

_GRAPH_RELS = """
MATCH (p:Product {id:'P1'}), (s:Process {id:'S1'}) CREATE (p)-[:HAS_PROCESS]->(s)
MATCH (s:Process {id:'S1'}), (e:Equipment {id:'DMC-50H'}) CREATE (s)-[:AT_EQUIPMENT]->(e)
MATCH (p:Product {id:'P1'}), (m:Material {id:'M1'}) CREATE (p)-[:USES_MATERIAL]->(m)
MATCH (e:Equipment {id:'DMC-50H'}), (c:Component {id:'C1'}) CREATE (e)-[:HAS_COMPONENT]->(c)
MATCH (c:Component {id:'C1'}), (s:Supplier {id:'SUP-A'}) CREATE (c)-[:SUPPLIED_BY]->(s)
MATCH (s:Supplier {id:'SUP-A'}), (cl:Clause {id:'CL-1'}) CREATE (s)-[:SUBJECT_TO]->(cl)
MATCH (m:Material {id:'M1'}), (s:Supplier {id:'SUP-B'}) CREATE (m)-[:SUPPLIED_MATERIAL]->(s)
MATCH (p:Product {id:'P2'}), (s:Process {id:'S2'}) CREATE (p)-[:HAS_PROCESS]->(s)
MATCH (s:Process {id:'S2'}), (e:Equipment {id:'E2'}) CREATE (s)-[:AT_EQUIPMENT]->(e)
MATCH (p:Product {id:'P2'}), (m:Material {id:'M2'}) CREATE (p)-[:USES_MATERIAL]->(m)
MATCH (e:Equipment {id:'E2'}), (c:Component {id:'C2'}) CREATE (e)-[:HAS_COMPONENT]->(c)
MATCH (c:Component {id:'C2'}), (s:Supplier {id:'SUP-B'}) CREATE (c)-[:SUPPLIED_BY]->(s)
MATCH (s:Supplier {id:'SUP-B'}), (cl:Clause {id:'CL-3'}) CREATE (s)-[:SUBJECT_TO]->(cl)
"""


def mock_schema():
    """模拟知识库 schema：在通用 5 域骨架上扩展判定属性列。

    Ladybug 强 schema：属性须预定义建表。通用 schema 保持干净（id/name/model），
    判定属性（知识层内容）由知识入库按需扩展——二楼对真实知识同法扩展，不碰 engine/。
    """
    schema = default_schema()
    for node in schema.nodes:
        if node.label == "Equipment":
            node.props["self_check_failed"] = "BOOLEAN"
        elif node.label == "Material":
            node.props["anomaly"] = "BOOLEAN"
        elif node.label == "Component":
            node.props["wear_level"] = "DOUBLE"
        elif node.label == "Clause":
            node.props["covers"] = "BOOLEAN"
    return schema


@pytest.fixture
def graph():
    g = LadybugGraphStore(":memory:", mock_schema())
    # Ladybug 多语句需分号分隔且不支持 MATCH 级联 → 逐条执行最稳
    for stmt in _GRAPH_NODES.splitlines() + _GRAPH_RELS.splitlines():
        stmt = stmt.strip()
        if stmt:
            g.execute(stmt)
    yield g
    g.close()


@pytest.fixture
def business():
    b = SQLiteBusinessStore(":memory:")
    b.upsert(
        "contract-1",
        "contract",
        {"supplier": "SUP-A", "orders": ["ORD-1"], "products": ["P-1", "P-2"]},
    )
    b.upsert(
        "contract-2", "contract", {"supplier": "SUP-B", "orders": ["ORD-2"], "products": ["P-3"]}
    )
    yield b
    b.close()


@pytest.fixture
def audit():
    return SQLiteAudit(":memory:")


@pytest.fixture
def service(graph, business, audit):
    nlu = NluSide()
    kernel = InferenceKernel(graph, rules=[])  # 规则按层注入，不全局匹配
    loop = TracingLoop(kernel, nlu, graph, business, audit, MOCK_LAYER_RULES)
    executor = Executor(business)
    svc = TracingService(loop, nlu, executor, audit)
    return svc


def make_event(
    entity_ref: str = "P1", indicators: list[str] | None = None, ts: float = 100.0
) -> EvidenceEvent:
    """构造模拟触发事实。"""
    return EvidenceEvent(
        entity_ref=entity_ref,
        entity_type="product",
        ts=ts,
        failed_indicators=indicators if indicators is not None else ["surface_roughness"],
        raw_ref=f"raw://{entity_ref}/qcr",
    )


# ---------------------------------------------------------------------------
# D6 知识入库 fixtures（stub 类定义在 tests/helpers.py，离线不碰真实网络）
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_graph():
    """纯净 5 域 schema 的 Ladybug 图（D6 入库目标）。"""
    g = LadybugGraphStore(":memory:", default_schema())
    yield g
    g.close()


@pytest.fixture
def stub_embedder():
    return StubEmbedder()
