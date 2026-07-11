#!/usr/bin/env python3
"""自研 RAG 离线评测 CLI 入口 —— v0（T301 一条命令输出报告）。

用法：

    # 最简形态：ground truth 必填；prediction 可选（缺失视为未召回）
    python3 -m eval.runner \\
        --ground-truth eval/datasets/tech-doc-qa-sample.jsonl \\
        --predicted eval/datasets/predicted-sample.jsonl \\
        --output-md reports/eval-2026-07-10.md \\
        --output-json reports/eval-2026-07-10.json \\
        --meta embedding=bge-m3@1.0.5 \\
        --meta chunker=technical-chunker@v1 \\
        --meta retriever=rrf-bm25+kNN@v1 \\
        --meta rerank=cross-encoder@1

依赖：Python 3.10+，仅使用标准库。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import metrics
from .metrics import GroundTruth, Prediction, render_markdown, write_json


def _read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            yield line


def _parse_meta(items: list[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            print(f"⚠️  --meta 必须是 key=value 形式，跳过: {item}", file=sys.stderr)
            continue
        k, v = item.split("=", 1)
        meta[k.strip()] = v.strip()
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="自研 RAG 离线评测（一条命令出报告）")
    parser.add_argument("--ground-truth", required=True, type=Path, help="标准答案 JSONL")
    parser.add_argument("--predicted", type=Path, help="系统预测 JSONL；省略时视为全部未召回")
    parser.add_argument("--output-md", type=Path, help="Markdown 报告输出路径")
    parser.add_argument("--output-json", type=Path, help="JSON 报告输出路径")
    parser.add_argument(
        "--meta",
        action="append",
        default=[],
        help="版本元数据 key=value，可重复（embedding / chunker / retriever / rerank / model 等）",
    )
    args = parser.parse_args(argv)

    if not args.ground_truth.exists():
        print(f"❌ ground-truth 文件不存在: {args.ground_truth}", file=sys.stderr)
        return 2

    try:
        gts = [GroundTruth.from_jsonl_line(line) for line in _read_jsonl(args.ground_truth)]
        if not gts:
            raise metrics.DatasetValidationError("ground-truth 解析为空")

        preds: list[Prediction] = []
        if args.predicted:
            if not args.predicted.exists():
                print(f"❌ predicted 文件不存在: {args.predicted}", file=sys.stderr)
                return 2
            preds = [Prediction.from_jsonl_line(line) for line in _read_jsonl(args.predicted)]
        metrics.validate_inputs(gts, preds)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"❌ 评测输入不合法: {exc}", file=sys.stderr)
        return 2

    meta = _parse_meta(args.meta)
    report = metrics.evaluate(gts, preds, meta=meta)

    # 默认输出：stdout + 落盘（按需）
    md = render_markdown(report)
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(md, encoding="utf-8")
    else:
        print(md)
    if args.output_json:
        write_json(report, args.output_json)

    # 退出码：Recall@5 太低 → 1；任何缺预测 → 3；其它失败 → 2
    if report.overall.total == 0:
        return 2
    if report.missing_predictions:
        return 3
    if report.overall.recall_at(5) < 0.5:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
