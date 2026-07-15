# 候选池大小（candidateLimit）调优实验报告

## 背景

精排（Rerank）用 Cross-Encoder 对 BM25+向量 RRF 融合后的候选集逐对打分，是检索链路里最慢的一环。
"减少候选数量"是三招提速里最直接的一招——候选数直接决定 Rerank 的推理次数（一次批量调用里
`documents` 数组的长度）。本实验用真实 `eval-set-v2`（150 题人工标注评估集）实测 `RetrievalOptions.
candidateLimit`（BM25/向量两路各自的召回条数 N，默认 50）从 50 降到 10 时，Recall@k/MRR/拒答质量
损失多少，换回多少延迟。

在此之前 `candidateLimit=50` 只是工程默认值，没有用评估集验证过是否是合适的取值。

## 方法

- 复用生产真实检索链路：`ElasticsearchHybridCandidateSource` + `HybridRetriever`（真实 BM25 + kNN + RRF
  + Rerank），模型用真实 SiliconFlow 云端 API（`BAAI/bge-m3` embedding、`BAAI/bge-reranker-v2-m3` rerank），
  不是 mock。
- 语料复用已有评测索引 `rag_chunks_eval_v3`（885 个 V3 真实切块，本科毕设语料），四组实验共用同一份索引，
  只改 `candidateLimit`，避免重复 embedding 入库的时间和调用成本。
- 对同一份 150 题评估集分别跑 `candidateLimit ∈ {10, 20, 30, 50}`，每题记录端到端检索延迟（含 query
  embedding 调用 + BM25/kNN 查询 + Rerank 调用，纯 wall-clock，不含生成模型）。
- 工具改动：`eval/scripts/EvalRetrievalRunner.java` 新增 `candidateLimit`/`skipIndex` 参数与逐题延迟
  记录（`<output>.latency.json`），跑批脚本见 `eval/scripts/run-candidate-limit-sweep.sh`。
- **重要限制**：每个 N 只跑了一遍（不是重复多次取平均），延迟数据来自单次真实网络调用，容易被
  SiliconFlow API 侧的偶发抖动干扰（下表 N=30 的 mean/p95 出现异常尖峰就是证据，并非 N 越大延迟
  必然越高）。因此**延迟结论以 median 为准，mean/p95 仅供参考**，不构成严格的性能基准。

## 结果

| candidateLimit | Recall@1 | Recall@5 | Recall@10 | MRR | 拒答F1 | 延迟 median | 延迟 mean | 延迟 p95 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 0.792 | 0.848 | 0.872 | 0.819 | 0.545 | 2528ms | 2714ms | 3573ms |
| 20 | 0.816 | 0.880 | 0.888 | 0.839 | 0.537 | 2724ms | 2845ms | 4211ms |
| 30 | 0.800 | 0.880 | 0.888 | 0.829 | 0.550 | 2777ms | 4161ms* | 13173ms* |
| **50（当前默认）** | **0.816** | **0.904** | **0.912** | **0.849** | **0.564** | 2954ms | 3770ms* | 5720ms* |

\* N=30/50 的 mean/p95 被个别慢请求（18~39 秒的 API 响应尖峰）拉高，不是 N 本身导致，见上文限制说明。

原始数据：`eval/reports/candlimit{10,20,30,50}-20260715.json`、
`eval/predictions/predicted-v2-candlimit{10,20,30,50}-20260715.jsonl(.latency.json)`。

## 结论

1. **N 从 50 降到 10，Recall@5 掉 5.6 个百分点（0.904→0.848），Recall@10 掉 4 个百分点，MRR 掉 3 个百分点，
   拒答 F1 也小幅下降**——候选池太小时，正确 chunk 有更高概率没被 RRF 融合进候选集，Rerank 排序再准也救不回来，
   这正好印证"召回率是天花板"这条铁律。
2. **换回的延迟收益按 median 算只有约 430ms（2954ms→2528ms，降 15%）**，且这 2.5~3 秒的大头是网络往返
   （query embedding + rerank 两次跨公网调 SiliconFlow API），不是本地计算，N 对总延迟的边际影响本来就有限。
3. **N=20/30 是 N=10 和 N=50 之间的过渡点**：比 N=50 掉 2~2.4 个百分点 Recall@5，比 N=10 好不少，延迟介于
   两者之间但被网络噪声干扰、难以下结论。
4. **在当前语料规模（885 chunks）和当前延迟预算下，candidateLimit=50 这个默认值没有问题，不建议下调**——
   本实验测的是"降低 N 能不能省出有意义的延迟"，答案是"能省一点，但要用几个百分点的检索质量换，
   不划算"。这算是把工程默认值第一次用评估集验证了一遍，结论是"保持现状"。
5. 如果以后语料规模长到几万~几十万 chunk、Rerank 真正成为端到端延迟的瓶颈（现在 median 2.5~3 秒里
   Rerank 只占一部分，AnswerGenerator 流式生成还没算进来），再回来重新用这套脚本测一遍——那时候候选池
   大小和延迟的关系可能不一样，需要重新用评估集验证，不能凭这次的结论直接套用。

## 复现方法

```bash
export JAVA_HOME=/Library/Java/JavaVirtualMachines/zulu-17.jdk/Contents/Home
export PATH="${JAVA_HOME}/bin:${PATH}"
cd backend && mvn -q dependency:build-classpath -Dmdep.outputFile=/tmp/rag-cp.txt && cd ..
javac -cp "$(cat /tmp/rag-cp.txt):backend/target/classes" -d eval/scripts eval/scripts/EvalRetrievalRunner.java
bash eval/scripts/run-candidate-limit-sweep.sh
```
