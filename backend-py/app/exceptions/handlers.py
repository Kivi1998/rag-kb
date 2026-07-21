"""全局异常处理器。对应 Java 版 exception/GlobalExceptionHandler.java(@RestControllerAdvice)。

错码约定(与 Java 版 / OpenSpec design 对齐):
- 400: 参数非法 / 业务校验失败
- 401: 未认证
- 403: 同租户内角色权限不足
- 404: 资源不存在(含跨租户——对其他组织资源一律按不存在处理)
- 409: 业务不变量冲突(如:降级最后一名 owner)
- 413: 上传文件超过大小限制
- 423: 账号已锁定
- 500: 服务端内部错误(非业务异常)

用 `register_exception_handlers(app)` 在 app.main 里统一挂载,不用装饰器分散注册,
方便一眼看清所有错码映射(对应 Java 版单个 @RestControllerAdvice 类的可读性)。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions.errors import (
    AccessDeniedException,
    AccountLockedException,
    BusinessConflictException,
    ResourceNotFoundException,
    UnauthenticatedException,
)

logger = logging.getLogger(__name__)


def _fail(code: int, message: str) -> dict:
    """对应 Java 版 ApiResponse.fail(code, message);data 字段按 @JsonInclude(NON_NULL) 省略。"""
    return {"code": code, "message": message}


def register_exception_handlers(app: FastAPI) -> None:
    """在 app.main 的 FastAPI 实例上挂载全部异常处理器。"""

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        """参数非法(400)。对应 Java 版 MethodArgumentNotValidException /
        MethodArgumentTypeMismatchException 处理器(FastAPI 把请求体/路径/查询参数校验失败
        统一归到 RequestValidationError,不像 Spring 那样拆成两个异常类型)。
        """
        parts = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
        message = "; ".join(parts) if parts else "参数校验失败"
        return JSONResponse(status_code=400, content=_fail(400, message))

    @app.exception_handler(ValueError)
    async def handle_value_error(_: Request, exc: ValueError) -> JSONResponse:
        """参数非法 / 业务校验失败(400)。对应 Java 版 IllegalArgumentException 处理器。"""
        return JSONResponse(status_code=400, content=_fail(400, str(exc)))

    @app.exception_handler(UnauthenticatedException)
    async def handle_unauthenticated(_: Request, exc: UnauthenticatedException) -> JSONResponse:
        """未认证(401)。"""
        return JSONResponse(status_code=401, content=_fail(401, str(exc)))

    @app.exception_handler(AccessDeniedException)
    async def handle_access_denied(_: Request, exc: AccessDeniedException) -> JSONResponse:
        """同租户内角色权限不足(403)。"""
        return JSONResponse(status_code=403, content=_fail(403, str(exc)))

    @app.exception_handler(AccountLockedException)
    async def handle_account_locked(_: Request, exc: AccountLockedException) -> JSONResponse:
        """账号已锁定(423)。"""
        return JSONResponse(status_code=423, content=_fail(423, str(exc)))

    @app.exception_handler(ResourceNotFoundException)
    async def handle_not_found(_: Request, exc: ResourceNotFoundException) -> JSONResponse:
        """资源不存在(404) —— 含跨租户(对其他组织资源一律按不存在处理)。"""
        return JSONResponse(status_code=404, content=_fail(404, str(exc)))

    @app.exception_handler(BusinessConflictException)
    async def handle_conflict(_: Request, exc: BusinessConflictException) -> JSONResponse:
        """业务不变量冲突(409)。"""
        return JSONResponse(status_code=409, content=_fail(409, str(exc)))

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        """数据库唯一约束或关联约束冲突(409),避免并发幂等请求泄漏为 500。
        对应 Java 版 DataIntegrityViolationException 处理器。
        """
        logger.info("数据完整性冲突", exc_info=exc)
        return JSONResponse(
            status_code=409,
            content=_fail(409, "请求与已有数据冲突，请使用相同参数重试或更换幂等键"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        """透传 FastAPI/依赖层主动抛出的 HTTPException(如鉴权依赖里的 401/503),
        统一包成 ApiResponse 形状,不让它们落到下面的 500 兜底。
        """
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content=_fail(exc.status_code, detail))

    @app.exception_handler(Exception)
    async def handle_unknown(_: Request, exc: Exception) -> JSONResponse:
        """服务端内部错误兜底(500)。对应 Java 版 Exception 处理器。"""
        logger.error("未捕获异常", exc_info=exc)
        return JSONResponse(status_code=500, content=_fail(500, "服务内部错误"))
