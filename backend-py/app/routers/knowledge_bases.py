"""知识库控制器(需认证+租户上下文)。对应 Java 版 controller/KnowledgeBaseController.java。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.member_repository import MemberRepository
from app.repositories.organization_repository import OrganizationRepository
from app.routers.deps import get_session, require_tenant
from app.schemas.common import ApiResponse
from app.schemas.knowledge_base import CreateKbRequest, KnowledgeBaseOut, UpdateKbRequest
from app.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter(
    prefix="/api/v1/knowledge-bases",
    tags=["knowledge-bases"],
    dependencies=[Depends(require_tenant)],
)


def _kb_service(db: AsyncSession = Depends(get_session)) -> KnowledgeBaseService:
    return KnowledgeBaseService(
        KnowledgeBaseRepository(db), OrganizationRepository(db), MemberRepository(db), db
    )


@router.post(
    "",
    response_model=ApiResponse[KnowledgeBaseOut],
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def create(
    req: CreateKbRequest, service: KnowledgeBaseService = Depends(_kb_service)
) -> ApiResponse[KnowledgeBaseOut]:
    kb = await service.create(req.name)
    return ApiResponse.ok(KnowledgeBaseOut.model_validate(kb))


@router.get("", response_model=ApiResponse[list[KnowledgeBaseOut]], response_model_exclude_none=True)
async def list_kbs(service: KnowledgeBaseService = Depends(_kb_service)) -> ApiResponse[list[KnowledgeBaseOut]]:
    kbs = await service.list_by_current_org()
    return ApiResponse.ok([KnowledgeBaseOut.model_validate(kb) for kb in kbs])


@router.get("/{kb_id}", response_model=ApiResponse[KnowledgeBaseOut], response_model_exclude_none=True)
async def get_by_id(
    kb_id: UUID, service: KnowledgeBaseService = Depends(_kb_service)
) -> ApiResponse[KnowledgeBaseOut]:
    kb = await service.get_by_id_and_current_org(kb_id)
    return ApiResponse.ok(KnowledgeBaseOut.model_validate(kb))


@router.patch("/{kb_id}", response_model=ApiResponse[KnowledgeBaseOut], response_model_exclude_none=True)
async def update(
    kb_id: UUID, req: UpdateKbRequest, service: KnowledgeBaseService = Depends(_kb_service)
) -> ApiResponse[KnowledgeBaseOut]:
    kb = await service.update(kb_id, req.name)
    return ApiResponse.ok(KnowledgeBaseOut.model_validate(kb))


@router.delete("/{kb_id}", response_model=ApiResponse[str], response_model_exclude_none=True)
async def delete(kb_id: UUID, service: KnowledgeBaseService = Depends(_kb_service)) -> ApiResponse[str]:
    fully_deleted = await service.delete(kb_id)
    if fully_deleted:
        return ApiResponse.ok("已删除")
    return ApiResponse.fail(202, "知识库已标记待清理(dataset 删除失败,将由对账任务处理)")
