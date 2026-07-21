"""多轮对话会话生命周期元数据。会话内容(消息/画像)本身存 MongoDB,这里只存 Hibernate
tenantFilter 需要的归属与状态机字段。对应 model/ChatSession.java,表定义分布在
V012__add_chat_session.sql / V013__add_chat_session_title.sql。
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import ChatSessionStatus

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase
    from app.models.member import Member
    from app.models.organization import Organization


class ChatSession(Base):
    __tablename__ = "chat_session"
    __table_args__ = (
        Index("idx_chat_session_org_id", "org_id"),
        Index("idx_chat_session_kb_id", "kb_id"),
        Index("idx_chat_session_member_id", "member_id"),
        Index("idx_chat_session_last_active_at", "last_active_at"),
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
    member_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("member.id"), nullable=False
    )
    # ACTIVE=30分钟内有新消息;IDLE=超过30分钟未超2小时;ARCHIVED=超过2小时;有新消息随时续期回 ACTIVE
    status: Mapped[ChatSessionStatus] = mapped_column(
        SAEnum(
            ChatSessionStatus, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        server_default=ChatSessionStatus.ACTIVE.value,
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # 首条用户消息前 30 字,写入时算好,只在为空时写一次;供历史会话列表展示(V013)
    title: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    org: Mapped["Organization"] = relationship(viewonly=True)
    knowledge_base: Mapped["KnowledgeBase"] = relationship(viewonly=True)
    member: Mapped["Member"] = relationship(viewonly=True)
