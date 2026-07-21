"""知识库 DTO。对应 Java 版 KnowledgeBaseController 内嵌的 CreateKbRequest / UpdateKbRequest,
以及直接把 model.KnowledgeBase 实体序列化返回的响应体。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import KbStatus


class CreateKbRequest(BaseModel):
    name: str = Field(..., min_length=1, description="知识库名称不能为空")


class UpdateKbRequest(BaseModel):
    name: str = Field(..., min_length=1, description="知识库名称不能为空")


class KnowledgeBaseOut(BaseModel):
    id: UUID
    org_id: UUID = Field(..., alias="orgId")
    team_id: UUID | None = Field(default=None, alias="teamId")
    name: str
    status: KbStatus
    created_by: UUID | None = Field(default=None, alias="createdBy")
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}
