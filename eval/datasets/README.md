# 评测集说明（eval/datasets/）

## 文件清单

| 文件 | 说明 |
|---|---|
| `corpus/部-测量标志/` | 9 篇源文档（8 真实文件 + 1 个 XLSX 转的 MD） |
| `corpus-index.jsonl` | dump 工具产物：532 个 chunk 的元数据（chunk_id/document/heading/snippet） |
| `eval-set-2026Q3.jsonl` | **QA 标注集 v0**：61 道题（8 文档各 6-9 道 + 8 道拒答） |
| `qa-set-skeleton.jsonl` | 中间产物，可忽略 |

## QA 集结构

每条 JSONL 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | `q-001` ~ `q-061` |
| `question` | str | 自然语言问题 |
| `ground_truth_chunk_ids` | str[] | ground-truth chunk_id 列表（拒答题为空） |
| `expect_refusal` | bool | 是否期望拒答 |
| `refusal_reason` | str? | 仅拒答题填（`OUT_OF_SCOPE` / `LOW_CONFIDENCE` / `SAFETY` / `NO_RETRIEVAL`） |
| `category` | str | `api` / `error-code` / `config` / `class-name` / `module` / `data-structure` / `troubleshoot` / `out-of-scope` |
| `difficulty` | str | `easy` / `medium` / `hard` |
| `kb_id` | str | `kb-bdzdc`（所有题都标同一 KB）|
| `org_id` | str | `org-bdzdc` |

## ⚠️ 重要：这是机器生成的骨架集

`build_qa_set.py` 是**基于 chunk snippet 实体抽取**自动出题，**不是**业务专家标注：

| ✅ 能用 | ❌ 不够 |
|---|---|
| ground_truth_chunk_id **真实**（直接来自 corpus-index.jsonl）| 题目措辞模板化（"这一节讲什么"）|
| 评测集格式 100% 合法（eval/ 框架可读）| 缺真实业务理解（接口语义/字段含义需业务专家）|
| 拒答题符合 schema | 拒答 pool 10 条重复 8 次 |
| 覆盖 8 篇文档 | 题数 61 道，离 200-300 道评估集标准还差 3-4 倍 |

> **重建评估集请直接使用 [标注指南.md](标注指南.md)**——含出题四原则、150 题配额表、
> 防假阴性的多 chunk 标注规则、拒答题构造、JSONL 模板与完整 SOP/验收门，
> 吸收了 2026-07-14 两次真实检索基线的诊断教训。以下清单是其简化版，仅供快速参考。

## 业务专家复核清单

每道题需要复核：

- [ ] **题目**：是否清晰、唯一指向一个或几个 chunk？
- [ ] **ground_truth**：引用的 chunk_id 是否真包含答案（不是相邻 chunk）？
- [ ] **category**：8 类分得对不对？
- [ ] **difficulty**：实际难度与标注难度一致吗？
- [ ] **拒答题**：refusal_reason 是否合适？（部分应改 SAFETY 而非 OUT_OF_SCOPE）

## 扩到 200-300 道的建议

按之前分工表的 Phase 3 节奏：

1. **业务专家 1 人**：精修 61 道题目（2-3 天）
2. **业务专家 2 人**：扩到 200 道（每篇 20-25 道，1-2 周）
3. **2 人一致性 check**：50 道重叠题，Cohen's Kappa ≥ 0.7（2-3 天）
4. 写正式 `eval-set-v1.jsonl`（带版本号）

## 跑评测（验证集格式合法）

```bash
# 当前没有 predicted JSONL，先用 mock 跑一遍（拒答全对、可答全错）
python3 eval/runner.py \
  --ground-truth eval/datasets/eval-set-2026Q3.jsonl \
  --predicted    eval/datasets/predicted-sample.jsonl \
  --output-md    eval/reports/eval-skeleton-2026Q3.md

# 退出码 = 0 = 通过格式校验
echo $?
```

## dump 工具（怎么生成 corpus-index.jsonl）

```bash
# 1) 拿 classpath
cd backend
mvn dependency:build-classpath -Dmdep.outputFile=/tmp/rag-cp.txt -q

# 2) 编译 dump 工具（需要 Java 17）
export JAVA_HOME=/Library/Java/JavaVirtualMachines/zulu-17.jdk/Contents/Home
javac -cp "$(cat /tmp/rag-cp.txt):target/classes" -d ../eval/scripts ../eval/scripts/EvalCorpusIndexer.java

# 3) 跑 dump
java -cp "eval/scripts:$(cat /tmp/rag-cp.txt):backend/target/classes" \
  EvalCorpusIndexer eval/datasets/corpus/部-测量标志 eval/datasets/corpus-index.jsonl

# 4) 生成 QA 集
python3 eval/scripts/build_qa_set.py
```

## XLSX / DOCX 预处理

V3 DocumentParserFactory 不支持 XLSX / 含图 DOCX，需要先预处理：

```bash
# XLSX → Markdown 表格
python3 eval/scripts/xlsx_to_md.py <input.xlsx> <output.md>

# DOCX → 纯文本 Markdown（绕过 V3 OCR 跳过）
python3 eval/scripts/docx_to_md.py <input.docx> <output.md>
```
