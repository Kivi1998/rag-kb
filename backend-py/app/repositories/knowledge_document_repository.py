"""对应 repository/KnowledgeDocumentRepository.java(model 为 KnowledgeDocument,表名 document)。"""

from uuid import UUID

from sqlalchemy import select

from app.models.enums import IngestionStatus
from app.models.knowledge_document import KnowledgeDocument
from app.repositories.base import BaseRepository


class KnowledgeDocumentRepository(BaseRepository[KnowledgeDocument]):
    model = KnowledgeDocument

    async def find_by_knowledge_base_id_and_org_id_order_by_created_at_desc(
        self, knowledge_base_id: UUID, org_id: UUID
    ) -> list[KnowledgeDocument]:
        """对应 Java findByKnowledgeBaseIdAndOrgIdOrderByCreatedAtDesc。"""
        stmt = (
            select(KnowledgeDocument)
            .where(KnowledgeDocument.kb_id == knowledge_base_id, KnowledgeDocument.org_id == org_id)
            .order_by(KnowledgeDocument.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_id_and_knowledge_base_id_and_org_id(
        self, id_: UUID, knowledge_base_id: UUID, org_id: UUID
    ) -> KnowledgeDocument | None:
        """对应 Java findByIdAndKnowledgeBaseIdAndOrgId。"""
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.id == id_,
            KnowledgeDocument.kb_id == knowledge_base_id,
            KnowledgeDocument.org_id == org_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_status_order_by_updated_at_asc(self, status: IngestionStatus) -> list[KnowledgeDocument]:
        """对应 Java findByStatusOrderByUpdatedAtAsc。

        未做租户过滤,继承自 Java 版原始行为:供摄取 Worker/对账任务跨租户扫描指定状态的
        文档(如批量重试 FAILED),不按单一 org_id 限定。
        """
        stmt = (
            select(KnowledgeDocument)
            .where(KnowledgeDocument.status == status)
            .order_by(KnowledgeDocument.updated_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
