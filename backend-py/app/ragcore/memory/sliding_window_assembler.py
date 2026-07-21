"""按 token 预算圈定滑动窗口。

对应 Java 版 `ragcore/conversation/SlidingWindowAssembler.java`。
从最近消息往前累加,超预算时用摘要压缩替换最旧的非关键事实消息,而不是直接丢弃;
关键事实消息始终保留原文,不计入被压缩的候选。

摘要压缩失败时 fail-open:退化为只保留窗口内消息、不带摘要,不向上抛异常——
与 `ConversationStore` / `CoreferenceResolver` 等记忆子组件的降级语义保持一致,
不应因为摘要 LLM 调用失败而让整个问答请求失败。
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.ragcore.memory.chat_message import ChatMessage
from app.ragcore.memory.conversation_summarizer import ConversationSummarizer
from app.ragcore.memory.conversation_window import ConversationWindow
from app.ragcore.memory.token_estimator import estimate

logger = logging.getLogger(__name__)


class SlidingWindowAssembler:
    def __init__(self, summarizer: ConversationSummarizer) -> None:
        self._summarizer = summarizer

    async def assemble(self, messages: Iterable[ChatMessage], token_budget: int) -> ConversationWindow:
        ordered = list(messages or [])
        if not ordered:
            return ConversationWindow(summary=None, recent_messages=())

        kept: list[ChatMessage] = []
        to_compress: list[ChatMessage] = []
        running_tokens = 0
        budget_exceeded = False

        # 从最新往最旧遍历,把还在预算内的放进 kept,超过预算的放进 to_compress。
        for message in reversed(ordered):
            if message.key_fact:
                kept.append(message)
                continue
            if not budget_exceeded:
                tokens = estimate(message.content)
                if running_tokens + tokens <= token_budget:
                    kept.append(message)
                    running_tokens += tokens
                    continue
                budget_exceeded = True
            to_compress.append(message)

        kept.reverse()
        to_compress.reverse()

        if not to_compress:
            return ConversationWindow(summary=None, recent_messages=tuple(kept))

        try:
            summary = await self._summarizer.summarize(list(to_compress))
            return ConversationWindow(summary=summary, recent_messages=tuple(kept))
        except Exception as ex:  # noqa: BLE001 - 摘要失败是降级路径,绝不上抛
            logger.warning("摘要压缩失败,本轮跳过摘要,仅保留窗口内消息: %s", ex)
            return ConversationWindow(summary=None, recent_messages=tuple(kept))
