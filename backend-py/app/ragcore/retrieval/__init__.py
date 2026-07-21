"""混合检索与重排子包。对应 Java 版 `ragcore/retrieval/` 包。

对外公共 API:
    端口:
        Retriever, HybridCandidateSource, LexicalCandidateSource,
        VectorCandidateSource, ChunkHydrator
    值对象:
        RetrievalOptions, RetrievalResult, RetrievalDiagnostics,
        VectorHit, VectorSearchRequest
    核心实现:
        HybridRetriever, RrfFusion.fuse, MIN_RRF_SCORE, MIN_RERANK_SCORE
        ProviderVectorCandidateSource, VectorRetrievalMetrics
    适配实现:
        ElasticsearchLexicalCandidateSource, ElasticsearchVectorCandidateSource,
        ElasticsearchHybridCandidateSource, ElasticsearchChunkHydrator,
        MilvusVectorCandidateSource

多租户三重过滤契约(必须由所有实现保留):
    1. 词法/向量召回端在底层 ES bool.filter / Milvus filter 表达式中强制注入
       organization_id / knowledge_base_id / retrieval_ready=true。
    2. 向量命中回 ES 补正文时,ES 查询再次带相同 org/kb 过滤。
    3. HybridRetriever 在拿到 ChunkHydrator 回包后,再对每条 chunk.organization_id
       / chunk.knowledge_base_id 与请求做显式比对,任何不一致直接丢弃。
"""

from app.ragcore.retrieval.chunk_hydrator import ChunkHydrator
from app.ragcore.retrieval.es_chunk_document_mapper import SOURCE_FIELDS, to_chunk
from app.ragcore.retrieval.es_chunk_hydrator import ElasticsearchChunkHydrator
from app.ragcore.retrieval.es_hybrid_candidate_source import ElasticsearchHybridCandidateSource
from app.ragcore.retrieval.es_lexical_candidate_source import ElasticsearchLexicalCandidateSource
from app.ragcore.retrieval.es_vector_candidate_source import ElasticsearchVectorCandidateSource
from app.ragcore.retrieval.hybrid_candidate_source import HybridCandidateSource
from app.ragcore.retrieval.hybrid_retriever import (
    MIN_RERANK_SCORE,
    HybridRetriever,
    REFUSAL_BLANK_QUERY,
    REFUSAL_EMPTY,
    REFUSAL_RERANK_BELOW,
)
from app.ragcore.retrieval.lexical_candidate_source import LexicalCandidateSource
from app.ragcore.retrieval.milvus_vector_candidate_source import MilvusVectorCandidateSource
from app.ragcore.retrieval.provider_vector_candidate_source import (
    FALLBACK_ES_TO_BM25,
    FALLBACK_MILVUS_AND_ES_TO_BM25,
    FALLBACK_SHADOW_TIMEOUT,
    PROVIDER_ELASTICSEARCH,
    PROVIDER_MILVUS,
    PROVIDER_SHADOW,
    ProviderConfig,
    ProviderVectorCandidateSource,
    VALID_PROVIDERS,
)
from app.ragcore.retrieval.retrieval_diagnostics import RetrievalDiagnostics
from app.ragcore.retrieval.retrieval_options import RetrievalOptions
from app.ragcore.retrieval.retrieval_result import RetrievalResult
from app.ragcore.retrieval.retriever import Retriever
from app.ragcore.retrieval.rrf_fusion import DEFAULT_RANK_CONSTANT, MIN_RRF_SCORE, fuse
from app.ragcore.retrieval.vector_candidate_source import VectorCandidateSource
from app.ragcore.retrieval.vector_hit import VectorHit
from app.ragcore.retrieval.vector_retrieval_metrics import VectorRetrievalMetrics
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest

__all__ = [
    # 端口
    "Retriever",
    "HybridCandidateSource",
    "LexicalCandidateSource",
    "VectorCandidateSource",
    "ChunkHydrator",
    # 值对象
    "RetrievalOptions",
    "RetrievalResult",
    "RetrievalDiagnostics",
    "VectorHit",
    "VectorSearchRequest",
    # 核心实现
    "HybridRetriever",
    "MIN_RERANK_SCORE",
    "MIN_RRF_SCORE",
    "DEFAULT_RANK_CONSTANT",
    "REFUSAL_BLANK_QUERY",
    "REFUSAL_EMPTY",
    "REFUSAL_RERANK_BELOW",
    "fuse",
    # 切流
    "ProviderConfig",
    "ProviderVectorCandidateSource",
    "VectorRetrievalMetrics",
    "PROVIDER_ELASTICSEARCH",
    "PROVIDER_SHADOW",
    "PROVIDER_MILVUS",
    "VALID_PROVIDERS",
    "FALLBACK_ES_TO_BM25",
    "FALLBACK_MILVUS_AND_ES_TO_BM25",
    "FALLBACK_SHADOW_TIMEOUT",
    # 适配实现
    "ElasticsearchLexicalCandidateSource",
    "ElasticsearchVectorCandidateSource",
    "ElasticsearchHybridCandidateSource",
    "ElasticsearchChunkHydrator",
    "MilvusVectorCandidateSource",
    "SOURCE_FIELDS",
    "to_chunk",
]
