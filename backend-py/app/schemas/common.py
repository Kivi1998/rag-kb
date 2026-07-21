"""统一响应格式。对应 Java 版 common/ApiResponse.java。"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """业务码:0=成功,非 0=业务异常。data 为空时序列化省略,对应 Java 版
    @JsonInclude(JsonInclude.Include.NON_NULL)——路由层用 response_model_exclude_none=True
    达到同样效果。
    """

    code: int = 0
    message: str = "success"
    data: T | None = None

    @classmethod
    def ok(cls, data: T | None = None) -> "ApiResponse[T]":
        return cls(code=0, message="success", data=data)

    @classmethod
    def fail(cls, code: int, message: str) -> "ApiResponse[T]":
        return cls(code=code, message=message, data=None)
