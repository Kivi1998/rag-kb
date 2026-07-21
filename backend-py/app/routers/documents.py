"""与前端 documentsApi 对齐的文档摄取 HTTP 契约。对应 Java 版 controller/DocumentController.java。

装配入口:`_ingestion_service` / `_direct_upload_service` 把 ObjectStorage / UploadPolicy /
IngestionJobLifecycleService / DocumentDeletionService / IngestionMetrics 按
`settings.rag_storage_type` 条件性串起来。生命周期服务(`SqlAlchemyIngestionJobLifecycleService`)
由 Worker 启动配套任务落地,真正接管 claim/heartbeat/advance/fail/retry 全量职责。
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.core.config import settings
from app.models.enums import IngestionStatus
from app.ragcore.ingestion.deletion_service import DocumentDeletionService
from app.ragcore.ingestion.lifecycle_service import IngestionJobLifecycleService
from app.ragcore.ingestion.metrics import IngestionMetrics
from app.ragcore.storage.object_storage import ObjectStorage
from app.ragcore.upload.document_upload_policy import DocumentUploadPolicy
from app.repositories.document_upload_session_repository import DocumentUploadSessionRepository
from app.repositories.ingestion_job_repository import IngestionJobRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository
from app.repositories.member_repository import MemberRepository
from app.routers._factories import build_lifecycle_service, build_object_storage
from app.routers.deps import get_session, require_tenant
from app.schemas.common import ApiResponse
from app.schemas.document import CompletedUploadView, DocumentView, InitiateUploadRequest, JobView, UploadSessionView
from app.services.document_direct_upload_service import DocumentDirectUploadService
from app.services.document_ingestion_service import DocumentIngestionService

router = APIRouter(prefix="/api/v1/documents", tags=["documents"], dependencies=[Depends(require_tenant)])


# ---- 工厂 -------------------------------------------------------------

def _upload_policy() -> DocumentUploadPolicy:
    return DocumentUploadPolicy()


def _metrics() -> IngestionMetrics:
    """未提供 Prometheus registry 时传 None,IngestionMetrics 全部 no-op。"""
    return IngestionMetrics(None)


def _lifecycle_service() -> IngestionJobLifecycleService:
    """从 `_factories.build_lifecycle_service` 拉取 SQLAlchemy 实现。

    真实生产路径(摄取 Worker 已启动)直接拿到具体类实例;若 worker 未启动,
    HTTP `/retry` 端点会触发 SQLite/PostgreSQL 上的真实状态翻转。
    """
    return build_lifecycle_service()


def _ingestion_service(db: AsyncSession = Depends(get_session)) -> DocumentIngestionService:
    return DocumentIngestionService(
        KnowledgeBaseRepository(db),
        KnowledgeDocumentRepository(db),
        IngestionJobRepository(db),
        MemberRepository(db),
        build_object_storage(),
        _lifecycle_service(),
        # lexical_index/vector_index 暂不接入(本文件内无现成的 ES/Milvus 索引装配代码),
        # 已知局限: 删除文档时仅清理 Postgres/MongoDB 记录,ES/Milvus 中的向量索引未清理。
        DocumentDeletionService(KnowledgeDocumentRepository(db), IngestionJobRepository(db), build_object_storage()),
        _upload_policy(),
        db,
    )


def _direct_upload_service(db: AsyncSession = Depends(get_session)) -> DocumentDirectUploadService:
    return DocumentDirectUploadService(
        KnowledgeBaseRepository(db),
        MemberRepository(db),
        KnowledgeDocumentRepository(db),
        IngestionJobRepository(db),
        DocumentUploadSessionRepository(db),
        build_object_storage(),
        _upload_policy(),
        _metrics(),
        db,
    )


@router.get("", response_model=ApiResponse[list[DocumentView]], response_model_exclude_none=True)
async def list_documents(
    kb_id: UUID = Query(alias="kbId"),
    status_filter: IngestionStatus | None = Query(default=None, alias="status"),
    service: DocumentIngestionService = Depends(_ingestion_service),
) -> ApiResponse[list[DocumentView]]:
    documents = await service.list(kb_id, status_filter)
    return ApiResponse.ok(documents)


@router.post(
    "/upload",
    response_model=ApiResponse[DocumentView],
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def upload(
    kb_id: UUID = Form(..., alias="kbId"),
    file: UploadFile = File(...),
    service: DocumentIngestionService = Depends(_ingestion_service),
) -> ApiResponse[DocumentView]:
    document_view, _job_view = await service.upload(kb_id, file.filename, file.size or 0, file.file)
    return ApiResponse.ok(document_view)


@router.post(
    "/uploads",
    response_model=ApiResponse[UploadSessionView],
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_direct_upload(
    req: InitiateUploadRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    service: DocumentDirectUploadService = Depends(_direct_upload_service),
) -> ApiResponse[UploadSessionView]:
    """为大文件签发 MinIO/S3 直传地址;同一幂等键重复调用返回同一会话。"""
    view = await service.initiate(req.kb_id, req.file_name, req.size_bytes, idempotency_key)
    return ApiResponse.ok(view)


@router.post(
    "/uploads/{session_id}/complete",
    response_model=ApiResponse[CompletedUploadView],
    response_model_exclude_none=True,
)
async def complete_direct_upload(
    session_id: UUID, service: DocumentDirectUploadService = Depends(_direct_upload_service)
) -> ApiResponse[CompletedUploadView]:
    """客户端 PUT 完成后调用;服务端确认对象存在且大小一致,再原子创建摄取任务。"""
    view = await service.complete(session_id)
    return ApiResponse.ok(view)


@router.get("/jobs/{job_id}", response_model=ApiResponse[JobView], response_model_exclude_none=True)
async def get_job(
    job_id: UUID, kb_id: UUID = Query(alias="kbId"), service: DocumentIngestionService = Depends(_ingestion_service)
) -> ApiResponse[JobView]:
    job = await service.get_job(kb_id, job_id)
    return ApiResponse.ok(job)


@router.post("/jobs/{job_id}/retry", response_model=ApiResponse[JobView], response_model_exclude_none=True)
async def retry(
    job_id: UUID, kb_id: UUID = Query(alias="kbId"), service: DocumentIngestionService = Depends(_ingestion_service)
) -> ApiResponse[JobView]:
    job = await service.retry(kb_id, job_id)
    return ApiResponse.ok(job)


@router.delete("/{document_id}", response_model=ApiResponse[None], response_model_exclude_none=True)
async def delete(
    document_id: UUID, kb_id: UUID = Query(alias="kbId"), service: DocumentIngestionService = Depends(_ingestion_service)
) -> ApiResponse[None]:
    await service.delete(kb_id, document_id)
    return ApiResponse.ok()
