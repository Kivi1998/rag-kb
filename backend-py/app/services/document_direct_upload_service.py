"""MinIO/S3 预签名直传会话编排。对应 Java 版 service/DocumentDirectUploadService.java。

**依赖状态说明(未接入 app.main,见 app/main.py 底部注释)**:同 `document_ingestion_service.py`,
依赖的 `app.ragcore.storage.object_storage.ObjectStorage`、
`app.ragcore.upload.document_upload_policy.DocumentUploadPolicy`、
`app.ragcore.upload.upload_content_inspector.UploadContentInspector`、
`app.ragcore.ingestion.ingestion_metrics.IngestionMetrics` 目前是空目录/未落地。

**转写差异说明**:
1. Java 版用 `PlatformTransactionManager`/`TransactionTemplate` 手动开三段独立事务
   (beginVerification 提交 VERIFYING 状态 → 事务外做对象存储校验(不持有 DB 连接,避免长时间
   占用连接池) → finalizeVerification 再开一个事务落库),这是为了不在做网络 IO(校验直传对象)
   期间占着数据库连接/锁。Python 版用同一个请求作用域的 `AsyncSession`,在
   `beginVerification`/`finalizeVerification` 前后端各自 `commit()` 达到同样的"分阶段提交"
   效果;`verifyUploadedObject` 之间不持有任何未提交的 DB 写操作。
2. `cleanupExpiredSessions`/`@Scheduled` 对应的定时清理任务不属于本次四层(service/router/
   schema/exception)迁移范围——它是后台 worker/调度器的职责,与 Ingestion Worker 一样应在
   独立的 worker 模块里用各自的 `SessionLocal()` 会话周期性调用本类的 `cleanup_expired_session`
   等方法,这里只保留业务方法本身,不在本文件内注册 cron/scheduler。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tenant_context import get_tenant_context
from app.exceptions.errors import (
    AccessDeniedException,
    BusinessConflictException,
    ResourceNotFoundException,
)
from app.models.document_upload_session import DocumentUploadSession
from app.models.enums import IngestionStatus, MemberRole, UploadSessionStatus
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.ragcore.ingestion.metrics import IngestionMetrics
from app.ragcore.storage.object_storage import ObjectStorage
from app.ragcore.upload.document_upload_policy import DocumentUploadPolicy
from app.ragcore.upload.upload_content_inspector import UploadContentInspector
from app.repositories.document_upload_session_repository import DocumentUploadSessionRepository
from app.repositories.ingestion_job_repository import IngestionJobRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository
from app.repositories.member_repository import MemberRepository
from app.schemas.document import CompletedUploadView, UploadSessionView

CONTENT_SNIFF_BYTES = 8192


class DocumentDirectUploadService:
    def __init__(
        self,
        kb_repository: KnowledgeBaseRepository,
        member_repository: MemberRepository,
        document_repository: KnowledgeDocumentRepository,
        job_repository: IngestionJobRepository,
        session_repository: DocumentUploadSessionRepository,
        object_storage: ObjectStorage,
        upload_policy: DocumentUploadPolicy,
        metrics: IngestionMetrics,
        session: AsyncSession,
    ) -> None:
        self._kbs = kb_repository
        self._members = member_repository
        self._documents = document_repository
        self._jobs = job_repository
        self._sessions = session_repository
        self._object_storage = object_storage
        self._upload_policy = upload_policy
        self._metrics = metrics
        self._session = session
        self._ttl_seconds = settings.rag_direct_upload_ttl_seconds
        self._verification_timeout_ms = settings.rag_direct_upload_verification_timeout_ms

    async def initiate(self, kb_id: UUID, file_name: str, size_bytes: int, idempotency_key: str) -> UploadSessionView:
        await self._require_document_manager()
        self._validate_ttl()
        if not self._object_storage.supports_direct_upload():
            raise BusinessConflictException("当前对象存储未启用 MinIO/S3 预签名直传")
        normalized_key = self._normalize_idempotency_key(idempotency_key)
        ctx = get_tenant_context()
        kb = await self._find_knowledge_base(kb_id)
        validated = self._upload_policy.validate(file_name, size_bytes)

        existing = await self._sessions.find_by_org_id_and_knowledge_base_id_and_idempotency_key(
            ctx.org_id, kb_id, normalized_key
        )
        if existing is not None:
            return await self._existing_view(existing)

        now = datetime.now(timezone.utc)
        upload_session = DocumentUploadSession(
            id=uuid4(),
            org_id=kb.org_id,
            kb_id=kb.id,
            created_by=ctx.member_id,
            file_name=validated.safe_file_name,
            content_type=validated.content_type,
            expected_size_bytes=validated.size_bytes,
            idempotency_key=normalized_key,
            status=UploadSessionStatus.PENDING,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
        )
        upload_session.object_storage_path = self._build_staging_key(kb_id, upload_session.id, validated.extension)
        await self._sessions.save(upload_session)
        await self._session.commit()
        self._metrics.upload_initiated()
        return await self._with_presigned_url(upload_session)

    async def complete(self, session_id: UUID) -> CompletedUploadView:
        await self._require_document_manager()
        ctx = get_tenant_context()
        self._validate_verification_timeout()

        completed, snapshot = await self._begin_verification(session_id, ctx.org_id)
        if completed is not None:
            return completed

        try:
            verified = await self._verify_uploaded_object(snapshot)
        except Exception:
            await self._reset_verification(snapshot)
            raise

        return await self._finalize_verification(snapshot, verified)

    async def _begin_verification(self, session_id: UUID, org_id: UUID):
        upload_session = await self._sessions.find_for_update(session_id, org_id)
        if upload_session is None:
            raise ResourceNotFoundException("上传会话不存在")
        if upload_session.status == UploadSessionStatus.COMPLETED:
            return await self._completed_view(upload_session), None
        if upload_session.status == UploadSessionStatus.VERIFYING:
            raise BusinessConflictException("上传对象正在校验，请稍后重试")
        if upload_session.status != UploadSessionStatus.PENDING:
            raise BusinessConflictException("上传会话已失效")
        if upload_session.expires_at <= datetime.now(timezone.utc):
            raise BusinessConflictException("上传会话已过期，请重新发起上传")

        token = uuid4()
        upload_session.status = UploadSessionStatus.VERIFYING
        upload_session.verification_token = token
        upload_session.verification_started_at = datetime.now(timezone.utc)
        await self._sessions.save(upload_session)
        await self._session.commit()
        snapshot = _VerificationSnapshot(
            session_id=upload_session.id,
            verification_token=token,
            file_name=upload_session.file_name,
            object_storage_path=upload_session.object_storage_path,
            expected_size_bytes=upload_session.expected_size_bytes,
        )
        return None, snapshot

    async def _verify_uploaded_object(self, snapshot: "_VerificationSnapshot") -> "_VerifiedObject":
        try:
            stored = await self._object_storage.stat(snapshot.object_storage_path)
        except OSError as exc:
            raise BusinessConflictException("尚未检测到已上传对象，请完成 PUT 后重试") from exc
        if stored.size_bytes != snapshot.expected_size_bytes:
            raise BusinessConflictException("对象大小与上传会话声明不一致")

        stream: BinaryIO = await self._object_storage.open(snapshot.object_storage_path)
        try:
            prefix = stream.read(CONTENT_SNIFF_BYTES)
            stream.seek(0)
            detected_content_type = UploadContentInspector.inspect(snapshot.file_name, prefix)

            digest = hashlib.sha256()
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
            return _VerifiedObject(
                content_type=detected_content_type, sha256=digest.hexdigest(), size_bytes=stored.size_bytes
            )
        finally:
            stream.close()

    async def _finalize_verification(
        self, snapshot: "_VerificationSnapshot", verified: "_VerifiedObject"
    ) -> CompletedUploadView:
        ctx = get_tenant_context()
        upload_session = await self._sessions.find_for_update(snapshot.session_id, ctx.org_id)
        if upload_session is None:
            raise ResourceNotFoundException("上传会话不存在")
        if upload_session.status == UploadSessionStatus.COMPLETED:
            return await self._completed_view(upload_session)
        self._require_verification_token(upload_session, snapshot.verification_token)

        document = KnowledgeDocument(
            kb_id=upload_session.kb_id,
            org_id=upload_session.org_id,
            created_by=upload_session.created_by,
            name=upload_session.file_name,
            content_type=verified.content_type,
            size_bytes=verified.size_bytes,
            object_storage_path=upload_session.object_storage_path,
            content_sha256=verified.sha256,
            status=IngestionStatus.QUEUED,
        )
        document = await self._documents.save(document)
        await self._session.flush()

        job = IngestionJob(
            document_id=document.id,
            kb_id=upload_session.kb_id,
            org_id=upload_session.org_id,
            status=IngestionStatus.QUEUED,
            attempt=0,
            max_attempts=3,
        )
        job = await self._jobs.save(job)

        upload_session.document_id = document.id
        upload_session.status = UploadSessionStatus.COMPLETED
        upload_session.completed_at = datetime.now(timezone.utc)
        self._clear_verification(upload_session)
        await self._sessions.save(upload_session)
        await self._session.commit()
        self._metrics.upload_completed()
        return CompletedUploadView(
            sessionId=upload_session.id, documentId=document.id, jobId=job.id, status=IngestionStatus.QUEUED
        )

    async def _reset_verification(self, snapshot: "_VerificationSnapshot") -> None:
        ctx = get_tenant_context()
        upload_session = await self._sessions.find_for_update(snapshot.session_id, ctx.org_id)
        if (
            upload_session is not None
            and upload_session.status == UploadSessionStatus.VERIFYING
            and upload_session.verification_token == snapshot.verification_token
        ):
            upload_session.status = UploadSessionStatus.PENDING
            self._clear_verification(upload_session)
            await self._sessions.save(upload_session)
            await self._session.commit()

    async def cleanup_expired_session(self, session_id: UUID, org_id: UUID) -> None:
        """供后台清理任务调用(见模块文档字符串),不在本类内注册调度。"""
        upload_session = await self._sessions.find_for_update(session_id, org_id)
        if (
            upload_session is None
            or upload_session.status != UploadSessionStatus.PENDING
            or upload_session.expires_at > datetime.now(timezone.utc)
        ):
            return
        await self._expire_session(upload_session)
        await self._session.commit()

    async def _expire_session(self, upload_session: DocumentUploadSession) -> None:
        await self._object_storage.delete(upload_session.object_storage_path)
        upload_session.status = UploadSessionStatus.EXPIRED
        self._clear_verification(upload_session)
        await self._sessions.save(upload_session)
        self._metrics.upload_expired()

    async def _existing_view(self, upload_session: DocumentUploadSession) -> UploadSessionView:
        if upload_session.status == UploadSessionStatus.PENDING and upload_session.expires_at > datetime.now(
            timezone.utc
        ):
            return await self._with_presigned_url(upload_session)
        if upload_session.status == UploadSessionStatus.VERIFYING:
            return UploadSessionView(
                sessionId=upload_session.id,
                status=upload_session.status,
                uploadUrl=None,
                method=None,
                headers=None,
                expiresAt=upload_session.expires_at,
                documentId=None,
            )
        if upload_session.status in (UploadSessionStatus.PENDING, UploadSessionStatus.EXPIRED):
            raise BusinessConflictException("该幂等键对应的上传会话已过期，请使用新的 Idempotency-Key")
        return UploadSessionView(
            sessionId=upload_session.id,
            status=upload_session.status,
            uploadUrl=None,
            method=None,
            headers=None,
            expiresAt=upload_session.expires_at,
            documentId=upload_session.document_id,
        )

    async def _with_presigned_url(self, upload_session: DocumentUploadSession) -> UploadSessionView:
        remaining = upload_session.expires_at - datetime.now(timezone.utc)
        if remaining.total_seconds() <= 0:
            return await self._existing_view(upload_session)
        signed = await self._object_storage.presign_put(
            upload_session.object_storage_path, upload_session.content_type, remaining
        )
        return UploadSessionView(
            sessionId=upload_session.id,
            status=upload_session.status,
            uploadUrl=signed.url,
            method=signed.method,
            headers=signed.headers,
            expiresAt=upload_session.expires_at,
            documentId=None,
        )

    async def _completed_view(self, upload_session: DocumentUploadSession) -> CompletedUploadView:
        job = await self._jobs.find_first_by_document_id_order_by_created_at_desc(upload_session.document_id)
        if job is None:
            raise RuntimeError("已完成上传会话缺少摄取任务")
        document = await self._documents.find_by_id(upload_session.document_id)
        return CompletedUploadView(
            sessionId=upload_session.id, documentId=upload_session.document_id, jobId=job.id, status=document.status
        )

    def _build_staging_key(self, kb_id: UUID, session_id: UUID, extension: str) -> str:
        ctx = get_tenant_context()
        return f"org/{ctx.org_id}/kb/{kb_id}/uploads/{session_id}.{extension}"

    def _normalize_idempotency_key(self, value: str | None) -> str:
        if not value or not value.strip() or len(value) > 200:
            raise ValueError("Idempotency-Key 必须为 1-200 个字符")
        return value.strip()

    def _validate_ttl(self) -> None:
        # S3/MinIO V4 预签名 URL 的有效期上限为 7 天。
        if self._ttl_seconds < 1 or self._ttl_seconds > 604_800:
            raise RuntimeError("rag_direct_upload_ttl_seconds 必须在 1-604800 之间")

    def _validate_verification_timeout(self) -> None:
        if self._verification_timeout_ms < 1_000 or self._verification_timeout_ms > 3_600_000:
            raise RuntimeError("rag_direct_upload_verification_timeout_ms 必须在 1000-3600000 之间")

    def _require_verification_token(self, upload_session: DocumentUploadSession, expected_token: UUID) -> None:
        if upload_session.status != UploadSessionStatus.VERIFYING or upload_session.verification_token != expected_token:
            raise BusinessConflictException("上传校验权已过期，请重试 complete")

    def _clear_verification(self, upload_session: DocumentUploadSession) -> None:
        upload_session.verification_token = None
        upload_session.verification_started_at = None

    async def _find_knowledge_base(self, kb_id: UUID):
        ctx = get_tenant_context()
        kb = await self._kbs.find_by_id_and_org_id(kb_id, ctx.org_id)
        if kb is None:
            raise ResourceNotFoundException("知识库不存在")
        return kb

    async def _require_document_manager(self) -> None:
        ctx = get_tenant_context()
        try:
            role = MemberRole(ctx.role)
        except ValueError as exc:
            raise AccessDeniedException("当前成员没有文档管理权限") from exc
        if role not in (MemberRole.OWNER, MemberRole.ADMIN):
            raise AccessDeniedException("仅组织 Owner 或 Admin 可以管理文档")


class _VerificationSnapshot:
    def __init__(
        self, session_id: UUID, verification_token: UUID, file_name: str, object_storage_path: str, expected_size_bytes: int
    ) -> None:
        self.session_id = session_id
        self.verification_token = verification_token
        self.file_name = file_name
        self.object_storage_path = object_storage_path
        self.expected_size_bytes = expected_size_bytes


class _VerifiedObject:
    def __init__(self, content_type: str, sha256: str, size_bytes: int) -> None:
        self.content_type = content_type
        self.sha256 = sha256
        self.size_bytes = size_bytes
