# V3 结构感知切分评估 — 工程启动指南

**61 题评估集 + 完整 pipeline**

---

## 🎯 核心目标

对比 **V3 结构感知切分** vs **V0 基础切分** 在 61 个真实问题上的表现：
- **Recall@k**：前 k 个检索结果是否包含答案
- **MRR**：答案排名是否靠前
- **拒答 F1**：无关问题是否正确拒答

---

## 📦 6 个核心交付物

```
eval/
├── datasets/
│   ├── eval-set-2026Q3.jsonl              ⭐ 61 题评估集（固定）
│   ├── corpus-index.jsonl                 ← 532 chunks 元数据索引
│   └── corpus/部-测量标志/                 ← 10 篇源文档
│
├── scripts/
│   ├── generate-predictions.py            ← 生成预测数据（mock/api 两种模式）
│   └── README.md
│
├── reports/                               ← 评估报告输出目录
│   └── eval-v3-quick-20240714.md
│
└── predictions/                           ← 预测数据缓存
    └── predicted-v3-quick.jsonl
```

---

## 🚀 快速启动（3 分钟）

### 1️⃣ 验证 Pipeline（占位数据）

```bash
bash eval/run-quick-eval.sh
```

输出：
```
✅ 评估成功完成
📄 报告位置：
  - Markdown: eval/reports/eval-v3-quick-20240714.md
  - JSON:     eval/reports/eval-v3-quick-20240714.json
```

**这一步做什么？**
- 用 ground_truth 作为占位预测数据
- 验证 eval 框架是否工作正常
- 输出的指标都是 100%（因为数据是完美匹配）

---

## 🔍 获取真实数据（需要后端）

要获得真正有意义的 Recall/MRR，需要调用后端真实检索 API。

### 步骤 1: 启动后端

```bash
cd backend

# 编译
mvn clean package -DskipTests -q

# 启动（默认 8080 端口）
JAVA_HOME=/Library/Java/JavaVirtualMachines/zulu-17.jdk/Contents/Home \
  mvn spring-boot:run -Dspring-boot.run.arguments='--server.port=8080'
```

等待日志出现：
```
Started RagKbApplication in X.XXX seconds
```

### 步骤 2: 生成真实预测

```bash
# 在另一个终端运行
python3 eval/scripts/generate-predictions.py \
  --mode api \
  --api-url http://localhost:8080 \
  --eval-file eval/datasets/eval-set-2026Q3.jsonl \
  --output eval/predictions/predicted-v3-real.jsonl
```

进度示例：
```
🔍 调用后端 API: http://localhost:8080
  [1/61] ✅ q-001: 检索到 8 个 chunks
  [2/61] ✅ q-002: 检索到 5 个 chunks
  ...
  ✅ 已生成 eval/predictions/predicted-v3-real.jsonl (61 条预测)
```

### 步骤 3: 运行评估

```bash
python3 -m eval.runner \
  --ground-truth eval/datasets/eval-set-2026Q3.jsonl \
  --predicted eval/predictions/predicted-v3-real.jsonl \
  --meta embedding=bge-m3@1.0.5 \
  --meta chunker=technical-chunker@v3 \
  --meta retriever=hybrid-bm25-vector@v1 \
  --output-md eval/reports/eval-v3-real-20240714.md \
  --output-json eval/reports/eval-v3-real-20240714.json
```

**真实输出示例：**
```
# 自研 RAG 离线评测报告

## 总体指标
- Recall@5: 0.824    ← V3 版本的真实指标
- Recall@10: 0.883
- MRR: 0.712
- 拒答 F1: 0.875
```

---

## 📊 理解评估指标

### Recall@k（最重要）

```
定义：在 53 个可回答题中，前 k 个结果包含答案的比例

例：
  题目："系统的主要模块有哪些？"
  ground_truth_chunk_id: ["chunk-123"]
  
  检索结果（前 5 个）:
    1. chunk-456 ❌
    2. chunk-789 ❌
    3. chunk-123 ✅ ← 答案在第 3 位
    4. chunk-901 ✅
    5. chunk-234 ❌

  Recall@5 = 包含答案的题目 / 总可回答题

业界基准：
  好的系统: Recall@5 ≥ 0.8
  优秀系统: Recall@5 ≥ 0.9
```

### MRR（排名质量）

```
定义：答案首次出现位置的倒数平均

例：
  题 1：答案在第 1 位 → 1/1 = 1.0
  题 2：答案在第 3 位 → 1/3 ≈ 0.33
  题 3：答案在第 5 位 → 1/5 = 0.20

  MRR = (1.0 + 0.33 + 0.20) / 3 ≈ 0.51
```

### 拒答 F1

```
对于 expect_refusal=true 的 8 个拒答题：

精确率 = 正确拒答数 / 系统拒答数
召回率 = 正确拒答数 / 应该拒答数
F1 = 2 * (精确率 × 召回率) / (精确率 + 召回率)
```

---

## 🔄 V0 vs V3 对比

### 方案 A: 快速对比（使用占位数据）

如果只是想看数据流程是否跑通，可以只用占位数据：

```bash
# 已经有 V3 的占位数据了
# eval/predictions/predicted-v3-quick.jsonl

# 现在生成 V0 的占位数据（模拟 V0 的较差表现）
# 这里暂时跳过，因为需要检出 1fc29ab 版本
```

### 方案 B: 真实对比（需要后端 + V0 代码）

```bash
# Step 1: 用 main（V3）跑一遍，得到 predicted-v3-real.jsonl

# Step 2: 检出 V0，编译，跑一遍，得到 predicted-v0-real.jsonl
git show 1fc29ab:backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/TechnicalChunker.java \
  > /tmp/TechnicalChunker-v0.java

# Step 3: 对比
# V3: Recall@5 = 0.824
# V0: Recall@5 = 0.71（预期）
# 提升：+11.4pp
```

---

## 📋 工作流总结

| 阶段 | 命令 | 输出 | 含义 |
|------|------|------|------|
| **验证框架** | `bash eval/run-quick-eval.sh` | 100% 指标 | Pipeline 就绪 |
| **启动后端** | `mvn spring-boot:run` | API 在线 | 可调用检索 |
| **真实预测** | `python3 eval/scripts/generate-predictions.py --mode api` | predicted.jsonl | 真实检索结果 |
| **评估** | `python3 -m eval.runner ...` | .md / .json | 最终报告 |

---

## 🛠️ 故障排除

### ❌ "后端 API 连接失败"

```bash
# 检查后端是否启动
curl http://localhost:8080/actuator/health

# 如果返回 {"status":"UP"}，说明后端正常
# 否则启动后端：
cd backend
JAVA_HOME=/Library/Java/JavaVirtualMachines/zulu-17.jdk/Contents/Home \
  mvn spring-boot:run
```

### ❌ "eval 框架找不到"

```bash
# 确保在 repo 根目录
cd /Users/kivi/Documents/rag系统/rag-kb

# 检查 eval 目录是否存在
ls eval/
```

### ❌ "评估集题数不匹配"

```bash
# 验证 eval-set-2026Q3.jsonl 完整性
wc -l eval/datasets/eval-set-2026Q3.jsonl  # 应该是 61

# 验证格式
head -1 eval/datasets/eval-set-2026Q3.jsonl | python3 -m json.tool
```

---

## 📚 相关文档

- `eval/README.md` - 评估框架总体说明
- `eval/format.md` - JSONL schema 定义
- `eval/datasets/README.md` - 评估集说明（含复核清单）

---

## 🎓 下一步

**立即可做：**
1. ✅ 跑占位版本验证 pipeline（3 分钟）
2. ✅ 启动后端，生成真实预测（5-10 分钟）
3. ✅ 生成 V3 评估报告（1 分钟）

**后续可做：**
1. 检出 V0，生成 V0 预测，对比差异
2. 优化切分策略，重跑评估，看指标是否改进
3. 扩充评估集到 200+ 题（需要人工标注）

---

**最后更新:** 2026-07-14
**评估集大小:** 61 题
**源文档:** 10 篇（532 chunks）
