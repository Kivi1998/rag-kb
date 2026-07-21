"""`RedisMongoConversationStore` 多租户隔离 + 降级行为测试。

对应 Java 版 `ragcore/conversation/impl/RedisMongoConversationStore.java`。
关键不变量:
- MongoDB 是权威存储,append_message / delete_session 失败必须让调用方感知
- Redis 写失败只记日志(降级,热路径不能因 Redis 不可达而失败)
- 滑动窗口读取时 Redis 不可达 → 返回空(退化到无历史问答)
- archived_messages 强制带 kbId(2026-07-15 漏洞修复)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ragcore.memory.chat_message import ChatMessage, ROLE_USER
from app.ragcore.memory.chat_message_document import ChatMessageDocument
from app.ragcore.memory.chat_message_repository import ChatMessageRepository
from app.ragcore.memory.redis_mongo_conversation_store import (
    REDIS_KEY_TTL_SECONDS,
    REDIS_WINDOW_SIZE,
    RedisMongoConversationStore,
    _redis_key,
    _serialize,
    _deserialize,
)


class _FakeRedis:
    """最小化 redis.asyncio 客户端,记录 rpush/ltrim/expire/lrange/delete 调用。"""

    def __init__(self) -> None:
        self._lists: dict[str, list[str]] = {}
        self._ttls: dict[str, int] = {}
        self.rpush_calls: list[dict] = []
        self.ltrim_calls: list[dict] = []
        self.expire_calls: list[dict] = []
        self.lrange_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self.raise_on_rpush: Exception | None = None
        self.raise_on_lrange: Exception | None = None
        self.raise_on_delete: Exception | None = None

    async def rpush(self, key, value):
        self.rpush_calls.append({"key": key, "value": value})
        if self.raise_on_rpush is not None:
            raise self.raise_on_rpush
        self._lists.setdefault(key, []).append(value)

    async def ltrim(self, key, start, end):
        self.ltrim_calls.append({"key": key, "start": start, "end": end})
        lst = self._lists.setdefault(key, [])
        if end == -1:
            lst = lst[start:]
        else:
            lst = lst[start : end + 1]
        self._lists[key] = lst

    async def expire(self, key, seconds):
        self.expire_calls.append({"key": key, "seconds": seconds})
        self._ttls[key] = seconds

    async def lrange(self, key, start, end):
        self.lrange_calls.append({"key": key, "start": start, "end": end})
        if self.raise_on_lrange is not None:
            raise self.raise_on_lrange
        lst = self._lists.get(key, [])
        if end == -1:
            return lst[start:]
        return lst[start : end + 1]

    async def delete(self, key):
        self.delete_calls.append({"key": key})
        if self.raise_on_delete is not None:
            raise self.raise_on_delete
        self._lists.pop(key, None)


def _repo_with_collection(col) -> ChatMessageRepository:
    return ChatMessageRepository(collection=col)


class _FakeCollection:
    def __init__(self) -> None:
        self._docs: list[dict] = []
        self._next_id = 1
        self.find_filters: list[dict] = []
        self.delete_filters: list[dict] = []

    async def insert_one(self, payload: dict) -> Any:
        from bson import ObjectId
        new_id = ObjectId()
        payload = {**payload, "_id": new_id}
        self._docs.append(payload)
        return type("_Result", (), {"inserted_id": new_id})()

    def find(self, query: dict):
        self.find_filters.append(query)
        results = []
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                results.append(doc)
        return _FakeCursor(results)

    async def delete_many(self, query: dict):
        self.delete_filters.append(query)
        before = len(self._docs)
        self._docs = [
            d for d in self._docs
            if not all(d.get(k) == v for k, v in query.items())
        ]
        return type("_Result", (), {"deleted_count": before - len(self._docs)})()


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field, direction):
        self._docs.sort(key=lambda d: d.get(field))
        return self

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()


class TestRedisKeyAndSerialization:
    def test_redis_key_format(self):
        session = uuid4()
        assert _redis_key(session) == f"chat:session:{session}:messages"

    def test_serialize_drops_citations(self):
        """Redis 滑动窗口只给指代消解/摘要用,不需要 citations——序列化时去掉,
        避免每条 assistant 消息白白把最多 8 条引用(含 500 字原文片段)写进 Redis。"""
        from app.ragcore.model import Citation

        cit = Citation(
            document_id=uuid4(), document_name="d", heading_path=("h",),
            snippet="s" * 500, page_no=1, line_start=10, line_end=12, score=0.9,
        )
        msg = ChatMessage.assistant("answer", datetime.now(timezone.utc), citations=[cit])
        raw = _serialize(msg)
        payload = json.loads(raw)
        # citations 不应出现在 payload 中
        assert "citations" not in payload
        assert payload["role"] == "assistant"
        assert payload["content"] == "answer"

    def test_serialize_user_message(self):
        msg = ChatMessage.user("hi", datetime.now(timezone.utc))
        raw = _serialize(msg)
        payload = json.loads(raw)
        assert payload["role"] == "user"
        assert payload["content"] == "hi"

    def test_deserialize_round_trip(self):
        original = ChatMessage.user("hi", datetime.now(timezone.utc))
        raw = _serialize(original)
        restored = _deserialize(raw)
        assert restored.role == original.role
        assert restored.content == original.content
        assert restored.citations is None  # 反序列化也不恢复 citations

    def test_constants(self):
        assert REDIS_WINDOW_SIZE == 50
        assert REDIS_KEY_TTL_SECONDS == 3 * 60 * 60


class TestAppendMessageWriteThrough:
    """写直达:MongoDB 先写(权威),Redis 后写(热路径,失败不阻断)。"""

    @pytest.mark.asyncio
    async def test_mongo_written_then_redis_written(self):
        redis = _FakeRedis()
        col = _FakeCollection()
        repo = _repo_with_collection(col)
        store = RedisMongoConversationStore(memory_redis=redis, chat_message_repository=repo)

        msg = ChatMessage.user("hi", datetime.now(timezone.utc))
        await store.append_message(uuid4(), uuid4(), uuid4(), uuid4(), msg)
        # MongoDB 写了
        assert len(col._docs) == 1
        # Redis 写了
        assert len(redis.rpush_calls) == 1
        actual_keys = [c["key"] for c in redis.rpush_calls]
        # 至少一个 key 形如 chat:session:<uuid>:messages
        assert any(k.startswith("chat:session:") and k.endswith(":messages") for k in actual_keys)

    @pytest.mark.asyncio
    async def test_redis_write_failure_does_not_break_mongo(self):
        """Redis 不可达时,MongoDB 写入必须仍成功(降级路径,只记日志)。"""
        redis = _FakeRedis()
        redis.raise_on_rpush = ConnectionError("redis down")
        col = _FakeCollection()
        repo = _repo_with_collection(col)
        store = RedisMongoConversationStore(memory_redis=redis, chat_message_repository=repo)

        msg = ChatMessage.user("hi", datetime.now(timezone.utc))
        # 不应抛异常
        await store.append_message(uuid4(), uuid4(), uuid4(), uuid4(), msg)
        assert len(col._docs) == 1  # MongoDB 仍写入

    @pytest.mark.asyncio
    async def test_window_size_ltrim_to_50(self):
        redis = _FakeRedis()
        col = _FakeCollection()
        repo = _repo_with_collection(col)
        store = RedisMongoConversationStore(memory_redis=redis, chat_message_repository=repo)

        msg = ChatMessage.user("hi", datetime.now(timezone.utc))
        await store.append_message(uuid4(), uuid4(), uuid4(), uuid4(), msg)
        # ltrim 调用必须把窗口裁到 REDIS_WINDOW_SIZE
        ltrim = redis.ltrim_calls[0]
        assert ltrim["start"] == -REDIS_WINDOW_SIZE
        assert ltrim["end"] == -1

    @pytest.mark.asyncio
    async def test_ttl_set(self):
        redis = _FakeRedis()
        col = _FakeCollection()
        repo = _repo_with_collection(col)
        store = RedisMongoConversationStore(memory_redis=redis, chat_message_repository=repo)

        msg = ChatMessage.user("hi", datetime.now(timezone.utc))
        await store.append_message(uuid4(), uuid4(), uuid4(), uuid4(), msg)
        assert redis.expire_calls[0]["seconds"] == REDIS_KEY_TTL_SECONDS


class TestRecentRawMessages:
    """recent_raw_messages 走 Redis;Redis 不可达时降级为空列表,绝不抛。"""

    @pytest.mark.asyncio
    async def test_redis_failure_returns_empty(self):
        redis = _FakeRedis()
        redis.raise_on_lrange = ConnectionError("redis down")
        col = _FakeCollection()
        repo = _repo_with_collection(col)
        store = RedisMongoConversationStore(memory_redis=redis, chat_message_repository=repo)

        # 不应抛
        result = await store.recent_raw_messages(uuid4(), uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_redis_returns_empty(self):
        redis = _FakeRedis()
        col = _FakeCollection()
        repo = _repo_with_collection(col)
        store = RedisMongoConversationStore(memory_redis=redis, chat_message_repository=repo)
        assert await store.recent_raw_messages(uuid4(), uuid4()) == []

    @pytest.mark.asyncio
    async def test_deserialization_failure_skips_bad_entry(self):
        """滑动窗口里单条 JSON 损坏时跳过,不影响其他正常消息。"""
        redis = _FakeRedis()
        # 预先塞一条非法 JSON
        session = uuid4()
        redis._lists[_redis_key(session)] = [
            "not-valid-json",
            _serialize(ChatMessage.user("valid", datetime.now(timezone.utc))),
        ]
        col = _FakeCollection()
        repo = _repo_with_collection(col)
        store = RedisMongoConversationStore(memory_redis=redis, chat_message_repository=repo)

        result = await store.recent_raw_messages(uuid4(), session)
        assert len(result) == 1
        assert result[0].content == "valid"


class TestArchivedMessagesKbIdProtection:
    """**kbId 跨知识库隔离**。ChatMessageRepository 已经在 MongoDB 查询和回程二次校验,
    这里通过 store 间接验证:archive_messages 调用会把 kbId 传到 repo。"""

    @pytest.mark.asyncio
    async def test_archived_messages_passes_kb_id_to_repo(self):
        redis = _FakeRedis()
        col = _FakeCollection()
        repo = _repo_with_collection(col)
        store = RedisMongoConversationStore(memory_redis=redis, chat_message_repository=repo)

        session = uuid4()
        org = uuid4()
        kb = uuid4()
        member = uuid4()
        await store.archived_messages(org, kb, member, session)
        # repo 拿到的查询必须含 kbId
        assert col.find_filters
        query = col.find_filters[0]
        assert query["kbId"] == kb


class TestDeleteSession:
    @pytest.mark.asyncio
    async def test_delete_session_passes_kb_id(self):
        """delete_session 也带 kbId,防止误删同 org 另一 kb 下的会话。"""
        redis = _FakeRedis()
        col = _FakeCollection()
        repo = _repo_with_collection(col)
        store = RedisMongoConversationStore(memory_redis=redis, chat_message_repository=repo)

        session = uuid4()
        org = uuid4()
        kb = uuid4()
        member = uuid4()
        await store.delete_session(org, kb, member, session)
        assert col.delete_filters
        query = col.delete_filters[0]
        assert query["kbId"] == kb
        assert query["sessionId"] == session
        assert query["organizationId"] == org
        assert query["memberId"] == member

    @pytest.mark.asyncio
    async def test_redis_delete_failure_does_not_propagate(self):
        """MongoDB 权威存储删除后,Redis 清理失败只记日志——Redis 有 TTL 自然过期。"""
        redis = _FakeRedis()
        redis.raise_on_delete = ConnectionError("redis down")
        col = _FakeCollection()
        repo = _repo_with_collection(col)
        store = RedisMongoConversationStore(memory_redis=redis, chat_message_repository=repo)

        # 不应抛
        await store.delete_session(uuid4(), uuid4(), uuid4(), uuid4())
        # MongoDB 仍清理了
        assert col.delete_filters
