# 自研 RAG 离线评测报告

## 版本追溯
- **chunker**: `technical-chunker@v3`
- **corpus**: `部-测量标志@532chunks`
- **embedding**: `siliconflow/BAAI-bge-m3@1024d`
- **rerank**: `siliconflow/BAAI-bge-reranker-v2-m3`
- **retriever**: `hybrid-bm25+kNN+rrf@v1`

## 总体指标

- 题目数: 61
- 可回答题数（Recall/MRR 分母）: 53
- 期望拒答题数: 8
- Recall@1: 0.075
- Recall@5: 0.264
- Recall@10: 0.415
- MRR: 0.165
- 拒答精确率: 0.000
- 拒答召回率: 0.000
- 拒答 F1: 0.000

## 按 category 分桶

| category | N | 可回答 N | 拒答 N | Recall@1 | Recall@5 | MRR | 拒答 F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| api | 2 | 2 | 0 | 0.000 | 0.000 | 0.071 | 0.000 |
| class-name | 3 | 3 | 0 | 0.000 | 0.333 | 0.067 | 0.000 |
| config | 2 | 2 | 0 | 0.000 | 0.000 | 0.000 | 0.000 |
| data-structure | 9 | 9 | 0 | 0.222 | 0.667 | 0.426 | 0.000 |
| module | 37 | 37 | 0 | 0.054 | 0.189 | 0.124 | 0.000 |
| out-of-scope | 8 | 0 | 8 | 0.000 | 0.000 | 0.000 | 0.000 |

## 按 difficulty 分桶

| difficulty | N | 可回答 N | 拒答 N | Recall@1 | Recall@5 | MRR | 拒答 F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| hard | 58 | 50 | 8 | 0.080 | 0.280 | 0.175 | 0.000 |
| medium | 3 | 3 | 0 | 0.000 | 0.000 | 0.000 | 0.000 |

---

## 与 BM25-only 基线对比（同评估集、同 V3 切块，2026-07-14）

| 指标 | BM25-only 基线 | 混合检索（+bge-m3 kNN +bge-reranker-v2-m3） | 变化 |
|---|---:|---:|---|
| Recall@1 | 0.038 | 0.075 | ×2.0 |
| Recall@5 | 0.094 | **0.264** | **×2.8** |
| Recall@10 | 0.189 | **0.415** | ×2.2 |
| MRR | 0.073 | 0.165 | ×2.3 |
| 拒答 F1 | 0.000 | 0.000 | 不变 |

**解读**：

1. **向量召回补上了 BM25 的语义短板**：提升最大的是 data-structure 类
   （Recall@5 0.000 → 0.667）；module 模板题从 0.135 → 0.189。方向与预期一致
   （模板题/语义题依赖向量通路）。
2. **绝对值仍不高的主因未变**：评估集里 46/53 是"这一节讲什么"式机器模板题 +
   ground truth 漏标相邻 chunk 的假阴性（见 BM25 基线报告的诊断）。**在按
   `eval/datasets/标注指南.md` 重建评估集之前，绝对值仅作趋势参考。**
3. **拒答 F1 仍为 0**：混合召回让每题都能凑出候选，`MIN_RRF_SCORE=0.01` 阈值
   依旧无区分度——阈值校准仍在待办。
4. 环境：embedding/rerank 已从内网 Xinference 切换为硅基流动
   （SiliconFlow）在线 API；embedding 模型因 `bge-large-zh-v1.5` 在硅基流动
   对 >512 token 输入直接报错（code 20015，实测），改用 `BAAI/bge-m3`
   （8K 上下文，同 1024 维，实测长输入通过）。
