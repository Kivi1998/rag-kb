"""路由层共享依赖:把 `app.core.security` 里的鉴权依赖工厂(`require_user_factory`/
`require_tenant_factory`)与请求级 `AsyncSession`(`app.core.db.get_db`)组装成 FastAPI
可以直接 `Depends()` 的函数。

`app.core.security` 的两个工厂需要一个实现 TokenVersionLookup/MemberLookup Protocol 的实例
——`UserRepository`/`MemberRepository` 天然满足(鸭子类型),但它们都绑定在某个具体请求的
`AsyncSession` 上,不能像 Java Spring 单例 bean 那样在模块加载期一次性调用工厂;这里改成
每次请求都用当前请求的 session 现构造一次(开销可忽略,只是闭包创建)。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import require_tenant_factory, require_user_factory
from app.repositories.member_repository import MemberRepository
from app.repositories.user_repository import UserRepository


async def require_user(request: Request, db: AsyncSession = Depends(get_db)) -> str:
    """免租户上下文端点用(创建组织/改密):只校验 JWT,不查 member。返回 JWT subject(userId 字符串)。"""
    user_repository = UserRepository(db)
    dependency = require_user_factory(user_repository)
    return await dependency(request)


async def require_tenant(
    request: Request,
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    """常规业务端点用:JWT + X-Org-Id + member 归属校验,写入租户上下文。返回 org_id。

    关于 X-Org-Id 状态码:`x_org_id` 必须声明为 `default=None` 关闭 FastAPI 自动校验,
    让"头缺失"和"头非法"统一在 `require_tenant_factory` 里走 401,不对外暴露 FastAPI
    自动 400 校验——这是为了和 Java 版保持一致。
    """
    user_repository = UserRepository(db)
    member_repository = MemberRepository(db)
    dependency = require_tenant_factory(user_repository, member_repository)
    return await dependency(request, x_org_id)


def get_session(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    """路由/服务工厂里统一用这个而不是直接 `Depends(get_db)`,便于将来替换而不改各路由签名。"""
    return db
