"""MinIO/S3 预签名直传会话;完成前不会创建可消费的 ingestion_job。
对应 model/DocumentUploadSession.java,表定义分布在 V009__add_document_upload_session.sql /
V011__add_upload_verification_lease.sql。
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import UploadSessionStatus

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase
    from app.models.knowledge_document import KnowledgeDocument
    from app.models.member import Member
    from app.models.organization import Organization


class DocumentUploadSession(Base):
    __tablename__ = "document_upload_session"
    __table_args__ = (
        CheckConstraint("expected_size_bytes > 0", name="chk_upload_session_size"),
        UniqueConstraint("org_id", "kb_id", "idempotency_key", name="uq_upload_session_idempotency"),
        # 校验 fencing:VERIFYING 状态必须同时持有 token+开始时间,其余状态必须同时为空(V011)
        CheckConstraint(
            "(status = 'VERIFYING' AND verification_token IS NOT NULL AND verification_started_at IS NOT NULL) "
            "OR (status <> 'VERIFYING' AND verification_token IS NULL AND verification_started_at IS NULL)",
            name="chk_upload_verification_lease",
        ),
        Index(
            "idx_upload_session_expiry",
            "expires_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "idx_upload_session_verification_recovery",
            "verification_started_at",
            postgresql_where=text("status = 'VERIFYING'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("member.id"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(200), nullable=False)
    expected_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[UploadSessionStatus] = mapped_column(
        SAEnum(
            UploadSessionStatus, native_enum=False, length=30, values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        server_default=UploadSessionStatus.PENDING.value,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 大文件完整性校验在数据库事务外进行,token 用于防止超时校验者误提交(V011)
    verification_token: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    verification_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    org: Mapped["Organization"] = relationship(viewonly=True)
    knowledge_base: Mapped["KnowledgeBase"] = relationship(viewonly=True)
    creator: Mapped["Member"] = relationship(viewonly=True)
    document: Mapped["KnowledgeDocument | None"] = relationship(viewonly=True)
