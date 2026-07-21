"""文档摄取 DTO。对应 Java 版 DocumentController 的请求体 record 以及
DocumentIngestionService.DocumentView/JobView、DocumentDirectUploadService.UploadSessionView/
CompletedUploadView 内嵌 record。

**依赖状态说明**:本文件本身只依赖 app.models.enums.IngestionStatus / UploadSessionStatus,
可以正常 import;但引用本文件的 app.services.document_ingestion_service /
document_direct_upload_service / app.routers.documents 依赖的
app.ragcore.ingestion / app.ragcore.storage / app.ragcore.upload 目前是空目录(其他并行
任务负责),尚未接入 app.main——见 app/main.py 底部的说明注释。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import IngestionStatus, UploadSessionStatus


class InitiateUploadRequest(BaseModel):
    kb_id: UUID = Field(..., alias="kbId")
    file_name: str = Field(..., min_length=1, alias="fileName")
    size_bytes: int = Field(..., gt=0, alias="sizeBytes")

    model_config = {"populate_by_name": True}


class DocumentView(BaseModel):
    document_id: UUID = Field(..., alias="documentId")
    kb_id: UUID = Field(..., alias="kbId")
    name: str
    size: int
    content_type: str | None = Field(default=None, alias="contentType")
    status: IngestionStatus
    error_message: str | None = Field(default=None, alias="errorMessage")
    retry_count: int = Field(..., alias="retryCount")
    retryable: bool
    uploaded_at: datetime = Field(..., alias="uploadedAt")
    ready_at: datetime | None = Field(default=None, alias="readyAt")
    job_id: UUID | None = Field(default=None, alias="jobId")

    model_config = {"populate_by_name": True}


class JobView(BaseModel):
    job_id: UUID = Field(..., alias="jobId")
    document_id: UUID = Field(..., alias="documentId")
    kb_id: UUID = Field(..., alias="kbId")
    status: IngestionStatus
    error_message: str | None = Field(default=None, alias="errorMessage")
    retry_limit: int = Field(..., alias="retryLimit")
    retryable: bool
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = {"populate_by_name": True}


class UploadSessionView(BaseModel):
    session_id: UUID = Field(..., alias="sessionId")
    status: UploadSessionStatus
    upload_url: str | None = Field(default=None, alias="uploadUrl")
    method: str | None = None
    headers: dict[str, str] | None = None
    expires_at: datetime = Field(..., alias="expiresAt")
    document_id: UUID | None = Field(default=None, alias="documentId")

    model_config = {"populate_by_name": True}


class CompletedUploadView(BaseModel):
    session_id: UUID = Field(..., alias="sessionId")
    document_id: UUID = Field(..., alias="documentId")
    job_id: UUID = Field(..., alias="jobId")
    status: IngestionStatus

    model_config = {"populate_by_name": True}
