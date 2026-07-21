"""请求级租户上下文。

对应 Java 版 TenantContext(ThreadLocal)。FastAPI/uvicorn 是单线程多协程模型,
并发请求共享同一批线程,普通 ThreadLocal 或全局变量会在并发请求间串号——必须用
contextvars.ContextVar,它按 asyncio task 隔离,语义上才等价于"每请求一份"。
生命周期:鉴权依赖里 set,请求结束时中间件 clear;不清理会导致连接池复用连接时
残留上一个请求的租户信息。
"""

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TenantContext:
    org_id: UUID
    member_id: UUID
    role: str


_tenant_context: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def set_tenant_context(org_id: UUID, member_id: UUID, role: str) -> None:
    _tenant_context.set(TenantContext(org_id=org_id, member_id=member_id, role=role))


def get_tenant_context() -> TenantContext:
    ctx = _tenant_context.get()
    if ctx is None:
        raise RuntimeError("租户上下文未初始化:必须先经过鉴权依赖才能访问")
    return ctx


def clear_tenant_context() -> None:
    _tenant_context.set(None)
