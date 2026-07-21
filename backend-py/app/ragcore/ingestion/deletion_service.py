"""文档删除补偿: ES 先隐藏 → Milvus 删除 → ES 物理删除 → 对象与元数据清理。

对应 Java 版 `ragcore/ingestion/DocumentDeletionService.java`。
多租户安全: 删除路径严格依赖服务端注入的 `org_id` / `kb_id`,绝不接受来自请求
上下文的覆盖,避免越权清理。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional, Protocol
from uuid import UUID

from app.ragcore.index.ports import LexicalChunkIndex, VectorChunkIndex
from app.ragcore.ingestion.status import (
    ACTIVE_STATUSES,
    INTERRUPTIBLE_STATUSES,
    IngestionStatus,
)
from app.ragcore.storage.object_storage import ObjectStorage

logger = logging.getLogger(__name__)


class _DocumentRecord(Protocol):
    id: UUID
    org_id: UUID
    kb_id: UUID
    status: IngestionStatus
    object_storage_path: str | None
    parse_artifact_path: str | None


class _DocumentRepository(Protocol):
    async def find_by_id(self, document_id: UUID) -> Optional[_DocumentRecord]: ...
    async def find_by_status_order_by_updated_at_asc(
        self, status: IngestionStatus
    ) -> list[_DocumentRecord]: ...
    async def delete(self, document: _DocumentRecord) -> None: ...


class _JobRepository(Protocol):
    async def mark_deleting_by_document_id(
        self,
        document_id: UUID,
        active_statuses: Iterable[IngestionStatus],
        deleting_status: IngestionStatus,
        now: datetime,
    ) -> int: ...
    async def delete_by_document_id(self, document_id: UUID) -> None: ...


class DocumentDeletionService:
    def __init__(
        self,
        document_repository: _DocumentRepository,
        job_repository: _JobRepository,
        object_storage: ObjectStorage,
        lexical_index: Optional[LexicalChunkIndex] = None,
        vector_index: Optional[VectorChunkIndex] = None,
    ) -> None:
        self._documents = document_repository
        self._jobs = job_repository
        self._storage = object_storage
        self._lexical = lexical_index
        self._vector = vector_index

    async def request_deletion(self, document_id: UUID) -> None:
        """先持久化删除意图,保证外部清理失败后仍可由补偿任务发现。"""
        document = await self._documents.find_by_id(document_id)
        if document is None:
            raise ValueError("文档不存在")
        document.status = IngestionStatus.DELETING
        await self._jobs.mark_deleting_by_document_id(
            document_id, INTERRUPTIBLE_STATUSES, IngestionStatus.DELETING, datetime.now(timezone.utc)
        )

    async def cleanup(self, document_id: UUID) -> bool:
        """幂等执行一次外部资源与元数据清理;True 表示已彻底删除。"""
        document = await self._documents.find_by_id(document_id)
        if document is None:
            return True
        if document.status != IngestionStatus.DELETING:
            return False
        try:
            if self._lexical is not None:
                # 先关闭正文权威源可见性;后续任一步失败也不会继续出现在问答引用中
                await self._lexical.deactivate_document(
                    document.org_id, document.kb_id, document.id
                )
            if self._vector is not None:
                await self._vector.delete_by_document_id(
                    document.org_id, document.kb_id, document.id
                )
            if self._lexical is not None:
                await self._lexical.delete_by_document_id(
                    document.org_id, document.kb_id, document.id
                )
            if document.object_storage_path:
                await self._storage.delete(document.object_storage_path)
            if document.parse_artifact_path:
                await self._storage.delete(document.parse_artifact_path)
            await self._jobs.delete_by_document_id(document.id)
            await self._documents.delete(document)
            return True
        except Exception as ex:  # noqa: BLE001
            logger.warning("文档删除补偿失败,documentId=%s,将重试: %s", document_id, ex)
            return False

    async def pending_deletion_ids(self, limit: int) -> list[UUID]:
        documents = await self._documents.find_by_status_order_by_updated_at_asc(IngestionStatus.DELETING)
        return [d.id for d in documents[:limit]]
