"""FastAPI 应用入口。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Callable, Optional

from fastapi import FastAPI, Request

from app.core.config import settings
from app.core.tenant_context import clear_tenant_context
from app.exceptions import register_exception_handlers
from app.ragcore.ingestion.status import IngestionStatus
from app.routers import auth, chat_sessions, documents, knowledge_bases, members, organizations, query, quick_documents, teams

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 后台任务启动期 helper
# ---------------------------------------------------------------------------
#
# 在 lifespan 里直接拼 80 行装配会很难看;每个子系统配一个独立 helper,
# 由 lifespan 在 startup/shutdown 时按序调用,逻辑闭环可读。helper 都用
# 同步 (def) 形式返回(对象 / 已启动 task / 启动失败的标记),内部 async 部分
# 用 `asyncio.get_event_loop().run_in_executor` 或在调用点用 `await` 处理。

def _build_memory_item_store():
    """构造记忆清理任务需要的 `MemoryItemStore` 依赖。底层客户端(ES / MongoDB)未就绪
    时返回 None,让 lifespan 跳过清理任务的启动,避免在未配置环境里拉起一个永远失败的
    后台任务。

    对应 Java 版: `MemoryCleanupTask` 由 Spring 容器在 `rag.memory.enabled=true` 时
    注入对应 bean;Python 版在 lifespan 里手动装配,等价语义。
    """
    from app.core.es_client import get_es_client
    from app.ragcore.memory.elasticsearch_memory_index import ElasticsearchMemoryIndex
    from app.ragcore.memory.memory_item_repository import MemoryItemRepository
    from app.ragcore.memory.memory_item_store_impl import MemoryItemStoreImpl

    if not settings.rag_memory_mongo_uri:
        logger.info("rag_memory_mongo_uri 未配置,跳过会话记忆清理任务")
        return None
    return MemoryItemStoreImpl(
        memory_index=ElasticsearchMemoryIndex(get_es_client()),
        memory_item_repository=MemoryItemRepository(),
        decay_half_life_days=settings.rag_memory_decay_half_life_days,
    )


def _build_ingestion_components():
    """装配摄取 Worker 需要的全部依赖。

    返回 `(worker, stop_event, job_repository)` 三元组:

    - `worker`: `IngestionWorker` 实例,直接 `await worker.run()` 即可。
    - `stop_event`: 关停信号,lifespan 在 shutdown 时 `set()` 一下让 worker 的轮询循环退出。
    - `job_repository`: `_WorkerJobRepositoryAdapter` 实例,供 `IngestionWorker._repo`
      使用——Worker 的 `_JobRepository` Protocol 现在是 async 的,与真实
      `IngestionJobRepository`(同样 async)语义完全对应;适配层只做两件事:按
      `session_factory=SessionLocal` 模式(与 `SqlAlchemyIngestionJobLifecycleService`
      一致)每次调用开一个短事务,以及把 `find_queued` 转调用真实存在的
      `IngestionJobRepository.find_by_status_order_by_created_at_asc`。

    对应 Java 版: `IngestionWorker` 由 Spring 容器在 `rag.ingestion.worker.enabled=true`
    时装配 `IngestionJobLifecycleService` / `DefaultDocumentIngestionPipeline` /
    `IngestionJobRepository` 并在 `@PostConstruct` 里启动轮询。
    """
    from app.core.db import SessionLocal
    from app.ragcore.chunk.technical_chunker import TechnicalChunker
    from app.ragcore.embedding.client import EmbeddingClient
    from app.ragcore.ingestion.artifact_store import ParsedArtifactStore
    from app.ragcore.ingestion.chunk_projection_orchestrator import (
        ChunkProjectionOrchestrator,
    )
    from app.ragcore.ingestion.default_pipeline import (
        DefaultDocumentIngestionPipeline,
    )
    from app.ragcore.ingestion.metrics import IngestionMetrics
    from app.ragcore.ingestion.sqlalchemy_lifecycle_service import (
        SqlAlchemyIngestionJobLifecycleService,
    )
    from app.ragcore.ingestion.worker import IngestionWorker
    from app.ragcore.parser.code_parser import CodeParser
    from app.ragcore.parser.docx_parser import DocxParser
    from app.ragcore.parser.factory import DocumentParserFactory
    from app.ragcore.parser.local_multimodal_parser import (
        LocalMultimodalDocumentParser,
    )
    from app.ragcore.parser.markdown_parser import MarkdownParser
    from app.ragcore.parser.pdf_parser import PdfParser
    from app.ragcore.parser.pptx_parser import PptxParser
    from app.ragcore.parser.structured_data_parser import (
        StructuredDataParser,
    )
    from app.ragcore.parser.subtitle_parser import SubtitleParser
    from app.ragcore.parser.text_parser import TextParser
    from app.repositories.ingestion_job_repository import (
        IngestionJobRepository,
    )

    stop_event = asyncio.Event()

    # 1) 8 个本地解析器 + 本地多模态兜底(deepdoc OCR + faster-whisper ASR),
    #    factory 无状态、模块级单例
    parser_factory = DocumentParserFactory(
        [
            MarkdownParser(),
            CodeParser(),
            DocxParser(),
            PdfParser(),
            PptxParser(),
            StructuredDataParser(),
            TextParser(),
            SubtitleParser(),
            LocalMultimodalDocumentParser(),
        ]
    )

    # 2) Embedding 客户端: 在未启用 embedding 时(None)DefaultDocumentIngestionPipeline
    #    仍能构造,具体调用在 .embed() 时由 HybridRetriever 自身的 fail-open 兜底
    #    处理。当前 lifespan 阶段 embedding 通路不强制连接,允许 None 占位。
    embedding_client: Optional[EmbeddingClient] = None
    if settings.rag_embedding_enabled:
        from app.ragcore.embedding.openai_compatible import (
            build_embedding_client as _build_embedding,
        )

        embedding_client = _build_embedding(settings)

    # 3) 词法/向量索引: ES 是 chunk 正文权威源(必须有),Milvus 在切流时再接
    lexical_index = None
    if settings.rag_es_enabled:
        from app.core.es_client import get_es_client
        from app.ragcore.index.es_chunk_index import ElasticsearchChunkIndex

        lexical_index = ElasticsearchChunkIndex(get_es_client())
    vector_index = None
    projection = ChunkProjectionOrchestrator(lexical_index, vector_index) if lexical_index else None

    chunker = TechnicalChunker()
    artifact_store = ParsedArtifactStore(_build_object_storage())
    metrics = IngestionMetrics(None)
    session_factory = SessionLocal
    lifecycle_service = SqlAlchemyIngestionJobLifecycleService(
        session_factory=session_factory
    )

    if projection is None or embedding_client is None:
        # ES / Embedding 任一未就绪,Worker 没有可写入的索引或向量化通路,
        # 启动会立刻在第一轮 process() 失败;直接不挂起,避免污染日志。
        logger.warning(
            "摄取 Worker 启动条件不满足(es=%s, embedding=%s),跳过 worker 装配",
            settings.rag_es_enabled,
            settings.rag_embedding_enabled,
        )
        return None, stop_event, _WorkerJobRepositoryAdapter(session_factory)

    pipeline = DefaultDocumentIngestionPipeline(
        parser_factory=parser_factory,
        chunker=chunker,
        embedding_client=embedding_client,
        projection_orchestrator=projection,
        object_storage=_build_object_storage(),
        lifecycle_service=lifecycle_service,
        artifact_store=artifact_store,
        metrics=metrics,
    )

    # 4) job_repository: `_WorkerJobRepositoryAdapter` 按 session_factory 模式包装
    #    真实 `IngestionJobRepository`,`count_by_status` / `find_queued` 都会真正
    #    查库,Worker 才能实际轮到 QUEUED 任务(而不只是靠 `lifecycle.claim()` 那条
    #    路径 —— 没有轮询就永远不会有任务被提交去 claim)。
    job_repository = _WorkerJobRepositoryAdapter(session_factory)

    worker = IngestionWorker(
        job_repository=job_repository,
        lifecycle_service=lifecycle_service,
        pipeline=pipeline,
        metrics=metrics,
        worker_id=settings.rag_ingestion_worker_id,
        concurrency=settings.rag_ingestion_worker_concurrency,
        batch_size=settings.rag_ingestion_worker_batch_size,
        lease_duration_ms=settings.rag_ingestion_worker_lease_duration_ms,
        poll_interval_seconds=max(
            0.05, settings.rag_ingestion_poll_interval_ms / 1000.0
        ),
        stop_event=stop_event,
    )
    return worker, stop_event, job_repository


def _build_object_storage():
    """对象存储装配(本地文件系统 / MinIO)。失败时不抛,留给后续上传路由做 4xx 映射。"""
    if settings.rag_storage_type == "minio":
        from app.ragcore.storage.minio_object_storage import MinioObjectStorage

        return MinioObjectStorage()
    from app.ragcore.storage.local_object_storage import LocalObjectStorage

    return LocalObjectStorage()


class _WorkerJobRepositoryAdapter:
    """`IngestionWorker` 的 `_JobRepository` Protocol 适配层,供 `poll_once()` 使用。

    真实 `IngestionJobRepository` 的每个方法都挂在一个 `AsyncSession` 上,而 Worker 的
    轮询循环跑在 lifespan 启动的后台 asyncio task 里长期存活——不能像请求级
    `Depends(get_session)` 那样每次请求给一个新 session,也不能让 Worker 长期持有一个
    共享 session(`AsyncSession` 不是并发安全的)。这里采用与
    `SqlAlchemyIngestionJobLifecycleService` 完全一致的模式:只持有
    `session_factory`(即 `SessionLocal`),每次调用内部
    `async with session_factory() as session: ...` 开一个短事务,自身不缓存任何状态。

    `find_queued` 转调用真实存在的
    `IngestionJobRepository.find_by_status_order_by_created_at_asc`(对应 Java 版
    `findByStatusOrderByCreatedAtAsc(status, Pageable)` 分页重载),并把 Worker 使用的
    协议层 `IngestionStatus`(`app.ragcore.ingestion.status`)转换成 DB 模型使用的
    `IngestionStatus`(`app.models.enums`)——两者字符串取值一致但是不同的 Python
    枚举类,与 `sqlalchemy_lifecycle_service._db_status` 的转换方式相同。
    """

    def __init__(
        self, session_factory: Callable[[], AbstractAsyncContextManager]
    ) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _db_status(status: IngestionStatus):
        from app.models.enums import IngestionStatus as DbIngestionStatus

        return DbIngestionStatus(status.value)

    async def count_by_status(self, status: IngestionStatus) -> int:
        from app.repositories.ingestion_job_repository import IngestionJobRepository

        async with self._session_factory() as session:
            repo = IngestionJobRepository(session)
            return await repo.count_by_status(self._db_status(status))

    async def find_queued(self, limit: int) -> list:
        from app.repositories.ingestion_job_repository import IngestionJobRepository

        async with self._session_factory() as session:
            repo = IngestionJobRepository(session)
            return await repo.find_by_status_order_by_created_at_asc(
                self._db_status(IngestionStatus.QUEUED), limit=limit
            )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """FastAPI 启动期:
    - `rag_memory_enabled=true` 时拉起 `run_cleanup_loop` 后台任务;
    - `rag_ingestion_worker_enabled=true` 且 ES/Embedding 就绪时拉起
      `IngestionWorker.run()` 轮询任务。
    关闭期: 取消并等待所有后台 task 真正结束,不留孤儿任务。
    """
    cleanup_task: asyncio.Task | None = None
    worker_task: asyncio.Task | None = None
    worker_stop: Optional[asyncio.Event] = None

    if settings.rag_memory_enabled:
        from app.ragcore.memory.memory_cleanup_task import run_cleanup_loop

        store = _build_memory_item_store()
        if store is not None:
            cleanup_task = asyncio.create_task(
                run_cleanup_loop(
                    memory_item_store=store,
                    decay_half_life_days=settings.rag_memory_decay_half_life_days,
                ),
                name="memory-cleanup-loop",
            )
            logger.info("会话记忆清理任务已启动 (rag_memory_enabled=true)")

    if settings.rag_ingestion_worker_enabled:
        worker, worker_stop, _repo = _build_ingestion_components()
        if worker is not None and worker_stop is not None:
            worker_task = asyncio.create_task(
                worker.run(), name="ingestion-worker-loop"
            )
            logger.info(
                "摄取 Worker 已启动 (workerId=%s, concurrency=%d, batchSize=%d)",
                settings.rag_ingestion_worker_id,
                settings.rag_ingestion_worker_concurrency,
                settings.rag_ingestion_worker_batch_size,
            )

    try:
        yield
    finally:
        # 关闭顺序: 先 stop worker(让轮询自然退出),再 cancel 兜底
        if worker_stop is not None:
            worker_stop.set()
        for task in (worker_task, cleanup_task):
            if task is None:
                continue
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as ex:  # noqa: BLE001 - 关闭期不阻断进程退出
                logger.warning("后台任务退出时异常: %s", ex)


app = FastAPI(title="rag-kb", version="0.1.0", lifespan=lifespan)

# 全局异常处理器,对应 Java 版 GlobalExceptionHandler(@RestControllerAdvice)。
# 必须在业务路由注册前挂载,保证所有路由都能命中。
register_exception_handlers(app)


@app.middleware("http")
async def clear_tenant_context_after_request(request: Request, call_next):
    """对应 Java 版 JwtAuthFilter finally 块:请求结束无条件清理租户上下文,
    防止 asyncio task 复用/连接池复用导致跨请求串号。"""
    try:
        return await call_next(request)
    finally:
        clear_tenant_context()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP"}


# 业务路由:service/router/schema/exception 四层里已完整实现且依赖闭合的模块。
# 对应 Java 版 controller/ 下 AuthController/OrganizationController/MemberController/
# TeamController/KnowledgeBaseController/ChatSessionController。
app.include_router(auth.router)
app.include_router(organizations.router)
app.include_router(members.router)
app.include_router(teams.router)
app.include_router(knowledge_bases.router)
app.include_router(chat_sessions.router)
app.include_router(documents.router)  # 摄取(上传/列表/删除/Jobs)
app.include_router(query.router)  # SSE 流式问答
# 会话内临时文档(长上下文直接塞入):按 `rag_quick_document_enabled` 门控,
# 对应 Java 版 `@ConditionalOnProperty(prefix = "rag.quick-document", name = "enabled")`。
if settings.rag_quick_document_enabled:
    app.include_router(quick_documents.router)
