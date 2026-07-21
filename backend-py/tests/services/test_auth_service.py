"""AuthService 注册/登录/改密/重置测试。

对照 Java 版 `service/AuthService.java`。
关键不变量:
- 注册:邮箱格式校验、密码强度校验、hash 后存库(不是明文)、重复邮箱拒绝
- 登录:5 次失败后锁定账号、锁定中拒绝登录、锁定到期自动解锁
- 登录失败路径立即 commit 锁定状态(不是"事务整体回滚")
- 改密/重置:旧密码必须验证、新密码必须 hash、token_version 自增使旧 JWT 失效

用 `unittest.mock.AsyncMock` 隔离 SQLAlchemy AsyncSession/repositories,不真连数据库。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.exceptions.errors import (
    AccessDeniedException,
    AccountLockedException,
    BusinessConflictException,
    ResourceNotFoundException,
    UnauthenticatedException,
)
from app.models.enums import UserStatus
from app.services.auth_service import (
    MAX_LOGIN_FAILURES,
    AuthService,
    _PASSWORD_PATTERN,
)
from app.services.password_service import hash_password, verify_password


# 合法密码 = 8 位以上、含字母含数字(参考 _PASSWORD_PATTERN)
_VALID_PASSWORD = "Sup3rSecret!"
_VALID_PASSWORD_2 = "An0therPass"


def _make_user(
    email: str = "alice@example.com",
    password: str = _VALID_PASSWORD,
    user_id: UUID | None = None,
    status: UserStatus = UserStatus.ACTIVE,
    failed_login_count: int = 0,
    locked_until: datetime | None = None,
    token_version: int = 0,
    must_change_password: bool = False,
) -> MagicMock:
    """构造一个具备 User 字段形状的 MagicMock——避免走真实 SQLAlchemy mapper 初始化。

    AuthService 只读/写 user 的若干属性(id/email/password_hash/status/failed_login_count/
    locked_until/must_change_password/token_version),不需要真 ORM 对象。
    """
    u = MagicMock(spec_set=[
        "id", "email", "password_hash", "display_name", "status",
        "failed_login_count", "locked_until", "must_change_password", "token_version",
    ])
    u.id = user_id or uuid4()
    u.email = email
    u.password_hash = hash_password(password)
    u.display_name = email.split("@")[0]
    u.status = status
    u.failed_login_count = failed_login_count
    u.locked_until = locked_until
    u.token_version = token_version
    u.must_change_password = must_change_password
    return u


def _build_service() -> tuple[AuthService, AsyncMock, AsyncMock, AsyncMock]:
    """构造 AuthService + mock 出来的 user_repo / member_repo / session。"""
    user_repo = AsyncMock()
    member_repo = AsyncMock()
    session = AsyncMock()
    service = AuthService(user_repo, member_repo, session)
    return service, user_repo, member_repo, session


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_hashes_password_and_returns_token(self):
        service, user_repo, _member_repo, session = _build_service()
        user_repo.exists_by_email.return_value = False

        saved_users: list[MagicMock] = []

        async def _save(u):
            # 真实 save() 会 flush 数据库让 gen_random_uuid() 触发,这里模拟相同行为
            if getattr(u, "id", None) is None:
                u.id = uuid4()
            saved_users.append(u)
            return u

        user_repo.save.side_effect = _save

        result = await service.register("Alice@Example.com", _VALID_PASSWORD, None)

        assert result.token  # 非空
        # 邮箱被规范化(小写 + strip)
        assert saved_users, "user_repo.save 应该被调用"
        u = saved_users[0]
        assert u.email == "alice@example.com"
        # 密码不能明文回写
        assert u.password_hash != _VALID_PASSWORD
        assert verify_password(_VALID_PASSWORD, u.password_hash)
        # display_name 默认取邮箱本地部分。
        # 已知问题(2026-07):实现在 `email.lower().strip()` 之后才规范化邮箱,
        # 但 `display_name` 仍使用原始入参 `email.split("@")[0]`——结果是大写
        # 邮箱注册时 display_name 会保留原始大小写("Alice" 而不是 "alice")。
        # 见报告里的疑似 bug 列表。这里只锁定"实现实际写了什么"作为现状。
        assert u.display_name == "Alice"
        # commit 被调用(成功路径上必须落库)
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_register_uses_explicit_display_name(self):
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.exists_by_email.return_value = False

        captured: list[MagicMock] = []

        async def _save(u):
            if getattr(u, "id", None) is None:
                u.id = uuid4()
            captured.append(u)
            return u

        user_repo.save.side_effect = _save

        await service.register("bob@example.com", _VALID_PASSWORD, "Bob 显式昵称")
        assert captured[0].display_name == "Bob 显式昵称"

    @pytest.mark.asyncio
    async def test_register_rejects_duplicate_email(self):
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.exists_by_email.return_value = True

        with pytest.raises(BusinessConflictException):
            await service.register("dup@example.com", _VALID_PASSWORD, None)
        # 不应调用 save/commit(duplicate 必须短路)
        user_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_rejects_invalid_email_format(self):
        service, user_repo, _member_repo, _session = _build_service()

        with pytest.raises(ValueError):
            await service.register("not-an-email", _VALID_PASSWORD, None)
        user_repo.exists_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_rejects_empty_email(self):
        service, user_repo, _member_repo, _session = _build_service()

        with pytest.raises(ValueError):
            await service.register("", _VALID_PASSWORD, None)
        user_repo.exists_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_rejects_weak_password(self):
        service, user_repo, _member_repo, session = _build_service()
        user_repo.exists_by_email.return_value = False

        with pytest.raises(ValueError):
            await service.register("weak@example.com", "short", None)
        # 弱密码应当在校验阶段失败,不要触达 save/commit
        user_repo.save.assert_not_called()
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_rejects_password_without_digit(self):
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.exists_by_email.return_value = False

        with pytest.raises(ValueError):
            await service.register("a@example.com", "NoDigitsHere", None)

    @pytest.mark.asyncio
    async def test_password_pattern_rejects_under_8_chars(self):
        """_PASSWORD_PATTERN 是 8 位 + 字母 + 数字——少一位都不行。"""
        assert not _PASSWORD_PATTERN.match("Aa1!")  # 4 位
        assert not _PASSWORD_PATTERN.match("Aa1!abc")  # 7 位
        assert _PASSWORD_PATTERN.match("Aa1!abcd")  # 8 位


class TestLoginSuccess:
    @pytest.mark.asyncio
    async def test_login_success_returns_token_and_user_id(self):
        user = _make_user()
        service, user_repo, member_repo, session = _build_service()
        user_repo.find_by_email.return_value = user
        member_repo.find_first_by_subject_id_order_by_created_at_asc.return_value = None

        result = await service.login("alice@example.com", _VALID_PASSWORD)

        assert result.token
        assert result.user_id == user.id
        # 失败计数清零
        assert user.failed_login_count == 0
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_login_normalizes_email_before_lookup(self):
        """大小写/空格不区分——避免运维改邮箱大小写后登不进来。"""
        user = _make_user(email="alice@example.com")
        service, user_repo, member_repo, _session = _build_service()
        user_repo.find_by_email.return_value = user
        # 显式置 None,避免 AsyncMock 默认行为被当对象访问导致 .org_id 是 Mock
        member_repo.find_first_by_subject_id_order_by_created_at_asc.return_value = None

        await service.login("  ALICE@Example.com  ", _VALID_PASSWORD)
        user_repo.find_by_email.assert_awaited_with("alice@example.com")

    @pytest.mark.asyncio
    async def test_login_returns_org_id_from_first_membership(self):
        """登录后从 member 表里查首个成员身份作为默认 orgId 返回。"""
        user = _make_user()
        first_member = MagicMock()
        first_member.org_id = uuid4()  # 必须是真实 UUID,不能是 MagicMock
        service, user_repo, member_repo, _session = _build_service()
        user_repo.find_by_email.return_value = user
        member_repo.find_first_by_subject_id_order_by_created_at_asc.return_value = first_member

        result = await service.login("alice@example.com", _VALID_PASSWORD)
        assert result.org_id == first_member.org_id

    @pytest.mark.asyncio
    async def test_login_propagates_must_change_password(self):
        user = _make_user(must_change_password=True)
        service, user_repo, member_repo, _session = _build_service()
        user_repo.find_by_email.return_value = user
        member_repo.find_first_by_subject_id_order_by_created_at_asc.return_value = None

        result = await service.login("alice@example.com", _VALID_PASSWORD)
        assert result.must_change_password is True


class TestLoginFailure:
    @pytest.mark.asyncio
    async def test_wrong_password_raises_and_increments_failure_count(self):
        user = _make_user(failed_login_count=2)
        service, user_repo, _member_repo, session = _build_service()
        user_repo.find_by_email.return_value = user

        with pytest.raises(UnauthenticatedException):
            await service.login("alice@example.com", "wrong-password")

        # 失败计数 +1,且必须 commit 落库(否则暴力破解锁定机制形同虚设)
        assert user.failed_login_count == 3
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_unknown_email_raises_without_incrementing(self):
        """邮箱不存在时:不抛错信息(防枚举),但也不应影响任何用户状态。"""
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.find_by_email.return_value = None

        with pytest.raises(UnauthenticatedException):
            await service.login("ghost@example.com", _VALID_PASSWORD)

        # 没找到用户,不应触达 save
        user_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_five_failures_locks_account(self):
        """第 5 次失败后账号应被锁定(LOCKED + locked_until 在未来)。"""
        user = _make_user(failed_login_count=MAX_LOGIN_FAILURES - 1)
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.find_by_email.return_value = user

        with pytest.raises(UnauthenticatedException):
            await service.login("alice@example.com", "wrong-password")

        assert user.status == UserStatus.LOCKED
        assert user.locked_until is not None
        # 锁定时间必须是未来,而不是过去
        assert user.locked_until > datetime.now(timezone.utc)


class TestAccountLocking:
    @pytest.mark.asyncio
    async def test_locked_account_rejects_login(self):
        user = _make_user(
            status=UserStatus.LOCKED,
            locked_until=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.find_by_email.return_value = user

        with pytest.raises(AccountLockedException):
            await service.login("alice@example.com", _VALID_PASSWORD)

    @pytest.mark.asyncio
    async def test_lock_expired_auto_unlocks(self):
        """锁定到期后,正确密码应该可以登进来(状态被清回 ACTIVE)。"""
        user = _make_user(
            status=UserStatus.LOCKED,
            locked_until=datetime.now(timezone.utc) - timedelta(seconds=1),
            failed_login_count=5,
        )
        service, user_repo, member_repo, _session = _build_service()
        user_repo.find_by_email.return_value = user
        member_repo.find_first_by_subject_id_order_by_created_at_asc.return_value = None

        result = await service.login("alice@example.com", _VALID_PASSWORD)
        # 解锁后状态被清掉,失败计数归零
        assert user.status == UserStatus.ACTIVE
        assert user.failed_login_count == 0
        assert user.locked_until is None
        assert result.token

    @pytest.mark.asyncio
    async def test_locked_with_no_locked_until_keeps_locked(self):
        """locked_until 为 None(数据异常)时,只要状态是 LOCKED 就一直拒绝——不能让它登进来。"""
        user = _make_user(status=UserStatus.LOCKED, locked_until=None)
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.find_by_email.return_value = user

        with pytest.raises(AccountLockedException):
            await service.login("alice@example.com", _VALID_PASSWORD)


class TestChangePassword:
    @pytest.mark.asyncio
    async def test_change_password_hashes_new_and_blacklists_token(self):
        user_id = uuid4()
        user = _make_user(user_id=user_id, password=_VALID_PASSWORD)
        service, user_repo, _member_repo, session = _build_service()
        user_repo.find_by_id.return_value = user

        # 避免真连 Redis(模块级 singleton 在跨事件循环时会爆"attached to a different loop")
        from app.core import redis_client as redis_client_module
        set_with_ttl_mock = AsyncMock()
        original = redis_client_module.set_with_ttl
        redis_client_module.set_with_ttl = set_with_ttl_mock
        try:
            await service.change_password(
                user_id=user_id,
                old_password=_VALID_PASSWORD,
                new_password=_VALID_PASSWORD_2,
                current_jti="old-jti-1",
                remaining_seconds=600,
            )
        finally:
            redis_client_module.set_with_ttl = original

        # 旧密码不再能 verify
        assert not verify_password(_VALID_PASSWORD, user.password_hash)
        # 新密码可以 verify
        assert verify_password(_VALID_PASSWORD_2, user.password_hash)
        # 改完不再强制下次必须改
        assert user.must_change_password is False
        session.commit.assert_awaited()
        # 旧 JWT 写入黑名单(redis_client.set_with_ttl 被调用)
        set_with_ttl_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_change_password_rejects_wrong_old(self):
        user_id = uuid4()
        user = _make_user(user_id=user_id, password=_VALID_PASSWORD)
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.find_by_id.return_value = user

        with pytest.raises(UnauthenticatedException):
            await service.change_password(
                user_id=user_id,
                old_password="WRONG",
                new_password=_VALID_PASSWORD_2,
                current_jti="old-jti",
                remaining_seconds=600,
            )
        # 密码不能被改
        assert verify_password(_VALID_PASSWORD, user.password_hash)

    @pytest.mark.asyncio
    async def test_change_password_user_not_found(self):
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.find_by_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.change_password(
                user_id=uuid4(),
                old_password="anything",
                new_password=_VALID_PASSWORD_2,
                current_jti=None,
                remaining_seconds=0,
            )

    @pytest.mark.asyncio
    async def test_change_password_rejects_weak_new(self):
        """新密码必须通过强度校验,不能改成 12345678(虽然 8 位+数字但缺字母)。"""
        user_id = uuid4()
        user = _make_user(user_id=user_id, password=_VALID_PASSWORD)
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.find_by_id.return_value = user

        with pytest.raises(ValueError):
            await service.change_password(
                user_id=user_id,
                old_password=_VALID_PASSWORD,
                new_password="12345678",  # 缺字母
                current_jti=None,
                remaining_seconds=0,
            )


class TestAdminResetPassword:
    @pytest.mark.asyncio
    async def test_owner_can_reset_and_bumps_token_version(self):
        caller = uuid4()
        target = _make_user(token_version=3)
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.find_by_id.return_value = target

        new_password = await service.admin_reset_password(
            caller_member_id=caller,
            target_user_id=target.id,
            caller_role="OWNER",
        )
        # 临时密码生成出来,12 位
        assert isinstance(new_password, str) and len(new_password) == 12
        # token_version 自增(旧 JWT 全部失效)
        assert target.token_version == 4
        assert target.must_change_password is True
        # 临时密码可以 verify
        assert verify_password(new_password, target.password_hash)
        _session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_admin_role_also_allowed(self):
        target = _make_user()
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.find_by_id.return_value = target

        new_password = await service.admin_reset_password(
            caller_member_id=uuid4(),
            target_user_id=target.id,
            caller_role="ADMIN",
        )
        assert new_password

    @pytest.mark.asyncio
    async def test_member_role_cannot_reset(self):
        service, _user_repo, _member_repo, _session = _build_service()

        with pytest.raises(AccessDeniedException):
            await service.admin_reset_password(
                caller_member_id=uuid4(),
                target_user_id=uuid4(),
                caller_role="MEMBER",
            )

    @pytest.mark.asyncio
    async def test_target_user_not_found(self):
        service, user_repo, _member_repo, _session = _build_service()
        user_repo.find_by_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.admin_reset_password(
                caller_member_id=uuid4(),
                target_user_id=uuid4(),
                caller_role="OWNER",
            )

    @pytest.mark.asyncio
    async def test_generated_temp_password_meets_requirements(self):
        """临时密码要 12 位,且能通过本服务的 password 强度校验(字母+数字至少 8 位)。"""
        from app.services.auth_service import AuthService

        service, _user_repo, _member_repo, _session = _build_service()
        for _ in range(20):  # 多跑几次,确保没有偶然"全部是字母"或"全部是数字"
            pwd = service._generate_temp_password()
            assert len(pwd) == 12
            assert _PASSWORD_PATTERN.match(pwd), f"临时密码 {pwd!r} 不符合强度要求"
