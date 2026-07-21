"""认证请求/响应 DTO。对应 Java 版 AuthController 内嵌的 RegisterRequest / LoginRequest /
ChangePasswordRequest record 类。
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

# 与 Java 版 AuthService.EMAIL_PATTERN 完全一致,不用 pydantic EmailStr(需要额外的
# email-validator 依赖,pyproject.toml 未声明);DTO 层和 AuthService 内部各校验一次，
# 与 Java 版 @Email 注解 + service 层正则双重校验的结构对应。
_EMAIL_REGEX = r"^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+$"


class RegisterRequest(BaseModel):
    email: str = Field(..., pattern=_EMAIL_REGEX, description="邮箱不能为空，需为合法邮箱格式")
    password: str = Field(..., min_length=8, description="密码不能为空，至少 8 位")
    display_name: str | None = Field(default=None, alias="displayName")

    model_config = {"populate_by_name": True}


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, description="邮箱不能为空")
    password: str = Field(..., min_length=1, description="密码不能为空")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, alias="oldPassword", description="旧密码不能为空")
    new_password: str = Field(..., min_length=8, alias="newPassword", description="新密码至少 8 位")

    model_config = {"populate_by_name": True}


class AuthResult(BaseModel):
    """对应 Java 版 AuthService.register/login 返回的 Map<String, Object>。"""

    token: str
    user_id: UUID = Field(..., alias="userId")
    org_id: UUID | None = Field(default=None, alias="orgId")
    must_change_password: bool | None = Field(default=None, alias="mustChangePassword")

    model_config = {"populate_by_name": True}
