"""JWT 鉴权依赖(`require_user_factory` / `require_tenant_factory`)测试。

对照 Java 版 `JwtAuthFilter` 的 8 步校验:
1. Authorization 头取 Bearer token
2. JWT 解析(签名+有效期)
3. Redis jti 黑名单(不可达 → 503)
4. token_version 比对
5. require_user 路径不查 member(require_tenant 路径查)
6. X-Org-Id 头解析
7. member 归属查询(找不到 → 401)
8. 写租户上下文

用 FastAPI `TestClient` + 自构造的 minimal app 跑端到端,所有外部依赖(redis/jwt/repo)
都用 monkeypatch / dependency_overrides 替换。
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI, Header
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.core.security import require_tenant_factory, require_user_factory


# ----------------------------- fixtures & helpers -----------------------------

JWT_SECRET = settings.jwt_secret
JWT_ALG = "HS256"


def _make_token(
    user_id: str,
    jti: str | None = None,
    token_version: int = 0,
    exp_offset: int = 3600,
) -> str:
    payload = {
        "sub": user_id,
        "jti": jti or str(uuid.uuid4()),
        "tv": token_version,
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _build_token_version_lookup(tv: int = 0):
    """UserRepository 的 token_version 查表 stub。"""
    repo = MagicMock()
    repo.get_token_version = AsyncMock(return_value=tv)
    return repo


def _build_member_lookup(found: tuple[UUID, str] | None = None):
    """MemberRepository 的 (subject_id, org_id) → (member_id, role) 查表 stub。"""
    repo = MagicMock()
    repo.find_member = AsyncMock(return_value=found)
    return repo


# 1) 只用 require_user(免租户上下文端点),用来专门测前 4 步校验
_user_app = FastAPI()


@_user_app.get("/protected")
async def protected(
    request,
    x_user: str = Header(alias="X-User-Id"),
):
    # 实际由 require_user 注入,这里不依赖 jwt 解析,只用于触发 dep chain
    return {"user": x_user}


_user_app_with_dep = FastAPI()


@_user_app_with_dep.get("/who")
async def who(subject: str):
    return {"subject": subject}


_user_app_with_dep.router.dependency_overrides = {}
_dep_user = require_user_factory(_build_token_version_lookup(tv=0))
_user_app_with_dep.dependency_overrides[_dep_user] = lambda: "subject-123"


# 2) 完整 require_tenant 校验链(可控制 redis / token_version / member 三个外部依赖)
_tenant_app = FastAPI()


@_tenant_app.get("/protected")
async def protected(
    request,
    org_id: UUID = None,  # placeholder,实际从 dep 拿
):
    from app.core.tenant_context import get_tenant_context

    ctx = get_tenant_context()
    return {"org_id": str(ctx.org_id), "member_id": str(ctx.member_id), "role": ctx.role}


# 通用工具:对一个 app 临时替换 redis_client / jwt_service / repos
def _patch_security_deps(
    monkeypatch,
    *,
    is_redis_available: bool = True,
    blacklist_hit: bool = False,
    token_version: int = 0,
    member_found: tuple[UUID, str] | None = None,
    jwt_invalid: bool = False,
):
    """monkeypatch app.core.security 内部用到的 redis_client / jwt_service。"""
    from app.core import jwt_service, redis_client, security

    if jwt_invalid:
        security.jwt_service.parse_token = MagicMock(return_value=None)
    else:
        # 默认走正常路径
        security.jwt_service.parse_token = jwt_service.parse_token

    security.redis_client.is_available = AsyncMock(return_value=is_redis_available)
    security.redis_client.exists = AsyncMock(return_value=blacklist_hit)

    # token_version 查表
    tv_lookup = MagicMock()
    tv_lookup.get_token_version = AsyncMock(return_value=token_version)

    # member 查表
    member_lookup = MagicMock()
    member_lookup.find_member = AsyncMock(return_value=member_found)

    return tv_lookup, member_lookup


# ----------------------------- require_user (无 tenant 校验) -----------------------------

class TestRequireUser:
    def test_missing_authorization_header_returns_401(self):
        """无 Authorization 头 → 401。"""
        from app.exceptions import register_exception_handlers

        tv_lookup = _build_token_version_lookup()
        app = FastAPI()
        register_exception_handlers(app)
        dep = require_user_factory(tv_lookup)

        @app.get("/p", dependencies=[Depends(dep)])
        async def p():
            return {"ok": True}

        client = TestClient(app)
        r = client.get("/p")
        assert r.status_code == 401
        body = r.json()
        # 走 ApiResponse 形状 {code, message}
        assert body.get("code") == 401
        assert "凭证" in body.get("message", "") or "未携带" in body.get("message", "")

    def test_malformed_authorization_header_returns_401(self):
        from app.exceptions import register_exception_handlers

        tv_lookup = _build_token_version_lookup()
        app = FastAPI()
        register_exception_handlers(app)
        dep = require_user_factory(tv_lookup)

        @app.get("/p", dependencies=[Depends(dep)])
        async def p():
            return {"ok": True}

        client = TestClient(app)
        # 没 Bearer 前缀
        r = client.get("/p", headers={"Authorization": "Token abc"})
        assert r.status_code == 401

    def test_invalid_token_returns_401(self, monkeypatch):
        """token 签名错误或过期 → 401。"""
        from app.core import security
        from app.exceptions import register_exception_handlers

        tv_lookup = _build_token_version_lookup()
        security.jwt_service.parse_token = MagicMock(return_value=None)

        dep = require_user_factory(tv_lookup)
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/p", dependencies=[Depends(dep)])
        async def p():
            return {"ok": True}

        client = TestClient(app)
        r = client.get("/p", headers={"Authorization": "Bearer invalid.token.value"})
        assert r.status_code == 401
        assert "无效" in r.json()["message"] or "过期" in r.json()["message"]

    def test_redis_unavailable_returns_503(self, monkeypatch):
        """Redis 不可达 → 503(对 JWT 黑名单场景是 fail-close,不是 fail-open)——必须正确返回 503。"""
        from app.core import security
        from app.exceptions import register_exception_handlers

        security.jwt_service.parse_token = MagicMock(
            return_value=MagicMock(sub=str(uuid.uuid4()), jti="jti-1", tv=0, exp=9999999999)
        )
        security.redis_client.is_available = AsyncMock(return_value=False)

        tv_lookup = _build_token_version_lookup()
        dep = require_user_factory(tv_lookup)
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/p", dependencies=[Depends(dep)])
        async def p():
            return {"ok": True}

        client = TestClient(app)
        token = _make_token(str(uuid.uuid4()))
        r = client.get("/p", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 503
        assert "不可用" in r.json()["message"]

    def test_blacklisted_token_returns_401(self, monkeypatch):
        from app.core import security
        from app.exceptions import register_exception_handlers

        security.jwt_service.parse_token = MagicMock(
            return_value=MagicMock(sub=str(uuid.uuid4()), jti="jti-2", tv=0, exp=9999999999)
        )
        security.redis_client.is_available = AsyncMock(return_value=True)
        security.redis_client.exists = AsyncMock(return_value=True)  # 在黑名单里

        tv_lookup = _build_token_version_lookup()
        dep = require_user_factory(tv_lookup)
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/p", dependencies=[Depends(dep)])
        async def p():
            return {"ok": True}

        client = TestClient(app)
        token = _make_token(str(uuid.uuid4()))
        r = client.get("/p", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        assert "失效" in r.json()["message"]

    def test_token_version_mismatch_returns_401(self, monkeypatch):
        """JWT 里的 tv 与 DB 不一致(密码已被重置) → 401。"""
        from app.core import security
        from app.exceptions import register_exception_handlers

        user_id = str(uuid.uuid4())
        security.jwt_service.parse_token = MagicMock(
            return_value=MagicMock(sub=user_id, jti="jti-3", tv=0, exp=9999999999)
        )
        security.redis_client.is_available = AsyncMock(return_value=True)
        security.redis_client.exists = AsyncMock(return_value=False)

        # DB 里 tv 已经自增到 5
        tv_lookup = _build_token_version_lookup(tv=5)
        dep = require_user_factory(tv_lookup)
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/p", dependencies=[Depends(dep)])
        async def p():
            return {"ok": True}

        client = TestClient(app)
        token = _make_token(user_id)
        r = client.get("/p", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        assert "失效" in r.json()["message"]


# ----------------------------- require_tenant (含 X-Org-Id + member) -----------------------------

class TestRequireTenant:
    def _build_app(self, monkeypatch, *, redis_ok=True, blacklist=False, tv=0, member=None):
        from app.core import security
        from app.exceptions import register_exception_handlers

        user_id = str(uuid.uuid4())
        security.jwt_service.parse_token = MagicMock(
            return_value=MagicMock(sub=user_id, jti="jti-tenant", tv=tv, exp=9999999999)
        )
        security.redis_client.is_available = AsyncMock(return_value=redis_ok)
        security.redis_client.exists = AsyncMock(return_value=blacklist)

        tv_lookup = _build_token_version_lookup(tv=tv)
        member_lookup = _build_member_lookup(found=member)
        dep = require_tenant_factory(tv_lookup, member_lookup)

        app = FastAPI()
        register_exception_handlers(app)

        from app.core.tenant_context import get_tenant_context

        @app.get("/p", dependencies=[Depends(dep)])
        async def p():
            ctx = get_tenant_context()
            return {"org_id": str(ctx.org_id), "member_id": str(ctx.member_id), "role": ctx.role}

        return app, dep, user_id

    def test_happy_path_writes_tenant_context(self, monkeypatch):
        org_id, member_id = uuid.uuid4(), uuid.uuid4()
        app, _dep, user_id = self._build_app(
            monkeypatch, member=(member_id, "OWNER")
        )
        token = _make_token(user_id)
        client = TestClient(app)
        r = client.get("/p", headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": str(org_id),
        })
        assert r.status_code == 200
        body = r.json()
        assert body["org_id"] == str(org_id)
        assert body["member_id"] == str(member_id)
        assert body["role"] == "OWNER"

    def test_missing_x_org_id_returns_401(self, monkeypatch):
        """缺 X-Org-Id 头 → 401(与"非法 UUID 值"返回同一状态码,和 Java 版对齐)。

        实现要求:`x_org_id` 必须声明为 `default=None`,关闭 FastAPI 自动校验,让"头缺失"
        和"头非法"统一在 dep 函数体里走 401。否则"头缺失"会被 FastAPI Header() 校验拦截
        返回 400,行为与 Java 版(`JwtAuthFilter` 统一 401)不一致。
        """
        org_id, member_id = uuid.uuid4(), uuid.uuid4()
        app, _dep, user_id = self._build_app(
            monkeypatch, member=(member_id, "OWNER")
        )
        token = _make_token(user_id)
        client = TestClient(app)
        r = client.get("/p", headers={"Authorization": f"Bearer {token}"})
        # 实际行为:401(dep 自己判 None 抛出)
        assert r.status_code == 401
        body = r.json()
        assert body.get("code") == 401
        assert "X-Org-Id" in body.get("message", "")

    def test_malformed_x_org_id_returns_401(self, monkeypatch):
        """X-Org-Id 是非 UUID 字符串 → 401(走到 dep body 自己 catch)。"""
        org_id, member_id = uuid.uuid4(), uuid.uuid4()
        app, _dep, user_id = self._build_app(
            monkeypatch, member=(member_id, "OWNER")
        )
        token = _make_token(user_id)
        client = TestClient(app)
        r = client.get("/p", headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": "not-a-uuid",
        })
        assert r.status_code == 401
        assert "X-Org-Id" in r.json()["message"]

    def test_member_not_in_org_returns_401(self, monkeypatch):
        """subject 在该 org 没有 member 身份 → 401(可能是 token 用了别人的 org)。"""
        org_id = uuid.uuid4()
        app, _dep, user_id = self._build_app(
            monkeypatch, member=None  # 找不到 member
        )
        token = _make_token(user_id)
        client = TestClient(app)
        r = client.get("/p", headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": str(org_id),
        })
        assert r.status_code == 401
        assert "成员" in r.json()["message"] or "无成员" in r.json()["message"]

    def test_blacklisted_token_401(self, monkeypatch):
        """黑名单 token 在 require_tenant 路径上同样 401(前 4 步统一)。"""
        app, _dep, user_id = self._build_app(
            monkeypatch, blacklist=True,
        )
        token = _make_token(user_id)
        client = TestClient(app)
        r = client.get("/p", headers={
            "Authorization": f"Bearer {token}",
            "X-Org-Id": str(uuid.uuid4()),
        })
        assert r.status_code == 401
