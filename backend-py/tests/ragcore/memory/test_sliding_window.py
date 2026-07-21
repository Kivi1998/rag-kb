"""`SlidingWindowAssembler` 摘要降级 + 关键事实保留测试。

对照 Java 版 `ragcore/conversation/SlidingWindowAssembler.java`。
行为契约:
- token 预算用尽时,把最旧消息扔给 summarizer 压缩,关键事实消息始终保留原文
- 摘要失败时 fail-open 退化为"只保留窗口内消息,不带摘要",不抛异常
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.ragcore.memory.chat_message import ChatMessage, ROLE_USER
from app.ragcore.memory.conversation_summarizer import ConversationSummarizer
from app.ragcore.memory.conversation_window import ConversationWindow
from app.ragcore.memory.sliding_window_assembler import SlidingWindowAssembler
from app.ragcore.memory.token_estimator import estimate


class _StubSummarizer(ConversationSummarizer):
    def __init__(self, response: str | None = "summary", raise_exc: Exception | None = None) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.call_count = 0

    async def summarize(self, messages_to_compress: list[ChatMessage]) -> str:
        self.call_count += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.response is None:
            raise RuntimeError("no response set")
        return self.response


def _msg(content: str, key_fact: bool = False) -> ChatMessage:
    return ChatMessage(
        role=ROLE_USER,
        content=content,
        created_at=datetime.now(timezone.utc),
        key_fact=key_fact,
    )


class TestEmptyAndSmallInputs:
    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_window(self):
        summarizer = _StubSummarizer(raise_exc=AssertionError("should not call"))
        assembler = SlidingWindowAssembler(summarizer)
        window = await assembler.assemble([], token_budget=1000)
        assert window.recent_messages == ()
        assert window.summary is None
        assert summarizer.call_count == 0

    @pytest.mark.asyncio
    async def test_small_input_no_summarization(self):
        summarizer = _StubSummarizer(raise_exc=AssertionError("should not call"))
        assembler = SlidingWindowAssembler(summarizer)
        msgs = [_msg("hi"), _msg("how are you?")]
        window = await assembler.assemble(msgs, token_budget=1000)
        assert len(window.recent_messages) == 2
        assert window.summary is None
        assert summarizer.call_count == 0


class TestTokenBudgetEnforcement:
    @pytest.mark.asyncio
    async def test_budget_exceeded_summarizes_oldest(self):
        summarizer = _StubSummarizer(response="summary of old messages")
        assembler = SlidingWindowAssembler(summarizer)
        # 1000 token 预算,每条中文 10 字符约 10 token
        msgs = [_msg("x" * 50) for _ in range(50)]  # 每条约 12.5 token
        window = await assembler.assemble(msgs, token_budget=200)
        # 最近的消息在 kept,最早的消息被压缩
        assert window.summary == "summary of old messages"
        assert summarizer.call_count == 1
        # 至少保留一些最新消息
        assert len(window.recent_messages) >= 1

    @pytest.mark.asyncio
    async def test_summary_failure_fails_open(self):
        """摘要失败时只保留窗口内消息,不带 summary,不抛异常——这是降级路径。"""
        summarizer = _StubSummarizer(raise_exc=RuntimeError("LLM unavailable"))
        assembler = SlidingWindowAssembler(summarizer)
        msgs = [_msg("x" * 50) for _ in range(50)]
        window = await assembler.assemble(msgs, token_budget=200)
        assert window.summary is None  # 摘要失败时 summary 为 None
        assert len(window.recent_messages) >= 1  # 但 kept 仍保留


class TestKeyFactPreservation:
    """关键事实消息始终保留原文,不计入被压缩的候选——这是用户偏好/长期事实
    必须可被指代消解看见的硬约束。"""

    @pytest.mark.asyncio
    async def test_key_fact_messages_always_kept(self):
        summarizer = _StubSummarizer(response="summary")
        assembler = SlidingWindowAssembler(summarizer)
        # 关键事实(很旧)+ 普通消息
        key_fact = ChatMessage(
            role="user",
            content="用户的关键事实",
            created_at=datetime.now(timezone.utc),
            key_fact=True,
        )
        normal_old = _msg("x" * 50)
        normal_new = _msg("新消息" * 10)

        msgs = [normal_old, key_fact, normal_new]
        # token 预算很小,会触发摘要压缩
        window = await assembler.assemble(msgs, token_budget=30)
        # 关键事实必须在 recent_messages 里
        kept_contents = [m.content for m in window.recent_messages]
        assert "用户的关键事实" in kept_contents


class TestTokenEstimator:
    def test_empty_returns_zero(self):
        assert estimate("") == 0
        assert estimate(None) == 0

    def test_cjk_chars_one_per_token(self):
        assert estimate("你好世界") == 4  # 4 个 CJK 字符

    def test_ascii_chars_per_four(self):
        # 4 个 ASCII 字符 = 1 token
        assert estimate("abcd") == 1
        assert estimate("abcde") == 2  # 5 字符 = 1+1=2

    def test_mixed(self):
        # 2 个 CJK + 4 个 ASCII = 2 + 1 = 3
        assert estimate("hi你好") == 3


class TestConversationWindow:
    def test_has_summary(self):
        w = ConversationWindow(summary="x", recent_messages=())
        assert w.has_summary is True
        w2 = ConversationWindow(summary="   ", recent_messages=())
        assert w2.has_summary is False
        w3 = ConversationWindow(summary=None, recent_messages=())
        assert w3.has_summary is False

    def test_of_factory(self):
        msgs = [_msg("a"), _msg("b")]
        w = ConversationWindow.of(msgs, summary="sum")
        assert w.recent_messages == tuple(msgs)
        assert w.summary == "sum"
