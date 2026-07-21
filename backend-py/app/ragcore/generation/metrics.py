"""上游生成服务返回或可安全推导出的用量摘要；不包含回答正文。

对应 Java 版 `ragcore/generation/GenerationMetrics.java`。

Java 版是不可变 record，通过 `AtomicLong`/流式回调在生成过程中累积后一次性构造。Python 版
用异步生成器 `yield QueryEvent` 输出正文（详见 `openai_compatible.py`），异步生成器没有
Java 方法那种"执行完再返回值"的机制，所以改成调用方传入一个可变的 `GenerationMetrics`
实例、由生成过程原地更新字段，`async for` 循环结束后调用方直接读取这个实例即可拿到最终值。
这是 Python 里处理"流式产出 + 收尾汇总"的惯用写法，字段语义和更新时机与 Java 版一致。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GenerationMetrics:
    model: str = "unknown"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    output_characters: int = 0
    # 非空表示 FactVerificationGate 判定参考资料不包含具体答案（found:false），触发了事实
    # 核验拒答——调用方据此把审计状态记为 REFUSED，而不是 COMPLETED。
    fact_verification_refusal_reason: str | None = None

    def __setattr__(self, name: str, value: object) -> None:
        if name in ("prompt_tokens", "completion_tokens") and value is not None and value < 0:
            raise ValueError("生成用量不能为负数")
        if name == "output_characters" and value < 0:
            raise ValueError("生成用量不能为负数")
        object.__setattr__(self, name, value)
