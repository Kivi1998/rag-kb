"""技术文档上传与摄取任务编排。对应 Java 版 service/DocumentIngestionService.java。

本服务只负责可靠地落原文件并创建 QUEUED 任务；解析、切分、向量化与索引由后续
Ingestion Worker 消费该任务。这样 HTTP 请求不会被复杂 PDF、代码仓库文档等长耗时工作阻塞。

**依赖状态说明(未接入 app.main,见该文件底部注释)**:本模块依赖的
`app.ragcore.storage.object_storage.ObjectStorage`、
`app.ragcore.upload.document_upload_policy.DocumentUploadPolicy`、
`app.ragcore.upload.upload_content_inspector.UploadContentInspector`、
`app.ragcore.ingestion.job_lifecycle_service.IngestionJobLifecycleService`、
`app.ragcore.ingestion.document_deletion_service.DocumentDeletionService`
目前是空目录/未落地(由其他并行任务负责 ragcore 摄取/存储/上传子系统)。这里按 Java 版
一一对应的类名/方法名先落好业务编排代码,导入路径是本次翻译按既有 ragcore 子包命名习惯
(如 `app.ragcore.retrieval.retriever` 的 `Retriever` Protocol 风格)推测的落点；等对应模块
落地后,若类名/模块路径与此处不同,只需改本文件顶部的 import 语句,不需要改业务逻辑。
"""

from __future__ import annotations

import hashlib
from typing import BinaryIO
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import get_tenant_context
from app.exceptions.errors import AccessDeniedException, ResourceNotFoundException
from app.models.enums import IngestionStatus, MemberRole
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.ragcore.ingestion.deletion_service import DocumentDeletionService
from app.ragcore.ingestion.lifecycle_service import IngestionJobLifecycleService
from app.ragcore.storage.object_storage import ObjectStorage
from app.ragcore.upload.document_upload_policy import DocumentUploadPolicy
from app.ragcore.upload.upload_content_inspector import UploadContentInspector
from app.repositories.ingestion_job_repository import IngestionJobRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.knowledge_document_repository import KnowledgeDocumentRepository
from app.repositories.member_repository import MemberRepository
from app.schemas.document import DocumentView, JobView

CONTENT_SNIFF_BYTES = 8 * 1024


class DocumentIngestionService:
    def __init__(
        self,
        kb_repository: KnowledgeBaseRepository,
        document_repository: KnowledgeDocumentRepository,
        job_repository: IngestionJobRepository,
        member_repository: MemberRepository,
        object_storage: ObjectStorage,
        lifecycle_service: IngestionJobLifecycleService,
        deletion_service: DocumentDeletionService,
        upload_policy: DocumentUploadPolicy,
        session: AsyncSession,
    ) -> None:
        self._kbs = kb_repository
        self._documents = document_repository
        self._jobs = job_repository
        self._members = member_repository
        self._object_storage = object_storage
        self._lifecycle_service = lifecycle_service
        self._deletion_service = deletion_service
        self._upload_policy = upload_policy
        self._session = session

    async def upload(
        self, kb_id: UUID, filename: str | None, size_bytes: int, file_stream: BinaryIO
    ) -> tuple[DocumentView, JobView]:
        """上传原文件并创建一个待消费的摄取任务。

        `file_stream` 对应 Java 版 `MultipartFile`;调用方(router)负责把 FastAPI
        `UploadFile.file` 传进来。
        """
        await self._require_document_manager()
        kb = await self._find_knowledge_base(kb_id)
        uploader = await self._current_member()
        validated = self._upload_policy.validate(filename, size_bytes)

        document = KnowledgeDocument(
            kb_id=kb.id,
            org_id=kb.org_id,
            created_by=uploader.id,
            name=validated.safe_file_name,
            size_bytes=size_bytes,
            status=IngestionStatus.QUEUED,
        )
        document = await self._documents.save(document)
        await self._session.flush()  # 确保 document.id 已生成

        storage_key = self._build_storage_key(kb_id, document.id, validated.extension)
        stored = False
        try:
            prefix = file_stream.read(CONTENT_SNIFF_BYTES)
            file_stream.seek(0)
            detected_content_type = UploadContentInspector.inspect(validated.safe_file_name, prefix)
            document.content_type = detected_content_type

            digest = hashlib.sha256()
            hashed_stream = _DigestReader(file_stream, digest)
            await self._object_storage.put(storage_key, hashed_stream, size_bytes, detected_content_type)
            stored = True
            document.object_storage_path = storage_key
            document.content_sha256 = digest.hexdigest()

            job = IngestionJob(
                document_id=document.id,
                kb_id=kb.id,
                org_id=kb.org_id,
                status=IngestionStatus.QUEUED,
                attempt=0,
                max_attempts=3,
            )
            job = await self._jobs.save(job)
            await self._session.commit()
            return self._to_document_view(document, job.id), self._to_job_view(job)
        except Exception:
            if stored:
                await self._object_storage.delete(storage_key)
            raise

    async def list(self, kb_id: UUID, status: IngestionStatus | None) -> list[DocumentView]:
        await self._find_knowledge_base(kb_id)
        ctx = get_tenant_context()
        documents = await self._documents.find_by_knowledge_base_id_and_org_id_order_by_created_at_desc(
            kb_id, ctx.org_id
        )
        result = []
        for document in documents:
            if status is not None and document.status != status:
                continue
            job_id = await self._latest_job_id(document.id)
            result.append(self._to_document_view(document, job_id))
        return result

    async def get_job(self, kb_id: UUID, job_id: UUID) -> JobView:
        await self._find_knowledge_base(kb_id)
        job = await self._find_job(job_id, kb_id)
        return self._to_job_view(job)

    async def retry(self, kb_id: UUID, job_id: UUID) -> JobView:
        """管理员可将失败任务重新放回队列;运行中或成功任务不能被重复入队。"""
        await self._require_document_manager()
        job = await self._find_job(job_id, kb_id)
        job = await self._lifecycle_service.retry(job.id)
        return self._to_job_view(job)

    async def delete(self, kb_id: UUID, document_id: UUID) -> None:
        """删除原文件、任务记录和文档元数据。向量索引删除在 Worker 的删除补偿任务中接入。"""
        await self._require_document_manager()
        await self._find_knowledge_base(kb_id)
        ctx = get_tenant_context()
        document = await self._documents.find_by_id_and_knowledge_base_id_and_org_id(document_id, kb_id, ctx.org_id)
        if document is None:
            raise ResourceNotFoundException("文档不存在")
        await self._deletion_service.request_deletion(document.id)
        await self._session.commit()
        await self._deletion_service.cleanup(document.id)
        await self._session.commit()

    async def _find_job(self, job_id: UUID, kb_id: UUID) -> IngestionJob:
        ctx = get_tenant_context()
        job = await self._jobs.find_by_id_and_knowledge_base_id_and_org_id(job_id, kb_id, ctx.org_id)
        if job is None:
            raise ResourceNotFoundException("摄取任务不存在")
        return job

    async def _find_knowledge_base(self, kb_id: UUID):
        ctx = get_tenant_context()
        kb = await self._kbs.find_by_id_and_org_id(kb_id, ctx.org_id)
        if kb is None:
            raise ResourceNotFoundException("知识库不存在")
        return kb

    async def _current_member(self):
        ctx = get_tenant_context()
        member = await self._members.find_by_id_and_org_id(ctx.member_id, ctx.org_id)
        if member is None:
            raise ResourceNotFoundException("成员不存在")
        return member

    async def _require_document_manager(self) -> None:
        ctx = get_tenant_context()
        try:
            role = MemberRole(ctx.role)
        except ValueError as exc:
            raise AccessDeniedException("当前成员没有文档管理权限") from exc
        if role not in (MemberRole.OWNER, MemberRole.ADMIN):
            raise AccessDeniedException("仅组织 Owner 或 Admin 可以管理文档")

    def _build_storage_key(self, kb_id: UUID, document_id: UUID, extension: str) -> str:
        ctx = get_tenant_context()
        return f"org/{ctx.org_id}/kb/{kb_id}/documents/{document_id}.{extension}"

    async def _latest_job_id(self, document_id: UUID) -> UUID | None:
        job = await self._jobs.find_first_by_document_id_order_by_created_at_desc(document_id)
        return job.id if job is not None else None

    def _to_document_view(self, document: KnowledgeDocument, job_id: UUID | None) -> DocumentView:
        return DocumentView(
            documentId=document.id,
            kbId=document.kb_id,
            name=document.name,
            size=document.size_bytes,
            contentType=document.content_type,
            status=document.status,
            errorMessage=document.last_error,
            retryCount=document.retry_count,
            retryable=document.status == IngestionStatus.FAILED and document.retry_count < 3,
            uploadedAt=document.created_at,
            readyAt=None,
            jobId=job_id,
        )

    def _to_job_view(self, job: IngestionJob) -> JobView:
        return JobView(
            jobId=job.id,
            documentId=job.document_id,
            kbId=job.kb_id,
            status=job.status,
            errorMessage=job.error_message,
            retryLimit=job.max_attempts,
            retryable=job.status == IngestionStatus.FAILED and job.attempt < job.max_attempts,
            createdAt=job.created_at,
            updatedAt=job.updated_at,
        )


class _DigestReader:
    """包一层同步 file-like 对象,读取时顺带累加 SHA-256——对应 Java 版
    `DigestInputStream` 包在 `BufferedInputStream` 外层,一次读取同时完成"转存对象存储"和
    "算内容哈希"两件事,不需要把整个文件读入内存两次。
    """

    def __init__(self, inner: BinaryIO, digest: "hashlib._Hash") -> None:
        self._inner = inner
        self._digest = digest

    def read(self, size: int = -1) -> bytes:
        chunk = self._inner.read(size)
        if chunk:
            self._digest.update(chunk)
        return chunk

    def close(self) -> None:
        pass
