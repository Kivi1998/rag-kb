"""GenerationMetrics 测试。

对照 Java 版 `GenerationMetrics.java`：Python 版改用可变 dataclass 原地更新（详见模块
docstring），重点验证默认值、原地更新语义,以及 `__setattr__` 对负数用量的校验。
"""

from __future__ import annotations

import pytest

from app.ragcore.generation.metrics import GenerationMetrics


class TestDefaults:
    def test_default_values(self):
        metrics = GenerationMetrics()
        assert metrics.model == "unknown"
        assert metrics.prompt_tokens is None
        assert metrics.completion_tokens is None
        assert metrics.output_characters == 0
        assert metrics.fact_verification_refusal_reason is None


class TestInPlaceMutation:
    def test_fields_can_be_updated_after_construction(self):
        metrics = GenerationMetrics()
        metrics.model = "gpt-4o-mini"
        metrics.prompt_tokens = 120
        metrics.completion_tokens = 40
        metrics.output_characters = 200
        metrics.fact_verification_refusal_reason = "found:false"

        assert metrics.model == "gpt-4o-mini"
        assert metrics.prompt_tokens == 120
        assert metrics.completion_tokens == 40
        assert metrics.output_characters == 200
        assert metrics.fact_verification_refusal_reason == "found:false"

    def test_streaming_style_incremental_update(self):
        """模拟 async generator 里逐块累加 output_characters 的用法。"""
        metrics = GenerationMetrics()
        for chunk in ["第一段", "第二段", "第三段"]:
            metrics.output_characters += len(chunk)
        assert metrics.output_characters == len("第一段") + len("第二段") + len("第三段")


class TestNegativeValueValidation:
    def test_negative_prompt_tokens_rejected(self):
        metrics = GenerationMetrics()
        with pytest.raises(ValueError):
            metrics.prompt_tokens = -1

    def test_negative_completion_tokens_rejected(self):
        metrics = GenerationMetrics()
        with pytest.raises(ValueError):
            metrics.completion_tokens = -1

    def test_negative_output_characters_rejected(self):
        metrics = GenerationMetrics()
        with pytest.raises(ValueError):
            metrics.output_characters = -1

    def test_none_token_counts_are_allowed(self):
        metrics = GenerationMetrics()
        metrics.prompt_tokens = None
        metrics.completion_tokens = None
        assert metrics.prompt_tokens is None
        assert metrics.completion_tokens is None

    def test_zero_is_allowed(self):
        metrics = GenerationMetrics()
        metrics.prompt_tokens = 0
        metrics.output_characters = 0
        assert metrics.prompt_tokens == 0
        assert metrics.output_characters == 0
