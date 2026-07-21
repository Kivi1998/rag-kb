"""对应 repository/UserRepository.java。

同时实现 app.core.security.TokenVersionLookup Protocol(鸭子类型,不需要显式继承):
`get_token_version(user_id) -> int`,对应 Java 版 `AuthService.getTokenVersion`——
查不到用户时返回 0(而不是抛异常),语义与「未设置过 token_version 的默认值」一致,
调用方(JWT 鉴权依赖)会用它和 JWT claims 里的 tv 比对,不一致则判定 token 已失效。
"""

from uuid import UUID

from sqlalchemy import select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def find_by_email(self, email: str) -> User | None:
        """对应 Java findByEmail。"""
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def exists_by_email(self, email: str) -> bool:
        """对应 Java existsByEmail。"""
        stmt = select(User.id).where(User.email == email).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_token_version(self, user_id: UUID) -> int:
        """满足 app.core.security.TokenVersionLookup Protocol;查不到用户返回 0。"""
        user = await self.find_by_id(user_id)
        return user.token_version if user is not None else 0
