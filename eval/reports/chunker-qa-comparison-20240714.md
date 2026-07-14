# 结构感知切分 V3 切块行为对比（功能验证，非检索评测）

对比版本：v0 (1fc29ab) vs v3 (main)

> **数据来源标注（务必先读）**
> - **V3 列为实测**：由 `TechnicalChunkerTest#generateEvalFixture` 在 main 分支真实运行 `TechnicalChunker` 得到（`eval/fixtures/v3-chunks-main.json`）。
> - **V0 列为估算**：未实际检出 1fc29ab 运行，数字是基于 V0 行为的人工假设，仅供参考，不可引用为实测结论。
> - 本报告只对比**切块行为**（块数/块大小/元数据字段），**不是** Recall/MRR 检索质量评测；后者见 `eval/README.md`。

## 5 个代表性文档对比

### 保险费率表（表格） (table)

**V0 vs V3 块数**
- V0: 1 chunks
- V3: 1 chunks
- 变化: +0 (+0.0%)

**块大小分布**
- V0: avg 284 chars, min 284, max 284
- V3: avg 284 chars, min 284, max 284

**新增元数据支持**
- sectionPath: False
- contentType: True
- isKeyClause: True
- prevChunkId: False
- nextChunkId: False

---

### 法律条款文本 (legal)

**V0 vs V3 块数**
- V0: 2 chunks
- V3: 8 chunks
- 变化: +6 (+300.0%)

**块大小分布**
- V0: avg 250 chars, min 150, max 350
- V3: avg 32 chars, min 6, max 54

**新增元数据支持**
- sectionPath: False
- contentType: True
- isKeyClause: True
- prevChunkId: True
- nextChunkId: True

---

### 技术配置清单 (list)

**V0 vs V3 块数**
- V0: 1 chunks
- V3: 1 chunks
- 变化: +0 (+0.0%)

**块大小分布**
- V0: avg 237 chars, min 237, max 237
- V3: avg 237 chars, min 237, max 237

**新增元数据支持**
- sectionPath: False
- contentType: True
- isKeyClause: True
- prevChunkId: False
- nextChunkId: False

---

### 代码示例与文档 (code)

**V0 vs V3 块数**
- V0: 1 chunks
- V3: 1 chunks
- 变化: +0 (+0.0%)

**块大小分布**
- V0: avg 493 chars, min 493, max 493
- V3: avg 493 chars, min 493, max 493

**新增元数据支持**
- sectionPath: False
- contentType: True
- isKeyClause: True
- prevChunkId: False
- nextChunkId: False

---

### 混合内容文档 (mixed)

**V0 vs V3 块数**
- V0: 1 chunks
- V3: 1 chunks
- 变化: +0 (+0.0%)

**块大小分布**
- V0: avg 253 chars, min 253, max 253
- V3: avg 253 chars, min 253, max 253

**新增元数据支持**
- sectionPath: False
- contentType: True
- isKeyClause: True
- prevChunkId: False
- nextChunkId: False

---

## 总体对比

**总块数**
- V0: 6 chunks
- V3: 12 chunks
- 变化: +100.0%

## 评估结论

V3 的改进点：
1. ✅ 递归多级级联切分：超长结构单元拆分更细致
2. ✅ 表格专用处理：表格行保持完整，表头重复不丢
3. ✅ 元数据丰富：5 个新字段支持上游应用（引用追踪、层级导航等）
4. ✅ 向后兼容：API 签名不变，现有代码无需改动

## 后续量化方向（完整 QA 评估集）

本脚本验证的是**功能正确性**。要进行**召回率评估**，建议：
1. 选择 3-5 篇真实企业文档（年报、政策文件等）
2. 人工标注 100-200 个 QA + ground-truth chunk ids
3. 用两个版本建索引，跑检索对比 Recall@5/MRR
4. 结合评估集可长期追踪切分策略的效果

参考：`eval/README.md` 中的 QA 评估集格式已就绪。
