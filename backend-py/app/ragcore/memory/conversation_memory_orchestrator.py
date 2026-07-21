"""记忆子系统的编排入口: 检索前准备(滑动窗口→指代消解→画像检索),
生成后记录(写直达持久化 + 异步画像提炼)。

对应 Java 版 `ragcore/conversation/ConversationMemoryOrchestrator.java`。
是 `QueryService` 与记忆各组件之间的唯一接触面,QueryService 只依赖这一个类
(通过 FastAPI 依赖注入可选装配),不需要单独认识六七个记忆相关组件。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable
from uuid import UUID

from app.ragcore.embedding.client import EmbeddingClient
from app.ragcore.memory.conversation_store import ConversationStore
from app.ragcore.memory.coreference_resolver import CoreferenceResolver
from app.ragcore.memory.memory_context import MemoryContext
from app.ragcore.memory.memory_extractor import MemoryExtractor
from app.ragcore.memory.sliding_window_assembler import SlidingWindowAssembler
from app.ragcore.memory.user_profile_injector import UserProfileInjector
from app.ragcore.model import Citation

logger = logging.getLogger(__name__)


class ConversationMemoryOrchestrator:
    def __init__(
        self,
        conversation_store: ConversationStore,
        sliding_window_assembler: SlidingWindowAssembler,
        coreference_resolver: CoreferenceResolver,
        embedding_client: EmbeddingClient,
        user_profile_injector: UserProfileInjector | None,
        memory_extractor: MemoryExtractor,
        token_budget: int,
    ) -> None:
        self._store = conversation_store
        self._window = sliding_window_assembler
        self._coref = coreference_resolver
        self._embedding = embedding_client
        self._profile = user_profile_injector
        self._extractor = memory_extractor
        self._token_budget = token_budget

    async def prepare_context(
        self,
        organization_id: UUID,
        member_id: UUID,
        session_id: UUID,
        question: str,
    ) -> MemoryContext:
        recent_raw = await self._store.recent_raw_messages(organization_id, session_id)
        window = await self._window.assemble(recent_raw, self._token_budget)
        resolved_question = await self._coref.resolve(question, list(window.recent_messages))

        profile_context = ""
        resolved_vector: list[float] | None = None
        try:
            embedding = await self._embedding.embed([resolved_question])
            if embedding.vectors:
                resolved_vector = list(embedding.vectors[0])
                if self._profile is not None and resolved_vector:
                    profile_context = await self._profile.build_system_context(
                        organization_id, member_id, resolved_vector
                    )
        except Exception as ex:  # noqa: BLE001 - 画像检索失败是降级路径
            logger.warning(
                "记忆检索用的向量化失败,本轮跳过画像注入: sessionId=%s, ex=%s",
                session_id, ex,
            )

        # 把这里算好的向量带给检索阶段复用,避免同一句 resolved_question 被检索链路
        # 重复调用 Embedding。
        return MemoryContext(
            resolved_question=resolved_question,
            profile_system_context=profile_context,
            resolved_question_vector=resolved_vector,
        )

    async def record_turn(
        self,
        organization_id: UUID,
        kb_id: UUID,
        member_id: UUID,
        session_id: UUID,
        question: str,
        answer: str,
        citations: Iterable[Citation] | None,
    ) -> None:
        # 同步写: MongoDB + Redis 滑动窗口(失败只记日志,不阻断已返回给用户的回答)
        try:
            from app.ragcore.memory.chat_message import ChatMessage  # 局部 import 避免循环

            now_user = ChatMessage.user(question, _now())
            await self._store.append_message(organization_id, kb_id, member_id, session_id, now_user)
            await self._store.append_message(
                organization_id,
                kb_id,
                member_id,
                session_id,
                ChatMessage.assistant(answer, _now(), citations),
            )
        except Exception as ex:  # noqa: BLE001
            logger.warning(
                "会话消息持久化失败,不影响已返回给用户的回答: sessionId=%s, ex=%s",
                session_id, ex,
            )

        # 异步触发画像提炼:失败被 extractor 内部捕获,不会传播到这里
        if self._extractor is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    _safe_extract(self._extractor, organization_id, member_id, session_id, question, answer)
                )
            except RuntimeError:
                # 没有 running loop(极少见,如同步测试调用);同步跑一次
                try:
                    await _safe_extract(
                        self._extractor, organization_id, member_id, session_id, question, answer
                    )
                except Exception:  # noqa: BLE001
                    pass


async def _safe_extract(
    extractor: MemoryExtractor,
    organization_id: UUID,
    member_id: UUID,
    session_id: UUID,
    question: str,
    answer: str,
) -> None:
    try:
        await extractor.extract_and_store(organization_id, member_id, session_id, question, answer)
    except Exception as ex:  # noqa: BLE001 - 双层防御,extractor 自身也不该抛
        logger.warning("画像提炼异步执行失败: %s", ex)


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
