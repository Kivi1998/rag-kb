"""eval/metrics 的零依赖单元测试。

不引入 pytest，标准库 unittest 是首选；
照样可以 `python3 -m pytest eval/tests/test_metrics.py -q` 跑。
"""

from __future__ import annotations

import unittest

from eval.metrics import (
    BucketStats,
    DatasetValidationError,
    GroundTruth,
    Prediction,
    evaluate,
    first_hit_rank,
    render_markdown,
    validate_inputs,
)


def _gt(
    id: str,
    golds: tuple[str, ...],
    expect_refusal: bool = False,
    category: str = "api",
    difficulty: str = "easy",
    reason: str | None = None,
) -> GroundTruth:
    return GroundTruth(
        id=id,
        kb_id="kb-1",
        org_id="org-1",
        category=category,
        question=f"q-{id}",
        ground_truth_chunk_ids=golds,
        expect_refusal=expect_refusal,
        refusal_reason=reason,
        difficulty=difficulty,
    )


def _pr(id: str, preds: tuple[str, ...], refusal: bool = False, reason: str | None = None) -> Prediction:
    return Prediction(
        id=id,
        predicted_chunk_ids=preds,
        predicted_refusal=refusal,
        predicted_refusal_reason=reason,
    )


class FirstHitRankTest(unittest.TestCase):
    def test_first_match_returns_one_indexed_rank(self):
        self.assertEqual(first_hit_rank(("a", "b", "c"), ("b",)), 2)

    def test_no_match_returns_none(self):
        self.assertIsNone(first_hit_rank(("a", "b"), ("x")))

    def test_first_match_wins_even_if_later_match_present(self):
        self.assertEqual(first_hit_rank(("a", "b", "c"), ("c", "a")), 1)


class BucketStatsTest(unittest.TestCase):
    def test_recall_at_k_independent_counters(self):
        b = BucketStats()
        b.add(hit_rank=1, expect_refusal=False, predicted_refusal=False)   # mrr +1.0
        b.add(hit_rank=5, expect_refusal=False, predicted_refusal=False)   # mrr +0.2
        b.add(hit_rank=11, expect_refusal=False, predicted_refusal=False)  # mrr +1/11，且不在 R@10 内
        self.assertAlmostEqual(b.recall_at(1), 1 / 3)
        self.assertAlmostEqual(b.recall_at(5), 2 / 3)
        self.assertAlmostEqual(b.recall_at(10), 2 / 3)
        expected_mrr = (1.0 + 0.2 + 1 / 11) / 3
        self.assertAlmostEqual(b.mrr(), expected_mrr)

    def test_refusal_confusion_matrix(self):
        b = BucketStats()
        # 期望拒答 + 实际拒答 → TP
        b.add(hit_rank=None, expect_refusal=True, predicted_refusal=True)
        # 期望拒答 + 实际不拒答 → FN
        b.add(hit_rank=None, expect_refusal=True, predicted_refusal=False)
        # 不期望拒答 + 实际拒答 → FP
        b.add(hit_rank=None, expect_refusal=False, predicted_refusal=True)
        # 不期望拒答 + 实际不拒答 → TN
        b.add(hit_rank=1, expect_refusal=False, predicted_refusal=False)
        self.assertEqual((b.refusal_tp, b.refusal_fp, b.refusal_fn, b.refusal_tn), (1, 1, 1, 1))
        self.assertAlmostEqual(b.refusal_precision(), 0.5)
        self.assertAlmostEqual(b.refusal_recall(), 0.5)
        self.assertAlmostEqual(b.refusal_f1(), 0.5)


class EvaluateTest(unittest.TestCase):
    def test_basic_aggregation(self):
        gts = [
            _gt("q1", ("c1",), category="api", difficulty="easy"),
            _gt("q2", ("c2",), category="api", difficulty="easy"),
            _gt("q3", (), category="config", difficulty="medium", expect_refusal=True, reason="OUT_OF_SCOPE"),
        ]
        preds = [
            _pr("q1", ("c1", "c9")),
            _pr("q2", ("c2",)),
            _pr("q3", (), refusal=True, reason="OUT_OF_SCOPE"),
        ]
        report = evaluate(gts, preds, meta={"embedding": "bge-m3@1"})
        self.assertEqual(report.overall.total, 3)
        self.assertEqual(report.overall.recall_at_5, 2)
        # q3 不期望召回 → 拒答 F1 = 1
        self.assertAlmostEqual(report.overall.refusal_f1(), 1.0)
        # category 桶
        self.assertIn("api", report.by_category)
        self.assertIn("config", report.by_category)
        # difficulty 桶
        self.assertIn("easy", report.by_difficulty)
        self.assertIn("medium", report.by_difficulty)

    def test_missing_predictions_counted_as_failures(self):
        gts = [_gt("q1", ("c1",))]
        preds: list[Prediction] = []
        report = evaluate(gts, preds)
        self.assertEqual(report.missing_predictions, ["q1"])
        self.assertEqual(report.overall.total, 1)
        self.assertEqual(report.overall.recall_at_5, 0)

    def test_version_meta_propagated(self):
        gts = [_gt("q1", ("c1",))]
        preds = [_pr("q1", ("c1",))]
        report = evaluate(gts, preds, meta={"embedding": "x", "chunker": "y"})
        self.assertEqual(report.version_meta, {"embedding": "x", "chunker": "y"})

    def test_false_negative_refusal_counted_in_denominator(self):
        # 期望拒答但系统不拒答 → 拒答 FN
        gts = [_gt("q1", (), expect_refusal=True, reason="OUT_OF_SCOPE")]
        preds = [_pr("q1", ("c-fake",))]
        report = evaluate(gts, preds)
        # 拒答召回率 = 0
        self.assertAlmostEqual(report.overall.refusal_recall(), 0.0)

    def test_retrieval_metrics_exclude_expected_refusal_questions(self):
        gts = [
            _gt("answerable", ("c1",)),
            _gt("refusal", (), expect_refusal=True, reason="OUT_OF_SCOPE"),
        ]
        preds = [_pr("answerable", ("c1",)), _pr("refusal", (), refusal=True)]
        report = evaluate(gts, preds)
        self.assertEqual(report.overall.total, 2)
        self.assertEqual(report.overall.answerable_total, 1)
        self.assertEqual(report.overall.expected_refusal_total, 1)
        self.assertAlmostEqual(report.overall.recall_at_5, 1.0)
        self.assertAlmostEqual(report.overall.mrr(), 1.0)


class InputValidationTest(unittest.TestCase):
    def test_rejects_duplicate_and_unknown_prediction_ids(self):
        gt = _gt("q1", ("c1",))
        with self.assertRaisesRegex(DatasetValidationError, "重复 id"):
            validate_inputs([gt, gt], [])
        with self.assertRaisesRegex(DatasetValidationError, "未知题目 id"):
            validate_inputs([gt], [_pr("other", ("c1",))])

    def test_rejects_inconsistent_refusal_and_empty_gold(self):
        with self.assertRaisesRegex(DatasetValidationError, "可回答题"):
            validate_inputs([_gt("q1", ())], [])
        with self.assertRaisesRegex(DatasetValidationError, "必须为空"):
            validate_inputs([_gt("q1", ("c1",), expect_refusal=True)], [])
        with self.assertRaisesRegex(DatasetValidationError, "predicted_refusal"):
            validate_inputs([_gt("q1", ("c1",))], [_pr("q1", ("c1",), refusal=True)])


class MarkdownReportTest(unittest.TestCase):
    def test_render_contains_overall_and_buckets(self):
        gts = [
            _gt("q1", ("c1",), category="api", difficulty="easy"),
            _gt("q2", (), category="api", difficulty="easy", expect_refusal=True, reason="OUT_OF_SCOPE"),
        ]
        preds = [
            _pr("q1", ("c1",)),
            _pr("q2", (), refusal=True, reason="OUT_OF_SCOPE"),
        ]
        report = evaluate(gts, preds, meta={"embedding": "bge-m3@1"})
        md = render_markdown(report)
        self.assertIn("# 自研 RAG 离线评测报告", md)
        self.assertIn("Recall@5", md)
        self.assertIn("bge-m3@1", md)
        self.assertIn("api", md)
        self.assertIn("easy", md)


if __name__ == "__main__":
    unittest.main()
