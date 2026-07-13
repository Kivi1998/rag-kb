#!/usr/bin/env python3
"""对解析网关执行可复现的文档吞吐验收；只依赖 Python 标准库。"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:18081/v1/parse")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--total", type=int, default=5000)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def main() -> int:
    args = parse_args()
    if args.total < 1 or args.concurrency < 1:
        raise SystemExit("total 和 concurrency 必须大于 0")
    payload = args.file.read_bytes()
    filename = args.file.name

    def request_once(index: int) -> tuple[bool, float, str]:
        started = time.perf_counter()
        document_id = uuid.uuid5(uuid.NAMESPACE_URL, f"rag-load-test-{index}")
        request = urllib.request.Request(args.endpoint, data=payload, method="POST", headers={
            "Authorization": f"Bearer {args.api_key}",
            "Content-Type": "application/octet-stream",
            "X-Document-Id": str(document_id),
            "X-Document-Filename": filename,
            "X-Source-Path": f"acceptance/load/{index}/{filename}",
        })
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                result = json.loads(response.read())
                if response.status != 200 or not result.get("sections"):
                    return False, time.perf_counter() - started, "响应缺少有效 sections"
                return True, time.perf_counter() - started, ""
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return False, time.perf_counter() - started, str(exc)

    wall_started = time.perf_counter()
    latencies: list[float] = []
    errors: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(request_once, index) for index in range(args.total)]
        for future in as_completed(futures):
            success, latency, error = future.result()
            latencies.append(latency)
            if not success:
                errors[error] = errors.get(error, 0) + 1

    elapsed = time.perf_counter() - wall_started
    failed = sum(errors.values())
    report = {
        "file": str(args.file),
        "fileBytes": len(payload),
        "total": args.total,
        "success": args.total - failed,
        "failed": failed,
        "successRate": round((args.total - failed) / args.total, 6),
        "concurrency": args.concurrency,
        "elapsedSeconds": round(elapsed, 3),
        "requestsPerSecond": round(args.total / elapsed, 3),
        "latencyMs": {
            "mean": round(statistics.fmean(latencies) * 1000, 3),
            "p50": round(percentile(latencies, 0.50) * 1000, 3),
            "p95": round(percentile(latencies, 0.95) * 1000, 3),
            "p99": round(percentile(latencies, 0.99) * 1000, 3),
            "max": round(max(latencies, default=0) * 1000, 3),
        },
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
