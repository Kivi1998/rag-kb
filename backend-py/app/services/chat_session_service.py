"""会话生命周期管理:创建、归属校验(跨组织/跨知识库/跨成员一律 404,不泄露会话是否存在)、
状态机流转(ACTIVE/IDLE/ARCHIVED,读时按 last_active_at 计算,不需要定时任务维护)。
对应 Java 版 service/ChatSessionService.java。

会话生命周期基于 Postgres `chat_session` 表,与 `rag_memory_enabled` 门控的
Redis/MongoDB/ES 记忆子系统无关——`session_id` 在查询请求上始终必填,因此本服务必须始终
可用;只有 `get_messages` 依赖的长期存档查询在记忆子系统关闭时才降级为空列表。

`conversation_store`/`memory_index` 对应 Java 版 `ObjectProvider<ConversationStore>` /
`ObjectProvider<MemoryIndex>`——`rag_memory_enabled=false` 或对应基础设施(ES 客户端等)
未装配时传 None,本类各方法据此优雅降级,不抛异常。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.exceptions.errors import ResourceNotFoundException
from app.models.chat_session import ChatSession
from app.models.enums import ChatSessionStatus
from app.ragcore.memory.chat_message import ChatMessage
from app.ragcore.memory.conversation_store import ConversationStore
from app.ragcore.memory.memory_index import MemoryIndex
from app.repositories.chat_session_repository import ChatSessionRepository

MAX_LISTED_SESSIONS = 50


@dataclass(frozen=True)
class ChatSessionSummary:
    session_id: UUID
    title: str | None
    last_active_at: datetime


class ChatSessionService:
    def __init__(
        self,
        chat_session_repository: ChatSessionRepository,
        session: AsyncSession,
        conversation_store: ConversationStore | None = None,
        memory_index: MemoryIndex | None = None,
    ) -> None:
        self._sessions = chat_session_repository
        self._session = session
        self._conversation_store = conversation_store
        self._memory_index = memory_index

    async def create_session(self, org_id: UUID, kb_id: UUID, member_id: UUID) -> ChatSession:
        """对应 Java 版 createSession;kb 归属校验由调用方(router)提前经
        KnowledgeBaseService.get_by_id_and_current_org 完成,越权/不存在时提前 404。
        """
        chat_session = ChatSession(org_id=org_id, kb_id=kb_id, member_id=member_id, status=ChatSessionStatus.ACTIVE)
        chat_session = await self._sessions.save(chat_session)
        await self._session.commit()
        return chat_session

    async def touch_session(self, org_id: UUID, kb_id: UUID, member_id: UUID, session_id: UUID) -> ChatSession:
        """校验归属(含 kb_id)并续期(有新消息时无论原状态如何都续期回 ACTIVE)。"""
        chat_session = await self._get_owned_session(org_id, kb_id, member_id, session_id)
        chat_session.status = ChatSessionStatus.ACTIVE
        chat_session.last_active_at = datetime.now(timezone.utc)
        chat_session = await self._sessions.save(chat_session)
        await self._session.commit()
        return chat_session

    async def require_owned_session(self, org_id: UUID, kb_id: UUID, member_id: UUID, session_id: UUID) -> None:
        """只校验归属(越权/不存在 → 404),不落库、不续期状态——供纯读取/清理类端点使用,
        避免像 touch_session 那样把只读请求悄悄变成一次写操作。
        """
        await self._get_owned_session(org_id, kb_id, member_id, session_id)

    async def get_messages(self, org_id: UUID, kb_id: UUID, member_id: UUID, session_id: UUID) -> list[ChatMessage]:
        chat_session = await self._get_owned_session(org_id, kb_id, member_id, session_id)
        if self._conversation_store is None:
            return []  # rag_memory 关闭时长期存档未接入,退化为空历史而非报错
        return await self._conversation_store.archived_messages(org_id, kb_id, member_id, chat_session.id)

    async def list_sessions(self, org_id: UUID, kb_id: UUID, member_id: UUID) -> list[ChatSessionSummary]:
        """当前成员在该知识库下最近活跃的会话列表,固定最多 MAX_LISTED_SESSIONS 条,按最后活跃
        时间倒序;只包含已发生过至少一轮问答(即已有标题)的会话。
        """
        sessions = await self._sessions.find_by_org_id_and_kb_id_and_member_id_and_title_is_not_null_order_by_last_active_at_desc(
            org_id, kb_id, member_id, limit=MAX_LISTED_SESSIONS
        )
        return [
            ChatSessionSummary(session_id=s.id, title=s.title, last_active_at=s.last_active_at) for s in sessions
        ]

    async def delete_session(self, org_id: UUID, kb_id: UUID, member_id: UUID, session_id: UUID) -> None:
        """硬删除:先校验归属(越权/不存在 → 404,不泄露存在性),再按"先删衍生索引/缓存,最后删
        权威记录"的顺序级联清理 Elasticsearch → MongoDB/Redis → Postgres;不影响该成员的长期画像
        (画像是 member 维度,与会话生命周期无关)。`rag_memory_enabled=false` 时
        memory_index/conversation_store 均为 None,只删 Postgres 行。
        """
        chat_session = await self._get_owned_session(org_id, kb_id, member_id, session_id)

        if self._memory_index is not None:
            await self._memory_index.delete_by_session(org_id, session_id)
        if self._conversation_store is not None:
            await self._conversation_store.delete_session(org_id, kb_id, member_id, session_id)

        await self._sessions.delete(chat_session)
        await self._session.commit()

    async def maybe_set_title(
        self, org_id: UUID, kb_id: UUID, member_id: UUID, session_id: UUID, content: str | None
    ) -> None:
        """首轮消息写入时截取前 30 字作为会话标题,只在标题当前为空时写入一次,非首轮不覆盖。
        找不到会话(如同一时刻被并发删除)时静默跳过,不抛异常。
        """
        chat_session = await self._sessions.find_by_id_and_org_id_and_kb_id_and_member_id(
            session_id, org_id, kb_id, member_id
        )
        if chat_session is None:
            return
        if not chat_session.title or not chat_session.title.strip():
            chat_session.title = self._truncate_title(content)
            await self._sessions.save(chat_session)
            await self._session.commit()

    def effective_status(self, chat_session: ChatSession) -> ChatSessionStatus:
        """只读地推断当前有效状态,不落库;落库的状态更新只在 touch_session 时发生。"""
        now = datetime.now(timezone.utc)
        since_last_active = now - chat_session.last_active_at
        if since_last_active.total_seconds() / 60 < settings.rag_memory_session_active_minutes:
            return ChatSessionStatus.ACTIVE
        if since_last_active.total_seconds() / 3600 < settings.rag_memory_session_idle_hours:
            return ChatSessionStatus.IDLE
        return ChatSessionStatus.ARCHIVED

    @staticmethod
    def _truncate_title(content: str | None) -> str | None:
        if content is None:
            return None
        trimmed = content.strip()
        if not trimmed:
            return None
        return trimmed[:30]

    async def _get_owned_session(self, org_id: UUID, kb_id: UUID, member_id: UUID, session_id: UUID) -> ChatSession:
        chat_session = await self._sessions.find_by_id_and_org_id_and_kb_id_and_member_id(
            session_id, org_id, kb_id, member_id
        )
        if chat_session is None:
            raise ResourceNotFoundException("会话不存在")
        return chat_session
