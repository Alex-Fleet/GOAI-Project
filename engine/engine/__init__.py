"""GOAI 一楼：通用分层溯源 Agent + 平台（行业无关，ARD §6 契约先行）。

对外公共 API——二楼 demo 只 import 本包，在契约内实例化知识/业务/适配器。
"""

from .agent.infer import InferenceKernel, Rule, RuleEngine
from .agent.loop import Failure, TracingLoop
from .agent.nlu import NluSide
from .contracts import (
    Action,
    ActionResult,
    Audit,
    BusinessStore,
    EdgeRef,
    EvidenceEvent,
    ExecutionReport,
    GraphStore,
    NodeRef,
    Proposal,
    TraceChain,
    TraceStep,
    Verdict,
)
from .kb import (
    BM25Hit,
    BM25Index,
    BruteForceVectorStore,
    Chunk,
    ChunkSplitter,
    DeepSeekClient,
    EmbedderProtocol,
    Entity,
    ExtractionResult,
    IngestProposal,
    IngestReport,
    KnowledgeIngestor,
    LLExtractor,
    LLMProtocol,
    Relationship,
    SiliconFlowEmbedder,
    StructureChunker,
    VectorHit,
    VectorStore,
)
from .platform.audit import SQLiteAudit
from .platform.business import SQLiteBusinessStore
from .platform.executor import Executor
from .platform.graph import (
    LadybugGraphStore,
    NodeTypeDef,
    RelTypeDef,
    SchemaDef,
    default_schema,
)
from .service.api import create_app
from .service.tracing import TracingService, to_dict

__all__ = [
    "Action",
    "ActionResult",
    "Audit",
    "BM25Hit",
    "BM25Index",
    "BruteForceVectorStore",
    "BusinessStore",
    "Chunk",
    "ChunkSplitter",
    "DeepSeekClient",
    "EdgeRef",
    "EmbedderProtocol",
    "Entity",
    "EvidenceEvent",
    "ExecutionReport",
    "Executor",
    "ExtractionResult",
    "Failure",
    "GraphStore",
    "IngestProposal",
    "IngestReport",
    "InferenceKernel",
    "KnowledgeIngestor",
    "LadybugGraphStore",
    "LLExtractor",
    "LLMProtocol",
    "NodeRef",
    "NodeTypeDef",
    "NluSide",
    "Proposal",
    "RelTypeDef",
    "Relationship",
    "Rule",
    "RuleEngine",
    "SchemaDef",
    "SiliconFlowEmbedder",
    "SQLiteAudit",
    "SQLiteBusinessStore",
    "StructureChunker",
    "TraceChain",
    "TraceStep",
    "TracingLoop",
    "TracingService",
    "Verdict",
    "VectorHit",
    "VectorStore",
    "create_app",
    "default_schema",
    "to_dict",
]
