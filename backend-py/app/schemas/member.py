"""成员 DTO。对应 Java 版 MemberController 内嵌的 InviteMemberRequest / ChangeRoleRequest,
以及直接把 model.Member 实体序列化返回的响应体。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import MemberRole


class InviteMemberRequest(BaseModel):
    subject_id: str = Field(..., min_length=1, alias="subjectId", description="subjectId 不能为空")
    role: MemberRole = Field(..., description="角色不能为空")

    model_config = {"populate_by_name": True}


class ChangeRoleRequest(BaseModel):
    role: MemberRole = Field(..., description="新角色不能为空")


class MemberOut(BaseModel):
    id: UUID
    subject_id: str = Field(..., alias="subjectId")
    org_id: UUID = Field(..., alias="orgId")
    role: MemberRole
    created_at: datetime = Field(..., alias="createdAt")
    updated_at: datetime = Field(..., alias="updatedAt")

    model_config = {"from_attributes": True, "populate_by_name": True}

# 重置密码接口直接返回 ApiResponse[str](临时密码字符串本体),
# 对应 Java 版 ApiResponse<String>,不需要额外包一层对象。
