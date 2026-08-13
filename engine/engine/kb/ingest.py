"""知识入库编排（ARD §5 知识入库 / D6）：文件 → 切块 → 抽取 → 人审 → 入图。

离线建设工具，不参与运行时推理。两条提交路径，产物互不替代：
- 检索索引：chunks 向量化 → VectorStore + Jieba/BM25 关键词索引（检索起点两路）
- 属性图：抽取三元组经人审后幂等 MERGE 进 Ladybug（推理核消费）

两阶段设计：propose() 产审核清单（chunks + 抽取产物 + issues），commit() 只把
审核通过的 chunk 落库——「人审 → 入 Ladybug」落在编排层，不进运行推理。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts import NodeRef
from ..platform.graph import LadybugGraphStore
from .bm25 import BM25Index
from .chunking import Chunk, StructureChunker
from .embed import EmbedderProtocol
from .extract import ExtractionResult, LLExtractor
from .vector import VectorStore


@dataclass
class IngestProposal:
    """一批知识文件的处理产物（供人工审核）。issues 非空 = 部分 chunk 抽取失败待处理。"""

    doc_id: str
    title: str
    chunks: list[Chunk] = field(default_factory=list)
    extractions: dict[str, ExtractionResult] = field(default_factory=dict)  # chunk_id -> 结果
    issues: list[str] = field(default_factory=list)


@dataclass
class IngestReport:
    """入库结果汇总。"""

    doc_id: str
    chunks_indexed: int
    entities_written: int
    relationships_written: int
    vector_collection: str


class KnowledgeIngestor:
    """入库编排器。chunker/extractor/embedder/tokenizer 依赖注入，离线测试可全部替换为 stub。"""

    def __init__(
        self,
        chunker: StructureChunker,
        extractor: LLExtractor,
        graph: LadybugGraphStore,
        vector_store: VectorStore,
        embedder: EmbedderProtocol,
        bm25: BM25Index,
        collection: str = "chunks",
        tokenizer: Callable[[str], list[str]] | None = None,
    ):
        self._chunker = chunker
        self._extractor = extractor
        self._graph = graph
        self._vector = vector_store
        self._embedder = embedder
        self._bm25 = bm25
        self._collection = collection
        if tokenizer is None:
            import jieba

            tokenizer = jieba.lcut
        self._tokenize = tokenizer
        self._vector.create_collection(collection, embedder.dim())

    # ---- 阶段一：处理（离线）----

    def propose(self, path: str | Path, doc_id: str, title: str = "") -> IngestProposal:
        """读文件 → 切块 → 逐块 LLM 抽取。抽取失败记 issues，不中断整批。"""
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        chunks = self._chunker.chunk_text(text, doc_id, title)
        extractions: dict[str, ExtractionResult] = {}
        issues: list[str] = []
        for c in chunks:
            result = self._extractor.extract(c)
            extractions[c.id] = result
            if result.error:
                issues.append(f"{c.id}: {result.error}")
        return IngestProposal(doc_id, title, chunks, extractions, issues)

    # ---- 阶段二：提交（人审通过后落库）----

    def commit(
        self,
        proposal: IngestProposal,
        approved_chunk_ids: list[str] | None = None,
        write_graph: bool = True,
        write_vector: bool = True,
        write_bm25: bool = True,
    ) -> IngestReport:
        """把审核通过的 chunk 落库：图 + 向量 + BM25 三份。

        边界：approved_chunk_ids 为空列表 → 不写任何内容（严格按审核来）；None → 全量。
        图写入幂等（实体 MERGE、关系存在即跳过），重复 commit 不产生脏边。
        """
        selected = [
            c for c in proposal.chunks if approved_chunk_ids is None or c.id in approved_chunk_ids
        ]
        if not selected:
            return IngestReport(proposal.doc_id, 0, 0, 0, self._collection)

        entities = relationships = 0
        if write_graph:
            for c in selected:
                result = proposal.extractions.get(c.id)
                if not result or result.error:
                    continue
                entities += self._write_entities(result.entities)
                relationships += self._write_relationships(result.relationships)

        if write_vector:
            ids, vectors, payloads = [], [], []
            for c in selected:
                ids.append(c.id)
                vectors.append(self._embedder.embed([c.text])[0])
                payloads.append(self._payload_for(c, proposal.extractions.get(c.id)))
            self._vector.insert(self._collection, ids, vectors, payloads)

        if write_bm25:
            for c in selected:
                if not self._bm25.contains(c.id):  # 幂等：重复 commit 不重索引进来的 chunk
                    self._bm25.index(
                        c.id, self._tokenize(c.text), self._payload_for(c, proposal.extractions.get(c.id))
                    )

        return IngestReport(
            proposal.doc_id, len(selected), entities, relationships, self._collection
        )

    def search_keywords(self, query: str, top_k: int = 10) -> list:
        """关键词路径：chunk 命中（BM25 打分排序）。供检索起点/推理核兜底。"""
        return self._bm25.search(query, top_k=top_k)

    def search_vectors(self, query_vector: list[float], top_k: int = 10) -> list:
        """向量路径：chunk 命中（余弦相似度排序）。供检索起点/推理核兜底。"""
        return self._vector.search(self._collection, query_vector, top_k=top_k)

    # ---- 图写入（Ladybug 强 schema，幂等）----

    def _write_entities(self, entities) -> int:
        n = 0
        for e in entities:
            cols = ", ".join(f"{k}: ${k}" for k in ("id", *e.props))
            self._graph.execute(f"MERGE (n:{e.label} {{{cols}}})", {"id": e.id, **e.props})
            n += 1
        return n

    def _write_relationships(self, rels) -> int:
        n = 0
        for r in rels:
            src = NodeRef(r.src_label, r.src_id)
            existing = self._graph.query(src, r.rel, "forward")
            if any(edge.dst.id == r.dst_id for edge in existing):
                continue  # 关系已存在 → 幂等跳过
            self._graph.execute(
                f"MATCH (a:{r.src_label} {{id:$src}}), (b:{r.dst_label} {{id:$dst}}) "
                f"CREATE (a)-[:{r.rel}]->(b)",
                {"src": r.src_id, "dst": r.dst_id},
            )
            n += 1
        return n

    # ---- 检索索引 ----

    @staticmethod
    def _payload_for(c: Chunk, result: ExtractionResult | None = None) -> dict:
        """检索命中 payload：chunk 身份 + 该块抽取出的图实体引用。

        entities 是「检索命中 → 图实体」的桥：检索兜底命中 chunk 后，据此把实体
        引用映射回图上节点（二层 Retriever 消费），推理核再沿图验证 basis 防编造。
        """
        payload = {"doc_id": c.doc_id, "source_ref": c.source_ref, "kind": c.kind}
        if result is not None and not result.error:
            payload["entities"] = [
                {"label": e.label, "id": e.id, "name": e.name} for e in result.entities
            ]
        return payload
