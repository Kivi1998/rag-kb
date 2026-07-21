"""认证路由器测试(register / login / change-password)。

对照 Java 版 controller/AuthController.java + service/AuthService.java。
重点:
- /api/v1/auth/register、/login 是免认证端点
- /api/v1/auth/change-password 需 JWT,鉴权失败(无 token)→ 401
- 业务校验失败(ValueError、BusinessConflictException)映射到对应 HTTP 状态码
- 业务成功 → 200/201 + ApiResponse.data
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import settings
from app.exceptions import register_exception_handlers
from app.models.enums import UserStatus
from app.routers import auth
from app.routers.deps import require_user
from app.services.auth_service import AuthService
from app.services.password_service import hash_password, verify_password

JWT_SECRET = settings.jwt_secret
JWT_ALG = "HS256"


def _make_token(user_id: str, tv: int = 0, jti: str | None = None, exp_offset: int = 3600) -> str:
    payload = {
        "sub": user_id,
        "jti": jti or str(uuid.uuid4()),
        "tv": tv,
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _build_user(**overrides) -> MagicMock:
    u = MagicMock(spec_set=[
        "id", "email", "password_hash", "display_name", "status",
        "failed_login_count", "locked_until", "must_change_password", "token_version",
    ])
    u.id = overrides.get("id", uuid.uuid4())
    u.email = overrides.get("email", "alice@example.com")
    u.password_hash = overrides.get("password_hash", hash_password("Sup3rSecret!"))
    u.display_name = overrides.get("display_name", "alice")
    u.status = overrides.get("status", UserStatus.ACTIVE)
    u.failed_login_count = overrides.get("failed_login_count", 0)
    u.locked_until = overrides.get("locked_until", None)
    u.token_version = overrides.get("token_version", 0)
    u.must_change_password = overrides.get("must_change_password", False)
    return u


def _build_user_repo(user_obj: MagicMock | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.exists_by_email.return_value = False
    repo.find_by_email.return_value = user_obj
    repo.find_by_id.return_value = user_obj
    repo.get_token_version.return_value = 0

    async def _save(entity):
        # 真实 save() 会 flush DB 触发 gen_random_uuid(),这里模拟相同行为
        if getattr(entity, "id", None) is None:
            entity.id = uuid.uuid4()
        return entity

    repo.save.side_effect = _save
    return repo


def _build_member_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.find_first_by_subject_id_order_by_created_at_asc.return_value = None
    return repo


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth.router)
    return app


# ----------------------------- /register -----------------------------

class TestRegister:
    def test_register_success_returns_201_with_token(self):
        app = _build_app()
        user_repo = _build_user_repo()
        service = AuthService(user_repo, _build_member_repo(), AsyncMock())
        app.dependency_overrides[auth._auth_service] = lambda: service

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/register",
            json={"email": "Alice@Example.com", "password": "Sup3rSecret!"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["token"]

    def test_register_duplicate_email_returns_409(self):
        app = _build_app()
        user_repo = _build_user_repo()
        user_repo.exists_by_email.return_value = True
        service = AuthService(user_repo, _build_member_repo(), AsyncMock())
        app.dependency_overrides[auth._auth_service] = lambda: service

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/register",
            json={"email": "dup@example.com", "password": "Sup3rSecret!"},
        )
        assert r.status_code == 409
        assert r.json()["code"] == 409

    def test_register_weak_password_returns_400(self):
        app = _build_app()
        user_repo = _build_user_repo()
        service = AuthService(user_repo, _build_member_repo(), AsyncMock())
        app.dependency_overrides[auth._auth_service] = lambda: service

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/register",
            json={"email": "x@example.com", "password": "short"},
        )
        assert r.status_code == 400

    def test_register_invalid_email_returns_400(self):
        """邮箱格式不合法(走 pydantic 校验或 service 正则,都返回 400)。"""
        app = _build_app()
        user_repo = _build_user_repo()
        service = AuthService(user_repo, _build_member_repo(), AsyncMock())
        app.dependency_overrides[auth._auth_service] = lambda: service

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/register",
            json={"email": "not-an-email", "password": "Sup3rSecret!"},
        )
        assert r.status_code == 400


# ----------------------------- /login -----------------------------

class TestLogin:
    def test_login_success_returns_token(self):
        u = _build_user()
        app = _build_app()
        user_repo = _build_user_repo(user_obj=u)
        service = AuthService(user_repo, _build_member_repo(), AsyncMock())
        app.dependency_overrides[auth._auth_service] = lambda: service

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "Sup3rSecret!"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["token"]
        assert body["data"]["userId"] == str(u.id)

    def test_login_wrong_password_returns_401(self):
        u = _build_user()
        app = _build_app()
        user_repo = _build_user_repo(user_obj=u)
        service = AuthService(user_repo, _build_member_repo(), AsyncMock())
        app.dependency_overrides[auth._auth_service] = lambda: service

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "WrongPass1!"},
        )
        assert r.status_code == 401

    def test_login_unknown_email_returns_401(self):
        """邮箱不存在也返回 401(不泄露存在性)。"""
        app = _build_app()
        user_repo = _build_user_repo(user_obj=None)
        user_repo.find_by_email.return_value = None
        service = AuthService(user_repo, _build_member_repo(), AsyncMock())
        app.dependency_overrides[auth._auth_service] = lambda: service

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "Sup3rSecret!"},
        )
        assert r.status_code == 401


# ----------------------------- /change-password -----------------------------

class TestChangePassword:
    def _build_change_pw_app(self, user_obj: MagicMock) -> tuple[FastAPI, MagicMock]:
        """构造一个最小可跑的 /change-password 测试 app:
        - 把 require_user 替换为"直接返回 subject + 设置 state"的 stub
        - 把 _auth_service 替换为对 AsyncMock repo 的 service
        """
        user_repo = _build_user_repo(user_obj=user_obj)
        member_repo = _build_member_repo()
        service = AuthService(user_repo, member_repo, AsyncMock())

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(auth.router)
        app.dependency_overrides[auth._auth_service] = lambda: service

        user_id = user_obj.id

        async def _req_user(request: FastAPIRequest):
            request.state.user_id = user_id
            request.state.jwt_jti = "jti-1"
            request.state.jwt_remaining_seconds = 600
            return str(user_id)

        app.dependency_overrides[require_user] = _req_user
        return app, user_repo

    def test_missing_token_returns_401(self):
        """无 Authorization 头 → require_user 抛 401。"""
        u = _build_user()
        app, _ = self._build_change_pw_app(u)

        # 撤销 require_user override,改成一个直接抛 401 的版本
        async def _401():
            raise HTTPException(status_code=401, detail="未携带有效认证凭证")

        app.dependency_overrides[require_user] = _401

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/change-password",
            json={"oldPassword": "Sup3rSecret!", "newPassword": "An0therPass"},
        )
        assert r.status_code == 401

    def test_change_password_happy_path(self):
        u = _build_user(must_change_password=True)
        app, _user_repo = self._build_change_pw_app(u)

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/change-password",
            json={"oldPassword": "Sup3rSecret!", "newPassword": "An0therPass"},
        )
        assert r.status_code == 200
        # 旧密码被覆盖为新密码
        assert verify_password("An0therPass", u.password_hash)
        # must_change_password 被清掉
        assert u.must_change_password is False

    def test_change_password_wrong_old_returns_401(self):
        u = _build_user()
        app, _user_repo = self._build_change_pw_app(u)

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/change-password",
            json={"oldPassword": "WRONG_PASS!", "newPassword": "An0therPass"},
        )
        assert r.status_code == 401
        # 旧密码未被覆盖
        assert verify_password("Sup3rSecret!", u.password_hash)

    def test_change_password_weak_new_returns_400(self):
        u = _build_user()
        app, _user_repo = self._build_change_pw_app(u)

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/change-password",
            json={"oldPassword": "Sup3rSecret!", "newPassword": "weak"},
        )
        assert r.status_code == 400
