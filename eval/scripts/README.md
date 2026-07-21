# eval/scripts/ — 评测集构建工具集

## 工具清单

| 工具 | 语言 | 用途 | 输入 → 输出 |
|---|---|---|---|
| `eval_corpus_indexer.py` | Python | 跑 V3 DocumentParserFactory + TechnicalChunker（backend-py 生产类），输出 JSONL 索引 | `corpus/` 目录 → `corpus-index.jsonl` |
| `eval_retrieval_runner.py` | Python | 用产品真实 `HybridRetriever` 对评估集跑检索，输出 predicted JSONL | `corpus-index.jsonl` + `eval-set-*.jsonl` → `predicted-*.jsonl` |
| `eval_fact_verification_runner.py` | Python | 对 `FactVerificationGate` 跑真实端到端回归验证（真实检索 + 真实生成模型） | `eval-set-v2.jsonl` → `no-retrieval-fact-verification-*.jsonl` |
| `eval_answer_self_checker_runner.py` | Python | 对 `AnswerSelfChecker` 跑真实回归验证（真实 Reranker，无 CLI 参数） | 内置测试语料 → 终端命中率报告 |
| `xlsx_to_md.py` | Python | XLSX → Markdown 表格（V3 不接 XLSX）| `.xlsx` → `.md` |
| `docx_to_md.py` | Python | DOCX → 纯文本 Markdown（绕过 V3 OCR 跳过）| `.docx` → `.md` |
| `build_qa_set.py` | Python | 基于 corpus-index.jsonl 自动生成 QA 骨架 | `corpus-index.jsonl` → `eval-set-2026Q3.jsonl` |

> `eval_*.py` 4 个工具移植自已删除的 4 个 Java 文件（`backend/` Java 后端退役后，
> 这是 eval 工具链最后一批 Java 代码），调用 `backend-py/app/ragcore/` 下的生产类
> （与 Java 版同一套解析/切块/检索/生成逻辑的 Python 等价物），而非重新实现一套。
> 运行方式统一：可在仓库任意目录下直接 `python3 eval/scripts/eval_xxx.py [参数]`
> 执行，脚本内部（见 `_eval_common.py`）自行处理 `backend-py` 的 `sys.path` 与 cwd
> 切换（`app.core.config.Settings` 用相对路径 `.env` 加载 `backend-py/.env`，需要
> cwd 切到 `backend-py/` 才能找到），不需要用户手动 `cd backend-py`。
> 环境变量（`RAG_EMBEDDING_*`/`RAG_RERANK_*`/`RAG_GENERATION_*`/`RAG_ES_*`）与
> Java 版同名，直接复用 `backend-py/.env`。

## 用法

### Step 1: 准备语料
把源文档放进 `eval/datasets/corpus/<主题>/`。

### Step 2: 预处理（XLSX/DOCX）
```bash
# XLSX → Markdown
for x in eval/datasets/corpus/<主题>/*.xlsx; do
  python3 eval/scripts/xlsx_to_md.py "$x" "${x%.xlsx}.md"
done

# DOCX → Markdown（纯文本，绕过 OCR）
for f in eval/datasets/corpus/<主题>/*.docx; do
  python3 eval/scripts/docx_to_md.py "$f" "${f%.docx}.md"
done
```

### Step 3: dump corpus 索引
```bash
python3 eval/scripts/eval_corpus_indexer.py \
  eval/datasets/corpus/<主题> \
  eval/datasets/corpus-index.jsonl
```

### Step 4: 生成 QA 集
```bash
python3 eval/scripts/build_qa_set.py
```

### Step 5: 跑 baseline 评测
```bash
# eval_retrieval_runner.py 直接调用 backend-py 生产 HybridRetriever 跑真实检索，
# 输出 predicted JSONL，不经过任何后端 HTTP 端点
python3 eval/scripts/eval_retrieval_runner.py \
  eval/datasets/corpus-index.jsonl \
  eval/datasets/eval-set-2026Q3.jsonl \
  eval/datasets/predicted.jsonl

python3 eval/runner.py \
  --ground-truth eval/datasets/eval-set-2026Q3.jsonl \
  --predicted    eval/datasets/predicted.jsonl \
  --output-md    reports/eval-2026Q3.md
```

## 工具维护要点

### eval_corpus_indexer.py
- 直接 import `backend-py` 的 `DocumentParserFactory`/`TechnicalChunker`，无需单独编译/classpath
- 输出 JSONL 字段：chunk_id/document_id/document_name/ordinal/heading_path/page_no/line_start/line_end/language/content_hash/snippet/content/metadata
- 失败的文档会 `[skip]` 跳过，但继续跑其他文件

### build_qa_set.py
- 每篇文档固定 8 道可标 + 1 道拒答
- 拒答 pool 10 条，按 doc 哈希循环取
- 题目从 chunk snippet 抽接口/类/字段/端口实体
- **业务专家必须复核 ground_truth_chunk_ids**
