#!/usr/bin/env python3
"""分析 rerank/RRF 分数在 expect_refusal=true/false 两组的分布，选阈值。

用法：
  python3 eval/scripts/analyze_refusal_threshold.py \
    eval/datasets/eval-set-v2.jsonl eval/predictions/predicted-v2-diag-20260714.jsonl
"""
import json
import sys

gt_file, pred_file = sys.argv[1], sys.argv[2]
gt = {json.loads(l)["id"]: json.loads(l) for l in open(gt_file)}
pred = {json.loads(l)["id"]: json.loads(l) for l in open(pred_file)}

refuse_scores, keep_scores = [], []
missing_score = 0
for qid, q in gt.items():
    p = pred.get(qid)
    if not p or p.get("predicted_refusal"):
        continue  # 已被 RRF 前置门拒答/无预测，跳过（当前应为 0 或极少数）
    score = p.get("_top_rerank_score")
    if score is None:
        missing_score += 1
        continue
    (refuse_scores if q["expect_refusal"] else keep_scores).append((qid, score))

refuse_scores.sort(key=lambda x: x[1])
keep_scores.sort(key=lambda x: x[1])

print(f"expect_refusal=true  (应拒答): {len(refuse_scores)} 题，rerank 分数缺失 {missing_score}")
for qid, s in refuse_scores:
    print(f"  {qid}  score={s:.4f}")
print()
print(f"expect_refusal=false (应回答): {len(keep_scores)} 题")
print(f"  min={keep_scores[0][1]:.4f} ({keep_scores[0][0]})  "
      f"p10={keep_scores[len(keep_scores)//10][1]:.4f}  "
      f"median={keep_scores[len(keep_scores)//2][1]:.4f}  max={keep_scores[-1][1]:.4f}")

print()
print("── 候选阈值扫描（threshold → 拒答精确率/召回率/F1，含误伤应答题数）──")
all_scores = sorted(set(round(s, 3) for _, s in refuse_scores + keep_scores))
best = None
for t in [x / 1000 for x in range(0, 1001, 5)]:
    tp = sum(1 for _, s in refuse_scores if s < t)
    fn = len(refuse_scores) - tp
    fp = sum(1 for _, s in keep_scores if s < t)  # 误伤：本该回答却被拒
    tn = len(keep_scores) - fp
    if tp == 0:
        continue
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    if best is None or f1 > best[1]:
        best = (t, f1, precision, recall, fp, tp)

if best:
    t, f1, p, r, fp, tp = best
    print(f"最佳阈值(按 F1) t={t:.3f}: 拒答F1={f1:.3f} 精确率={p:.3f} 召回率={r:.3f} "
          f"（命中拒答 {tp}/{len(refuse_scores)}，误伤应答题 {fp}/{len(keep_scores)}）")

# 寻找 0 误伤的最大阈值（稳健优先，不伤应答题）
zero_fp_max_t, zero_fp_tp = 0.0, 0
for t in [x / 1000 for x in range(0, 1001, 5)]:
    fp = sum(1 for _, s in keep_scores if s < t)
    if fp == 0:
        tp = sum(1 for _, s in refuse_scores if s < t)
        if tp >= zero_fp_tp:
            zero_fp_max_t, zero_fp_tp = t, tp
print(f"零误伤阈值: t={zero_fp_max_t:.3f} → 命中拒答 {zero_fp_tp}/{len(refuse_scores)}，误伤应答题 0/{len(keep_scores)}")
