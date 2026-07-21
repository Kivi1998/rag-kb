"""意图分类训练数据留存:存「问题原文 + 预测意图标签」,供未来训练 BERT 分类器替换
现在的 LLM Prompt 粗分类。对应 model/IntentTrainingSample.java,表定义见
V015__add_intent_training_sample.sql。

与 QueryAuditLog 不同:本表存问题原文,明文不脱敏,默认开启
(rag.intent-training-data.enabled=true),不做自动清理 —— 均为 2026-07-17 brainstorming
阶段用户明确决定。三个外键均带 ON DELETE CASCADE,对齐 document 表(V003)的既有模式。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class IntentTrainingSample(Base):
    __tablename__ = "intent_training_sample"
    __table_args__ = (
        Index("idx_intent_training_sample_org_created", "org_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("member.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_intent: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
