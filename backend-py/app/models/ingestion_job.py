"""文档异步摄取任务。对应 model/IngestionJob.java,表定义分布在
V005__add_document_ingestion.sql / V007__add_ingestion_worker_lease.sql。
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import IngestionStatus

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase
    from app.models.knowledge_document import KnowledgeDocument
    from app.models.organization import Organization

# 活跃(未终态)摄取状态,对应 Flyway 分区索引里重复出现的 WHERE status IN (...) 条件
_ACTIVE_STATUSES_SQL = "status IN ('QUEUED', 'PARSING', 'CHUNKING', 'EMBEDDING', 'INDEXING')"


class IngestionJob(Base):
    __tablename__ = "ingestion_job"
    __table_args__ = (
        CheckConstraint("attempt >= 0 AND max_attempts > 0", name="chk_ingestion_job_attempts"),
        Index("idx_ingestion_job_document_id", "document_id"),
        Index("idx_ingestion_job_org_kb_status", "org_id", "kb_id", "status"),
        Index(
            "idx_ingestion_job_queued",
            "created_at",
            postgresql_where=text("status = 'QUEUED'"),
        ),
        Index(
            "idx_ingestion_job_lease_recovery",
            "lease_expires_at",
            postgresql_where=text(_ACTIVE_STATUSES_SQL),
        ),
        # 同一文档同一时间只能有一个活跃摄取流程;FAILED 必须显式重试后迁回 QUEUED
        Index(
            "uq_ingestion_job_active_document",
            "document_id",
            unique=True,
            postgresql_where=text(_ACTIVE_STATUSES_SQL),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_base.id"), nullable=False
    )
    status: Mapped[IngestionStatus] = mapped_column(
        SAEnum(IngestionStatus, native_enum=False, length=30, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=IngestionStatus.QUEUED.value,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 当前处理实例及其租约;用于多实例竞争与故障接管(V007)
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    document: Mapped["KnowledgeDocument"] = relationship(viewonly=True)
    org: Mapped["Organization"] = relationship(viewonly=True)
    knowledge_base: Mapped["KnowledgeBase"] = relationship(viewonly=True)
