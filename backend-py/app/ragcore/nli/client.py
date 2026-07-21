"""自然语言推理（NLI）客户端协议：判断 premise 是否蕴含 hypothesis。

对应 Java 版 `ragcore/nli/NliClient.java` + `NliVerdict.java`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class NliVerdict:
    """单次 NLI 判定结果：premise 是否蕴含 hypothesis 的三分类概率。

    对应 Java 版 `ragcore/nli/NliVerdict.java`。
    """

    label: str
    entailment_prob: float
    neutral_prob: float
    contradiction_prob: float


@runtime_checkable
class NliClient(Protocol):
    async def check(self, premise: str, hypothesis: str) -> NliVerdict: ...
