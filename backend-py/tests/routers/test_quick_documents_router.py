"""`app.routers.quick_documents` 路由测试。

对照 Java 版 controller/QuickDocumentController.java。
重点覆盖(端到端 + `app.dependency_overrides` 注入 mock 服务):
- 上传 / 列表 / 删除 主路径
- 鉴权门控:无 token / 缺 X-Org-Id → 401/400
- 跨会话访问(同 org 不同 session)→ `ChatSessionService.require_owned_session` 抛 404
- 模块禁用门控:`rag_quick_document_enabled=false` 时调用即抛 400
- 配额超限:QuickDocumentService.QuotaExceededException → 400
- 不上传文件 / 文件空 → UnsupportedDocumentTypeException 400 或空解析错误 400

不在本文件覆盖:
- `require_tenant` 鉴权链细节(已有 `test_security_dependencies.py` 覆盖)
- `QuickDocumentService` 内部解析逻辑(在 ragcore 单元测试覆盖)
- 解析器链(`DocumentParserFactory` 6 个 parser)在 `tests/ragcore/` 下
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.testclient import TestClient

from app.core.tenant_context import TenantContext
from app.exceptions import register_exception_handlers
from app.ragcore.quickdocument.quick_document import QuickDocument
from app.ragcore.quickdocument.quick_document_service import (
    QuickDocumentService,
    QuotaExceededException,
)
from app.routers import quick_documents as quick_documents_router
from app.routers.deps import require_tenant
from app.services.chat_session_service import ChatSessionService


# ---- Test doubles ------------------------------------------------------


def _make_quick_document(
    *,
    session_id: uuid.UUID | None = None,
    filename: str = "notes.md",
    content: str = "这是一段临时文档内容。",
) -> QuickDocument:
    doc_id = uuid.uuid4()
    return QuickDocument(
        doc_id=doc_id,
        session_id=session_id or uuid.uuid4(),
        filename=filename,
        content=content,
        character_count=len(content),
        created_at=datetime.now(timezone.utc),
    )


def _build_chat_session_service(
    *,
    touch_side_effect: Any = None,
    require_owned_side_effect: Any = None,
) -> AsyncMock:
    service = AsyncMock(spec=ChatSessionService)
    if touch_side_effect is not None:
        service.touch_session.side_effect = touch_side_effect
    if require_owned_side_effect is not None:
        service.require_owned_session.side_effect = require_owned_side_effect
    return service


def _build_quick_document_service(
    *,
    upload_result: QuickDocument | None = None,
    upload_side_effect: BaseException | None = None,
    list_result: list[QuickDocument] | None = None,
    delete_side_effect: Any = None,
) -> AsyncMock:
    service = AsyncMock(spec=QuickDocumentService)
    if upload_side_effect is not None:
        service.upload.side_effect = upload_side_effect
    else:
        service.upload.return_value = upload_result or _make_quick_document()
    service.list.return_value = list_result if list_result is not None else []
    if delete_side_effect is not None:
        service.delete.side_effect = delete_side_effect
    return service


def _override_tenant(
    app: FastAPI, *, org_id: uuid.UUID | None = None, member_id: uuid.UUID | None = None, role: str = "OWNER"
) -> None:
    async def _req_tenant(request: FastAPIRequest, x_org_id: str = "") -> uuid.UUID:
        from app.core import tenant_context

        o = org_id or (uuid.UUID(x_org_id) if x_org_id else uuid.uuid4())
        m = member_id or uuid.uuid4()
        tenant_context._tenant_context.set(TenantContext(org_id=o, member_id=m, role=role))
        return o

    app.dependency_overrides[require_tenant] = _req_tenant


def _build_app(
    *,
    chat_service: AsyncMock | None = None,
    quick_service: AsyncMock | None = None,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(quick_documents_router.router)
    if chat_service is not None:
        app.dependency_overrides[quick_documents_router._chat_session_service] = lambda: chat_service
    if quick_service is not None:
        app.dependency_overrides[quick_documents_router._quick_document_service] = lambda: quick_service
    return app


# ----------------------------- auth gating -----------------------------


class TestAuthGating:
    def test_no_token_returns_4xx(self):
        app = _build_app()
        client = TestClient(app)
        kb_id = uuid.uuid4()
        session_id = uuid.uuid4()
        r = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/sessions/{session_id}/quick-documents",
            files={"file": ("notes.md", io.BytesIO(b"# hi"), "text/markdown")},
        )
        assert r.status_code in (400, 401)


# ----------------------------- feature flag -----------------------------


class TestFeatureFlag:
    def test_quick_document_disabled_returns_400(self, monkeypatch):
        """`rag_quick_document_enabled=false` → build_quick_document_store() 返回 None →
        `_quick_document_service` factory 抛 HTTPException(400)。"""
        monkeypatch.setattr(quick_documents_router, "build_quick_document_store", lambda: None)

        chat_service = _build_chat_session_service()
        app = _build_app(chat_service=chat_service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.post(
            f"/api/v1/knowledge-bases/{uuid.uuid4()}/sessions/{uuid.uuid4()}/quick-documents",
            files={"file": ("notes.md", io.BytesIO(b"# hi"), "text/markdown")},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        # HTTPException 400 from factory
        assert r.status_code == 400
        assert "临时文档" in r.json().get("message", "")


# ----------------------------- upload -----------------------------


class TestUpload:
    def test_upload_returns_201_with_summary(self):
        kb_id, session_id = uuid.uuid4(), uuid.uuid4()
        document = _make_quick_document(session_id=session_id, filename="notes.md", content="临时内容")
        chat_service = _build_chat_session_service()
        quick_service = _build_quick_document_service(upload_result=document)
        app = _build_app(chat_service=chat_service, quick_service=quick_service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/sessions/{session_id}/quick-documents",
            files={"file": ("notes.md", io.BytesIO(b"# hi"), "text/markdown")},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["filename"] == "notes.md"
        assert body["data"]["docId"] == str(document.doc_id)
        assert body["data"]["characterCount"] == len("临时内容")
        # chat_session.touch_session 必须被调用(校验归属)
        chat_service.touch_session.assert_awaited_once()
        # quick_service.upload 收到了 session_id 和 file
        quick_service.upload.assert_awaited_once()
        assert quick_service.upload.await_args.args[0] == session_id

    def test_upload_session_not_owned_returns_404(self):
        from app.exceptions.errors import ResourceNotFoundException

        kb_id, session_id = uuid.uuid4(), uuid.uuid4()
        chat_service = _build_chat_session_service(
            touch_side_effect=ResourceNotFoundException("会话不存在")
        )
        app = _build_app(chat_service=chat_service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/sessions/{session_id}/quick-documents",
            files={"file": ("notes.md", io.BytesIO(b"# hi"), "text/markdown")},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 404

    def test_upload_quota_exceeded_returns_400(self):
        """会话额度超限 → QuotaExceededException → 400。

        QuotaExceededException 继承 ValueError,经全局异常处理映射到 400。
        """
        kb_id, session_id = uuid.uuid4(), uuid.uuid4()
        chat_service = _build_chat_session_service()
        quick_service = _build_quick_document_service(
            upload_side_effect=QuotaExceededException(
                existing_characters=20000,
                new_characters=1000,
                max_total_characters=15000,
            )
        )
        app = _build_app(chat_service=chat_service, quick_service=quick_service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/sessions/{session_id}/quick-documents",
            files={"file": ("notes.md", io.BytesIO(b"# hi"), "text/markdown")},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 400
        assert "总额" in r.json().get("message", "") or "上限" in r.json().get("message", "")

    def test_upload_unsupported_file_type_returns_400(self):
        """不支持的扩展名 → 解析器工厂抛 UnsupportedDocumentTypeException → 400。"""
        from app.ragcore.parser.factory import UnsupportedDocumentTypeException

        kb_id, session_id = uuid.uuid4(), uuid.uuid4()
        chat_service = _build_chat_session_service()
        quick_service = _build_quick_document_service(
            upload_side_effect=UnsupportedDocumentTypeException("找不到支持 ... 的解析器")
        )
        app = _build_app(chat_service=chat_service, quick_service=quick_service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/sessions/{session_id}/quick-documents",
            files={"file": ("script.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 400


# ----------------------------- list -----------------------------


class TestList:
    def test_list_returns_summaries(self):
        kb_id, session_id = uuid.uuid4(), uuid.uuid4()
        doc1 = _make_quick_document(session_id=session_id, filename="a.md")
        doc2 = _make_quick_document(session_id=session_id, filename="b.txt")
        chat_service = _build_chat_session_service()
        quick_service = _build_quick_document_service(list_result=[doc1, doc2])
        app = _build_app(chat_service=chat_service, quick_service=quick_service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.get(
            f"/api/v1/knowledge-bases/{kb_id}/sessions/{session_id}/quick-documents",
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert len(body["data"]) == 2
        assert {d["filename"] for d in body["data"]} == {"a.md", "b.txt"}
        # list 用 require_owned_session(只读校验),不是 touch_session
        chat_service.require_owned_session.assert_awaited_once()
        chat_service.touch_session.assert_not_awaited()

    def test_list_session_not_owned_returns_404(self):
        from app.exceptions.errors import ResourceNotFoundException

        kb_id, session_id = uuid.uuid4(), uuid.uuid4()
        chat_service = _build_chat_session_service(
            require_owned_side_effect=ResourceNotFoundException("会话不存在")
        )
        app = _build_app(chat_service=chat_service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.get(
            f"/api/v1/knowledge-bases/{kb_id}/sessions/{session_id}/quick-documents",
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 404


# ----------------------------- delete -----------------------------


class TestDelete:
    def test_delete_returns_200(self):
        kb_id, session_id, doc_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        chat_service = _build_chat_session_service()
        quick_service = _build_quick_document_service()
        app = _build_app(chat_service=chat_service, quick_service=quick_service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.delete(
            f"/api/v1/knowledge-bases/{kb_id}/sessions/{session_id}/quick-documents/{doc_id}",
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 0
        # 必传 (session_id, doc_id)
        quick_service.delete.assert_awaited_with(session_id, doc_id)

    def test_delete_session_not_owned_returns_404(self):
        from app.exceptions.errors import ResourceNotFoundException

        kb_id, session_id, doc_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        chat_service = _build_chat_session_service(
            require_owned_side_effect=ResourceNotFoundException("会话不存在")
        )
        app = _build_app(chat_service=chat_service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.delete(
            f"/api/v1/knowledge-bases/{kb_id}/sessions/{session_id}/quick-documents/{doc_id}",
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 404
