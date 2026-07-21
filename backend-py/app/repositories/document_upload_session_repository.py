"""对应 repository/DocumentUploadSessionRepository.java。"""

from typing import NamedTuple
from uuid import UUID
from datetime import datetime

from sqlalchemy import select

from app.models.document_upload_session import DocumentUploadSession
from app.models.enums import UploadSessionStatus
from app.repositories.base import BaseRepository


class ExpiredSessionRef(NamedTuple):
    """对应 Java 内嵌投影接口 DocumentUploadSessionRepository.ExpiredSessionRef。

    清理任务只需要 (session_id, org_id) 两列,不必把整行 DocumentUploadSession 取回来。
    """

    session_id: UUID
    org_id: UUID


class DocumentUploadSessionRepository(BaseRepository[DocumentUploadSession]):
    model = DocumentUploadSession

    async def find_by_id_and_org_id(self, id_: UUID, org_id: UUID) -> DocumentUploadSession | None:
        """对应 Java findByIdAndOrgId。"""
        stmt = select(DocumentUploadSession).where(
            DocumentUploadSession.id == id_, DocumentUploadSession.org_id == org_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_for_update(self, id_: UUID, org_id: UUID) -> DocumentUploadSession | None:
        """对应 Java findForUpdate:@Lock(PESSIMISTIC_WRITE),complete 回调用悲观锁串行化。"""
        stmt = (
            select(DocumentUploadSession)
            .where(DocumentUploadSession.id == id_, DocumentUploadSession.org_id == org_id)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_org_id_and_knowledge_base_id_and_idempotency_key(
        self, org_id: UUID, knowledge_base_id: UUID, idempotency_key: str
    ) -> DocumentUploadSession | None:
        """对应 Java findByOrgIdAndKnowledgeBaseIdAndIdempotencyKey。"""
        stmt = select(DocumentUploadSession).where(
            DocumentUploadSession.org_id == org_id,
            DocumentUploadSession.kb_id == knowledge_base_id,
            DocumentUploadSession.idempotency_key == idempotency_key,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_expired_session_refs(
        self, status: UploadSessionStatus, now: datetime, limit: int
    ) -> list[ExpiredSessionRef]:
        """对应 Java findExpiredSessionRefs:清理任务扫描已过期的 PENDING 会话。

        未做租户过滤,继承自 Java 版原始行为:清理任务是系统级后台 job,按设计跨组织扫描,
        不按单一 org_id 限定;`limit` 对应 Java 版的 Pageable 参数。
        """
        stmt = (
            select(
                DocumentUploadSession.id.label("session_id"), DocumentUploadSession.org_id.label("org_id")
            )
            .where(DocumentUploadSession.status == status, DocumentUploadSession.expires_at < now)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [ExpiredSessionRef(session_id=row.session_id, org_id=row.org_id) for row in result]

    async def find_stale_verification_refs(
        self, status: UploadSessionStatus, cutoff: datetime, limit: int
    ) -> list[ExpiredSessionRef]:
        """对应 Java findStaleVerificationRefs:回收超时未完成校验(VERIFYING)的会话。

        未做租户过滤,继承自 Java 版原始行为:同样是系统级后台 job,跨组织扫描。
        """
        stmt = (
            select(
                DocumentUploadSession.id.label("session_id"), DocumentUploadSession.org_id.label("org_id")
            )
            .where(
                DocumentUploadSession.status == status,
                DocumentUploadSession.verification_started_at < cutoff,
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [ExpiredSessionRef(session_id=row.session_id, org_id=row.org_id) for row in result]
