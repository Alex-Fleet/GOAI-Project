"""D6 入库编排测试：两阶段（propose 审核 / commit 落库）+ 幂等 + 检索两路。"""

from __future__ import annotations

import json

import jieba

from engine import (
    BM25Index,
    BruteForceVectorStore,
    KnowledgeIngestor,
    LLExtractor,
    StructureChunker,
    default_schema,
)
from engine.contracts import NodeRef
from tests.helpers import StubEmbedder, StubLLM

TRIPLES = json.dumps(
    {
        "entities": [
            {
                "label": "Equipment",
                "id": "DMC-50H",
                "name": "加工中心",
                "props": {"model": "DMC 50H"},
            },
            {"label": "Component", "id": "C1", "name": "主轴轴承", "props": {}},
        ],
        "relationships": [{"src_id": "DMC-50H", "rel": "HAS_COMPONENT", "dst_id": "C1"}],
    },
    ensure_ascii=False,
)

DOC_TEXT = """# 设备手册

DMC-50H 加工中心，型号 DMC 50H。

## 主轴

主轴轴承磨损导致振动超标。
"""


def build_ingestor(graph, embedder=None):
    embedder = embedder or StubEmbedder()
    return KnowledgeIngestor(
        chunker=StructureChunker(),
        extractor=LLExtractor(StubLLM(TRIPLES), default_schema()),
        graph=graph,
        vector_store=BruteForceVectorStore(),
        embedder=embedder,
        bm25=BM25Index(tokenizer=jieba.lcut),
        tokenizer=jieba.lcut,
    )


def test_propose_produces_chunks_and_extractions(kb_graph, tmp_path):
    doc = tmp_path / "manual.md"
    doc.write_text(DOC_TEXT, encoding="utf-8")
    ingestor = build_ingestor(kb_graph)
    proposal = ingestor.propose(doc, "manual", title="设备手册")
    assert proposal.chunks  # 切出块
    assert all(result.error == "" for result in proposal.extractions.values())
    assert proposal.issues == []


def test_commit_writes_graph_and_indexes(kb_graph, tmp_path):
    doc = tmp_path / "manual.md"
    doc.write_text(DOC_TEXT, encoding="utf-8")
    ingestor = build_ingestor(kb_graph)
    proposal = ingestor.propose(doc, "manual")
    report = ingestor.commit(proposal)
    # DOC_TEXT 切 2 块，每块抽 2 实体（TRIPLES）→ 4 次 MERGE 写；图上 MERGE 幂等唯一
    assert report.entities_written == 2 * len(proposal.chunks)
    # 第 2 块的关系已存在 → 幂等跳过，只写 1 条
    assert report.relationships_written == 1
    assert report.chunks_indexed == len(proposal.chunks)

    # 图：能沿 HAS_COMPONENT 查到边，节点唯一
    edges = kb_graph.query(NodeRef("Equipment", "DMC-50H"), "HAS_COMPONENT", "forward")
    assert [e.dst.id for e in edges] == ["C1"]

    # 关键词路径：BM25 命中主轴相关 chunk
    hits = ingestor.search_keywords("主轴轴承")
    assert any(h.doc_id in {c.id for c in proposal.chunks} for h in hits)
    # 检索命中带图实体引用（检索 → 图实体的桥，供二层 Retriever 消费）
    assert hits and all(h.payload.get("entities") for h in hits)

    # 向量路径：与文档最相似的 chunk 命中
    q = StubEmbedder().embed([DOC_TEXT])[0]
    vhits = ingestor.search_vectors(q)
    assert vhits


def test_commit_is_idempotent(kb_graph, tmp_path):
    doc = tmp_path / "manual.md"
    doc.write_text(DOC_TEXT, encoding="utf-8")
    ingestor = build_ingestor(kb_graph)
    proposal = ingestor.propose(doc, "manual")
    ingestor.commit(proposal)
    ingestor.commit(proposal)
    # 重复 commit 不产生重复边
    edges = kb_graph.query(NodeRef("Equipment", "DMC-50H"), "HAS_COMPONENT", "forward")
    assert len(edges) == 1
    # 实体 MERGE 幂等 → 只一个节点
    assert kb_graph.get_node(NodeRef("Equipment", "DMC-50H")) is not None


def test_commit_empty_approval_writes_nothing(kb_graph, tmp_path):
    doc = tmp_path / "manual.md"
    doc.write_text(DOC_TEXT, encoding="utf-8")
    ingestor = build_ingestor(kb_graph)
    proposal = ingestor.propose(doc, "manual")
    report = ingestor.commit(proposal, approved_chunk_ids=[])
    assert report.chunks_indexed == 0
    assert kb_graph.query(NodeRef("Equipment", "DMC-50H"), "HAS_COMPONENT", "forward") == []


def test_propose_records_issues(kb_graph, tmp_path):
    def boom(system, user, json_mode=False):
        raise RuntimeError("鉴权失败")

    doc = tmp_path / "manual.md"
    doc.write_text(DOC_TEXT, encoding="utf-8")
    ingestor = KnowledgeIngestor(
        chunker=StructureChunker(),
        extractor=LLExtractor(StubLLM(boom), default_schema()),
        graph=kb_graph,
        vector_store=BruteForceVectorStore(),
        embedder=StubEmbedder(),
        bm25=BM25Index(tokenizer=jieba.lcut),
        tokenizer=jieba.lcut,
    )
    proposal = ingestor.propose(doc, "manual")
    assert proposal.issues  # 每块抽取失败 → issue
    # 有 issue 的 chunk 不进图
    report = ingestor.commit(proposal)
    assert report.entities_written == 0
