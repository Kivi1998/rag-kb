"""MemberService 邀请/角色变更测试。

对照 Java 版 `service/MemberService.java`。
关键不变量:
- 角色层级矩阵:OWNER > ADMIN > MEMBER,ADMIN 不能管理 ADMIN/OWNER
- 至少保留一名 owner(降级最后一名 owner → 409)
- 跨租户成员查找通过 `find_by_subject_id_and_org_id`,不允许直接跨租户
- 鉴权约束从 `tenant_context` 拿,而不是参数传入(对应 Java 版 SecurityContext)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.tenant_context import TenantContext
from app.exceptions.errors import (
    AccessDeniedException,
    BusinessConflictException,
    ResourceNotFoundException,
)
from app.models.enums import MemberRole
from app.services.member_service import MemberService


@pytest.fixture
def set_tenant(monkeypatch):
    """在每个用例里设置 tenant_context。pytest-asyncio 每个 async 测试都在独立的 asyncio task
    里跑,任务结束 ContextVar 自动清理——所以这里不用手动 reset。
    """
    from app.core import tenant_context

    def _set(org_id: UUID, member_id: UUID, role: str):
        ctx = TenantContext(org_id=org_id, member_id=member_id, role=role)
        tenant_context._tenant_context.set(ctx)

    return _set


def _build_service() -> tuple[MemberService, AsyncMock, AsyncMock, AsyncMock]:
    member_repo = AsyncMock()
    org_repo = AsyncMock()
    session = AsyncMock()
    service = MemberService(member_repo, org_repo, session)
    return service, member_repo, org_repo, session


class TestInvite:
    @pytest.mark.asyncio
    async def test_owner_can_invite_member(self, set_tenant):
        org_id, member_id = uuid4(), uuid4()
        set_tenant(org_id, member_id, "OWNER")
        service, member_repo, org_repo, session = _build_service()
        member_repo.find_by_subject_id_and_org_id.return_value = None
        org_repo.find_by_id.return_value = MagicMock(id=org_id)
        new_member_id = uuid4()

        async def _save(m):
            m.id = new_member_id
            return m

        member_repo.save.side_effect = _save

        result = await service.invite(subject_id="new-user-id", role=MemberRole.MEMBER)

        assert result.id == new_member_id
        assert result.subject_id == "new-user-id"
        assert result.role == MemberRole.MEMBER
        assert result.org_id == org_id
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_admin_can_invite_member(self, set_tenant):
        set_tenant(uuid4(), uuid4(), "ADMIN")
        service, member_repo, org_repo, _session = _build_service()
        member_repo.find_by_subject_id_and_org_id.return_value = None
        org_repo.find_by_id.return_value = MagicMock(id=uuid4())
        member_repo.save.side_effect = lambda m: m

        result = await service.invite("new-user", MemberRole.MEMBER)
        assert result.role == MemberRole.MEMBER

    @pytest.mark.asyncio
    async def test_admin_cannot_invite_admin(self, set_tenant):
        """ADMIN 不可邀请 ADMIN(角色越权)。"""
        set_tenant(uuid4(), uuid4(), "ADMIN")
        service, member_repo, _org_repo, _session = _build_service()

        with pytest.raises(AccessDeniedException):
            await service.invite("new-admin", MemberRole.ADMIN)

    @pytest.mark.asyncio
    async def test_admin_cannot_invite_owner(self, set_tenant):
        set_tenant(uuid4(), uuid4(), "ADMIN")
        service, _member_repo, _org_repo, _session = _build_service()

        with pytest.raises(AccessDeniedException):
            await service.invite("new-owner", MemberRole.OWNER)

    @pytest.mark.asyncio
    async def test_member_cannot_invite_others(self, set_tenant):
        set_tenant(uuid4(), uuid4(), "MEMBER")
        service, _member_repo, _org_repo, _session = _build_service()

        with pytest.raises(AccessDeniedException):
            await service.invite("anyone", MemberRole.MEMBER)

    @pytest.mark.asyncio
    async def test_cannot_invite_as_owner_directly(self, set_tenant):
        """OWNER 也不能直接邀请为 OWNER——必须走"转让 owner"接口,避免意外多 owner。"""
        set_tenant(uuid4(), uuid4(), "OWNER")
        service, _member_repo, _org_repo, _session = _build_service()

        with pytest.raises(AccessDeniedException):
            await service.invite("new-owner", MemberRole.OWNER)

    @pytest.mark.asyncio
    async def test_invite_duplicate_rejected(self, set_tenant):
        set_tenant(uuid4(), uuid4(), "OWNER")
        service, member_repo, _org_repo, _session = _build_service()
        # 主体已在当前组织中
        member_repo.find_by_subject_id_and_org_id.return_value = MagicMock()

        with pytest.raises(BusinessConflictException):
            await service.invite("existing-user", MemberRole.MEMBER)
        # 不应触达 save
        member_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_invite_org_not_found(self, set_tenant):
        set_tenant(uuid4(), uuid4(), "OWNER")
        service, member_repo, org_repo, _session = _build_service()
        member_repo.find_by_subject_id_and_org_id.return_value = None
        org_repo.find_by_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.invite("x", MemberRole.MEMBER)


class TestChangeRole:
    @pytest.mark.asyncio
    async def test_owner_can_change_member_to_admin(self, set_tenant):
        set_tenant(uuid4(), uuid4(), "OWNER")
        service, member_repo, _org_repo, _session = _build_service()
        target_id = uuid4()
        target = MagicMock()
        target.id = target_id
        target.role = MemberRole.MEMBER
        member_repo.find_by_id_and_org_id.return_value = target
        member_repo.save.side_effect = lambda m: m

        result = await service.change_role(target_id, MemberRole.ADMIN)
        assert result.role == MemberRole.ADMIN
        _session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_admin_cannot_promote_to_owner(self, set_tenant):
        """ADMIN 不能把任何人(包括 MEMBER) 提升为 OWNER。"""
        set_tenant(uuid4(), uuid4(), "ADMIN")
        service, member_repo, _org_repo, _session = _build_service()
        target = MagicMock()
        target.id = uuid4()
        target.role = MemberRole.MEMBER
        member_repo.find_by_id_and_org_id.return_value = target

        with pytest.raises(AccessDeniedException):
            await service.change_role(target.id, MemberRole.OWNER)

    @pytest.mark.asyncio
    async def test_admin_cannot_demote_owner(self, set_tenant):
        """ADMIN 不可降级 OWNER(防止 ADMIN 偷偷把 OWNER 降为 MEMBER 自己上位)。"""
        set_tenant(uuid4(), uuid4(), "ADMIN")
        service, member_repo, _org_repo, _session = _build_service()
        target = MagicMock()
        target.id = uuid4()
        target.role = MemberRole.OWNER
        member_repo.find_by_id_and_org_id.return_value = target

        with pytest.raises(AccessDeniedException):
            await service.change_role(target.id, MemberRole.MEMBER)

    @pytest.mark.asyncio
    async def test_cannot_demote_last_owner(self, set_tenant):
        """组织必须至少保留一名 owner——降级最后一名 owner 应该被业务拒绝。"""
        set_tenant(uuid4(), uuid4(), "OWNER")
        service, member_repo, _org_repo, _session = _build_service()
        target = MagicMock()
        target.id = uuid4()
        target.role = MemberRole.OWNER
        member_repo.find_by_id_and_org_id.return_value = target
        # 唯一一名 owner
        member_repo.count_by_org_id_and_role.return_value = 1

        with pytest.raises(BusinessConflictException):
            await service.change_role(target.id, MemberRole.ADMIN)
        # 不应保存
        member_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_can_demote_owner_when_others_remain(self, set_tenant):
        """组织还有其它 owner 时,降级一名 owner 是合法的。"""
        set_tenant(uuid4(), uuid4(), "OWNER")
        service, member_repo, _org_repo, _session = _build_service()
        target = MagicMock()
        target.id = uuid4()
        target.role = MemberRole.OWNER
        member_repo.find_by_id_and_org_id.return_value = target
        member_repo.count_by_org_id_and_role.return_value = 2  # 还有一名 owner
        member_repo.save.side_effect = lambda m: m

        result = await service.change_role(target.id, MemberRole.MEMBER)
        assert result.role == MemberRole.MEMBER

    @pytest.mark.asyncio
    async def test_target_member_not_found(self, set_tenant):
        set_tenant(uuid4(), uuid4(), "OWNER")
        service, member_repo, _org_repo, _session = _build_service()
        member_repo.find_by_id_and_org_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.change_role(uuid4(), MemberRole.ADMIN)


class TestCrossTenantLookup:
    @pytest.mark.asyncio
    async def test_get_by_id_and_current_org_scoped_to_org(self, set_tenant):
        """get_by_id_and_current_org 必须按 org_id 过滤,不能用主键单查。"""
        org_id = uuid4()
        set_tenant(org_id, uuid4(), "OWNER")
        service, member_repo, _org_repo, _session = _build_service()
        member_repo.find_by_id_and_org_id.return_value = MagicMock(id=uuid4())

        await service.get_by_id_and_current_org(uuid4())
        # 必须传 (id, org_id)——证明 org_id 被作为过滤条件
        member_repo.find_by_id_and_org_id.assert_awaited_once()
        args = member_repo.find_by_id_and_org_id.await_args.args
        assert args[1] == org_id

    @pytest.mark.asyncio
    async def test_get_by_id_and_current_org_not_found(self, set_tenant):
        set_tenant(uuid4(), uuid4(), "OWNER")
        service, member_repo, _org_repo, _session = _build_service()
        member_repo.find_by_id_and_org_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.get_by_id_and_current_org(uuid4())

    @pytest.mark.asyncio
    async def test_list_by_current_org_scoped(self, set_tenant):
        org_id = uuid4()
        set_tenant(org_id, uuid4(), "OWNER")
        service, member_repo, _org_repo, _session = _build_service()
        member_repo.find_by_org_id.return_value = []

        await service.list_by_current_org()
        member_repo.find_by_org_id.assert_awaited_with(org_id)
