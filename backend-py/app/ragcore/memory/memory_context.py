"""一次问答里,记忆子系统准备好的上下文。

对应 Java 版 `ragcore/conversation/MemoryContext.java`。
`resolved_question` 用于检索(指代消解后);`profile_system_context` 仅用于生成阶段
的 System 上下文注入(可能为空字符串);`resolved_question_vector` 是画像检索时已经
算好的向量,供检索阶段直接复用——避免对同一句 resolved_question 被检索链路再次调用
Embedding。画像向量化失败(fail-open)或没有画像子系统时为 None,检索阶段会退回自己算。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryContext:
    resolved_question: str
    profile_system_context: str = ""
    resolved_question_vector: list[float] | None = None

    def __post_init__(self) -> None:
        if not self.resolved_question:
            raise ValueError("MemoryContext.resolved_question 不能为空")
        if self.resolved_question_vector is not None:
            object.__setattr__(self, "resolved_question_vector", list(self.resolved_question_vector))

    @property
    def has_profile_context(self) -> bool:
        return bool(self.profile_system_context and self.profile_system_context.strip())
