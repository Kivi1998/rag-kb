"""RAG 查询审计;只保存可观测性元数据,不保存问题、答案、Prompt 或正文。
对应 model/QueryAuditLog.java,表定义分布在 V006__add_rag_query_audit.sql /
V014__add_query_predicted_intent.sql。

注意:Java 实体上没有 @Filter(tenantFilter) 注解,repository 也只继承基础 JpaRepository、
没有任何按 org_id 过滤的自定义查询方法 —— 如实照搬这一行为,不在本次改造中臆造过滤逻辑
(该表虽有 org_id/kb_id 外键字段,但访问层历史上就是全表可查,继承自 Java 版原始行为)。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class QueryAuditLog(Base):
    __tablename__ = "rag_query_audit"
    __table_args__ = (
        CheckConstraint(
            "retrieval_latency_ms >= 0 AND generation_latency_ms >= 0 "
            "AND total_latency_ms >= 0 AND output_characters >= 0",
            name="chk_rag_query_audit_latency",
        ),
        Index("idx_rag_query_audit_org_kb_created", "org_id", "kb_id", text("created_at DESC")),
        Index("idx_rag_query_audit_trace_id", "trace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_base.id"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("member.id"), nullable=False
    )
    # Java 侧用 @Enumerated(EnumType.STRING) 但列上无 CHECK 约束,这里用 String 而非 SAEnum
    # 保持与既有列宽/无约束的行为完全一致;应用层校验请用 app.models.enums.QueryAuditStatus。
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    retrieval_latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generation_latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    document_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    final_scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    rerank_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    refusal_reason: Mapped[str | None] = mapped_column(String(300))
    # precise-lookup/semantic/comparative/out-of-scope 之一;分类失败或未启用时为 null。不存问题原文(V014)
    predicted_intent: Mapped[str | None] = mapped_column(String(32))
    generation_model: Mapped[str | None] = mapped_column(String(300))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    output_characters: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
