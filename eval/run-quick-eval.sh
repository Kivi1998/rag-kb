#!/bin/bash
# 快速评估启动脚本（使用占位数据验证 pipeline）

set -e
cd "$(git rev-parse --show-toplevel)"

echo "════════════════════════════════════════════════════════════"
echo "V3 结构感知切分 — 快速评估启动"
echo "════════════════════════════════════════════════════════════"
echo ""

# Step 1: 生成占位 prediction
echo "📋 Step 1: 生成占位预测数据..."
python3 eval/scripts/generate-predictions.py \
  --mode mock \
  --eval-file eval/datasets/eval-set-2026Q3.jsonl \
  --output eval/predictions/predicted-v3-quick.jsonl
echo ""

# Step 2: 验证文件
echo "✅ Step 2: 验证评估数据完整性..."
EVAL_COUNT=$(wc -l < eval/datasets/eval-set-2026Q3.jsonl)
PRED_COUNT=$(wc -l < eval/predictions/predicted-v3-quick.jsonl)
echo "  评估集: $EVAL_COUNT 题"
echo "  预测集: $PRED_COUNT 条"
[ "$EVAL_COUNT" = "$PRED_COUNT" ] || (echo "❌ 题数不匹配"; exit 1)
echo ""

# Step 3: 跑评估
echo "🚀 Step 3: 运行评估框架..."
python3 -m eval.runner \
  --ground-truth eval/datasets/eval-set-2026Q3.jsonl \
  --predicted eval/predictions/predicted-v3-quick.jsonl \
  --meta embedding=bge-m3@1.0.5 \
  --meta chunker=technical-chunker@v3 \
  --meta retriever=hybrid-bm25-vector@v1 \
  --output-md eval/reports/eval-v3-quick-20240714.md \
  --output-json eval/reports/eval-v3-quick-20240714.json

EXIT_CODE=$?

echo ""
echo "════════════════════════════════════════════════════════════"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 评估成功完成"
    echo "════════════════════════════════════════════════════════════"
    echo ""
    echo "📄 报告位置："
    echo "  - Markdown: eval/reports/eval-v3-quick-20240714.md"
    echo "  - JSON:     eval/reports/eval-v3-quick-20240714.json"
    echo ""
    echo "📊 关键指标："
    head -80 eval/reports/eval-v3-quick-20240714.md | tail -50
else
    echo "❌ 评估失败 (exit code: $EXIT_CODE)"
    echo "════════════════════════════════════════════════════════════"
fi

exit $EXIT_CODE
