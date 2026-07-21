"""NliSelfCheckGate 测试。

这是本模块最重要的行为：fail-open 降级路径必须被覆盖——网关未启用（client=None）或
调用异常（含超时）时自检直接跳过、返回 None，不能抛出异常拖垮主问答流程。对照 Java 版
`AnswerSelfChecker.java` 第 67-70 行同款 fail-open 模式（见 `gate.py` 模块 docstring）。
"""

from __future__ import annotations

import asyncio

import pytest

from app.ragcore.nli.client import NliVerdict
from app.ragcore.nli.gate import NliSelfCheckGate


class _StubClient:
    def __init__(self, verdict: NliVerdict | None = None, exc: Exception | None = None):
        self._verdict = verdict
        self._exc = exc
        self.calls: list[tuple[str, str]] = []

    async def check(self, premise: str, hypothesis: str) -> NliVerdict:
        self.calls.append((premise, hypothesis))
        if self._exc is not None:
            raise self._exc
        assert self._verdict is not None
        return self._verdict


class TestDisabledFailOpen:
    """client=None（NLI 未启用）时必须直接跳过，不抛异常。"""

    async def test_none_client_returns_none_without_raising(self):
        gate = NliSelfCheckGate(None)
        result = await gate.check("premise", "hypothesis")
        assert result is None

    def test_enabled_property_false_when_client_is_none(self):
        gate = NliSelfCheckGate(None)
        assert gate.enabled is False


class TestEnabledHappyPath:
    async def test_returns_verdict_from_client_when_enabled(self):
        verdict = NliVerdict(label="entailment", entailment_prob=0.9, neutral_prob=0.08, contradiction_prob=0.02)
        client = _StubClient(verdict=verdict)
        gate = NliSelfCheckGate(client)

        result = await gate.check("premise text", "hypothesis text")

        assert result is verdict
        assert client.calls == [("premise text", "hypothesis text")]

    def test_enabled_property_true_when_client_present(self):
        gate = NliSelfCheckGate(_StubClient())
        assert gate.enabled is True


class TestExceptionFailOpen:
    """调用异常（含超时）必须被捕获，返回 None，不能向上抛出——这是"不阻塞主问答流程"的核心保证。"""

    async def test_generic_exception_is_swallowed_and_returns_none(self):
        client = _StubClient(exc=RuntimeError("nli-gateway 500"))
        gate = NliSelfCheckGate(client)

        result = await gate.check("p", "h")

        assert result is None

    async def test_timeout_exception_is_swallowed_and_returns_none(self):
        client = _StubClient(exc=asyncio.TimeoutError("nli-gateway timed out"))
        gate = NliSelfCheckGate(client)

        result = await gate.check("p", "h")

        assert result is None

    async def test_connection_error_is_swallowed_and_returns_none(self):
        client = _StubClient(exc=ConnectionError("connection refused"))
        gate = NliSelfCheckGate(client)

        result = await gate.check("p", "h")

        assert result is None

    async def test_does_not_re_raise_base_exception_subclasses(self):
        """`except Exception` 覆盖所有非 BaseException 的异常类型，包括自定义异常类。"""

        class _CustomModelError(Exception):
            pass

        client = _StubClient(exc=_CustomModelError("boom"))
        gate = NliSelfCheckGate(client)

        result = await gate.check("p", "h")

        assert result is None
