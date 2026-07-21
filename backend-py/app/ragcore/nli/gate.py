"""NLI 自检 fail-open 网关：网关未启用/调用异常（含超时）时自检直接跳过，不阻塞主问答流程。

Java 版现状说明（移植时核对过，避免臆造未上线的行为）：`ragcore/nli/` 目前只有
`NliClient`/`HttpNliClient` 两个基础设施类，`AnswerSelfChecker` 实际生产代码仍然用的是
`RerankerClient`（见 `generation/self_checker.py` 的说明）——用真实 NLI 模型替换 Reranker
做生成后自检的方案还停留在设计文档
`docs/superpowers/specs/2026-07-16-nli-based-self-check-design.md`，尚未落地校准阈值，
Java 侧也还没有把 `NliClient` 接进任何调用方。

但该设计文档明确写了目标行为：「未启用/服务不可达时自检直接跳过（fail-open，与原 Reranker
异常时行为一致，不影响主问答流程）」，且这与已经实际上线的 `AnswerSelfChecker` 对
`RerankerClient` 异常的 fail-open 处理（`ragcore/generation/AnswerSelfChecker.java`
第 67-70 行：捕获异常记 warning、返回 `SelfCheckResult.none()`）是同一套模式。这里提前把
这个网关落地，等 Java 侧真正把 NLI 接入自检、校准出 `entailment_prob` 阈值后，Python 这边
只需要在使用处调用 `NliSelfCheckGate.check()` 并加上阈值判断，网关本身的 fail-open 语义不
会变。
"""

from __future__ import annotations

import logging

from app.ragcore.nli.client import NliClient, NliVerdict

logger = logging.getLogger(__name__)


class NliSelfCheckGate:
    """包一层 fail-open：`client` 为 None（未启用）或调用抛异常（含超时）时返回 None。"""

    def __init__(self, client: NliClient | None) -> None:
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def check(self, premise: str, hypothesis: str) -> NliVerdict | None:
        if self._client is None:
            return None
        try:
            return await self._client.check(premise, hypothesis)
        except Exception as exc:  # noqa: BLE001 - fail-open：任何异常都不能拖垮主问答流程
            logger.warning("NLI 自检调用失败，本轮跳过: %s", exc)
            return None
