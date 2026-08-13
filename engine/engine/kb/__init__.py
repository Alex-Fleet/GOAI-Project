"""知识库入库（D6）：离线建设工具——知识文件 → 切块 → LLM 抽取 → 人审 → 入图/检索索引。

不参与运行时推理；检索产物（关键词 + 向量两路）是本体推理的检索起点。
"""

from .bm25 import BM25Hit, BM25Index
from .chunking import Chunk, ChunkSplitter, StructureChunker
from .embed import EmbedderProtocol, SiliconFlowEmbedder
from .extract import Entity, ExtractionResult, LLExtractor, Relationship
from .ingest import IngestProposal, IngestReport, KnowledgeIngestor
from .llm import DeepSeekClient, LLMProtocol
from .vector import BruteForceVectorStore, VectorHit, VectorStore

__all__ = [
    "BM25Hit",
    "BM25Index",
    "BruteForceVectorStore",
    "Chunk",
    "ChunkSplitter",
    "DeepSeekClient",
    "EmbedderProtocol",
    "Entity",
    "ExtractionResult",
    "IngestProposal",
    "IngestReport",
    "KnowledgeIngestor",
    "LLExtractor",
    "LLMProtocol",
    "Relationship",
    "SiliconFlowEmbedder",
    "StructureChunker",
    "VectorHit",
    "VectorStore",
]
