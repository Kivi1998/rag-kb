#!/usr/bin/env python3
"""对 nli-self-check-calibration-set.jsonl 跑真实 nli-gateway，扫描 entailment_prob 阈值选 F1 最优点。

用法：
  python3 eval/scripts/analyze_nli_threshold.py \
    eval/datasets/nli-self-check-calibration-set.jsonl \
    http://127.0.0.1:8082/nli \
    eval/predictions/nli-calibration-<日期>.jsonl
"""
import json
import sys
import urllib.request

dataset_file = sys.argv[1]
nli_endpoint = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8082/nli"
output_file = sys.argv[3] if len(sys.argv) > 3 else None

rows = [json.loads(l) for l in open(dataset_file) if l.strip()]

predictions = []
for row in rows:
    body = json.dumps({"premise": row["premise"], "hypothesis": row["hypothesis"]}).encode("utf-8")
    req = urllib.request.Request(nli_endpoint, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        verdict = json.loads(resp.read())
    predictions.append({**row, **verdict})
    print(f"[{row['id']}] {row['category']} expect_flagged={row['expect_flagged']} "
          f"entailment_prob={verdict['entailment_prob']:.4f} label={verdict['label']}")

if output_file:
    with open(output_file, "w") as f:
        for p in predictions:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"\n[done] 预测结果写入 {output_file}")

# expect_flagged=true 代表"不该被 entailment 支撑"（unrelated/partial/misattributed），
# expect_flagged=false 代表"应该被支撑"（accurate）。
flagged_scores = [(p["id"], p["entailment_prob"]) for p in predictions if p["expect_flagged"]]
supported_scores = [(p["id"], p["entailment_prob"]) for p in predictions if not p["expect_flagged"]]

flagged_scores.sort(key=lambda x: x[1])
supported_scores.sort(key=lambda x: x[1])

print()
print(f"expect_flagged=true（应判定不支撑）: {len(flagged_scores)} 条")
for qid, s in flagged_scores:
    print(f"  {qid}  entailment_prob={s:.4f}")
print()
print(f"expect_flagged=false（应判定支撑）: {len(supported_scores)} 条")
for qid, s in supported_scores:
    print(f"  {qid}  entailment_prob={s:.4f}")

print()
print("── 候选阈值扫描（entailment_prob < t 判定为不支撑；扫描 t，选 F1 最优）──")
best = None
for i in range(0, 1001, 5):
    t = i / 1000
    tp = sum(1 for _, s in flagged_scores if s < t)  # 命中：真的不支撑，也判定为不支撑
    fn = len(flagged_scores) - tp
    fp = sum(1 for _, s in supported_scores if s < t)  # 误伤：真的支撑，却判定为不支撑
    if tp == 0:
        continue
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    if best is None or f1 > best[1]:
        best = (t, f1, precision, recall, fp, tp)

if best:
    t, f1, p, r, fp, tp = best
    print(f"最佳阈值(按 F1) t={t:.3f}: F1={f1:.3f} 精确率={p:.3f} 召回率={r:.3f} "
          f"（命中不支撑 {tp}/{len(flagged_scores)}，误伤真实支撑 {fp}/{len(supported_scores)}）")
else:
    print("未找到任何有效阈值（所有候选下 tp=0）")
