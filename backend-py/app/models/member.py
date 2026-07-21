"""成员:subject(认证主体)在某组织内的身份。对应 model/Member.java,
表定义见 V001__create_tenant_tables.sql。

唯一约束 (subject_id, org_id) —— 一个 subject 在一个组织只能有一条记录,一个 subject 可
在多个组织各有一条 member 记录(多组织身份的基础)。
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import MemberRole

if TYPE_CHECKING:
    from app.models.organization import Organization


class Member(Base):
    __tablename__ = "member"
    __table_args__ = (
        UniqueConstraint("subject_id", "org_id", name="uk_member_subject_org"),
        Index("idx_member_org_id", "org_id"),
        Index("idx_member_subject_id", "subject_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False
    )
    role: Mapped[MemberRole] = mapped_column(
        SAEnum(MemberRole, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=MemberRole.MEMBER.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    org: Mapped["Organization"] = relationship(viewonly=True)
