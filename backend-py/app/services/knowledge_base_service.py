"""知识库服务。对应 Java 版 service/KnowledgeBaseService.java。

RAG 核心重构期间仅负责知识库业务元数据。文档摄取、索引与问答由 ragcore 模块接入。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import get_tenant_context
from app.exceptions.errors import ResourceNotFoundException
from app.models.enums import KbStatus
from app.models.knowledge_base import KnowledgeBase
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.member_repository import MemberRepository
from app.repositories.organization_repository import OrganizationRepository


class KnowledgeBaseService:
    def __init__(
        self,
        kb_repository: KnowledgeBaseRepository,
        org_repository: OrganizationRepository,
        member_repository: MemberRepository,
        session: AsyncSession,
    ) -> None:
        self._kbs = kb_repository
        self._orgs = org_repository
        self._members = member_repository
        self._session = session

    async def create(self, name: str) -> KnowledgeBase:
        ctx = get_tenant_context()
        org = await self._orgs.find_by_id(ctx.org_id)
        if org is None:
            raise ResourceNotFoundException("组织不存在")

        creator = await self._members.find_by_id(ctx.member_id)
        if creator is None:
            raise ResourceNotFoundException("成员不存在")

        kb = KnowledgeBase(org_id=org.id, name=name, created_by=creator.id, status=KbStatus.ACTIVE)
        kb = await self._kbs.save(kb)
        await self._session.commit()
        return kb

    async def update(self, kb_id: UUID, new_name: str) -> KnowledgeBase:
        kb = await self.get_by_id_and_current_org(kb_id)
        kb.name = new_name
        kb = await self._kbs.save(kb)
        await self._session.commit()
        return kb

    async def delete(self, kb_id: UUID) -> bool:
        """删除知识库业务记录。"""
        kb = await self.get_by_id_and_current_org(kb_id)
        await self._kbs.delete(kb)
        await self._session.commit()
        return True

    async def get_by_id_and_current_org(self, kb_id: UUID) -> KnowledgeBase:
        ctx = get_tenant_context()
        kb = await self._kbs.find_by_id_and_org_id(kb_id, ctx.org_id)
        if kb is None:
            raise ResourceNotFoundException("知识库不存在")
        return kb

    async def list_by_current_org(self) -> list[KnowledgeBase]:
        ctx = get_tenant_context()
        return await self._kbs.find_by_org_id(ctx.org_id)
