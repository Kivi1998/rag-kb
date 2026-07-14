#!/usr/bin/env python3
"""
生成预测数据 (prediction.jsonl)

两种模式：
1. --mock: 使用 ground_truth 作为占位（快速验证 pipeline）
2. --api: 调用后端 HTTP API 获取真实检索结果
"""

import json
import sys
import argparse
from pathlib import Path
from typing import List, Dict

def generate_mock_predictions(eval_file: Path, output_file: Path) -> int:
    """使用 ground_truth 作为占位预测（用于快速验证 pipeline）"""
    print(f"  📋 读取评估集: {eval_file}")

    questions = []
    with open(eval_file) as f:
        for line in f:
            questions.append(json.loads(line))

    print(f"  ✅ 已加载 {len(questions)} 个问题")

    predictions = []
    for q in questions:
        # 关键：占位数据 = ground_truth
        # 这样 Recall@5 会是 100%，但能验证 eval 框架是否工作
        prediction = {
            "id": q["id"],
            "predicted_chunk_ids": q["ground_truth_chunk_ids"],
            "predicted_refusal": q.get("expect_refusal", False),
            "reranked": False
        }
        predictions.append(prediction)

    # 写出
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        for p in predictions:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"  ✅ 已生成 {output_file} ({len(predictions)} 条预测)")
    print(f"  ⚠️  这是占位数据，Recall@5 会是 100%（用于验证 pipeline）")
    return 0


def generate_api_predictions(eval_file: Path, output_file: Path, api_url: str = "http://localhost:8080") -> int:
    """调用后端 API 获取真实检索结果"""
    try:
        import requests
    except ImportError:
        print("❌ 需要 requests 库: pip install requests")
        return 1

    print(f"  📋 读取评估集: {eval_file}")
    questions = []
    with open(eval_file) as f:
        for line in f:
            questions.append(json.loads(line))

    print(f"  ✅ 已加载 {len(questions)} 个问题")
    print(f"  🔗 调用后端 API: {api_url}")
    print()

    predictions = []
    success_count = 0
    fail_count = 0

    for i, q in enumerate(questions, 1):
        try:
            # 调用后端检索 API
            # 注意：实际 endpoint 可能需要根据后端实现调整
            resp = requests.post(
                f"{api_url}/api/v1/query",
                json={
                    "query": q["question"],
                    "kb_id": q.get("kb_id", "kb-bdzdc"),
                    "top_k": 10
                },
                timeout=10
            )

            if resp.status_code == 200:
                data = resp.json()
                chunks = data.get("chunks", [])

                # 提取 chunk_ids
                chunk_ids = [c.get("id") for c in chunks if "id" in c]

                prediction = {
                    "id": q["id"],
                    "predicted_chunk_ids": chunk_ids,
                    "predicted_refusal": len(chunk_ids) == 0,
                    "reranked": data.get("reranked", False)
                }
                predictions.append(prediction)
                success_count += 1

                print(f"  [{i}/{len(questions)}] ✅ {q['id']}: 检索到 {len(chunk_ids)} 个 chunks")
            else:
                print(f"  [{i}/{len(questions)}] ⚠️  {q['id']}: HTTP {resp.status_code}")
                fail_count += 1
                # 使用空结果作为占位
                predictions.append({
                    "id": q["id"],
                    "predicted_chunk_ids": [],
                    "predicted_refusal": True,
                    "reranked": False
                })

        except requests.exceptions.ConnectionError:
            print(f"  ❌ 后端 API 连接失败: {api_url}")
            print(f"     确保后端已启动: mvn spring-boot:run -Dspring-boot.run.arguments='--server.port=8080'")
            return 1
        except Exception as e:
            print(f"  [{i}/{len(questions)}] ❌ {q['id']}: {e}")
            fail_count += 1

    # 写出
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        for p in predictions:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print()
    print(f"  ✅ 已生成 {output_file}")
    print(f"  统计: {success_count} 成功, {fail_count} 失败")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成预测数据")
    parser.add_argument(
        "--mode",
        choices=["mock", "api"],
        default="mock",
        help="生成模式（mock=占位 / api=真实检索）"
    )
    parser.add_argument(
        "--eval-file",
        default="eval/datasets/eval-set-2026Q3.jsonl",
        help="评估集文件路径"
    )
    parser.add_argument(
        "--output",
        default="eval/predictions/predicted-v3-20240714.jsonl",
        help="输出文件路径"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8080",
        help="后端 API 基础 URL"
    )

    args = parser.parse_args()

    eval_file = Path(args.eval_file)
    output_file = Path(args.output)

    if not eval_file.exists():
        print(f"❌ 评估集不存在: {eval_file}")
        sys.exit(1)

    print("════════════════════════════════════════════════════════════")
    print(f"生成预测数据 (mode: {args.mode})")
    print("════════════════════════════════════════════════════════════")
    print()

    if args.mode == "mock":
        exit_code = generate_mock_predictions(eval_file, output_file)
    else:  # api
        exit_code = generate_api_predictions(eval_file, output_file, args.api_url)

    print()
    sys.exit(exit_code)
