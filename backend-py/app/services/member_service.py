"""成员服务。对应 Java 版 service/MemberService.java。

角色层级矩阵:
- OWNER:  全权(可管理所有成员角色,含 admin;可转让/撤销 owner)
- ADMIN:  可管理 MEMBER(邀请/移除/读),但不可设/改 OWNER,不可修改 OWNER
- MEMBER: 只读

硬约束:组织始终至少保留一名 owner。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import get_tenant_context
from app.exceptions.errors import (
    AccessDeniedException,
    BusinessConflictException,
    ResourceNotFoundException,
)
from app.models.enums import MemberRole
from app.models.member import Member
from app.repositories.member_repository import MemberRepository
from app.repositories.organization_repository import OrganizationRepository


class MemberService:
    def __init__(
        self,
        member_repository: MemberRepository,
        org_repository: OrganizationRepository,
        session: AsyncSession,
    ) -> None:
        self._members = member_repository
        self._orgs = org_repository
        self._session = session

    async def invite(self, subject_id: str, role: MemberRole) -> Member:
        if role == MemberRole.OWNER:
            raise AccessDeniedException("不能直接邀请为 owner,请使用转让 owner 接口")

        ctx = get_tenant_context()
        caller_role = MemberRole(ctx.role)
        self._assert_can_manage(caller_role, role)

        existing = await self._members.find_by_subject_id_and_org_id(subject_id, ctx.org_id)
        if existing is not None:
            raise BusinessConflictException("该主体已是本组织成员")

        org = await self._orgs.find_by_id(ctx.org_id)
        if org is None:
            raise ResourceNotFoundException("组织不存在")

        member = Member(subject_id=subject_id, org_id=org.id, role=role)
        member = await self._members.save(member)
        await self._session.commit()
        return member

    async def change_role(self, target_member_id: UUID, new_role: MemberRole) -> Member:
        ctx = get_tenant_context()
        caller_role = MemberRole(ctx.role)

        target = await self._members.find_by_id_and_org_id(target_member_id, ctx.org_id)
        if target is None:
            raise ResourceNotFoundException("成员不存在")

        if new_role == MemberRole.OWNER and caller_role != MemberRole.OWNER:
            raise AccessDeniedException("只有 owner 可以设/改为 owner 角色")

        if target.role == MemberRole.OWNER and caller_role != MemberRole.OWNER:
            raise AccessDeniedException("只有 owner 可以修改 owner 的角色")

        self._assert_can_manage(caller_role, new_role)

        if target.role == MemberRole.OWNER and new_role != MemberRole.OWNER:
            owner_count = await self._members.count_by_org_id_and_role(ctx.org_id, MemberRole.OWNER)
            if owner_count <= 1:
                raise BusinessConflictException("组织必须至少保留一名 owner")

        target.role = new_role
        target = await self._members.save(target)
        await self._session.commit()
        return target

    async def list_by_current_org(self) -> list[Member]:
        ctx = get_tenant_context()
        return await self._members.find_by_org_id(ctx.org_id)

    async def get_by_id_and_current_org(self, member_id: UUID) -> Member:
        ctx = get_tenant_context()
        member = await self._members.find_by_id_and_org_id(member_id, ctx.org_id)
        if member is None:
            raise ResourceNotFoundException("成员不存在")
        return member

    def _assert_can_manage(self, caller_role: MemberRole, target_role: MemberRole) -> None:
        if caller_role == MemberRole.OWNER:
            return
        if caller_role == MemberRole.ADMIN:
            if target_role in (MemberRole.OWNER, MemberRole.ADMIN):
                raise AccessDeniedException("admin 只能管理 member 角色")
            return
        raise AccessDeniedException("member 角色无权执行此操作")
