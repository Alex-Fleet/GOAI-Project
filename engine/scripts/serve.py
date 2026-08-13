"""本地演示服务入口：mock 知识/业务 + 一楼引擎 + D6 检索兜底 → FastAPI（默认 8800）。

二楼 demo 用真实知识/适配器替换本脚本的 mock 部分，契约不变。
演示两条定位路径（前端改 entity_ref 切换）：
- `P1`：图遍历直连工艺图（explore_l1 正常路径）
- `DMC-50H`：图遍历定位不到 → D6 检索两路（BM25 关键词 + 向量）兜底命中 → 走正常把关

用法：`python scripts/serve.py`（需已建 .venv 且装有 requirements.txt）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 允许从任意 cwd 运行

import jieba
import uvicorn

from engine import (
    BM25Index,
    BruteForceVectorStore,
    Chunk,
    Entity,
    ExtractionResult,
    InferenceKernel,
    IngestProposal,
    KnowledgeIngestor,
    LadybugGraphStore,
    LLExtractor,
    NluSide,
    Relationship,
    Rule,
    SQLiteAudit,
    SQLiteBusinessStore,
    StructureChunker,
    TracingLoop,
    TracingService,
    create_app,
    default_schema,
)
from engine.agent.layers import Candidate
from engine.contracts import NodeRef
from engine.platform.executor import Executor

# mock 判定规则（二楼替换为行业规则）
MOCK_LAYER_RULES = {
    "L2_equipment": [Rule("equipment_self_check", "Equipment", "self_check_failed", "==", True)],
    "L2_material": [Rule("material_anomaly", "Material", "anomaly", "==", True)],
    "L3": [Rule("component_wear", "Component", "wear_level", ">=", 2.8)],
    "L4": [Rule("clause_covers", "Clause", "covers", "==", True)],
}

_NODES = """
CREATE (:Product {id:'P1', name:'product-1'})
CREATE (:Process {id:'S1', name:'milling'})
CREATE (:Equipment {id:'DMC-50H', model:'DMC 50H', self_check_failed:true})
CREATE (:Material {id:'M1', name:'steel', anomaly:false})
CREATE (:Component {id:'C1', name:'spindle-bearing', wear_level:3.5})
CREATE (:Supplier {id:'SUP-A', name:'Acme'})
CREATE (:Clause {id:'CL-1', name:'warranty', covers:true})
CREATE (:Clause {id:'CL-2', name:'warranty', covers:false})
"""

_RELS = """
MATCH (p:Product {id:'P1'}), (s:Process {id:'S1'}) CREATE (p)-[:HAS_PROCESS]->(s)
MATCH (s:Process {id:'S1'}), (e:Equipment {id:'DMC-50H'}) CREATE (s)-[:AT_EQUIPMENT]->(e)
MATCH (p:Product {id:'P1'}), (m:Material {id:'M1'}) CREATE (p)-[:USES_MATERIAL]->(m)
MATCH (e:Equipment {id:'DMC-50H'}), (c:Component {id:'C1'}) CREATE (e)-[:HAS_COMPONENT]->(c)
MATCH (c:Component {id:'C1'}), (s:Supplier {id:'SUP-A'}) CREATE (c)-[:SUPPLIED_BY]->(s)
MATCH (s:Supplier {id:'SUP-A'}), (cl:Clause {id:'CL-1'}) CREATE (s)-[:SUBJECT_TO]->(cl)
MATCH (m:Material {id:'M1'}), (s:Supplier {id:'SUP-B'}) CREATE (m)-[:SUPPLIED_MATERIAL]->(s)
"""


def _schema():
    schema = default_schema()
    # mock 判定属性列（知识入库按需扩展，二楼对真实知识同法，不碰 engine/）
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


# ---------------------------------------------------------------------------
# D6 检索索引（演示用 mock 知识：手写 chunks + 抽取，绕过真实 LLM）
# 二楼用真实管线：文件 → 切块 → DeepSeek 抽取 → 人审 → commit（契约不变）。
# ---------------------------------------------------------------------------


class _NoopLLM:
    """serve 演示不接真实 LLM：知识直接结构化构造，propose() 不被调用。"""

    def chat(self, system, user, json_mode=False):
        raise RuntimeError("serve 演示不接真实 LLM：知识用结构化构造，绕过 propose 抽取")


class DemoEmbedder:
    """确定性 embedding：字符 ord 直方图（与测试 stub 同构，serve 自包含不依赖 tests）。"""

    DIM = 16

    def embed(self, texts):
        out = []
        for t in texts:
            vec = [0.0] * self.DIM
            for ch in t:
                vec[ord(ch) % self.DIM] += 1.0
            out.append(vec)
        return out

    def dim(self):
        return self.DIM


def _build_knowledge_proposal() -> IngestProposal:
    """mock 设备手册知识：chunks + 抽取（实体引用与 _NODES/_RELS 图数据一致）。"""
    chunks = [
        Chunk(
            id="manual:1:0",
            doc_id="manual",
            kind="section",
            text="DMC-50H 加工中心，型号 DMC 50H。主轴轴承 C1 磨损，磨损量 3.5。",
            title_path=["设备手册"],
            source_ref="manual#L1",
        ),
        Chunk(
            id="manual:2:0",
            doc_id="manual",
            kind="section",
            text="C1 主轴轴承由供应商 SUP-A（Acme）供货，质保条款 CL-1 覆盖磨损索赔。",
            title_path=["设备手册"],
            source_ref="manual#L2",
        ),
        Chunk(
            id="manual:3:0",
            doc_id="manual",
            kind="section",
            text="产品 P1 经铣削工序 S1 在 DMC-50H 加工中心完成。",
            title_path=["设备手册"],
            source_ref="manual#L3",
        ),
    ]
    extractions = {
        chunks[0].id: ExtractionResult(
            chunks[0].id,
            [
                Entity("Equipment", "DMC-50H", {"model": "DMC 50H"}, "加工中心"),
                Entity("Component", "C1", {}, "主轴轴承"),
            ],
            [Relationship("DMC-50H", "HAS_COMPONENT", "C1")],
        ),
        chunks[1].id: ExtractionResult(
            chunks[1].id,
            [
                Entity("Component", "C1", {}, "主轴轴承"),
                Entity("Supplier", "SUP-A", {}, "Acme"),
                Entity("Clause", "CL-1", {}, "质保条款"),
            ],
            [
                Relationship("C1", "SUPPLIED_BY", "SUP-A"),
                Relationship("SUP-A", "SUBJECT_TO", "CL-1"),
            ],
        ),
        chunks[2].id: ExtractionResult(
            chunks[2].id,
            [
                Entity("Product", "P1", {}, "产品-1"),
                Entity("Process", "S1", {}, "铣削"),
                Entity("Equipment", "DMC-50H", {}, "加工中心"),
            ],
            [
                Relationship("P1", "HAS_PROCESS", "S1"),
                Relationship("S1", "AT_EQUIPMENT", "DMC-50H"),
            ],
        ),
    }
    return IngestProposal("manual", "设备手册", chunks, extractions)


class KnowledgeRetriever:
    """二层检索兜底实现：BM25 关键词 + 向量两路 → 命中 chunk → 图实体 → 真实 basis。

    basis 从图上反向回溯构造（工艺入口边），推理核把关时沿图验证——
    检索只是「起点」，候选依据必须真实存在于图上。
    """

    def __init__(self, ingestor: KnowledgeIngestor, graph: LadybugGraphStore, embedder):
        self._ingestor = ingestor
        self._graph = graph
        self._embedder = embedder

    def retrieve(self, event) -> list[Candidate]:
        query = " ".join(
            filter(None, [event.entity_ref, event.entity_type, *event.failed_indicators])
        )
        hits = self._ingestor.search_keywords(query, top_k=5)  # 关键词路
        hits += self._ingestor.search_vectors(self._embedder.embed([query])[0], top_k=5)  # 向量路
        out: list[Candidate] = []
        seen: set[tuple[str, str]] = set()
        for h in hits:
            for e in h.payload.get("entities", []):
                key = (e["label"], e["id"])
                if key in seen:
                    continue
                seen.add(key)
                if not self._mentions(e, query):
                    continue  # 候选与触发事实无关联 → 不采信（防检索伪命中引入幻觉）
                cand = self._locate(e)
                if cand:
                    out.append(cand)
        return out

    @staticmethod
    def _mentions(e: dict, query: str) -> bool:
        """候选实体与触发事实的关联校验：实体 id 或名称出现在事实描述里。

        mock embedding（ord 直方图）无真实语义区分度，必须有此防线——否则任意
        查询（如未知对象 XYZ-999）也能兜底到无关实体 DMC-50H。真实 bge-m3 + 二楼
        NLU 消歧后仍建议保留「候选必须与事实关联」的通用校验（宁缺毋滥，不硬出结论）。
        """
        return bool(e.get("id") and e["id"] in query) or bool(e.get("name") and e["name"] in query)

    def _locate(self, e: dict) -> Candidate | None:
        node = self._graph.get_node(NodeRef(e["label"], e["id"]))
        if node is None:
            return None  # 图上无该实体 → 无据候选
        basis = self._backtrace_basis(node)
        if not basis:
            return None  # 图上孤立（无工艺入口）→ 无据候选
        return Candidate(node, basis)

    def _backtrace_basis(self, node: NodeRef):
        """通用反向工艺回溯：从候选节点沿入边找定位入口（返回真实图边）。"""
        if node.label == "Equipment":
            for ae in self._graph.query(node, "AT_EQUIPMENT", "backward"):
                for hp in self._graph.query(ae.src, "HAS_PROCESS", "backward"):
                    return [hp, ae]
        elif node.label == "Material":
            for um in self._graph.query(node, "USES_MATERIAL", "backward"):
                return [um]
        return []


def build():
    """组装完整服务（前端联调 / 演示用）：图 + 业务 + 检索索引 + 引擎。"""
    graph = LadybugGraphStore(":memory:", _schema())
    for stmt in _NODES.splitlines() + _RELS.splitlines():
        if stmt.strip():
            graph.execute(stmt)

    business = SQLiteBusinessStore(":memory:")
    business.upsert(
        "contract-1", "contract", {"supplier": "SUP-A", "orders": ["ORD-1"], "products": ["P-1"]}
    )

    # D6 检索索引（演示用 mock 知识；只建检索，不重复写图）
    embedder = DemoEmbedder()
    ingestor = KnowledgeIngestor(
        chunker=StructureChunker(),
        extractor=LLExtractor(_NoopLLM(), _schema()),
        graph=graph,
        vector_store=BruteForceVectorStore(),
        embedder=embedder,
        bm25=BM25Index(tokenizer=jieba.lcut),
        tokenizer=jieba.lcut,
    )
    ingestor.commit(_build_knowledge_proposal(), write_graph=False)

    audit = SQLiteAudit(":memory:")
    nlu = NluSide()
    kernel = InferenceKernel(graph, rules=[])
    retriever = KnowledgeRetriever(ingestor, graph, embedder)
    loop = TracingLoop(kernel, nlu, graph, business, audit, MOCK_LAYER_RULES, retriever=retriever)
    executor = Executor(business)
    svc = TracingService(loop, nlu, executor, audit)
    return create_app(svc, nlu)


if __name__ == "__main__":
    uvicorn.run(build(), host="127.0.0.1", port=8800)
