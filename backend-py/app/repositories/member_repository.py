"""对应 repository/MemberRepository.java。

同时实现 app.core.security.MemberLookup Protocol(鸭子类型,不需要显式继承):
`find_member(subject_id, org_id) -> (member_id, role) | None`,对应 Java 版
`AuthService` 里查 `MemberRepository.findBySubjectIdAndOrgId` 再取 (id, role) 的逻辑,
供 JWT 鉴权依赖 `require_tenant_factory` 使用。
"""

from uuid import UUID

from sqlalchemy import func, select

from app.models.member import Member
from app.models.enums import MemberRole
from app.repositories.base import BaseRepository


class MemberRepository(BaseRepository[Member]):
    model = Member

    async def find_by_org_id(self, org_id: UUID) -> list[Member]:
        """对应 Java findByOrgId。"""
        stmt = select(Member).where(Member.org_id == org_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_id_and_org_id(self, id_: UUID, org_id: UUID) -> Member | None:
        """对应 Java findByIdAndOrgId。"""
        stmt = select(Member).where(Member.id == id_, Member.org_id == org_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_subject_id_and_org_id(self, subject_id: str, org_id: UUID) -> Member | None:
        """对应 Java findBySubjectIdAndOrgId:查某 subject 在某组织的 member 记录。"""
        stmt = select(Member).where(Member.subject_id == subject_id, Member.org_id == org_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_by_org_id_and_role(self, org_id: UUID, role: MemberRole) -> int:
        """对应 Java countByOrgIdAndRole:某组织内指定角色(如 OWNER)的成员数量。"""
        stmt = select(func.count()).select_from(Member).where(Member.org_id == org_id, Member.role == role)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def find_first_by_subject_id_order_by_created_at_asc(self, subject_id: str) -> Member | None:
        """对应 Java findFirstBySubjectIdOrderByCreatedAtAsc:查某 subject 的首个成员记录。

        未做租户过滤,继承自 Java 版原始行为:按设计跨组织查找同一 subject 最早加入的
        组织身份(如注册后自动选中默认组织),不应带 org_id 条件。
        """
        stmt = (
            select(Member)
            .where(Member.subject_id == subject_id)
            .order_by(Member.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_member(self, subject_id: str, org_id: UUID) -> tuple[UUID, str] | None:
        """满足 app.core.security.MemberLookup Protocol。"""
        member = await self.find_by_subject_id_and_org_id(subject_id, org_id)
        if member is None:
            return None
        role = member.role.value if isinstance(member.role, MemberRole) else member.role
        return member.id, role
