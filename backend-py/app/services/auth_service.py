"""认证服务:注册/登录/改密/重置。对应 Java 版 service/AuthService.java。

JWT 签发/解析、Redis 黑名单读写、token_version 比对这些底层能力已经在
`app.core.jwt_service` + `app.core.redis_client` + repository 层具备(鉴权依赖
`require_user_factory`/`require_tenant_factory` 也复用同一套),本类只负责 Java 版
AuthService 里 register/login/changePassword/adminResetPassword 这几个业务方法。

行为差异说明(刻意修正,非遗漏):Java 版 `login()` 整个方法在一个 `@Transactional` 里,
登录失败计数/账号锁定的 `userRepository.save()` 之后紧接着 `throw` 一个 `RuntimeException`
子类(`UnauthenticatedException`/`AccountLockedException`)——Spring 默认对 `RuntimeException`
回滚整个事务,这会导致失败计数增量和锁定状态实际上从未写入数据库,暴力破解锁定机制形同虚设。
这是安全关键路径,不允许"明知有洞还交付",因此 Python 版在失败计数/锁定落库后立即
`commit()`,再抛异常,确保锁定机制真实生效;其余方法维持"成功路径末尾统一 commit"的
惯例,与 Java 版 `@Transactional` 方法边界语义一致。
"""

from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jwt_service, redis_client
from app.exceptions.errors import (
    AccessDeniedException,
    AccountLockedException,
    BusinessConflictException,
    ResourceNotFoundException,
    UnauthenticatedException,
)
from app.models.enums import UserStatus
from app.models.user import User
from app.repositories.member_repository import MemberRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import AuthResult
from app.services.password_service import hash_password, verify_password

MAX_LOGIN_FAILURES = 5
LOCK_DURATION_MINUTES = 15
_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+$")
_PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


class AuthService:
    def __init__(
        self,
        user_repository: UserRepository,
        member_repository: MemberRepository,
        session: AsyncSession,
    ) -> None:
        self._users = user_repository
        self._members = member_repository
        self._session = session

    async def register(self, email: str, password: str, display_name: str | None) -> AuthResult:
        if not email or not _EMAIL_PATTERN.match(email):
            raise ValueError("邮箱格式不正确")
        if await self._users.exists_by_email(email):
            raise BusinessConflictException("该邮箱已注册")
        self._validate_password(password)

        user = User(
            email=email.lower().strip(),
            password_hash=hash_password(password),
            display_name=display_name if display_name else email.split("@")[0],
        )
        user = await self._users.save(user)
        await self._session.commit()

        token = jwt_service.generate_token(user.id, user.token_version)
        return AuthResult(token=token, userId=user.id)

    async def login(self, email: str, password: str) -> AuthResult:
        normalized_email = email.lower().strip() if email else ""
        user = await self._users.find_by_email(normalized_email)
        if user is None:
            # 统一返回,不泄露邮箱是否存在
            raise UnauthenticatedException("邮箱或密码错误")

        if user.status == UserStatus.LOCKED:
            if user.locked_until is not None and datetime.now(timezone.utc) > user.locked_until:
                user.status = UserStatus.ACTIVE
                user.failed_login_count = 0
                user.locked_until = None
                await self._users.save(user)
                await self._session.commit()
            else:
                raise AccountLockedException("账号已锁定,请稍后再试")

        if not verify_password(password, user.password_hash):
            await self._handle_login_failure(user)
            raise UnauthenticatedException("邮箱或密码错误")

        user.failed_login_count = 0
        await self._users.save(user)

        token = jwt_service.generate_token(user.id, user.token_version)
        org_id: UUID | None = None
        first_member = await self._members.find_first_by_subject_id_order_by_created_at_asc(str(user.id))
        if first_member is not None:
            org_id = first_member.org_id

        must_change_password = user.must_change_password
        await self._session.commit()

        return AuthResult(
            token=token,
            userId=user.id,
            orgId=org_id,
            mustChangePassword=True if must_change_password else None,
        )

    async def change_password(
        self,
        user_id: UUID,
        old_password: str,
        new_password: str,
        current_jti: str | None,
        remaining_seconds: int,
    ) -> None:
        """事务提交后再将当前 JWT jti 写入 Redis 黑名单(确保原子性)。"""
        user = await self._users.find_by_id(user_id)
        if user is None:
            raise ResourceNotFoundException("用户不存在")

        if not verify_password(old_password, user.password_hash):
            raise UnauthenticatedException("旧密码错误")
        self._validate_password(new_password)

        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        await self._users.save(user)
        await self._session.commit()

        await self._blacklist_token(current_jti, remaining_seconds)

    async def admin_reset_password(self, caller_member_id: UUID, target_user_id: UUID, caller_role: str) -> str:
        if caller_role not in ("OWNER", "ADMIN"):
            raise AccessDeniedException("只有 owner/admin 可以重置密码")

        target_user = await self._users.find_by_id(target_user_id)
        if target_user is None:
            raise ResourceNotFoundException("用户不存在")

        temp_password = self._generate_temp_password()
        target_user.password_hash = hash_password(temp_password)
        target_user.must_change_password = True
        target_user.token_version = target_user.token_version + 1  # 旧 JWT 全部失效
        await self._users.save(target_user)
        await self._session.commit()

        return temp_password

    async def _blacklist_token(self, jti: str | None, remaining_seconds: int) -> None:
        if jti and remaining_seconds > 0:
            await redis_client.set_with_ttl(f"blacklist:jti:{jti}", "1", remaining_seconds)

    async def _handle_login_failure(self, user: User) -> None:
        user.failed_login_count = user.failed_login_count + 1
        if user.failed_login_count >= MAX_LOGIN_FAILURES:
            user.status = UserStatus.LOCKED
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCK_DURATION_MINUTES)
        await self._users.save(user)
        # 安全关键:落库后立即提交,确保锁定状态真实生效(见模块文档字符串)。
        await self._session.commit()

    def _validate_password(self, password: str | None) -> None:
        if not password or not _PASSWORD_PATTERN.match(password):
            raise ValueError("密码至少 8 位,必须包含字母和数字")

    def _generate_temp_password(self) -> str:
        """12 位: 3 大写 + 3 小写 + 3 数字 + 3 特殊字符,打乱顺序。"""
        upper = string.ascii_uppercase
        lower = string.ascii_lowercase
        digits = string.digits
        special = "!@#$%^&*"
        chars = (
            [secrets.choice(upper) for _ in range(3)]
            + [secrets.choice(lower) for _ in range(3)]
            + [secrets.choice(digits) for _ in range(3)]
            + [secrets.choice(special) for _ in range(3)]
        )
        secrets.SystemRandom().shuffle(chars)
        return "".join(chars)
