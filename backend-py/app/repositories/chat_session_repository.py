"""对应 repository/ChatSessionRepository.java。"""

from uuid import UUID

from sqlalchemy import select

from app.models.chat_session import ChatSession
from app.repositories.base import BaseRepository


class ChatSessionRepository(BaseRepository[ChatSession]):
    model = ChatSession

    async def find_by_id_and_org_id_and_kb_id_and_member_id(
        self, id_: UUID, org_id: UUID, kb_id: UUID, member_id: UUID
    ) -> ChatSession | None:
        """对应 Java findByIdAndOrgIdAndKbIdAndMemberId。"""
        stmt = select(ChatSession).where(
            ChatSession.id == id_,
            ChatSession.org_id == org_id,
            ChatSession.kb_id == kb_id,
            ChatSession.member_id == member_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_org_id_and_kb_id_and_member_id_and_title_is_not_null_order_by_last_active_at_desc(
        self, org_id: UUID, kb_id: UUID, member_id: UUID, limit: int, offset: int = 0
    ) -> list[ChatSession]:
        """对应 Java findByOrgIdAndKbIdAndMemberIdAndTitleIsNotNullOrderByLastActiveAtDesc(..., Pageable)。

        只返回已有标题(即已发生过至少一轮问答)的会话,尚未使用过的空会话不出现在历史列表里。
        `limit`/`offset` 对应 Java 版的 Pageable 分页参数。
        """
        stmt = (
            select(ChatSession)
            .where(
                ChatSession.org_id == org_id,
                ChatSession.kb_id == kb_id,
                ChatSession.member_id == member_id,
                ChatSession.title.is_not(None),
            )
            .order_by(ChatSession.last_active_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
