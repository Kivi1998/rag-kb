"""本地账号(认证主体)。对应 model/User.java,表定义见 V002__create_user_table.sql。

与 Member 通过 subject_id(= user.id 的字符串形式)关联,本表不持有 org_id —— 一个 User
可在多个组织各有一条 Member 记录。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.enums import UserStatus


class User(Base):
    __tablename__ = "app_user"
    __table_args__ = (Index("idx_user_email", "email"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=UserStatus.ACTIVE.value,
    )
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # 管理员重置密码时自增;JWT 里携带的 token_version 与此值不一致即视为旧 token 失效
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
