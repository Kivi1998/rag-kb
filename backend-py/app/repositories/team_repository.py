"""对应 repository/TeamRepository.java。"""

from uuid import UUID

from sqlalchemy import select

from app.models.team import Team
from app.repositories.base import BaseRepository


class TeamRepository(BaseRepository[Team]):
    model = Team

    async def find_by_org_id(self, org_id: UUID) -> list[Team]:
        """对应 Java findByOrgId。"""
        stmt = select(Team).where(Team.org_id == org_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_id_and_org_id(self, id_: UUID, org_id: UUID) -> Team | None:
        """对应 Java findByIdAndOrgId。"""
        stmt = select(Team).where(Team.id == id_, Team.org_id == org_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
