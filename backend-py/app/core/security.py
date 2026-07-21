"""JWT 鉴权 + 租户上下文注入依赖。对应 Java 版 JwtAuthFilter 的 8 步校验:

1. 从 Authorization 头取 Bearer token
2. 解析 JWT 签名+有效期
3. Redis jti 黑名单检查 —— Redis 不可达时 fail-close(503),不是 fail-open
4. token_version 比对(管理员重置密码后旧 token 全部失效)
5. 免租户上下文端点(创建组织/改密)只需 JWT subject,不查 member —— 由调用方选用
   require_user 还是 require_tenant 两个依赖来区分,不是像 Java 版那样按 URL 路径判断
6. X-Org-Id 请求头解析
7. 服务端查 member(subject + orgId → role),查不到即 401
8. 设置租户上下文(org_id/member_id/role),FastAPI 中间件在响应结束后清理

关键差异说明:Java 版用 shouldNotFilter() 按 URL 前缀免鉴权;FastAPI 里更明确的做法是
按路由显式声明依赖 require_user/require_tenant,未声明依赖的路由(如 /health)天然不
鉴权,不需要维护一份和路由表分离的排除列表。
"""

from typing import Protocol
from uuid import UUID

from fastapi import Header, HTTPException, Request

from app.core import jwt_service, redis_client
from app.core.tenant_context import set_tenant_context


class TokenVersionLookup(Protocol):
    """由 repository 层实现,security.py 不直接依赖 SQLAlchemy 模型。"""

    async def get_token_version(self, user_id: UUID) -> int: ...


class MemberLookup(Protocol):
    """(subject_id, org_id) -> (member_id, role);查不到返回 None。"""

    async def find_member(self, subject_id: str, org_id: UUID) -> tuple[UUID, str] | None: ...


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if header is None or not header.startswith("Bearer "):
        return None
    return header[len("Bearer ") :]


async def _authenticate(request: Request, token_version_lookup: TokenVersionLookup) -> tuple[str, str, int]:
    """公共前 4 步:返回 (subject, jti, remaining_seconds)。失败直接抛 HTTPException。"""
    token = _extract_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="未携带有效认证凭证")

    claims = jwt_service.parse_token(token)
    if claims is None:
        raise HTTPException(status_code=401, detail="无效或已过期的 token")

    if not await redis_client.is_available():
        raise HTTPException(status_code=503, detail="认证服务不可用")
    if await redis_client.exists(f"blacklist:jti:{claims.jti}"):
        raise HTTPException(status_code=401, detail="token 已失效")

    current_tv = await token_version_lookup.get_token_version(UUID(claims.sub))
    if claims.tv != current_tv:
        raise HTTPException(status_code=401, detail="token 已失效(密码已被重置)")

    request.state.jwt_jti = claims.jti
    request.state.jwt_remaining_seconds = jwt_service.remaining_seconds(claims)
    request.state.user_id = UUID(claims.sub)
    return claims.sub, claims.jti, jwt_service.remaining_seconds(claims)


def require_user_factory(token_version_lookup: TokenVersionLookup):
    """免租户上下文端点用(创建组织/改密):只校验 JWT,不查 member。"""

    async def _dep(request: Request) -> str:
        subject, _jti, _remaining = await _authenticate(request, token_version_lookup)
        return subject

    return _dep


def require_tenant_factory(token_version_lookup: TokenVersionLookup, member_lookup: MemberLookup):
    """常规业务端点用:JWT + X-Org-Id + member 归属校验,写入租户上下文。

    关于 X-Org-Id 状态码:Java 版对"头缺失"和"头非法"统一返回 401。Python 版必须把
    `x_org_id` 声明为 `default=None` 关闭 FastAPI 自动校验,再在函数体里显式判 None
    和 UUID 解析失败,让两种情况都走同一 401 分支——否则"头缺失"会被 FastAPI 抛
    RequestValidationError 走 400,与 Java 版不一致。
    """

    async def _dep(
        request: Request,
        x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    ) -> UUID:
        subject, _jti, _remaining = await _authenticate(request, token_version_lookup)

        if x_org_id is None:
            raise HTTPException(status_code=401, detail="缺少或非法的 X-Org-Id 请求头")
        try:
            org_id = UUID(x_org_id)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=401, detail="缺少或非法的 X-Org-Id 请求头") from exc

        result = await member_lookup.find_member(subject, org_id)
        if result is None:
            raise HTTPException(status_code=401, detail="该主体在此组织无成员身份")
        member_id, role = result

        set_tenant_context(org_id=org_id, member_id=member_id, role=role)
        return org_id

    return _dep
