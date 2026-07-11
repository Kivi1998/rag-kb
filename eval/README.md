# 自研 RAG 离线评测（eval/）— T301

> 一条命令跑完整离线评测；JSONL 评测格式；至少 50 题脱敏技术问题。
> 适用于 T201/T202 落地后做检索 / 拒答 / 引用质量回归。

## 目录

```
eval/
├── __init__.py
├── __main__.py               ← python3 -m eval ... 入口
├── metrics.py                ← Recall@k / MRR / 拒答指标（移植 rag3 + 扩展）
├── runner.py                 ← CLI 入口（一条命令出报告）
├── format.md                 ← JSONL Schema 文档
├── README.md                 ← 本文件
├── LICENSE_THIRD_PARTY       ← rag3 (MIT) 移植声明
├── datasets/
│   ├── tech-doc-qa-sample.jsonl     ← 55 道脱敏技术题 + 期望拒答
│   └── predicted-sample.jsonl       ← 演示用 prediction（模拟高分检索 + 全部拒答命中）
└── tests/
    └── test_metrics.py
```

## 用法

### 1. 跑样例（无需任何外部依赖）

```bash
cd rag-kb
python3 -m eval.runner \
  --ground-truth eval/datasets/tech-doc-qa-sample.jsonl \
  --predicted    eval/datasets/predicted-sample.jsonl \
  --meta embedding=bge-m3@1.0.5 \
  --meta chunker=technical-chunker@v1 \
  --meta retriever=rrf-bm25+kNN@v1 \
  --meta rerank=cross-encoder@1
```

会输出 Markdown 报告到 stdout，包含版本追溯 + 总体指标 + 按 category / difficulty 分桶。
自动退出码：

| 退出码 | 含义 |
|---|---|
| `0` | 全部完成且 Recall@5 ≥ 0.5 |
| `1` | 完成但 Recall@5 < 0.5（评估失败） |
| `2` | 文件缺失 / schema 错误 |
| `3` | 存在缺预测（id 没在 predicted 里） |

### 2. 落盘 Markdown + JSON

```bash
python3 -m eval.runner \
  --ground-truth eval/datasets/tech-doc-qa-sample.jsonl \
  --predicted    eval/predicted/$(date +%Y%m%d).jsonl \
  --output-md    reports/eval-$(date +%Y%m%d).md \
  --output-json  reports/eval-$(date +%Y%m%d).json
```

### 3. 准备生产 prediction

T201/T202 落地后，后端评测入口（`/api/v1/eval/run`，由 T306 安全复核）应输出本 schema 的 JSONL。
本地离线测试可手工构造或基于 fixture 生成。

## 指标说明

### 总指标

- **Recall@k**：仅在可回答题中，答案 chunk 出现在前 k 个里的题目占比
- **MRR**：仅在可回答题中计算答案 chunk 首次命中排名的倒数平均
- **拒答精确率 / 召回率 / F1**：四象限 TP/FP/FN/TN
- **缺预测**：predicted 文件缺 id 会使命令退出码为 `3`

### 分桶

- **category**：api / error-code / config / class-name / module / data-structure / troubleshoot / out-of-scope
- **difficulty**：easy / medium / hard

可在 `metrics.py:BucketStats` 上扩展（例如按 `kb_id` 分桶），schema 不变。

## 版本追溯

`--meta key=value` 可多次指定，会原样落到报告"版本追溯"段。推荐固定字段：

| 字段 | 含义 |
|---|---|
| `embedding` | embedding 模型版本（含分词） |
| `chunker` | 切块器版本（含 overlap / 语言策略） |
| `retriever` | 检索器版本（BM25 / kNN / RRF 权重） |
| `rerank` | rerank 模型版本（"none" 表示未启用） |
| `model` | 生成模型版本（含 prompt 模板 hash） |

详见 `format.md`。

## 测试

```bash
python3 -m pytest eval/tests/test_metrics.py -q   # 推荐
# 零依赖退路
python3 eval/tests/test_metrics.py
```

## 来源声明

- 移植自 `rag-from-zero`（MIT，参见 `LICENSE_THIRD_PARTY`）
- 任何后续修改必须保留该许可证声明
- **不要**把 rag1 / rag2 的业务逻辑塞进本目录——eval 是独立测量工具，与产品代码解耦
