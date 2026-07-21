"""Parser → Chunker → Embedding → 双投影提交的生产摄取编排。

对应 Java 版 `ragcore/ingestion/DefaultDocumentIngestionPipeline.java`。
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Protocol
from uuid import UUID

from app.ragcore.chunk.technical_chunker import TechnicalChunker
from app.ragcore.chunk.models import ChunkingContext, ChunkingOptions
from app.ragcore.embedding.client import EmbeddingClient
from app.ragcore.ingestion.artifact_store import ParsedArtifactStore
from app.ragcore.ingestion.chunk_projection_orchestrator import ChunkProjectionOrchestrator
from app.ragcore.ingestion.lifecycle_service import IngestionJobLifecycleService
from app.ragcore.ingestion.metrics import IngestionMetrics
from app.ragcore.ingestion.pipeline import DocumentIngestionPipeline
from app.ragcore.ingestion.status import IngestionStatus
from app.ragcore.ingestion.task import IngestionTask
from app.ragcore.model import EmbeddingResult
from app.ragcore.models import DocumentInput
from app.ragcore.parser.factory import DocumentParserFactory
from app.ragcore.storage.object_storage import ObjectStorage

logger = logging.getLogger(__name__)


class _DocumentInputAdapter(DocumentInput):
    """把 (task, 已异步读取的字节内容) 包成 Parser 需要的 DocumentInput 协议。

    ObjectStorage 是异步接口,而 Parser.parse() 期望同步的 open_stream()。
    在事件循环中不能用 asyncio.run() 桥接(会因 loop 已在运行而抛
    RuntimeError),所以改为:进入同步 parser 之前先异步把完整文件内容读入
    内存(上传文件本身有 settings.rag_upload_max_size_bytes 大小上限,一次
    性读入可接受),再用 io.BytesIO 包装成同步的类文件对象。
    """

    def __init__(self, task: IngestionTask, content: bytes) -> None:
        self._task = task
        self._content = content

    def document_id(self) -> UUID:
        return self._task.document_id

    def filename(self) -> str:
        return self._task.filename

    def content_type(self) -> str | None:
        return self._task.content_type

    def source_path(self) -> str:
        return self._task.object_storage_path

    def open_stream(self):
        return io.BytesIO(self._content)


class DefaultDocumentIngestionPipeline(DocumentIngestionPipeline):
    def __init__(
        self,
        parser_factory: DocumentParserFactory,
        chunker: TechnicalChunker,
        embedding_client: EmbeddingClient,
        projection_orchestrator: ChunkProjectionOrchestrator,
        object_storage: ObjectStorage,
        lifecycle_service: IngestionJobLifecycleService,
        artifact_store: ParsedArtifactStore,
        metrics: IngestionMetrics,
    ) -> None:
        self._factory = parser_factory
        self._chunker = chunker
        self._embedding = embedding_client
        self._projection = projection_orchestrator
        self._storage = object_storage
        self._lifecycle = lifecycle_service
        self._artifact_store = artifact_store
        self._metrics = metrics

    async def process(self, task: IngestionTask) -> None:
        self._require_storage_path(task)
        parsed = await self._timed("parse", lambda: self._load_or_parse(task))
        await self._lifecycle.advance(task, IngestionStatus.CHUNKING)

        chunks = await self._timed(
            "chunk",
            lambda: asyncio.to_thread(
                self._chunker.chunk,
                parsed,
                ChunkingContext(
                    organization_id=task.organization_id,
                    knowledge_base_id=task.knowledge_base_id,
                ),
                ChunkingOptions.defaults(),
            ),
        )
        if not chunks:
            raise ValueError("文档不含可索引的文本内容")
        await self._lifecycle.advance(task, IngestionStatus.EMBEDDING)

        embedding = await self._timed(
            "embedding",
            lambda: self._embedding.embed([chunk.content for chunk in chunks]),
        )
        if not isinstance(embedding, EmbeddingResult) or len(embedding.vectors) != len(chunks):
            raise RuntimeError("Embedding 返回向量数量与 chunk 数量不一致")
        await self._lifecycle.advance(task, IngestionStatus.INDEXING)

        await self._timed(
            "index",
            lambda: self._projection.project(
                chunks,
                [list(v) for v in embedding.vectors],
                embedding.model_version,
            ),
        )
        await self._lifecycle.advance(task, IngestionStatus.READY)

    async def _load_or_parse(self, task: IngestionTask):
        cached = await self._artifact_store.load(task)
        if cached is not None:
            return cached
        content = await self._read_object(task)
        parsed = await self._factory.parse(_DocumentInputAdapter(task, content))
        saved = await self._artifact_store.save(task, parsed)
        if hasattr(self._lifecycle, "record_parsed_artifact"):
            await self._lifecycle.record_parsed_artifact(
                task, saved.path, saved.parser_name, saved.parser_version
            )
        return parsed

    async def _read_object(self, task: IngestionTask) -> bytes:
        """异步把对象存储中的原始文件完整读入内存。"""
        stream = await self._storage.open(task.object_storage_path)
        try:
            return await asyncio.to_thread(stream.read)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                await asyncio.to_thread(close)

    async def _timed(self, stage: str, action):
        started = self._metrics.start_nanos()
        try:
            result = await action()
            self._metrics.stage_finished(stage, started, True)
            return result
        except Exception:
            self._metrics.stage_finished(stage, started, False)
            raise

    @staticmethod
    def _require_storage_path(task: IngestionTask) -> None:
        if not task.object_storage_path or not task.object_storage_path.strip():
            raise RuntimeError("文档缺少对象存储路径")
