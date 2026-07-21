"""`DeepSeekCoreferenceResolver` / `DeepSeekConversationSummarizer` / 
`DeepSeekMemoryExtractor` fail-open 行为测试。

对应 Java 版 `ragcore/conversation/impl/DeepSeek*`。
三者的共同契约:
- CoreferenceResolver:调用失败/超时时返回原始问题,不抛异常
- ConversationSummarizer:失败由 SlidingWindowAssembler 处理,本类不抛
- MemoryExtractor:所有异常在内部捕获,绝不向调用方传播
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ragcore.embedding.client import EmbeddingClient
from app.ragcore.generation.client import ChatCompletionClient
from app.ragcore.memory.chat_message import (
    ChatMessage,
    ROLE_ASSISTANT,
    ROLE_USER,
)
from app.ragcore.memory.deepseek_conversation_summarizer import DeepSeekConversationSummarizer
from app.ragcore.memory.deepseek_coreference_resolver import DeepSeekCoreferenceResolver
from app.ragcore.memory.deepseek_memory_extractor import DeepSeekMemoryExtractor
from app.ragcore.memory.memory_extractor import MemoryExtractor
from app.ragcore.memory.memory_item_store import MemoryItemStore
from app.ragcore.model import EmbeddingResult


class _StubChat(ChatCompletionClient):
    def __init__(self, response: str | None = None, raise_exc: Exception | None = None) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.last_system: str | None = None
        self.last_user: str | None = None

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.last_system = system_prompt
        self.last_user = user_prompt
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.response is None:
            return ""
        return self.response


class _StubEmbedding(EmbeddingClient):
    def __init__(self, vectors: list[list[float]] | None = None, raise_exc: Exception | None = None) -> None:
        self.vectors = vectors or [[0.1, 0.2, 0.3]]
        self.raise_exc = raise_exc
        self.call_count = 0

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        self.call_count += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return EmbeddingResult(model_version="stub", vectors=tuple(tuple(v) for v in self.vectors))


class _StubMemoryStore(MemoryItemStore):
    def __init__(self) -> None:
        self.find_calls = 0
        self.create_calls: list[dict] = []
        self.similar_hit: bool = False

    async def find_similar_existing(self, organization_id, member_id, candidate_vector):
        self.find_calls += 1
        return None  # 默认未命中

    async def create_item(
        self, organization_id, member_id, type, content,
        initial_importance, vector, source_session_id,
    ):
        self.create_calls.append({
            "organization_id": organization_id,
            "member_id": member_id,
            "type": type,
            "content": content,
            "importance": initial_importance,
            "vector": vector,
            "source_session_id": source_session_id,
        })
        return None  # type: ignore[return-value]

    async def top_k_for_generation(self, organization_id, member_id, query_vector, top_k):
        return []

    async def cleanup_stale(self, cutoff, importance_threshold):
        return 0


# ---- DeepSeekCoreferenceResolver -----------------------------------------


class TestCoreferenceResolver:
    @pytest.mark.asyncio
    async def test_empty_history_returns_original_question(self):
        chat = _StubChat(response="这个")
        resolver = DeepSeekCoreferenceResolver(chat)
        result = await resolver.resolve("它是什么?", [])
        assert result == "它是什么?"
        assert chat.last_user is None  # 不发 LLM 调用

    @pytest.mark.asyncio
    async def test_llm_failure_returns_original_question(self):
        """fail-open:任何 LLM 异常都不能阻断问答主流程。"""
        chat = _StubChat(raise_exc=TimeoutError("API timeout"))
        resolver = DeepSeekCoreferenceResolver(chat)
        history = [
            ChatMessage.user("什么是 RAG?", datetime.now(timezone.utc)),
            ChatMessage.assistant("RAG 是检索增强生成。", datetime.now(timezone.utc)),
        ]
        result = await resolver.resolve("它的原理?", history)
        assert result == "它的原理?"

    @pytest.mark.asyncio
    async def test_llm_returns_empty_returns_original_question(self):
        chat = _StubChat(response="")
        resolver = DeepSeekCoreferenceResolver(chat)
        history = [ChatMessage.user("x", datetime.now(timezone.utc))]
        result = await resolver.resolve("y", history)
        assert result == "y"

    @pytest.mark.asyncio
    async def test_llm_returns_whitespace_returns_original_question(self):
        chat = _StubChat(response="   \n  ")
        resolver = DeepSeekCoreferenceResolver(chat)
        history = [ChatMessage.user("x", datetime.now(timezone.utc))]
        result = await resolver.resolve("y", history)
        assert result == "y"

    @pytest.mark.asyncio
    async def test_happy_path_returns_resolved(self):
        chat = _StubChat(response="RAG 是什么?")
        resolver = DeepSeekCoreferenceResolver(chat)
        history = [
            ChatMessage.user("RAG 是什么?", datetime.now(timezone.utc)),
            ChatMessage.assistant("是检索增强生成。", datetime.now(timezone.utc)),
        ]
        result = await resolver.resolve("它怎么用?", history)
        assert result == "RAG 是什么?"

    @pytest.mark.asyncio
    async def test_system_prompt_forbids_rewriting_technical_terms(self):
        """system prompt 必须明确禁止改写技术术语/类名/错误码,避免 LLM 自由发挥。"""
        chat = _StubChat(response="x")
        resolver = DeepSeekCoreferenceResolver(chat)
        history = [ChatMessage.user("x", datetime.now(timezone.utc))]
        await resolver.resolve("y", history)
        # system prompt 应包含禁止性约束
        assert "不要改写" in chat.last_system or "禁止" in chat.last_system

    @pytest.mark.asyncio
    async def test_user_prompt_includes_history(self):
        chat = _StubChat(response="x")
        resolver = DeepSeekCoreferenceResolver(chat)
        history = [
            ChatMessage.user("RAG 是什么?", datetime.now(timezone.utc)),
            ChatMessage.assistant("检索增强生成。", datetime.now(timezone.utc)),
        ]
        await resolver.resolve("它怎么用?", history)
        assert "RAG 是什么?" in chat.last_user
        assert "它怎么用?" in chat.last_user


# ---- DeepSeekConversationSummarizer --------------------------------------


class TestConversationSummarizer:
    @pytest.mark.asyncio
    async def test_empty_messages_returns_empty_string(self):
        chat = _StubChat(raise_exc=AssertionError("should not call"))
        summarizer = DeepSeekConversationSummarizer(chat)
        result = await summarizer.summarize([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_summarizes_messages(self):
        chat = _StubChat(response="摘要:RAG 与 Embedding。")
        summarizer = DeepSeekConversationSummarizer(chat)
        messages = [
            ChatMessage.user("RAG 是什么?", datetime.now(timezone.utc)),
            ChatMessage.assistant("检索增强生成。", datetime.now(timezone.utc)),
        ]
        result = await summarizer.summarize(messages)
        assert "摘要" in result

    @pytest.mark.asyncio
    async def test_transcript_includes_role_labels(self):
        chat = _StubChat(response="x")
        summarizer = DeepSeekConversationSummarizer(chat)
        messages = [
            ChatMessage.user("RAG 是什么?", datetime.now(timezone.utc)),
            ChatMessage.assistant("检索增强生成。", datetime.now(timezone.utc)),
        ]
        await summarizer.summarize(messages)
        # user/assistant 应该被中文 label 化
        assert "用户" in chat.last_user
        assert "助手" in chat.last_user


# ---- DeepSeekMemoryExtractor ---------------------------------------------


class TestMemoryExtractor:
    @pytest.mark.asyncio
    async def test_llm_failure_does_not_propagate(self):
        """Extractor 内部 fail-open:LLM 失败也不抛。"""
        chat = _StubChat(raise_exc=RuntimeError("LLM down"))
        embedding = _StubEmbedding()
        store = _StubMemoryStore()
        extractor = DeepSeekMemoryExtractor(chat, embedding, store)
        # 必须不抛
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")
        assert store.create_calls == []

    @pytest.mark.asyncio
    async def test_invalid_json_response_does_not_propagate(self):
        chat = _StubChat(response="这不是 JSON")
        extractor = DeepSeekMemoryExtractor(chat, _StubEmbedding(), _StubMemoryStore())
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")

    @pytest.mark.asyncio
    async def test_empty_items_does_not_call_embedding(self):
        chat = _StubChat(response='{"items":[]}')
        embedding = _StubEmbedding()
        store = _StubMemoryStore()
        extractor = DeepSeekMemoryExtractor(chat, embedding, store)
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")
        assert embedding.call_count == 0
        assert store.create_calls == []

    @pytest.mark.asyncio
    async def test_code_fence_stripped_before_parse(self):
        """LLM 偶尔会用 ```json ... ``` 包响应,Extactor 必须能剥。"""
        chat = _StubChat(response='```json\n{"items":[{"type":"PREFERENCE","content":"喜欢 Python","importance":0.7}]}\n```')
        embedding = _StubEmbedding()
        store = _StubMemoryStore()
        extractor = DeepSeekMemoryExtractor(chat, embedding, store)
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")
        assert len(store.create_calls) == 1
        assert store.create_calls[0]["type"] == "PREFERENCE"
        assert store.create_calls[0]["content"] == "喜欢 Python"

    @pytest.mark.asyncio
    async def test_valid_item_creates_memory(self):
        chat = _StubChat(response='{"items":[{"type":"FACT","content":"公司主要用 Java","importance":0.8}]}')
        store = _StubMemoryStore()
        extractor = DeepSeekMemoryExtractor(chat, _StubEmbedding(), store)
        org = uuid4()
        member = uuid4()
        session = uuid4()
        await extractor.extract_and_store(org, member, session, "q", "a")
        assert len(store.create_calls) == 1
        call = store.create_calls[0]
        assert call["type"] == "FACT"
        assert call["organization_id"] == org
        assert call["member_id"] == member
        assert call["source_session_id"] == session
        assert call["importance"] == 0.8

    @pytest.mark.asyncio
    async def test_importance_clamped_to_0_1(self):
        chat = _StubChat(response='{"items":[{"type":"FACT","content":"x","importance":2.5}]}')
        store = _StubMemoryStore()
        extractor = DeepSeekMemoryExtractor(chat, _StubEmbedding(), store)
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")
        # 2.5 应被裁到 1.0
        assert store.create_calls[0]["importance"] == 1.0

    @pytest.mark.asyncio
    async def test_importance_clamped_to_0_min(self):
        chat = _StubChat(response='{"items":[{"type":"FACT","content":"x","importance":-0.5}]}')
        store = _StubMemoryStore()
        extractor = DeepSeekMemoryExtractor(chat, _StubEmbedding(), store)
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")
        assert store.create_calls[0]["importance"] == 0.0

    @pytest.mark.asyncio
    async def test_invalid_importance_defaults_to_0_5(self):
        chat = _StubChat(response='{"items":[{"type":"FACT","content":"x","importance":"high"}]}')
        store = _StubMemoryStore()
        extractor = DeepSeekMemoryExtractor(chat, _StubEmbedding(), store)
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")
        assert store.create_calls[0]["importance"] == 0.5

    @pytest.mark.asyncio
    async def test_invalid_type_skipped(self):
        """type 不在 PREFERENCE/FACT/GOAL 内 → 跳过该条目。"""
        chat = _StubChat(response='{"items":[{"type":"WEIRD","content":"x","importance":0.5}]}')
        store = _StubMemoryStore()
        extractor = DeepSeekMemoryExtractor(chat, _StubEmbedding(), store)
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")
        assert store.create_calls == []

    @pytest.mark.asyncio
    async def test_blank_content_skipped(self):
        chat = _StubChat(response='{"items":[{"type":"FACT","content":"","importance":0.5}]}')
        store = _StubMemoryStore()
        extractor = DeepSeekMemoryExtractor(chat, _StubEmbedding(), store)
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")
        assert store.create_calls == []

    @pytest.mark.asyncio
    async def test_dedup_skips_creating_similar_memory(self):
        """如果 ES 已有相似记忆,不重复写入。"""
        chat = _StubChat(response='{"items":[{"type":"FACT","content":"公司用 Java","importance":0.8}]}')
        embedding = _StubEmbedding()
        store = _StubMemoryStore()
        store.similar_hit = True

        # 模拟 find_similar_existing 命中
        class _HitStore(_StubMemoryStore):
            async def find_similar_existing(self, organization_id, member_id, candidate_vector):
                return object()  # 非 None,意味着已存在相似

        hit_store = _HitStore()
        extractor = DeepSeekMemoryExtractor(chat, embedding, hit_store)
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")
        assert hit_store.create_calls == []

    @pytest.mark.asyncio
    async def test_embedding_failure_skips_item(self):
        """Embedding 失败时跳过该条 item,不影响其他 item。"""
        chat = _StubChat(
            response='{"items":[{"type":"FACT","content":"x","importance":0.8},{"type":"GOAL","content":"y","importance":0.9}]}'
        )
        store = _StubMemoryStore()
        embedding = _StubEmbedding(raise_exc=RuntimeError("embed down"))
        extractor = DeepSeekMemoryExtractor(chat, embedding, store)
        await extractor.extract_and_store(uuid4(), uuid4(), uuid4(), "q", "a")
        assert store.create_calls == []
