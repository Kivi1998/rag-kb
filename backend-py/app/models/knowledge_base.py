"""知识库(归属唯一组织,可选归属团队)。对应 model/KnowledgeBase.java,
表定义见 V001__create_tenant_tables.sql,ragflow_chat_id 见 V004__add_kb_ragflow_chat_id.sql。
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import KbStatus

if TYPE_CHECKING:
    from app.models.member import Member
    from app.models.organization import Organization
    from app.models.team import Team


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    __table_args__ = (
        Index("idx_kb_org_id", "org_id"),
        Index("idx_kb_team_id", "team_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False
    )
    # 可选:归属团队
    team_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("team.id"))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    # RAGFlow dataset 映射(历史字段,自研链路不再写入,保留兼容旧数据)
    ragflow_dataset_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[KbStatus] = mapped_column(
        SAEnum(KbStatus, native_enum=False, length=30, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=KbStatus.ACTIVE.value,
    )
    # 知识库关联的 RAGFlow Chat Assistant;懒建策略,首次问答时由 QueryService 创建并写入(V004)
    ragflow_chat_id: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("member.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    org: Mapped["Organization"] = relationship(viewonly=True)
    team: Mapped["Team | None"] = relationship(viewonly=True)
    creator: Mapped["Member | None"] = relationship(viewonly=True)
