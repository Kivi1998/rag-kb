# eval/scripts/ — 评测集构建工具集

## 工具清单

| 工具 | 语言 | 用途 | 输入 → 输出 |
|---|---|---|---|
| `EvalCorpusIndexer.java` | Java 17 | 跑 V3 DocumentParserFactory + TechnicalChunker，输出 JSONL 索引 | `corpus/` 目录 → `corpus-index.jsonl` |
| `xlsx_to_md.py` | Python | XLSX → Markdown 表格（V3 不接 XLSX）| `.xlsx` → `.md` |
| `docx_to_md.py` | Python | DOCX → 纯文本 Markdown（绕过 V3 OCR 跳过）| `.docx` → `.md` |
| `build_qa_set.py` | Python | 基于 corpus-index.jsonl 自动生成 QA 骨架 | `corpus-index.jsonl` → `eval-set-2026Q3.jsonl` |

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
cd backend
mvn dependency:build-classpath -Dmdep.outputFile=/tmp/rag-cp.txt -q
cd ..

export JAVA_HOME=/Library/Java/JavaVirtualMachines/zulu-17.jdk/Contents/Home
export PATH=$JAVA_HOME/bin:$PATH

CP="$(cat /tmp/rag-cp.txt):backend/target/classes"
javac -cp "$CP" -d eval/scripts eval/scripts/EvalCorpusIndexer.java
java -cp "eval/scripts:$CP" EvalCorpusIndexer \
  eval/datasets/corpus/<主题> \
  eval/datasets/corpus-index.jsonl
```

### Step 4: 生成 QA 集
```bash
python3 eval/scripts/build_qa_set.py
```

### Step 5: 跑 baseline 评测
```bash
# 还需要后端跑一次实际检索，输出 predicted JSONL
# （本期未实现：需要 rag-kb 后端加一个 /api/v1/eval/run 端点）
python3 eval/runner.py \
  --ground-truth eval/datasets/eval-set-2026Q3.jsonl \
  --predicted    eval/datasets/predicted.jsonl \
  --output-md    reports/eval-2026Q3.md
```

## 工具维护要点

### EvalCorpusIndexer.java
- **必须 Java 17**（rag-kb 编译产物版本 61.0）
- classpath 必须含 `backend/target/classes`
- 输出 JSONL 字段：chunk_id/document_id/document_name/ordinal/heading_path/page_no/line_start/line_end/language/content_hash/snippet/content/metadata
- 失败的文档会 `[skip]` 跳过，但继续跑其他文件

### build_qa_set.py
- 每篇文档固定 8 道可标 + 1 道拒答
- 拒答 pool 10 条，按 doc 哈希循环取
- 题目从 chunk snippet 抽接口/类/字段/端口实体
- **业务专家必须复核 ground_truth_chunk_ids**
