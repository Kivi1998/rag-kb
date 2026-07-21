"""从一轮问答中异步提炼候选画像条目(偏好/事实/长期目标)的端口。

对应 Java 版 `ragcore/conversation/MemoryExtractor.java`。
实现 SHALL 捕获内部所有异常,不得向调用方抛出——这是锦上添花的增强,失败不应影响
用户已经收到的回答。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class MemoryExtractor(Protocol):
    async def extract_and_store(
        self,
        organization_id: UUID,
        member_id: UUID,
        session_id: UUID,
        question: str,
        answer: str,
    ) -> None: ...
