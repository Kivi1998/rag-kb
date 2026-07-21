"""`AnswerSelfChecker` 的核查结果；`unsupported_claims` 为空表示本轮没有发现问题。

对应 Java 版 `ragcore/generation/SelfCheckResult.java` record。Python 版用 frozen dataclass
对应 record 的不可变语义,并在 `__post_init__` 里把 `unsupported_claims` 归一化成 tuple
(同 `QueryEvent` 等不可变类型的处理),避免外部修改影响后续判等/审计。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SelfCheckResult:
    """核查结果不可变值对象。`unsupported_claims` 为空表示没有问题。"""

    unsupported_claims: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # None/列表统一归一化成 tuple：调用方传 None 或 list 都能用,行为等价 Java 版
        # `List.copyOf(unsupportedClaims == null ? List.of() : unsupportedClaims)`。
        normalized = tuple(self.unsupported_claims or ())
        object.__setattr__(self, "unsupported_claims", normalized)

    @property
    def has_unsupported_claims(self) -> bool:
        return bool(self.unsupported_claims)

    @classmethod
    def none(cls) -> "SelfCheckResult":
        """工厂方法：没有发现问题或本轮跳过自检时返回空结果。对应 Java `SelfCheckResult.none()`。"""
        return cls(())

    def build_warning_message(self) -> str:
        """拼成追加在 `done` 之前的提醒文案；调用方需先检查 `has_unsupported_claims`。

        对应 Java `buildWarningMessage()`,文案结构保持一致:第一行总述 + 每条 claim 一行
        `- ` 前缀。翻译/改写文案不在本次移植范围,这里原样复用。
        """
        message = "⚠️ 自检提示:以下内容未在参考资料中找到明确支撑,请以资料原文为准核实:"
        for claim in self.unsupported_claims:
            message += f"\n- {claim}"
        return message
