"""自研 RAG 离线评测 — 指标计算（纯标准库，零依赖）。

移植自 rag-from-zero（MIT）chapters/ch10-evaluation/eval_demo.py，
并扩展支持：
- 可回答题的 Recall@k / MRR（拒答题不污染检索分母）
- 拒答精确率 / 召回率 / F1
- 期望拒答与实际拒答的二分类指标
- 按 category / difficulty 分桶统计

参考：
- rag_project/tests/sample_qa.jsonl（JSONL schema 设计）
- 11 节 v0 契约（Chunk / RetrievedChunk / IngestionStatus）
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# ──────────────────────────────────────────────────────────────────────────────
# 数据结构（与 format.md 配套，schema 变更请同步两边）
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GroundTruth:
    id: str
    kb_id: str
    org_id: str
    category: str
    question: str
    ground_truth_chunk_ids: tuple[str, ...]
    expect_refusal: bool
    refusal_reason: str | None = None
    difficulty: str = "medium"
    notes: str | None = None

    @classmethod
    def from_jsonl_line(cls, line: str) -> "GroundTruth":
        obj = json.loads(line)
        return cls(
            id=str(obj["id"]),
            kb_id=str(obj["kb_id"]),
            org_id=str(obj["org_id"]),
            category=str(obj.get("category", "general")),
            question=str(obj["question"]),
            ground_truth_chunk_ids=tuple(str(x) for x in obj["ground_truth_chunk_ids"]),
            expect_refusal=bool(obj.get("expect_refusal", False)),
            refusal_reason=obj.get("refusal_reason"),
            difficulty=str(obj.get("difficulty", "medium")),
            notes=obj.get("notes"),
        )


@dataclass(frozen=True)
class Prediction:
    id: str
    predicted_chunk_ids: tuple[str, ...]
    predicted_refusal: bool
    predicted_refusal_reason: str | None = None
    reranked: bool = False

    @classmethod
    def from_jsonl_line(cls, line: str) -> "Prediction":
        obj = json.loads(line)
        return cls(
            id=str(obj["id"]),
            predicted_chunk_ids=tuple(str(x) for x in obj.get("predicted_chunk_ids", [])),
            predicted_refusal=bool(obj.get("predicted_refusal", False)),
            predicted_refusal_reason=obj.get("predicted_refusal_reason"),
            reranked=bool(obj.get("reranked", False)),
        )


@dataclass
class BucketStats:
    # 全部样本数，用于拒答二分类指标。
    total: int = 0
    # 仅 expect_refusal=false 的样本数，Recall / MRR 的唯一分母。
    answerable_total: int = 0
    expected_refusal_total: int = 0
    recall_at_1: int = 0
    recall_at_5: int = 0
    recall_at_10: int = 0
    mrr_sum: float = 0.0
    refusal_tp: int = 0  # 期望拒答 & 实际拒答
    refusal_fp: int = 0  # 不期望拒答 & 实际拒答
    refusal_fn: int = 0  # 期望拒答 & 实际不拒答
    refusal_tn: int = 0  # 不期望拒答 & 实际不拒答

    def add(self, hit_rank: int | None, expect_refusal: bool, predicted_refusal: bool) -> None:
        self.total += 1
        if expect_refusal:
            self.expected_refusal_total += 1
        else:
            self.answerable_total += 1
        if not expect_refusal and hit_rank is not None:
            if hit_rank <= 1:
                self.recall_at_1 += 1
            if hit_rank <= 5:
                self.recall_at_5 += 1
            if hit_rank <= 10:
                self.recall_at_10 += 1
            self.mrr_sum += 1.0 / hit_rank
        if expect_refusal and predicted_refusal:
            self.refusal_tp += 1
        elif (not expect_refusal) and predicted_refusal:
            self.refusal_fp += 1
        elif expect_refusal and (not predicted_refusal):
            self.refusal_fn += 1
        else:
            self.refusal_tn += 1

    def recall_at(self, k: int) -> float:
        if self.answerable_total == 0:
            return 0.0
        if k == 1:
            return self.recall_at_1 / self.answerable_total
        if k == 5:
            return self.recall_at_5 / self.answerable_total
        if k == 10:
            return self.recall_at_10 / self.answerable_total
        raise ValueError(f"不支持的 k={k}")

    def mrr(self) -> float:
        return self.mrr_sum / self.answerable_total if self.answerable_total else 0.0

    def refusal_precision(self) -> float:
        denom = self.refusal_tp + self.refusal_fp
        return self.refusal_tp / denom if denom else 0.0

    def refusal_recall(self) -> float:
        denom = self.refusal_tp + self.refusal_fn
        return self.refusal_tp / denom if denom else 0.0

    def refusal_f1(self) -> float:
        p = self.refusal_precision()
        r = self.refusal_recall()
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)


@dataclass
class Report:
    overall: BucketStats = field(default_factory=BucketStats)
    by_category: dict[str, BucketStats] = field(default_factory=lambda: defaultdict(BucketStats))
    by_difficulty: dict[str, BucketStats] = field(default_factory=lambda: defaultdict(BucketStats))
    version_meta: dict[str, str] = field(default_factory=dict)
    missing_predictions: list[str] = field(default_factory=list)


class DatasetValidationError(ValueError):
    """评测输入违反 JSONL schema 或跨文件一致性约束。"""


# ──────────────────────────────────────────────────────────────────────────────
# 指标计算核心（移植自 rag3 / 自研扩展）
# ──────────────────────────────────────────────────────────────────────────────


def first_hit_rank(
    predicted: tuple[str, ...], golds: tuple[str, ...]
) -> int | None:
    """返回首个命中 gold 的排名（1-based）；未命中返回 None。"""
    gold_set = set(golds)
    for idx, chunk_id in enumerate(predicted, start=1):
        if chunk_id in gold_set:
            return idx
    return None


def evaluate(
    ground_truths: Iterable[GroundTruth],
    predictions: Iterable[Prediction],
    meta: dict[str, str] | None = None,
) -> Report:
    """逐条对 ground_truth 和 prediction，并产出多桶聚合 Report。"""
    ground_truth_list = list(ground_truths)
    prediction_list = list(predictions)
    validate_inputs(ground_truth_list, prediction_list)
    pred_index = {p.id: p for p in prediction_list}

    report = Report(version_meta=dict(meta or {}))

    for gt in ground_truth_list:
        pred = pred_index.get(gt.id)
        # 没预测：未召回（hit_rank=None）、视为"未拒答"
        if pred is None:
            report.missing_predictions.append(gt.id)
            _record(report, gt, hit_rank=None, predicted_refusal=False)
            continue
        hit_rank = first_hit_rank(pred.predicted_chunk_ids, gt.ground_truth_chunk_ids)
        _record(report, gt, hit_rank=hit_rank, predicted_refusal=pred.predicted_refusal)

    return report


def validate_inputs(ground_truths: Iterable[GroundTruth], predictions: Iterable[Prediction]) -> None:
    """严格检查 ID、拒答语义与最小可评测性，避免静默产出错误指标。"""
    ground_truth_list = list(ground_truths)
    prediction_list = list(predictions)
    gt_ids: set[str] = set()
    for gt in ground_truth_list:
        if gt.id in gt_ids:
            raise DatasetValidationError(f"ground truth 存在重复 id: {gt.id}")
        gt_ids.add(gt.id)
        if gt.expect_refusal and gt.ground_truth_chunk_ids:
            raise DatasetValidationError(
                f"{gt.id}: expect_refusal=true 时 ground_truth_chunk_ids 必须为空"
            )
        if not gt.expect_refusal and not gt.ground_truth_chunk_ids:
            raise DatasetValidationError(
                f"{gt.id}: 可回答题必须至少提供一个 ground_truth_chunk_id"
            )
        if gt.refusal_reason and not gt.expect_refusal:
            raise DatasetValidationError(f"{gt.id}: 非拒答题不能设置 refusal_reason")

    prediction_ids: set[str] = set()
    for prediction in prediction_list:
        if prediction.id in prediction_ids:
            raise DatasetValidationError(f"prediction 存在重复 id: {prediction.id}")
        prediction_ids.add(prediction.id)
        if prediction.id not in gt_ids:
            raise DatasetValidationError(f"prediction 引用了未知题目 id: {prediction.id}")
        if prediction.predicted_refusal and prediction.predicted_chunk_ids:
            raise DatasetValidationError(
                f"{prediction.id}: predicted_refusal=true 时 predicted_chunk_ids 必须为空"
            )
        if not prediction.predicted_refusal and prediction.predicted_refusal_reason:
            raise DatasetValidationError(
                f"{prediction.id}: 非拒答预测不能设置 predicted_refusal_reason"
            )


def _record(
    report: Report,
    gt: GroundTruth,
    hit_rank: int | None,
    predicted_refusal: bool,
) -> None:
    """把一条 GT 写入 overall + category + difficulty 三个桶。"""
    report.overall.add(hit_rank, gt.expect_refusal, predicted_refusal)
    bucket_cat = report.by_category.get(gt.category) or _new_bucket(report.by_category, gt.category)
    bucket_cat.add(hit_rank, gt.expect_refusal, predicted_refusal)
    bucket_diff = report.by_difficulty.get(gt.difficulty) or _new_bucket(report.by_difficulty, gt.difficulty)
    bucket_diff.add(hit_rank, gt.expect_refusal, predicted_refusal)


def _new_bucket(container: dict[str, "BucketStats"], key: str) -> "BucketStats":
    """defaultdict 工厂的等价物；正常路径上 overrride 写回容器，避免吞 defaultdict 默认值。"""
    bucket = BucketStats()
    container[key] = bucket
    return bucket


def render_markdown(report: Report) -> str:
    """把 Report 渲染成 Markdown 表格（一行命令输出报告所要求）。"""
    lines: list[str] = []
    lines.append("# 自研 RAG 离线评测报告")
    lines.append("")
    lines.append("## 版本追溯")
    if report.version_meta:
        for k, v in sorted(report.version_meta.items()):
            lines.append(f"- **{k}**: `{v}`")
    else:
        lines.append("- _未提供版本元数据（建议用 `--meta-key value` 注入）_")
    lines.append("")

    lines.append("## 总体指标")
    lines.append("")
    lines.append(f"- 题目数: {report.overall.total}")
    lines.append(f"- 可回答题数（Recall/MRR 分母）: {report.overall.answerable_total}")
    lines.append(f"- 期望拒答题数: {report.overall.expected_refusal_total}")
    lines.append(f"- Recall@1: {report.overall.recall_at(1):.3f}")
    lines.append(f"- Recall@5: {report.overall.recall_at(5):.3f}")
    lines.append(f"- Recall@10: {report.overall.recall_at(10):.3f}")
    lines.append(f"- MRR: {report.overall.mrr():.3f}")
    lines.append(f"- 拒答精确率: {report.overall.refusal_precision():.3f}")
    lines.append(f"- 拒答召回率: {report.overall.refusal_recall():.3f}")
    lines.append(f"- 拒答 F1: {report.overall.refusal_f1():.3f}")
    lines.append("")

    if report.by_category:
        lines.append("## 按 category 分桶")
        lines.append("")
        lines.append("| category | N | 可回答 N | 拒答 N | Recall@1 | Recall@5 | MRR | 拒答 F1 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for cat, b in sorted(report.by_category.items()):
            lines.append(
                f"| {cat} | {b.total} | {b.answerable_total} | {b.expected_refusal_total} | {b.recall_at(1):.3f} | {b.recall_at(5):.3f} | {b.mrr():.3f} | {b.refusal_f1():.3f} |"
            )
        lines.append("")

    if report.by_difficulty:
        lines.append("## 按 difficulty 分桶")
        lines.append("")
        lines.append("| difficulty | N | 可回答 N | 拒答 N | Recall@1 | Recall@5 | MRR | 拒答 F1 |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for d, b in sorted(report.by_difficulty.items()):
            lines.append(
                f"| {d} | {b.total} | {b.answerable_total} | {b.expected_refusal_total} | {b.recall_at(1):.3f} | {b.recall_at(5):.3f} | {b.mrr():.3f} | {b.refusal_f1():.3f} |"
            )
        lines.append("")

    if report.missing_predictions:
        lines.append("## 缺预测的题目 ID")
        lines.append("")
        lines.append(", ".join(report.missing_predictions[:50]))
        lines.append("")
    return "\n".join(lines)


def write_json(report: Report, path: Path) -> None:
    payload = {
        "version_meta": report.version_meta,
        "overall": {
            "total": report.overall.total,
            "answerable_total": report.overall.answerable_total,
            "expected_refusal_total": report.overall.expected_refusal_total,
            "recall_at_1": report.overall.recall_at(1),
            "recall_at_5": report.overall.recall_at(5),
            "recall_at_10": report.overall.recall_at(10),
            "mrr": report.overall.mrr(),
            "refusal_precision": report.overall.refusal_precision(),
            "refusal_recall": report.overall.refusal_recall(),
            "refusal_f1": report.overall.refusal_f1(),
        },
        "by_category": {
            cat: {
                "total": b.total,
                "answerable_total": b.answerable_total,
                "expected_refusal_total": b.expected_refusal_total,
                "recall_at_5": b.recall_at(5),
                "mrr": b.mrr(),
                "refusal_f1": b.refusal_f1(),
            }
            for cat, b in report.by_category.items()
        },
        "by_difficulty": {
            d: {
                "total": b.total,
                "answerable_total": b.answerable_total,
                "expected_refusal_total": b.expected_refusal_total,
                "recall_at_5": b.recall_at(5),
                "mrr": b.mrr(),
                "refusal_f1": b.refusal_f1(),
            }
            for d, b in report.by_difficulty.items()
        },
        "missing_predictions": report.missing_predictions,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
