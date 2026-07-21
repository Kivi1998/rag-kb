"""`ConversationMemoryOrchestrator` 与 `UserProfileInjector` 测试。

对照 Java 版 `ragcore/conversation/ConversationMemoryOrchestrator.java` 与
`UserProfileInjector.java`。
关键不变量:
- record_turn 持久化失败只记日志,不影响已返回给用户的回答
- prepare_context 画像检索向量化失败时降级为空 system 上下文
- UserProfileInjector 只读 memory 检索结果,不影响候选池/过滤/权重
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ragcore.embedding.client import EmbeddingClient
from app.ragcore.generation.client import ChatCompletionClient
from app.ragcore.memory.chat_message import ChatMessage, ROLE_ASSISTANT, ROLE_USER
from app.ragcore.memory.conversation_store import ConversationStore
from app.ragcore.memory.coreference_resolver import CoreferenceResolver
from app.ragcore.memory.conversation_memory_orchestrator import ConversationMemoryOrchestrator
from app.ragcore.memory.memory_extractor import MemoryExtractor
from app.ragcore.memory.memory_item_document import MemoryItemDocument
from app.ragcore.memory.memory_item_store import MemoryItemStore
from app.ragcore.memory.sliding_window_assembler import SlidingWindowAssembler
from app.ragcore.memory.user_profile_injector import UserProfileInjector
from app.ragcore.model import EmbeddingResult


class _StubStore(ConversationStore):
    def __init__(self, raise_exc: Exception | None = None) -> None:
        self.append_calls: list[dict] = []
        self.raise_exc = raise_exc
        self.recent_return: list[ChatMessage] = []

    async def append_message(self, organization_id, kb_id, member_id, session_id, message):
        self.append_calls.append({
            "organization_id": organization_id,
            "kb_id": kb_id,
            "member_id": member_id,
            "session_id": session_id,
            "message": message,
        })
        if self.raise_exc is not None:
            raise self.raise_exc

    async def recent_raw_messages(self, organization_id, session_id):
        return self.recent_return

    async def archived_messages(self, organization_id, kb_id, member_id, session_id):
        return []

    async def delete_session(self, organization_id, kb_id, member_id, session_id):
        pass


class _StubSlidingWindow(SlidingWindowAssembler):
    def __init__(self, window) -> None:
        self._window = window
        self.call_count = 0

    async def assemble(self, messages, token_budget):
        from app.ragcore.memory.conversation_window import ConversationWindow
        self.call_count += 1
        if isinstance(self._window, ConversationWindow):
            return self._window
        return ConversationWindow.of([])


class _StubCoref(CoreferenceResolver):
    def __init__(self, response: str | None = None, raise_exc: Exception | None = None) -> None:
        self.response = response
        self.raise_exc = raise_exc

    async def resolve(self, question, history):
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response if self.response is not None else question


class _StubEmbedding(EmbeddingClient):
    def __init__(self, vectors: list[list[float]] | None = None, raise_exc: Exception | None = None) -> None:
        self.vectors = vectors or [[0.1, 0.2]]
        self.raise_exc = raise_exc
        self.last_texts: list[str] | None = None

    async def embed(self, texts):
        self.last_texts = list(texts)
        if self.raise_exc is not None:
            raise self.raise_exc
        return EmbeddingResult(model_version="stub", vectors=tuple(tuple(v) for v in self.vectors))


class _StubProfileInjector:
    def __init__(self, response: str = "", raise_exc: Exception | None = None) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.call_count = 0

    async def build_system_context(self, organization_id, member_id, query_vector):
        self.call_count += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response


class _StubExtractor(MemoryExtractor):
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.raise_exc: Exception | None = None

    async def extract_and_store(self, organization_id, member_id, session_id, question, answer):
        self.calls.append({
            "organization_id": organization_id,
            "member_id": member_id,
            "session_id": session_id,
            "question": question,
            "answer": answer,
        })
        if self.raise_exc is not None:
            raise self.raise_exc


def _make_window(messages=()):
    from app.ragcore.memory.conversation_window import ConversationWindow
    return ConversationWindow(summary=None, recent_messages=tuple(messages))


class TestPrepareContext:
    @pytest.mark.asyncio
    async def test_no_profile_injector_skipped(self):
        store = _StubStore()
        window = _make_window([ChatMessage.user("hi", _now())])
        sliding = _StubSlidingWindow(window)
        coref = _StubCoref(response="RAG 是什么?")
        embedding = _StubEmbedding([[0.1, 0.2]])

        orch = ConversationMemoryOrchestrator(
            conversation_store=store,
            sliding_window_assembler=sliding,
            coreference_resolver=coref,
            embedding_client=embedding,
            user_profile_injector=None,
            memory_extractor=_StubExtractor(),
            token_budget=1000,
        )
        ctx = await orch.prepare_context(uuid4(), uuid4(), uuid4(), "它是什么?")
        assert ctx.resolved_question == "RAG 是什么?"
        assert ctx.resolved_question_vector == [0.1, 0.2]
        assert ctx.profile_system_context == ""

    @pytest.mark.asyncio
    async def test_profile_injector_called_with_vector(self):
        store = _StubStore()
        window = _make_window()
        sliding = _StubSlidingWindow(window)
        coref = _StubCoref(response="resolved-q")
        embedding = _StubEmbedding([[0.5, 0.6]])
        profile = _StubProfileInjector(response="用户背景:技术专家")

        orch = ConversationMemoryOrchestrator(
            conversation_store=store,
            sliding_window_assembler=sliding,
            coreference_resolver=coref,
            embedding_client=embedding,
            user_profile_injector=profile,
            memory_extractor=_StubExtractor(),
            token_budget=1000,
        )
        ctx = await orch.prepare_context(uuid4(), uuid4(), uuid4(), "original q")
        assert profile.call_count == 1
        assert ctx.profile_system_context == "用户背景:技术专家"

    @pytest.mark.asyncio
    async def test_embedding_failure_does_not_break_prepare(self):
        """Embedding 失败时 prepare_context 不抛,profile_system_context 留空,
        resolved_question_vector 留 None(下游 HybridRetriever 退回自己算)。"""
        store = _StubStore()
        window = _make_window()
        sliding = _StubSlidingWindow(window)
        coref = _StubCoref(response="q")
        embedding = _StubEmbedding(raise_exc=RuntimeError("embed down"))

        orch = ConversationMemoryOrchestrator(
            conversation_store=store,
            sliding_window_assembler=sliding,
            coreference_resolver=coref,
            embedding_client=embedding,
            user_profile_injector=_StubProfileInjector(raise_exc=AssertionError("should not call")),
            memory_extractor=_StubExtractor(),
            token_budget=1000,
        )
        ctx = await orch.prepare_context(uuid4(), uuid4(), uuid4(), "q")
        assert ctx.resolved_question == "q"
        assert ctx.resolved_question_vector is None
        assert ctx.profile_system_context == ""


class TestRecordTurn:
    @pytest.mark.asyncio
    async def test_record_turn_writes_user_then_assistant(self):
        store = _StubStore()
        orch = ConversationMemoryOrchestrator(
            conversation_store=store,
            sliding_window_assembler=_StubSlidingWindow(_make_window()),
            coreference_resolver=_StubCoref(),
            embedding_client=_StubEmbedding(),
            user_profile_injector=None,
            memory_extractor=_StubExtractor(),
            token_budget=1000,
        )
        await orch.record_turn(uuid4(), uuid4(), uuid4(), uuid4(), "q", "a", citations=None)
        assert len(store.append_calls) == 2
        # 第一条 user
        assert store.append_calls[0]["message"].role == ROLE_USER
        assert store.append_calls[0]["message"].content == "q"
        # 第二条 assistant
        assert store.append_calls[1]["message"].role == ROLE_ASSISTANT
        assert store.append_calls[1]["message"].content == "a"

    @pytest.mark.asyncio
    async def test_record_turn_persistence_failure_does_not_raise(self):
        """持久化失败只记日志,不阻断已返回给用户的回答。"""
        store = _StubStore(raise_exc=ConnectionError("MongoDB down"))
        orch = ConversationMemoryOrchestrator(
            conversation_store=store,
            sliding_window_assembler=_StubSlidingWindow(_make_window()),
            coreference_resolver=_StubCoref(),
            embedding_client=_StubEmbedding(),
            user_profile_injector=None,
            memory_extractor=_StubExtractor(),
            token_budget=1000,
        )
        # 不应抛
        await orch.record_turn(uuid4(), uuid4(), uuid4(), uuid4(), "q", "a", citations=None)

    @pytest.mark.asyncio
    async def test_record_turn_fires_extractor_async(self):
        """record_turn 同步落库后,异步触发画像提炼——失败只记日志,不影响主流程。"""
        store = _StubStore()
        extractor = _StubExtractor()
        orch = ConversationMemoryOrchestrator(
            conversation_store=store,
            sliding_window_assembler=_StubSlidingWindow(_make_window()),
            coreference_resolver=_StubCoref(),
            embedding_client=_StubEmbedding(),
            user_profile_injector=None,
            memory_extractor=extractor,
            token_budget=1000,
        )
        await orch.record_turn(uuid4(), uuid4(), uuid4(), uuid4(), "q", "a", citations=None)
        # 等待异步任务完成
        await asyncio.sleep(0.05)
        assert len(extractor.calls) == 1
        call = extractor.calls[0]
        assert call["question"] == "q"
        assert call["answer"] == "a"


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


class TestUserProfileInjector:
    @pytest.mark.asyncio
    async def test_empty_profile_returns_empty_string(self):
        """没有相关画像时返回空字符串——调用方据此不拼任何 system 上下文。"""
        store = _StubMemoryStoreEmpty()
        injector = UserProfileInjector(memory_item_store=store, top_k=3)
        result = await injector.build_system_context(uuid4(), uuid4(), [0.1, 0.2])
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_formatted_bullets(self):
        items = [
            MemoryItemDocument(
                member_id=uuid4(), organization_id=uuid4(),
                type="PREFERENCE", content="喜欢 Python",
                importance=0.8, access_count=0,
                last_accessed_at=_now(), created_at=_now(),
            ),
            MemoryItemDocument(
                member_id=uuid4(), organization_id=uuid4(),
                type="FACT", content="团队主要用 Java",
                importance=0.7, access_count=0,
                last_accessed_at=_now(), created_at=_now(),
            ),
        ]
        store = _StubMemoryStoreWith(items)
        injector = UserProfileInjector(memory_item_store=store, top_k=3)
        result = await injector.build_system_context(uuid4(), uuid4(), [0.1, 0.2])
        assert "以下是关于该用户的背景信息" in result
        assert "(PREFERENCE) 喜欢 Python" in result
        assert "(FACT) 团队主要用 Java" in result


class _StubMemoryStoreEmpty(MemoryItemStore):
    async def find_similar_existing(self, organization_id, member_id, candidate_vector):
        return None

    async def create_item(self, organization_id, member_id, type, content, initial_importance, vector, source_session_id):
        return None  # type: ignore

    async def top_k_for_generation(self, organization_id, member_id, query_vector, top_k):
        return []

    async def cleanup_stale(self, cutoff, importance_threshold):
        return 0


class _StubMemoryStoreWith(MemoryItemStore):
    def __init__(self, items: list[MemoryItemDocument]) -> None:
        self._items = items

    async def find_similar_existing(self, organization_id, member_id, candidate_vector):
        return None

    async def create_item(self, organization_id, member_id, type, content, initial_importance, vector, source_session_id):
        return None  # type: ignore

    async def top_k_for_generation(self, organization_id, member_id, query_vector, top_k):
        return self._items

    async def cleanup_stale(self, cutoff, importance_threshold):
        return 0
