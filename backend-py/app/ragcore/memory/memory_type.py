"""统一记忆索引里区分短期会话消息与长期画像条目。对应 Java 版 `ragcore/conversation/MemoryType.java`。"""

from __future__ import annotations

from enum import Enum


class MemoryType(str, Enum):
    SESSION_MESSAGE = "SESSION_MESSAGE"
    PROFILE_ITEM = "PROFILE_ITEM"
