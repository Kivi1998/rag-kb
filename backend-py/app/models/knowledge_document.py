"""知识库中的原始技术文档及其对象存储定位。对应 model/KnowledgeDocument.java(表名 document),
表定义分布在 V003__create_document_table.sql / V005__add_document_ingestion.sql /
V008__add_document_content_hash.sql / V010__add_document_parse_artifact.sql。

注意:org_id 在此表冗余存储(不经 kb_id 二跳查 knowledge_base),便于直接按租户过滤,
对应 V003 注释「文档隶属于知识库,冗余 org_id 以便 Hibernate @Filter 直接过滤」。
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import IngestionStatus

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase
    from app.models.member import Member
    from app.models.organization import Organization


class KnowledgeDocument(Base):
    __tablename__ = "document"
    __table_args__ = (
        Index("idx_document_org_id", "org_id"),
        Index("idx_document_kb_id", "kb_id"),
        # 部分索引:仅对已有内容哈希的行建索引,用于同知识库内容去重查询(V008)
        Index(
            "idx_document_org_kb_content_hash",
            "org_id",
            "kb_id",
            "content_sha256",
            postgresql_where=text("content_sha256 IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    # 历史 RAGFlow 文档映射,自研链路不再写入(V005 起新链路只用 object_storage_path)
    ragflow_doc_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[IngestionStatus] = mapped_column(
        SAEnum(IngestionStatus, native_enum=False, length=30, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=IngestionStatus.QUEUED.value,
    )
    # DB 列存在但 Java 实体未映射(model/KnowledgeDocument.java 缺 errorMessage 字段);
    # 按 Flyway schema 为准原样保留,避免访问层丢字段。
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("member.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # MinIO/S3 对象键,格式 org/{orgId}/kb/{kbId}/documents/{documentId}.{ext}(V005)
    object_storage_path: Mapped[str | None] = mapped_column(String(1000))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 原始文件的 SHA-256,用于审计、内容去重与版本追溯(V008)
    content_sha256: Mapped[str | None] = mapped_column(String(64))

    # 结构化 ParsedDocument JSON 的对象存储路径及解析器版本(V010)
    parse_artifact_path: Mapped[str | None] = mapped_column(String(1000))
    parser_name: Mapped[str | None] = mapped_column(String(200))
    parser_version: Mapped[str | None] = mapped_column(String(100))
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    knowledge_base: Mapped["KnowledgeBase"] = relationship(viewonly=True)
    org: Mapped["Organization"] = relationship(viewonly=True)
    creator: Mapped["Member | None"] = relationship(viewonly=True)
