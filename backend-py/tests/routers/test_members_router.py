"""成员路由测试(invite / list / me / change_role / reset_password)。

对照 Java 版 controller/MemberController.java。
重点:
- 整个 router 强制 `Depends(require_tenant)`,鉴权失败 → 401/400
- invite 走 Role-based 权限矩阵(OWNER > ADMIN > MEMBER),admin 不可邀请 admin/owner
- change_role 同理
- reset_password:admin 不能重置 owner 密码(防止越级)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.testclient import TestClient

from app.core.tenant_context import TenantContext
from app.exceptions import register_exception_handlers
from app.models.enums import MemberRole
from app.routers import members as members_router
from app.routers.deps import require_tenant
from app.services.auth_service import AuthService
from app.services.member_service import MemberService


def _build_member(**overrides) -> MagicMock:
    from datetime import datetime, timezone

    m = MagicMock(spec_set=[
        "id", "subject_id", "org_id", "role", "created_at", "updated_at",
    ])
    m.id = overrides.get("id", uuid.uuid4())
    m.subject_id = overrides.get("subject_id", str(uuid.uuid4()))
    m.org_id = overrides.get("org_id", uuid.uuid4())
    m.role = overrides.get("role", MemberRole.MEMBER)
    m.created_at = overrides.get("created_at", datetime.now(timezone.utc))
    m.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))
    return m


def _build_member_repo() -> AsyncMock:
    from datetime import datetime, timezone

    repo = AsyncMock()
    repo.find_by_subject_id_and_org_id.return_value = None
    repo.find_by_id_and_org_id.return_value = None
    repo.find_by_org_id.return_value = []
    repo.count_by_org_id_and_role.return_value = 0

    async def _save(m):
        now = datetime.now(timezone.utc)
        if getattr(m, "id", None) is None:
            m.id = uuid.uuid4()
        if getattr(m, "created_at", None) is None:
            m.created_at = now
        if getattr(m, "updated_at", None) is None:
            m.updated_at = now
        return m

    repo.save.side_effect = _save
    return repo


def _build_user_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.find_by_id.return_value = None
    repo.save.side_effect = lambda u: u
    return repo


def _build_org_repo() -> AsyncMock:
    repo = AsyncMock()
    org = MagicMock(spec_set=["id"])
    org.id = uuid.uuid4()
    repo.find_by_id.return_value = org
    return repo


def _build_member_service() -> MemberService:
    return MemberService(_build_member_repo(), _build_org_repo(), AsyncMock())


def _build_auth_service() -> AuthService:
    return AuthService(_build_user_repo(), _build_member_repo(), AsyncMock())


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(members_router.router)
    app.dependency_overrides[members_router._member_service] = lambda: _build_member_service()
    app.dependency_overrides[members_router._auth_service] = lambda: _build_auth_service()
    return app


def _override_tenant_with_role(role: str) -> None:
    """重置 require_tenant 覆盖,设置一个带指定 role 的 tenant。"""

    async def _req_tenant(request: FastAPIRequest, x_org_id: str = ""):
        from app.core import tenant_context
        org_id = uuid.UUID(x_org_id) if x_org_id else uuid.uuid4()
        tenant_context._tenant_context.set(
            TenantContext(org_id=org_id, member_id=uuid.uuid4(), role=role)
        )
        return org_id

    # 通过 app 上下文覆盖
    # 用一个线程局部存当前的 app 来避免反复传
    return _req_tenant


# ----------------------------- /me -----------------------------

class TestMe:
    def test_me_returns_current_member(self):
        app = _build_app()
        member = _build_member()
        # 让 member_service.get_by_id_and_current_org 返回这个 member
        member_svc = members_router._member_service.__wrapped__ if False else None

        # 直接构造一个可以 stub 的 service
        from unittest.mock import MagicMock as _MM

        class _StubSvc:
            def __init__(self, m):
                self._m = m
                self.calls = []

            async def get_by_id_and_current_org(self, mid):
                self.calls.append(mid)
                return self._m

        stub = _StubSvc(member)
        app.dependency_overrides[members_router._member_service] = lambda: stub

        async def _req_tenant(request: FastAPIRequest, x_org_id: str = ""):
            from app.core import tenant_context
            org_id = uuid.UUID(x_org_id) if x_org_id else uuid.uuid4()
            tenant_context._tenant_context.set(
                TenantContext(org_id=org_id, member_id=member.id, role="MEMBER")
            )
            return org_id

        app.dependency_overrides[require_tenant] = _req_tenant

        client = TestClient(app)
        r = client.get("/api/v1/members/me", headers={"X-Org-Id": str(uuid.uuid4())})
        assert r.status_code == 200
        assert r.json()["data"]["id"] == str(member.id)


# ----------------------------- /invite -----------------------------

class TestInvite:
    def test_member_cannot_invite_returns_403(self):
        app = _build_app()

        async def _req_tenant(request: FastAPIRequest, x_org_id: str = ""):
            from app.core import tenant_context
            org_id = uuid.UUID(x_org_id) if x_org_id else uuid.uuid4()
            tenant_context._tenant_context.set(
                TenantContext(org_id=org_id, member_id=uuid.uuid4(), role="MEMBER")
            )
            return org_id

        app.dependency_overrides[require_tenant] = _req_tenant

        client = TestClient(app)
        r = client.post(
            "/api/v1/members",
            json={"subjectId": str(uuid.uuid4()), "role": "MEMBER"},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        # MEMBER 角色不能邀请 → AccessDeniedException → 403
        assert r.status_code == 403

    def test_admin_cannot_invite_admin_returns_403(self):
        app = _build_app()

        async def _req_tenant(request: FastAPIRequest, x_org_id: str = ""):
            from app.core import tenant_context
            org_id = uuid.UUID(x_org_id) if x_org_id else uuid.uuid4()
            tenant_context._tenant_context.set(
                TenantContext(org_id=org_id, member_id=uuid.uuid4(), role="ADMIN")
            )
            return org_id

        app.dependency_overrides[require_tenant] = _req_tenant

        client = TestClient(app)
        r = client.post(
            "/api/v1/members",
            json={"subjectId": str(uuid.uuid4()), "role": "ADMIN"},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        # ADMIN 邀请 ADMIN → 403
        assert r.status_code == 403

    def test_owner_invite_member_success(self):
        app = _build_app()

        async def _req_tenant(request: FastAPIRequest, x_org_id: str = ""):
            from app.core import tenant_context
            org_id = uuid.UUID(x_org_id) if x_org_id else uuid.uuid4()
            tenant_context._tenant_context.set(
                TenantContext(org_id=org_id, member_id=uuid.uuid4(), role="OWNER")
            )
            return org_id

        app.dependency_overrides[require_tenant] = _req_tenant

        client = TestClient(app)
        r = client.post(
            "/api/v1/members",
            json={"subjectId": str(uuid.uuid4()), "role": "MEMBER"},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        assert r.json()["data"]["role"] == "MEMBER"


# ----------------------------- /change_role -----------------------------

class TestChangeRole:
    def test_admin_cannot_promote_to_owner_returns_403(self):
        app = _build_app()

        async def _req_tenant(request: FastAPIRequest, x_org_id: str = ""):
            from app.core import tenant_context
            org_id = uuid.UUID(x_org_id) if x_org_id else uuid.uuid4()
            tenant_context._tenant_context.set(
                TenantContext(org_id=org_id, member_id=uuid.uuid4(), role="ADMIN")
            )
            return org_id

        app.dependency_overrides[require_tenant] = _req_tenant

        # 用一个 stub member service 让其返回一个 MEMBER,然后 ADMIN 试图把它改成 OWNER
        class _StubSvc:
            async def get_by_id_and_current_org(self, mid):
                return _build_member(role=MemberRole.MEMBER)

            async def change_role(self, target_member_id, new_role):
                from app.exceptions.errors import AccessDeniedException
                raise AccessDeniedException("只有 owner 可以设/改为 owner 角色")

        app.dependency_overrides[members_router._member_service] = lambda: _StubSvc()

        client = TestClient(app)
        target_id = uuid.uuid4()
        r = client.patch(
            f"/api/v1/members/{target_id}/role",
            json={"role": "OWNER"},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 403


# ----------------------------- /reset_password -----------------------------

class TestResetPassword:
    def test_admin_cannot_reset_owner_password_returns_403(self):
        """admin 重置 owner 密码 → AccessDeniedException(防越级)。"""
        app = _build_app()

        async def _req_tenant(request: FastAPIRequest, x_org_id: str = ""):
            from app.core import tenant_context
            org_id = uuid.UUID(x_org_id) if x_org_id else uuid.uuid4()
            tenant_context._tenant_context.set(
                TenantContext(org_id=org_id, member_id=uuid.uuid4(), role="ADMIN")
            )
            return org_id

        app.dependency_overrides[require_tenant] = _req_tenant

        # stub member_service: 返回一个 OWNER 角色的 member
        owner_member = _build_member(role=MemberRole.OWNER)

        class _StubMemberSvc:
            async def get_by_id_and_current_org(self, mid):
                return owner_member

        app.dependency_overrides[members_router._member_service] = lambda: _StubMemberSvc()

        client = TestClient(app)
        target_id = uuid.uuid4()
        r = client.post(
            f"/api/v1/members/{target_id}/reset-password",
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        # admin 不可重置 owner 密码 → 403
        assert r.status_code == 403

    def test_admin_can_reset_member_password(self):
        app = _build_app()

        async def _req_tenant(request: FastAPIRequest, x_org_id: str = ""):
            from app.core import tenant_context
            org_id = uuid.UUID(x_org_id) if x_org_id else uuid.uuid4()
            tenant_context._tenant_context.set(
                TenantContext(org_id=org_id, member_id=uuid.uuid4(), role="ADMIN")
            )
            return org_id

        app.dependency_overrides[require_tenant] = _req_tenant

        target_member = _build_member(role=MemberRole.MEMBER, subject_id=str(uuid.uuid4()))

        class _StubMemberSvc:
            async def get_by_id_and_current_org(self, mid):
                return target_member

        app.dependency_overrides[members_router._member_service] = lambda: _StubMemberSvc()

        class _StubAuthSvc:
            async def admin_reset_password(self, caller_member_id, target_user_id, caller_role):
                # 12 位临时密码
                return "TmpP@ssw0rd!"

        app.dependency_overrides[members_router._auth_service] = lambda: _StubAuthSvc()

        client = TestClient(app)
        r = client.post(
            f"/api/v1/members/{target_member.id}/reset-password",
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        # 临时密码返回
        assert r.json()["data"] == "TmpP@ssw0rd!"
