"""Rerank 拒答门槛常量测试。

只确认 `MIN_RERANK_SCORE` 没有被意外改动——这个数值是拿 150 题评估集校准出来的
（`eval/reports/refusal-threshold-calibration-20260714.md`），改动会让已发布的评测结论
失真，禁止随意调整（详见模块 docstring）。
"""

from __future__ import annotations

from app.ragcore.rerank.thresholds import MIN_RERANK_SCORE


class TestMinRerankScore:
    def test_value_is_calibrated_constant(self):
        assert MIN_RERANK_SCORE == 0.06

    def test_is_a_float(self):
        assert isinstance(MIN_RERANK_SCORE, float)
