"""组织 DTO。对应 Java 版 OrganizationController 内嵌的 CreateOrgRequest,
以及直接把 model.Organization 实体序列化返回的响应体。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateOrgRequest(BaseModel):
    name: str = Field(..., min_length=1, description="组织名称不能为空")


class OrganizationOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}
