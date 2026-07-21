"""路由层共享的装配工厂(只为路由层服务,不放在 ragcore)。

为什么需要这一层:在 Java 版里这些 bean 装配由 Spring `@Configuration` 集中管理;
Python 侧没有容器,改为在路由工厂里手动装配。六类工厂集中在本模块:
1. **模型客户端**:Embedding / Rerank / Generation / ChatCompletion(对应 `rag.*_enabled`)
2. **意图分类**:LlmQueryIntentClassifier(依赖 ChatCompletionClient)
3. **检索层**:HybridRetriever(词法+向量+ES chunk hydrator+可选 Milvus/Provider)
4. **记忆层**:ConversationMemoryOrchestrator(只在 `rag_memory_enabled=true` 时装配)
5. **临时文档层**:RedisQuickDocumentStore(只在 `rag_quick_document_enabled=true` 时装配)
6. **摄取层**:DocumentParserFactory 9 个解析器链 + IngestionJobLifecycleService +
   ObjectStorage,Ingestion Worker 在 lifespan 里按需装配

所有工厂都按 `settings.rag_*_enabled` 等开关条件性返回 None,service 层 / QueryService
对 None 输入已有优雅降级,fail-open 已在对应组件内部实现,这里不做兜底包装。
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from functools import lru_cache
from typing import TYPE_CHECKING, Callable

from app.core.config import settings

if TYPE_CHECKING:  # pragma: no cover - 仅类型提示,避免循环 import
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.ragcore.embedding.client import EmbeddingClient
    from app.ragcore.generation.client import AnswerGenerator, ChatCompletionClient
    from app.ragcore.ingestion.lifecycle_service import IngestionJobLifecycleService
    from app.ragcore.intent.query_intent_classifier import QueryIntentClassifier
    from app.ragcore.memory.conversation_memory_orchestrator import ConversationMemoryOrchestrator
    from app.ragcore.parser.factory import DocumentParserFactory
    from app.ragcore.quickdocument.quick_document_store import QuickDocumentStore
    from app.ragcore.rerank.client import RerankerClient
    from app.ragcore.retrieval.retriever import Retriever
    from app.ragcore.storage.object_storage import ObjectStorage


# ---- 模型客户端 --------------------------------------------------------

@lru_cache(maxsize=1)
def build_answer_generator() -> "AnswerGenerator | None":
    """生成器(流式 ChatCompletion),`rag_generation_enabled=false` 时返回 None。"""
    from app.ragcore.generation.openai_compatible_answer_generator import build_answer_generator as _impl

    return _impl(settings)


@lru_cache(maxsize=1)
def build_embedding_client() -> "EmbeddingClient | None":
    """Embedding 客户端,`rag_embedding_enabled=false` 时返回 None。

    None 时 HybridRetriever 的 _search_vector 走 BM25-only 降级——fail-open 已在
    HybridRetriever 内部实现(`ModelClientException` → 退化为 BM25),这里不重复兜底。
    """
    from app.ragcore.embedding.openai_compatible import build_embedding_client as _impl

    return _impl(settings)


@lru_cache(maxsize=1)
def build_reranker_client() -> "RerankerClient | None":
    """Rerank 客户端,`rag_rerank_enabled=false` 时返回 None。

    None 时 HybridRetriever 直接使用 RRF 顺序结果,fail-open 已由
    HybridRetriever 的 `reranker_provider.get_if_available() is None` 分支处理。
    """
    from app.ragcore.rerank.openai_compatible import build_reranker_client as _impl

    return _impl(settings)


@lru_cache(maxsize=1)
def build_chat_completion_client() -> "ChatCompletionClient | None":
    """非流式 ChatCompletion 客户端,意图分类/指代消解/摘要/画像提炼共用。

    `rag_generation_enabled=false`(默认)时返回 None;意图分类调用失败由
    LlmQueryIntentClassifier 内部 catch 后回退 QueryIntent.UNKNOWN。
    """
    from app.ragcore.generation.openai_compatible_chat_completion_client import (
        build_chat_completion_client as _impl,
    )

    return _impl(settings)


def build_intent_classifier() -> "QueryIntentClassifier | None":
    """意图分类器,只在 `rag_intent_classification_enabled=true` 时返回有效实例。

    依赖 ChatCompletionClient——若 generation 开关未开而意图开关开了,会得到 None,
    调用方(QueryService)按 None = 不启用意图分类处理。
    """
    if not settings.rag_intent_classification_enabled:
        return None
    client = build_chat_completion_client()
    if client is None:
        return None
    from app.ragcore.intent.llm_query_intent_classifier import LlmQueryIntentClassifier

    return LlmQueryIntentClassifier(client)


# ---- 检索层 -----------------------------------------------------------

def _build_milvus_source():
    """构造 Milvus 向量候选源(`rag_milvus_enabled=true` 且配置齐全时)。

    Milvus 客户端没有现成的单例工厂,这里按最小可用实现建一个:使用 pymilvus 同步
    客户端。ProviderVectorCandidateSource 在 provider=milvus/shadow 模式才会真正
    调用它,provider=elasticsearch 时 milvus_source 传 None。
    """
    if not settings.rag_milvus_enabled or not settings.rag_milvus_uri:
        return None
    from pymilvus import MilvusClient  # type: ignore[import-untyped]

    from app.ragcore.retrieval.milvus_vector_candidate_source import MilvusVectorCandidateSource

    client = MilvusClient(
        uri=settings.rag_milvus_uri,
        token=settings.rag_milvus_token or None,
        db_name=settings.rag_milvus_database,
    )
    return MilvusVectorCandidateSource(client)


@lru_cache(maxsize=1)
def build_hybrid_retriever() -> "Retriever | None":
    """构造 HybridRetriever(ES BM25 + 词法 + 向量 + ChunkHydrator + 可选 Milvus/Provider)。

    返回条件:`rag_es_enabled=true` 时才返回有效实例(词法/向量都依赖 ES);否则
    返回 None——QueryService 的 `retriever is None` 路径在现有代码里没有,所以
    主调用点(query router)应在 `build_hybrid_retriever() is None` 时考虑
    关闭 `/query` 端点(本实现不阻断: 仍允许 build 出 HybridRetriever,让 ES
    客户端单点拉起即可,具体保护由 main.py 的 `rag_query_enabled` 开关承担)。

    实现要点:
    - 词法源 = ElasticsearchLexicalCandidateSource(get_es_client())
    - 向量兜底 = ElasticsearchVectorCandidateSource(get_es_client())
    - Provider 路由器 = 始终用 ProviderVectorCandidateSource,按 settings.rag_vector_provider
      切流(elasticsearch / shadow / milvus),内部处理 ES→BM25、Milvus→ES→BM25 回退
    - chunk_hydrator = ElasticsearchChunkHydrator(get_es_client())——纵深防御第三道
    - embedding_client = build_embedding_client()(None 时降级为 BM25-only)
    - reranker_provider = build_reranker_client()(None 时跳过 rerank)
    - vector_metrics = VectorRetrievalMetrics(None)(测试环境无 Prometheus registry)
    """
    if not settings.rag_es_enabled:
        return None
    from app.core.es_client import get_es_client
    from app.ragcore.retrieval.es_chunk_hydrator import ElasticsearchChunkHydrator
    from app.ragcore.retrieval.es_lexical_candidate_source import ElasticsearchLexicalCandidateSource
    from app.ragcore.retrieval.es_vector_candidate_source import ElasticsearchVectorCandidateSource
    from app.ragcore.retrieval.hybrid_retriever import HybridRetriever
    from app.ragcore.retrieval.provider_vector_candidate_source import (
        ProviderConfig,
        ProviderVectorCandidateSource,
    )
    from app.ragcore.retrieval.vector_retrieval_metrics import VectorRetrievalMetrics

    es = get_es_client()
    lexical = ElasticsearchLexicalCandidateSource(es)
    es_vector = ElasticsearchVectorCandidateSource(es)
    milvus_vector = _build_milvus_source()
    provider = ProviderVectorCandidateSource(
        elasticsearch_source=es_vector,
        milvus_source=milvus_vector,
        config=ProviderConfig(
            provider=settings.rag_vector_provider,
            fallback_to_elasticsearch=settings.rag_vector_fallback_to_es,
            shadow_timeout_ms=settings.rag_vector_shadow_timeout_ms,
            shadow_sample_rate=settings.rag_vector_shadow_sample_rate,
        ),
        metrics=VectorRetrievalMetrics(None),
    )
    hydrator = ElasticsearchChunkHydrator(es)
    return HybridRetriever(
        lexical_source=lexical,
        vector_source=provider,
        chunk_hydrator=hydrator,
        embedding_client=build_embedding_client(),  # None = BM25-only
        reranker_provider=build_reranker_client(),  # None = 跳过 rerank
        vector_metrics=None,
    )


# ---- 记忆层 -----------------------------------------------------------

def _build_memory_orchestrator() -> "ConversationMemoryOrchestrator | None":
    """构造 ConversationMemoryOrchestrator,只在 `rag_memory_enabled=true` 时返回实例。

    内部依赖链较长(ConversationStore / SlidingWindowAssembler / CoreferenceResolver /
    UserProfileInjector / MemoryExtractor),全部为 None 时整个 orchestrator 为 None,
    任何一个底层失败由 orchestrator 自身 catch 住(fail-open),不传播到 QueryService。
    """
    if not settings.rag_memory_enabled:
        return None
    from app.ragcore.memory.conversation_memory_orchestrator import ConversationMemoryOrchestrator
    from app.ragcore.memory.deepseek_conversation_summarizer import DeepSeekConversationSummarizer
    from app.ragcore.memory.deepseek_coreference_resolver import DeepSeekCoreferenceResolver
    from app.ragcore.memory.deepseek_memory_extractor import DeepSeekMemoryExtractor
    from app.ragcore.memory.elasticsearch_memory_index import ElasticsearchMemoryIndex
    from app.ragcore.memory.memory_item_repository import MemoryItemRepository
    from app.ragcore.memory.memory_item_store_impl import MemoryItemStoreImpl
    from app.ragcore.memory.redis_mongo_conversation_store import RedisMongoConversationStore
    from app.ragcore.memory.sliding_window_assembler import SlidingWindowAssembler
    from app.ragcore.memory.user_profile_injector import UserProfileInjector

    chat_client = build_chat_completion_client()
    if chat_client is None:
        # 记忆子系统的所有 LLM 路径都依赖 chat_completion_client;开关未开时整体降级
        return None
    embedding = build_embedding_client()
    if embedding is None:
        # UserProfileInjector 与指代消解都依赖 embedding;未开时整体降级
        return None

    from app.core.es_client import get_es_client

    es = get_es_client() if settings.rag_es_enabled else None
    if es is None:
        return None
    memory_index = ElasticsearchMemoryIndex(es, index_name=settings.rag_memory_es_index_name)
    memory_item_store = MemoryItemStoreImpl(
        memory_index=memory_index,
        memory_item_repository=MemoryItemRepository(),
        decay_half_life_days=settings.rag_memory_decay_half_life_days,
    )
    store = RedisMongoConversationStore()
    summarizer = DeepSeekConversationSummarizer(chat_client)
    coref = DeepSeekCoreferenceResolver(chat_client)
    window = SlidingWindowAssembler(summarizer)
    profile = UserProfileInjector(memory_item_store, top_k=settings.rag_memory_profile_top_k)
    extractor = DeepSeekMemoryExtractor(chat_client, embedding, memory_item_store)

    return ConversationMemoryOrchestrator(
        conversation_store=store,
        sliding_window_assembler=window,
        coreference_resolver=coref,
        embedding_client=embedding,
        user_profile_injector=profile,
        memory_extractor=extractor,
        token_budget=settings.rag_memory_token_budget,
    )


# ---- 临时文档层 -------------------------------------------------------

@lru_cache(maxsize=1)
def build_quick_document_store() -> "QuickDocumentStore | None":
    """会话内临时文档存储,只在 `rag_quick_document_enabled=true` 时返回实例。

    返回 None 时 QuickDocumentService 无法构造(其 store 字段是必选);调用方
    (query.py / quick_documents.py)按 None = 整个临时文档子系统不可用处理:
    - query.py: 不向 contexts 注入临时文档
    - quick_documents.py: 直接在 router 层拒绝(404 或 400 都可,本实现选 400
      表示"模块未启用,功能不可用",与"额度满"区分)
    """
    if not settings.rag_quick_document_enabled:
        return None
    import redis.asyncio as redis_async

    from app.ragcore.quickdocument.redis_quick_document_store import RedisQuickDocumentStore

    client = redis_async.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        db=settings.rag_quick_document_redis_database,
        decode_responses=True,
    )
    return RedisQuickDocumentStore(client)


# ---- 摄取层 ----------------------------------------------------------

@lru_cache(maxsize=1)
def build_parser_factory() -> "DocumentParserFactory":
    """Ingestion Worker / 临时文档共享的解析器链工厂。

    9 个解析器:6 个本地 (Pdf/Docx/Pptx/Markdown/StructuredData/Code) +
    TextParser / SubtitleParser / HttpMultimodalDocumentParser(网关兜底,关闭时
    supports() 自动 False)。无内部状态,模块级单例即可。
    """
    from app.ragcore.parser.code_parser import CodeParser
    from app.ragcore.parser.docx_parser import DocxParser
    from app.ragcore.parser.factory import DocumentParserFactory
    from app.ragcore.parser.markdown_parser import MarkdownParser
    from app.ragcore.parser.multimodal_parser import HttpMultimodalDocumentParser
    from app.ragcore.parser.pdf_parser import PdfParser
    from app.ragcore.parser.pptx_parser import PptxParser
    from app.ragcore.parser.structured_data_parser import StructuredDataParser
    from app.ragcore.parser.subtitle_parser import SubtitleParser
    from app.ragcore.parser.text_parser import TextParser

    return DocumentParserFactory(
        [
            PdfParser(),
            DocxParser(),
            PptxParser(),
            MarkdownParser(),
            StructuredDataParser(),
            CodeParser(),
            TextParser(),
            SubtitleParser(),
            HttpMultimodalDocumentParser(),
        ]
    )


def build_object_storage() -> "ObjectStorage":
    """按 `settings.rag_storage_type` 选本地 / MinIO 实现。Worker 拉起时用。"""
    if settings.rag_storage_type == "minio":
        from app.ragcore.storage.minio_object_storage import MinioObjectStorage

        return MinioObjectStorage()
    from app.ragcore.storage.local_object_storage import LocalObjectStorage

    return LocalObjectStorage()


def build_lifecycle_service(
    session_factory: "Callable[[], AsyncContextManager[AsyncSession]] | None" = None,
) -> "IngestionJobLifecycleService":
    """返回 SQLAlchemy 实现的摄取任务状态机服务。

    不显式绑定 session——lifecycle_service 在每个方法内部按 session_factory
    打开短生命周期 session(Worker 的 claim/heartbeat 跑在不同的 asyncio task
    里,各自需要独立 session)。`session_factory=None` 时 fallback 到
    `SessionLocal()`(lifespan 里的默认行为)。
    """
    from app.ragcore.ingestion.sqlalchemy_lifecycle_service import (
        SqlAlchemyIngestionJobLifecycleService,
    )

    if session_factory is None:
        from app.core.db import SessionLocal

        session_factory = SessionLocal
    return SqlAlchemyIngestionJobLifecycleService(session_factory=session_factory)


def build_chunk_projection_orchestrator():
    """构造 ChunkProjectionOrchestrator(ES 词法 + 可选 Milvus 向量)。

    `rag_es_enabled=false` 时返回 None——ChunkProjectionOrchestrator 必须有
    lexical_index, 没有 ES 客户端则整个摄取链路无意义。Lifespan 看到 None 就
    跳过 worker 启动,和 memory_cleanup_task 的"开关未开就跳过"语义一致。
    """
    if not settings.rag_es_enabled:
        return None
    from app.core.es_client import get_es_client
    from app.ragcore.index.es_chunk_index import ElasticsearchChunkIndex
    from app.ragcore.ingestion.chunk_projection_orchestrator import (
        ChunkProjectionOrchestrator,
    )

    es = get_es_client()
    lexical = ElasticsearchChunkIndex(es)
    return ChunkProjectionOrchestrator(lexical_index=lexical, vector_index=None)


def build_ingestion_pipeline():
    """构造 `DefaultDocumentIngestionPipeline`,任何一个依赖未就绪时返回 None。

    返回 None 不抛异常:调用方(lifespan)直接跳过 worker 启动,日志里说明原因。
    """
    from app.ragcore.chunk.technical_chunker import TechnicalChunker
    from app.ragcore.ingestion.artifact_store import ParsedArtifactStore
    from app.ragcore.ingestion.default_pipeline import DefaultDocumentIngestionPipeline
    from app.ragcore.ingestion.metrics import IngestionMetrics

    projection = build_chunk_projection_orchestrator()
    if projection is None:
        logger.info("ES 未启用,跳过摄取 Worker 装配")
        return None
    embedding = build_embedding_client()
    if embedding is None:
        logger.info("Embedding 未启用,跳过摄取 Worker 装配")
        return None
    try:
        object_storage = build_object_storage()
    except Exception as ex:  # noqa: BLE001
        logger.warning("对象存储构造失败,跳过摄取 Worker 装配: %s", ex)
        return None
    try:
        lifecycle = build_lifecycle_service()
    except Exception as ex:  # noqa: BLE001
        logger.warning("Lifecycle service 构造失败,跳过摄取 Worker 装配: %s", ex)
        return None

    return DefaultDocumentIngestionPipeline(
        parser_factory=build_parser_factory(),
        chunker=TechnicalChunker(),
        embedding_client=embedding,
        projection_orchestrator=projection,
        object_storage=object_storage,
        lifecycle_service=lifecycle,
        artifact_store=ParsedArtifactStore(object_storage),
        metrics=IngestionMetrics(None),
    )
