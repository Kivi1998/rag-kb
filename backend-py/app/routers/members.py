"""成员控制器(需认证+租户上下文)。对应 Java 版 controller/MemberController.java。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import get_tenant_context
from app.exceptions.errors import AccessDeniedException, ResourceNotFoundException
from app.models.enums import MemberRole
from app.repositories.member_repository import MemberRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.routers.deps import get_session, require_tenant
from app.schemas.common import ApiResponse
from app.schemas.member import ChangeRoleRequest, InviteMemberRequest, MemberOut
from app.services.auth_service import AuthService
from app.services.member_service import MemberService

router = APIRouter(
    prefix="/api/v1/members",
    tags=["members"],
    dependencies=[Depends(require_tenant)],
)


def _member_service(db: AsyncSession = Depends(get_session)) -> MemberService:
    return MemberService(MemberRepository(db), OrganizationRepository(db), db)


def _auth_service(db: AsyncSession = Depends(get_session)) -> AuthService:
    return AuthService(UserRepository(db), MemberRepository(db), db)


@router.post("", response_model=ApiResponse[MemberOut], response_model_exclude_none=True)
async def invite(
    req: InviteMemberRequest, service: MemberService = Depends(_member_service)
) -> ApiResponse[MemberOut]:
    member = await service.invite(req.subject_id, req.role)
    return ApiResponse.ok(MemberOut.model_validate(member))


@router.get("", response_model=ApiResponse[list[MemberOut]], response_model_exclude_none=True)
async def list_members(service: MemberService = Depends(_member_service)) -> ApiResponse[list[MemberOut]]:
    members = await service.list_by_current_org()
    return ApiResponse.ok([MemberOut.model_validate(m) for m in members])


@router.get("/me", response_model=ApiResponse[MemberOut], response_model_exclude_none=True)
async def me(service: MemberService = Depends(_member_service)) -> ApiResponse[MemberOut]:
    ctx = get_tenant_context()
    if ctx.member_id is None:
        raise ResourceNotFoundException("当前用户无成员身份")
    member = await service.get_by_id_and_current_org(ctx.member_id)
    return ApiResponse.ok(MemberOut.model_validate(member))


@router.get("/{member_id}", response_model=ApiResponse[MemberOut], response_model_exclude_none=True)
async def get_by_id(member_id: UUID, service: MemberService = Depends(_member_service)) -> ApiResponse[MemberOut]:
    member = await service.get_by_id_and_current_org(member_id)
    return ApiResponse.ok(MemberOut.model_validate(member))


@router.patch("/{member_id}/role", response_model=ApiResponse[MemberOut], response_model_exclude_none=True)
async def change_role(
    member_id: UUID, req: ChangeRoleRequest, service: MemberService = Depends(_member_service)
) -> ApiResponse[MemberOut]:
    member = await service.change_role(member_id, req.role)
    return ApiResponse.ok(MemberOut.model_validate(member))


@router.post("/{member_id}/reset-password", response_model=ApiResponse[str], response_model_exclude_none=True)
async def reset_password(
    member_id: UUID,
    member_service: MemberService = Depends(_member_service),
    auth_service: AuthService = Depends(_auth_service),
) -> ApiResponse[str]:
    """管理员重置成员密码(仅 owner/admin)。"""
    target_member = await member_service.get_by_id_and_current_org(member_id)
    target_user_id = UUID(target_member.subject_id)
    ctx = get_tenant_context()
    # admin 不可重置 owner 密码,防止通过临时密码完成特权提升
    if ctx.role == "ADMIN" and target_member.role == MemberRole.OWNER:
        raise AccessDeniedException("admin 不可重置 owner 的密码")
    temp_password = await auth_service.admin_reset_password(ctx.member_id, target_user_id, ctx.role)
    return ApiResponse.ok(temp_password)
