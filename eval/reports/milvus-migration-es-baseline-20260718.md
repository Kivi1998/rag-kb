# Milvus 迁移前 Elasticsearch 检索基线（2026-07-18）

本报告冻结 `migrate-vector-retrieval-to-milvus` 变更实施前的 ES BM25+kNN 基线，供影子读、灰度切流和回滚验收比较。不得把小样本人工观测延迟写成生产压测结论。

## 质量基线

数据集：`eval/datasets/eval-set-v2.jsonl`，150 题（125 可回答、25 应拒答），26 篇真实文档、885 个 V3 Chunk。检索链为 BGE-M3 + Elasticsearch BM25/kNN + RRF + BGE Reranker，并应用已校准拒答阈值。

| 指标 | 迁移前基线 |
|---|---:|
| Recall@1 | 0.816 |
| Recall@5 | 0.904 |
| Recall@10 | 0.912 |
| MRR | 0.849 |
| 拒答 F1 | 0.564 |

权威原始报告：`eval/reports/eval-v2-calibrated-20260714.md`。

## 延迟参考

`docs/自研RAG核心重构架构设计.md` 记录的小样本人工观测为：检索阶段 P95=6211ms、端到端 P95=10809ms、P99=11723ms；观测峰值仅 2 请求/分钟。这些值只用于迁移前问题定位，**不是目标并发下的性能验收基线**。正式 ES/Milvus P50/P95/P99、吞吐和资源成本必须由任务 8.4 在相同负载下重新测量。

## 复现命令

产品检索基线由 `eval/scripts/EvalRetrievalRunner.java` 生成，完整环境变量和命令见该文件头部以及 `docs/评估指南.md`。生成预测后执行：

```bash
python3 -m eval.runner \
  --ground-truth eval/datasets/eval-set-v2.jsonl \
  --predicted eval/predictions/eval-v2-calibrated.jsonl \
  --meta retriever=elasticsearch-bm25-knn-rrf \
  --output-md eval/reports/eval-v2-calibrated-recheck.md
```

迁移前相关单元回归：

```bash
cd backend
export RAG_TASK_JAVA_HOME=$(/usr/libexec/java_home -v 17)
JAVA_HOME="$RAG_TASK_JAVA_HOME" mvn -q \
  -Dtest=ElasticsearchHybridCandidateSourceTest,ElasticsearchChunkIndexTest,HybridRetrieverTest test
```

2026-07-18 执行结果：通过。
