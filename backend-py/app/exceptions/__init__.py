"""业务异常类 + FastAPI 全局异常处理器。对应 Java 版 exception/ 包。"""

from app.exceptions.errors import (
    AccessDeniedException,
    AccountLockedException,
    BusinessConflictException,
    ResourceNotFoundException,
    UnauthenticatedException,
)
from app.exceptions.handlers import register_exception_handlers

__all__ = [
    "AccessDeniedException",
    "AccountLockedException",
    "BusinessConflictException",
    "ResourceNotFoundException",
    "UnauthenticatedException",
    "register_exception_handlers",
]
