"""组织服务。对应 Java 版 service/OrganizationService.java。

创建组织 = bootstrap:免租户上下文,创建后 subject 自动成为 owner。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.errors import ResourceNotFoundException
from app.models.enums import MemberRole
from app.models.member import Member
from app.models.organization import Organization
from app.repositories.member_repository import MemberRepository
from app.repositories.organization_repository import OrganizationRepository


class OrganizationService:
    def __init__(
        self,
        org_repository: OrganizationRepository,
        member_repository: MemberRepository,
        session: AsyncSession,
    ) -> None:
        self._orgs = org_repository
        self._members = member_repository
        self._session = session

    async def create(self, subject_id: str, name: str) -> Organization:
        org = Organization(name=name)
        org = await self._orgs.save(org)
        await self._session.flush()  # 确保 org.id 已生成,供下面外键使用

        owner = Member(subject_id=subject_id, org_id=org.id, role=MemberRole.OWNER)
        await self._members.save(owner)
        await self._session.commit()
        return org

    async def get_by_id(self, org_id: UUID) -> Organization:
        org = await self._orgs.find_by_id(org_id)
        if org is None:
            raise ResourceNotFoundException("组织不存在")
        return org
