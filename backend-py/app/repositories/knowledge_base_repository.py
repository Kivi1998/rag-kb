"""对应 repository/KnowledgeBaseRepository.java。"""

from uuid import UUID

from sqlalchemy import select

from app.models.enums import KbStatus
from app.models.knowledge_base import KnowledgeBase
from app.repositories.base import BaseRepository


class KnowledgeBaseRepository(BaseRepository[KnowledgeBase]):
    model = KnowledgeBase

    async def find_by_org_id(self, org_id: UUID) -> list[KnowledgeBase]:
        """对应 Java findByOrgId。"""
        stmt = select(KnowledgeBase).where(KnowledgeBase.org_id == org_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_id_and_org_id(self, id_: UUID, org_id: UUID) -> KnowledgeBase | None:
        """对应 Java findByIdAndOrgId。"""
        stmt = select(KnowledgeBase).where(KnowledgeBase.id == id_, KnowledgeBase.org_id == org_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_status(self, status: KbStatus) -> list[KnowledgeBase]:
        """对应 Java findByStatus:对账任务用,查询待清理的知识库。

        未做租户过滤,继承自 Java 版原始行为:对账任务是系统级后台job,需要扫描所有组织下
        状态为 PENDING_CLEANUP 的知识库,不按单一 org_id 限定。
        """
        stmt = select(KnowledgeBase).where(KnowledgeBase.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
