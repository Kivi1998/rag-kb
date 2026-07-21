"""组织控制器。对应 Java 版 controller/OrganizationController.java。

POST /api/v1/organizations = bootstrap(免租户上下文,但需 JWT)
GET  /api/v1/organizations/{id} = 需认证+租户上下文
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.repositories.member_repository import MemberRepository
from app.repositories.organization_repository import OrganizationRepository
from app.routers.deps import get_session, require_tenant, require_user
from app.schemas.common import ApiResponse
from app.schemas.organization import CreateOrgRequest, OrganizationOut
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


def _org_service(db: AsyncSession = Depends(get_session)) -> OrganizationService:
    return OrganizationService(OrganizationRepository(db), MemberRepository(db), db)


@router.post(
    "",
    response_model=ApiResponse[OrganizationOut],
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def create(
    req: CreateOrgRequest,
    subject_id: str = Depends(require_user),
    service: OrganizationService = Depends(_org_service),
) -> ApiResponse[OrganizationOut]:
    """创建组织(免租户上下文,但需有效 JWT);subject 从鉴权依赖返回值获取(已验证 JWT 签名)。"""
    org = await service.create(subject_id, req.name)
    return ApiResponse.ok(OrganizationOut.model_validate(org))


@router.get("/{org_id}", response_model=ApiResponse[OrganizationOut], response_model_exclude_none=True)
async def get_by_id(
    org_id: UUID,
    _: UUID = Depends(require_tenant),
    service: OrganizationService = Depends(_org_service),
) -> ApiResponse[OrganizationOut]:
    org = await service.get_by_id(org_id)
    return ApiResponse.ok(OrganizationOut.model_validate(org))
