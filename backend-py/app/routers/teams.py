"""团队控制器(需认证+租户上下文)。对应 Java 版 controller/TeamController.java。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.repositories.organization_repository import OrganizationRepository
from app.repositories.team_repository import TeamRepository
from app.routers.deps import get_session, require_tenant
from app.schemas.common import ApiResponse
from app.schemas.team import CreateTeamRequest, TeamOut
from app.services.team_service import TeamService

router = APIRouter(prefix="/api/v1/teams", tags=["teams"], dependencies=[Depends(require_tenant)])


def _team_service(db: AsyncSession = Depends(get_session)) -> TeamService:
    return TeamService(TeamRepository(db), OrganizationRepository(db), db)


@router.post(
    "",
    response_model=ApiResponse[TeamOut],
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def create(req: CreateTeamRequest, service: TeamService = Depends(_team_service)) -> ApiResponse[TeamOut]:
    team = await service.create(req.name)
    return ApiResponse.ok(TeamOut.model_validate(team))


@router.get("", response_model=ApiResponse[list[TeamOut]], response_model_exclude_none=True)
async def list_teams(service: TeamService = Depends(_team_service)) -> ApiResponse[list[TeamOut]]:
    teams = await service.list_by_current_org()
    return ApiResponse.ok([TeamOut.model_validate(t) for t in teams])


@router.get("/{team_id}", response_model=ApiResponse[TeamOut], response_model_exclude_none=True)
async def get_by_id(team_id: UUID, service: TeamService = Depends(_team_service)) -> ApiResponse[TeamOut]:
    team = await service.get_by_id_and_current_org(team_id)
    return ApiResponse.ok(TeamOut.model_validate(team))
