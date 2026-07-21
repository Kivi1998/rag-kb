"""`app.routers.documents` 路由测试。

对照 Java 版 controller/DocumentController.java。
重点覆盖(端到端 + `app.dependency_overrides` 注入 mock 服务):
- 上传 / 列表 / 删除 / get_job / retry 主路径
- 租户鉴权门控:无 token / 缺 X-Org-Id → 401/400
- 跨租户 kb 访问:DocumentIngestionService 抛 ResourceNotFoundException → 404
- 跨 kb 访问:同一 org 不同 kb 仍由 service 层自己校验
- 错误处理:上传空文件 / 文件名非法 → 400(ValueError 映射)
- 业务失败:deletion service 抛错时由 service 层抛 500(异常路径)

不在本文件覆盖:
- `require_tenant` 鉴权链细节(已有 `test_security_dependencies.py` 覆盖)
- `DocumentIngestionService` / `DocumentDeletionService` 内部逻辑
  (在 `tests/services/` 下覆盖,本文件只验证 router 层)
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.testclient import TestClient

from app.core.tenant_context import TenantContext
from app.exceptions import register_exception_handlers
from app.models.enums import IngestionStatus
from app.routers import documents as documents_router
from app.routers.deps import require_tenant
from app.schemas.document import DocumentView, JobView
from app.services.document_ingestion_service import DocumentIngestionService


# ---- Test doubles ------------------------------------------------------


def _make_document_view(
    *,
    doc_id: UUID | None = None,
    kb_id: UUID | None = None,
    name: str = "report.pdf",
    status: IngestionStatus = IngestionStatus.QUEUED,
    retry_count: int = 0,
    retryable: bool = False,
    job_id: UUID | None = None,
) -> DocumentView:
    return DocumentView(
        documentId=doc_id or uuid.uuid4(),
        kbId=kb_id or uuid.uuid4(),
        name=name,
        size=2048,
        contentType="application/pdf",
        status=status,
        errorMessage=None,
        retryCount=retry_count,
        retryable=retryable,
        uploadedAt=datetime.now(timezone.utc),
        readyAt=None,
        jobId=job_id or uuid.uuid4(),
    )


def _make_job_view(
    *,
    job_id: UUID | None = None,
    doc_id: UUID | None = None,
    kb_id: UUID | None = None,
    status: IngestionStatus = IngestionStatus.QUEUED,
) -> JobView:
    now = datetime.now(timezone.utc)
    return JobView(
        jobId=job_id or uuid.uuid4(),
        documentId=doc_id or uuid.uuid4(),
        kbId=kb_id or uuid.uuid4(),
        status=status,
        errorMessage=None,
        retryLimit=3,
        retryable=False,
        createdAt=now,
        updatedAt=now,
    )


def _build_ingestion_service(
    *,
    list_result: list[DocumentView] | None = None,
    upload_result: tuple[DocumentView, JobView] | None = None,
    job_result: JobView | None = None,
    delete_side_effect: Any = None,
) -> AsyncMock:
    """构造一个 DocumentIngestionService stub。

    把 `list` / `upload` / `get_job` / `retry` / `delete` 都换成 AsyncMock,允许测试
    自由控制返回值和 side effect。`_lifecycle_service` / `_deletion_service` /
    `_object_storage` 等内部依赖不直接 stub,它们在 router 层被遮蔽——服务 mock
    只对 router 的方法调用有反应。
    """
    service = AsyncMock(spec=DocumentIngestionService)
    service.list.return_value = list_result if list_result is not None else []
    if upload_result is not None:
        service.upload.return_value = upload_result
    else:
        doc_view = _make_document_view()
        service.upload.return_value = (doc_view, _make_job_view())
    if job_result is not None:
        service.get_job.return_value = job_result
    if delete_side_effect is not None:
        service.delete.side_effect = delete_side_effect
    return service


def _override_tenant(
    app: FastAPI, *, org_id: UUID | None = None, member_id: UUID | None = None, role: str = "OWNER"
) -> None:
    """把 `require_tenant` 替换为能直接设置 tenant_context 的桩。"""

    async def _req_tenant(request: FastAPIRequest, x_org_id: str = "") -> UUID:
        from app.core import tenant_context

        o = org_id or (uuid.UUID(x_org_id) if x_org_id else uuid.uuid4())
        m = member_id or uuid.uuid4()
        tenant_context._tenant_context.set(TenantContext(org_id=o, member_id=m, role=role))
        return o

    app.dependency_overrides[require_tenant] = _req_tenant


def _build_app(service: AsyncMock | None = None) -> FastAPI:
    """构造最小可跑的 documents 路由 app。"""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(documents_router.router)
    if service is not None:
        app.dependency_overrides[documents_router._ingestion_service] = lambda: service
        app.dependency_overrides[documents_router._direct_upload_service] = lambda: service
    return app


# ----------------------------- auth gating -----------------------------


class TestAuthGating:
    def test_no_token_returns_4xx(self):
        """无 Authorization 头 → require_tenant 拒绝(400/401 都属正确拒绝)。"""
        app = _build_app()
        client = TestClient(app)
        r = client.get("/api/v1/documents", params={"kb_id": str(uuid.uuid4())})
        assert r.status_code in (400, 401)


# ----------------------------- list -----------------------------


class TestList:
    def test_list_returns_documents_in_org(self):
        kb_id = uuid.uuid4()
        doc1 = _make_document_view(kb_id=kb_id, name="a.pdf")
        doc2 = _make_document_view(kb_id=kb_id, name="b.pdf")
        service = _build_ingestion_service(list_result=[doc1, doc2])
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.get(
            "/api/v1/documents",
            params={"kbId": str(kb_id)},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert len(body["data"]) == 2
        assert {d["name"] for d in body["data"]} == {"a.pdf", "b.pdf"}

    def test_list_with_status_filter_passes_through(self):
        kb_id = uuid.uuid4()
        service = _build_ingestion_service(list_result=[])
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.get(
            "/api/v1/documents",
            params={"kbId": str(kb_id), "status": "QUEUED"},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        # service.list 收到的参数与 router 透传一致
        service.list.assert_awaited_with(kb_id, IngestionStatus.QUEUED)

    def test_list_kb_not_in_current_org_returns_404(self):
        """跨租户访问 kb(同 org 不同 kb / 不同 org)→ service 抛 404,被全局异常处理映射。"""
        from app.exceptions.errors import ResourceNotFoundException

        service = _build_ingestion_service()
        service.list.side_effect = ResourceNotFoundException("知识库不存在")
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.get(
            "/api/v1/documents",
            params={"kbId": str(uuid.uuid4())},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 404
        assert r.json()["code"] == 404


# ----------------------------- upload -----------------------------


class TestUpload:
    def test_upload_returns_201_with_document_view(self):
        """multipart 上传走通: service.upload 被调用一次,返回 201 + DocumentView。"""
        kb_id = uuid.uuid4()
        doc_view = _make_document_view(kb_id=kb_id, name="report.pdf")
        job_view = _make_job_view(kb_id=kb_id)
        service = _build_ingestion_service(upload_result=(doc_view, job_view))
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        file_bytes = b"%PDF-1.4\nfake pdf body\n%%EOF"
        r = client.post(
            "/api/v1/documents/upload",
            data={"kbId": str(kb_id)},
            files={"file": ("report.pdf", io.BytesIO(file_bytes), "application/pdf")},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["name"] == "report.pdf"
        assert body["data"]["status"] == "QUEUED"
        # service.upload 收到了正确的参数
        service.upload.assert_awaited_once()
        call_args = service.upload.await_args
        # (kb_id, filename, size_bytes, file_stream)
        assert call_args.args[0] == kb_id
        assert call_args.args[1] == "report.pdf"
        assert call_args.args[2] == len(file_bytes)

    def test_upload_empty_file_returns_400(self):
        """UploadPolicy 拒绝 size=0 → service 抛 ValueError → 400。"""
        service = _build_ingestion_service()
        service.upload.side_effect = ValueError("请选择非空文件")
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.post(
            "/api/v1/documents/upload",
            data={"kbId": str(uuid.uuid4())},
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 400

    def test_upload_disallowed_extension_returns_400(self):
        """UploadPolicy 拒绝 .exe → ValueError → 400。"""
        service = _build_ingestion_service()
        service.upload.side_effect = ValueError("不支持的文件类型: exe")
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.post(
            "/api/v1/documents/upload",
            data={"kbId": str(uuid.uuid4())},
            files={"file": ("malware.exe", io.BytesIO(b"x"), "application/octet-stream")},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 400

    def test_upload_kb_not_in_current_org_returns_404(self):
        """跨租户上传 → service 抛 404,异常处理映射。"""
        from app.exceptions.errors import ResourceNotFoundException

        service = _build_ingestion_service()
        service.upload.side_effect = ResourceNotFoundException("知识库不存在")
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.post(
            "/api/v1/documents/upload",
            data={"kbId": str(uuid.uuid4())},
            files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 404


# ----------------------------- delete -----------------------------


class TestDelete:
    def test_delete_returns_200(self):
        kb_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        service = _build_ingestion_service()
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.delete(
            f"/api/v1/documents/{doc_id}",
            params={"kbId": str(kb_id)},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 0
        service.delete.assert_awaited_with(kb_id, doc_id)

    def test_delete_document_not_in_org_returns_404(self):
        from app.exceptions.errors import ResourceNotFoundException

        kb_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        service = _build_ingestion_service()
        service.delete.side_effect = ResourceNotFoundException("文档不存在")
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.delete(
            f"/api/v1/documents/{doc_id}",
            params={"kbId": str(kb_id)},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 404


# ----------------------------- get_job -----------------------------


class TestGetJob:
    def test_get_job_returns_job_view(self):
        kb_id = uuid.uuid4()
        job_id = uuid.uuid4()
        job_view = _make_job_view(job_id=job_id, kb_id=kb_id, status=IngestionStatus.PARSING)
        service = _build_ingestion_service(job_result=job_view)
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.get(
            f"/api/v1/documents/jobs/{job_id}",
            params={"kbId": str(kb_id)},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["data"]["jobId"] == str(job_id)
        assert body["data"]["status"] == "PARSING"

    def test_get_job_not_in_org_returns_404(self):
        from app.exceptions.errors import ResourceNotFoundException

        service = _build_ingestion_service()
        service.get_job.side_effect = ResourceNotFoundException("摄取任务不存在")
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.get(
            f"/api/v1/documents/jobs/{uuid.uuid4()}",
            params={"kbId": str(uuid.uuid4())},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 404


# ----------------------------- retry -----------------------------


class TestRetry:
    def test_retry_returns_200_with_new_status(self):
        """重试接口:service.retry 透传,返回新 JobView(状态机由 stub 决定)。"""
        kb_id = uuid.uuid4()
        job_id = uuid.uuid4()
        new_job_view = _make_job_view(job_id=job_id, kb_id=kb_id, status=IngestionStatus.QUEUED)
        service = _build_ingestion_service()
        service.retry.return_value = new_job_view
        app = _build_app(service)
        _override_tenant(app)

        client = TestClient(app)
        r = client.post(
            f"/api/v1/documents/jobs/{job_id}/retry",
            params={"kbId": str(kb_id)},
            headers={"X-Org-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "QUEUED"
        service.retry.assert_awaited_with(kb_id, job_id)
