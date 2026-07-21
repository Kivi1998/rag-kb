"""认证控制器:注册/登录/改密。对应 Java 版 controller/AuthController.java。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.repositories.member_repository import MemberRepository
from app.repositories.user_repository import UserRepository
from app.routers.deps import get_session, require_user
from app.schemas.auth import AuthResult, ChangePasswordRequest, LoginRequest, RegisterRequest
from app.schemas.common import ApiResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _auth_service(db: AsyncSession = Depends(get_session)) -> AuthService:
    return AuthService(UserRepository(db), MemberRepository(db), db)


@router.post(
    "/register",
    response_model=ApiResponse[AuthResult],
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def register(req: RegisterRequest, service: AuthService = Depends(_auth_service)) -> ApiResponse[AuthResult]:
    """注册(免认证)。"""
    result = await service.register(req.email, req.password, req.display_name)
    return ApiResponse.ok(result)


@router.post("/login", response_model=ApiResponse[AuthResult], response_model_exclude_none=True)
async def login(req: LoginRequest, service: AuthService = Depends(_auth_service)) -> ApiResponse[AuthResult]:
    """登录(免认证)。"""
    result = await service.login(req.email, req.password)
    return ApiResponse.ok(result)


@router.post("/change-password", response_model=ApiResponse[None], response_model_exclude_none=True)
async def change_password(
    req: ChangePasswordRequest,
    request: Request,
    subject: str = Depends(require_user),
    service: AuthService = Depends(_auth_service),
) -> ApiResponse[None]:
    """修改密码(需认证)。userId/jti/剩余有效期均来自鉴权依赖写入的 request.state
    (对应 Java 版从 HttpServletRequest attribute 读取 JwtAuthFilter 设置的值)。
    """
    user_id = getattr(request.state, "user_id", None) or UUID(subject)
    jti = getattr(request.state, "jwt_jti", None)
    remaining_seconds = getattr(request.state, "jwt_remaining_seconds", 0)

    await service.change_password(user_id, req.old_password, req.new_password, jti, remaining_seconds)
    return ApiResponse.ok()
