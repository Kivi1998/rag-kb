"""ChatSessionService 会话生命周期测试。

对照 Java 版 `service/ChatSessionService.java`。
关键不变量:
- 跨 org / 跨 kb / 跨 member 读取会话一律 404,不泄露"会话是否存在"
- `touch_session` 续期 = ACTIVE + last_active_at = now + commit;
  找不到会话 → 404(越权也走这条)
- `get_messages` 在 `conversation_store=None`(rag_memory_enabled=false)时退化为空列表,
  不抛异常——和 `rag_memory_enabled` 开关解耦
- `maybe_set_title`:首条消息写入时截前 30 字作为标题,只在当前为空时写一次
- `delete_session` 顺序:先 memory_index,再 conversation_store,最后 Postgres 行
  (衍生索引/缓存先于权威记录)
- `effective_status` 按 last_active_at 推断:ACTIVE < 30min < IDLE < 2h < ARCHIVED
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.exceptions.errors import ResourceNotFoundException
from app.models.chat_session import ChatSession
from app.models.enums import ChatSessionStatus
from app.ragcore.memory.chat_message import ChatMessage
from app.ragcore.memory.conversation_store import ConversationStore
from app.ragcore.memory.memory_index import MemoryIndex
from app.services.chat_session_service import ChatSessionService


def _make_session(
    org_id: "uuid4() | None" = None,
    kb_id: "uuid4() | None" = None,
    member_id: "uuid4() | None" = None,
    title: str | None = None,
    last_active_at: datetime | None = None,
) -> ChatSession:
    """构造 SQLAlchemy ChatSession 实例——它的字段不带 server_default 反推逻辑,
    可以在测试里直接给值,不需要走真实 mapper init。
    """
    s = ChatSession(
        org_id=org_id or uuid4(),
        kb_id=kb_id or uuid4(),
        member_id=member_id or uuid4(),
    )
    s.id = uuid4()
    s.title = title
    s.last_active_at = last_active_at or datetime.now(timezone.utc)
    s.status = ChatSessionStatus.ACTIVE
    return s


def _build_service(
    conversation_store: ConversationStore | None = None,
    memory_index: MemoryIndex | None = None,
) -> tuple[ChatSessionService, AsyncMock, AsyncMock, AsyncMock]:
    repo = AsyncMock()
    session = AsyncMock()
    service = ChatSessionService(repo, session, conversation_store, memory_index)
    return service, repo, session, conversation_store or AsyncMock()


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_create_persists_new_session(self):
        service, repo, session, _store = _build_service()
        org_id, kb_id, member_id = uuid4(), uuid4(), uuid4()

        async def _save(s):
            if s.id is None:
                s.id = uuid4()
            return s

        repo.save.side_effect = _save

        s = await service.create_session(org_id, kb_id, member_id)

        assert s.org_id == org_id
        assert s.kb_id == kb_id
        assert s.member_id == member_id
        # 默认 ACTIVE
        assert s.status == ChatSessionStatus.ACTIVE
        session.commit.assert_awaited()


class TestTouchSession:
    @pytest.mark.asyncio
    async def test_touch_session_returns_404_when_not_found(self):
        """越权 / 不存在 全部 404,不泄露存在性。"""
        service, repo, _session, _store = _build_service()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.touch_session(uuid4(), uuid4(), uuid4(), uuid4())
        # 找不到时不应 commit
        _session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_touch_session_renews_to_active_and_commits(self):
        service, repo, session, _store = _build_service()
        existing = _make_session()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = existing
        repo.save.side_effect = lambda s: s

        before = existing.last_active_at
        result = await service.touch_session(
            existing.org_id, existing.kb_id, existing.member_id, existing.id
        )

        # 续期回 ACTIVE
        assert result.status == ChatSessionStatus.ACTIVE
        # last_active_at 必须推进
        assert result.last_active_at >= before
        session.commit.assert_awaited()


class TestRequireOwnedSession:
    @pytest.mark.asyncio
    async def test_require_owned_session_does_not_commit(self):
        """只读校验:不写库,不续期——纯只读端点用这个避免把 GET 变成写。"""
        service, repo, session, _store = _build_service()
        existing = _make_session()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = existing

        await service.require_owned_session(
            existing.org_id, existing.kb_id, existing.member_id, existing.id
        )
        # 关键:不应 commit
        session.commit.assert_not_called()
        # 也不应改 last_active_at
        assert existing.status == ChatSessionStatus.ACTIVE  # 没被改

    @pytest.mark.asyncio
    async def test_require_owned_session_404_on_missing(self):
        service, repo, _session, _store = _build_service()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.require_owned_session(uuid4(), uuid4(), uuid4(), uuid4())


class TestGetMessages:
    @pytest.mark.asyncio
    async def test_get_messages_404_when_session_not_found(self):
        service, repo, _session, _store = _build_service()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.get_messages(uuid4(), uuid4(), uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_get_messages_returns_empty_when_no_conversation_store(self):
        """rag_memory_enabled=false → conversation_store=None → 退化为空,不报错。"""
        service, repo, _session, _store = _build_service(conversation_store=None)
        existing = _make_session()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = existing

        msgs = await service.get_messages(
            existing.org_id, existing.kb_id, existing.member_id, existing.id
        )
        assert msgs == []

    @pytest.mark.asyncio
    async def test_get_messages_delegates_to_conversation_store(self):
        """有 conversation_store 时,从它取历史消息并按 (org/kb/member/session_id) 传参。"""
        store = AsyncMock(spec=ConversationStore)
        fake_msgs = [ChatMessage.user("hi", datetime.now(timezone.utc))]
        store.archived_messages.return_value = fake_msgs

        service, repo, _session, _ = _build_service(conversation_store=store)
        existing = _make_session()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = existing

        msgs = await service.get_messages(
            existing.org_id, existing.kb_id, existing.member_id, existing.id
        )
        assert msgs == fake_msgs
        store.archived_messages.assert_awaited_once()


class TestDeleteSession:
    @pytest.mark.asyncio
    async def test_delete_404_when_session_not_found(self):
        service, repo, _session, _store = _build_service()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = None

        with pytest.raises(ResourceNotFoundException):
            await service.delete_session(uuid4(), uuid4(), uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_delete_cascades_memory_index_then_conversation_then_row(self):
        """删除顺序:memory_index → conversation_store → chat_session 行;先衍生再权威。"""
        order: list[str] = []
        mem = AsyncMock(spec=MemoryIndex)
        store = AsyncMock(spec=ConversationStore)
        mem.delete_by_session.side_effect = lambda *a, **k: order.append("memory") or AsyncMock()
        store.delete_session.side_effect = lambda *a, **k: order.append("conv")

        service, repo, session, _ = _build_service(conversation_store=store, memory_index=mem)
        existing = _make_session()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = existing
        repo.delete.side_effect = lambda *a, **k: order.append("row")

        await service.delete_session(
            existing.org_id, existing.kb_id, existing.member_id, existing.id
        )
        assert order == ["memory", "conv", "row"]
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_skips_unavailable_optional_clients(self):
        """memory_index/conversation_store 为 None 时,只删 Postgres 行。"""
        service, repo, session, _ = _build_service(conversation_store=None, memory_index=None)
        existing = _make_session()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = existing

        await service.delete_session(
            existing.org_id, existing.kb_id, existing.member_id, existing.id
        )
        # 只调了 Postgres 行的 delete
        repo.delete.assert_awaited_once_with(existing)
        session.commit.assert_awaited()


class TestMaybeSetTitle:
    @pytest.mark.asyncio
    async def test_writes_title_when_empty(self):
        service, repo, session, _store = _build_service()
        existing = _make_session(title=None)
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = existing
        repo.save.side_effect = lambda s: s

        await service.maybe_set_title(
            existing.org_id, existing.kb_id, existing.member_id, existing.id,
            "如何部署 RAG 系统?",
        )
        # 取前 30 字
        assert existing.title == "如何部署 RAG 系统?"
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_truncates_title_at_30_chars(self):
        service, repo, session, _store = _build_service()
        existing = _make_session(title=None)
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = existing
        repo.save.side_effect = lambda s: s

        long = "a" * 100
        await service.maybe_set_title(
            existing.org_id, existing.kb_id, existing.member_id, existing.id, long
        )
        assert existing.title == "a" * 30

    @pytest.mark.asyncio
    async def test_does_not_overwrite_existing_title(self):
        """非首轮不能覆盖标题——只在当前为空时写一次。"""
        service, repo, session, _store = _build_service()
        existing = _make_session(title="首条已设置")
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = existing

        await service.maybe_set_title(
            existing.org_id, existing.kb_id, existing.member_id, existing.id,
            "新问题",
        )
        # 标题未被改
        assert existing.title == "首条已设置"
        session.commit.assert_not_called()
        repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_silently_skips_when_session_concurrently_deleted(self):
        """找不到会话(并发删除)时静默跳过,不抛。"""
        service, repo, _session, _store = _build_service()
        repo.find_by_id_and_org_id_and_kb_id_and_member_id.return_value = None

        # 不应抛
        await service.maybe_set_title(
            uuid4(), uuid4(), uuid4(), uuid4(), "anything"
        )


class TestEffectiveStatus:
    def test_active_within_30_minutes(self):
        s = _make_session(last_active_at=datetime.now(timezone.utc) - timedelta(minutes=5))
        service, *_ = _build_service()
        assert service.effective_status(s) == ChatSessionStatus.ACTIVE

    def test_idle_between_30_minutes_and_2_hours(self):
        s = _make_session(last_active_at=datetime.now(timezone.utc) - timedelta(minutes=60))
        service, *_ = _build_service()
        assert service.effective_status(s) == ChatSessionStatus.IDLE

    def test_archived_after_2_hours(self):
        s = _make_session(last_active_at=datetime.now(timezone.utc) - timedelta(hours=3))
        service, *_ = _build_service()
        assert service.effective_status(s) == ChatSessionStatus.ARCHIVED
