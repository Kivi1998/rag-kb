"""团队 DTO。对应 Java 版 TeamController 内嵌的 CreateTeamRequest,
以及直接把 model.Team 实体序列化返回的响应体。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, description="团队名称不能为空")


class TeamOut(BaseModel):
    id: UUID
    org_id: UUID = Field(..., alias="orgId")
    name: str
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}
