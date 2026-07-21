"""团队服务。对应 Java 版 service/TeamService.java。

创建团队时校验:父组织必须等于当前租户上下文的 org_id。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import get_tenant_context
from app.exceptions.errors import AccessDeniedException, ResourceNotFoundException
from app.models.enums import MemberRole
from app.models.team import Team
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.team_repository import TeamRepository


class TeamService:
    def __init__(
        self,
        team_repository: TeamRepository,
        org_repository: OrganizationRepository,
        session: AsyncSession,
    ) -> None:
        self._teams = team_repository
        self._orgs = org_repository
        self._session = session

    async def create(self, name: str) -> Team:
        ctx = get_tenant_context()
        try:
            caller_role = MemberRole(ctx.role)
        except ValueError as exc:
            raise AccessDeniedException("用户角色未设置，无权创建团队") from exc
        if caller_role == MemberRole.MEMBER:
            raise AccessDeniedException("member 角色无权创建团队")

        org = await self._orgs.find_by_id(ctx.org_id)
        if org is None:
            raise ResourceNotFoundException("组织不存在")

        team = Team(org_id=org.id, name=name)
        team = await self._teams.save(team)
        await self._session.commit()
        return team

    async def list_by_current_org(self) -> list[Team]:
        ctx = get_tenant_context()
        return await self._teams.find_by_org_id(ctx.org_id)

    async def get_by_id_and_current_org(self, team_id: UUID) -> Team:
        ctx = get_tenant_context()
        team = await self._teams.find_by_id_and_org_id(team_id, ctx.org_id)
        if team is None:
            raise ResourceNotFoundException("团队不存在")
        return team
