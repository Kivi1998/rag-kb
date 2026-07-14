# eval/datasets/ 评估集说明

> **权威基线（2026-07-14，v2 集 × 完整混合检索）：Recall@1 = 0.824，Recall@5 = 0.912，
> Recall@10 = 0.920，MRR = 0.857**，拒答 F1 = 0（阈值待校准，见 TODOS）。
> 报告：[`eval/reports/eval-v2-hybrid-real-20260714.md`](../reports/eval-v2-hybrid-real-20260714.md)。

## 当前交付物

| 文件 | 说明 |
|---|---|
| `corpus/本科毕设/` | 26 个源文档（docx + pdf + pptx + md 预处理产物，RPCA 地震去噪毕设材料） |
| `corpus-index.jsonl` | 885 个 chunk（V3 切分后，含 md/pdf/pptx 多格式副本） |
| **`eval-set-v2.jsonl`** | ⭐ **权威评估集：150 题（125 可答 + 25 拒答），人工出题 + 锚点定位 GT** |
| `eval-set-v1.jsonl` | ❌ 已废弃：机器模板生成，体检发现 GT 大面积错位（60/129 题 GT 不含题目实体词）+ 18 组重复题，保留仅供追溯 |
| `标注指南.md` | 出题规范与 SOP（v2 按此构建） |
| `predicted-sample.jsonl` | 占位数据（pipeline 自检用） |

## v2 是怎么构建的（可复现）

构建脚本：[`eval/scripts/build_eval_set_v2.py`](../scripts/build_eval_set_v2.py)

1. **人工出题**：标注人（AI 标注员，2026-07-14）通读全部核心语料（毕业论文 md 全文、
   文献翻译、任务书、年会投稿、评语/评议/答辩表）后手写 125 道可答题，题目为真实用户
   问法（无"这一节讲什么"类指代措辞，`grep` 验证为 0）；
2. **锚点定位 GT**：每题带 2-4 组锚点短语（脚本内 `anchors` 字段，AND/OR 语义），
   在 885 chunks 全库归一化匹配。语料含 4-6 份全文副本（查重报告/归档/pdf 版），
   同一答案的所有副本 chunk 全部标入 GT（平均 8.1 chunks/题），杜绝跨格式假阴性；
3. **人工复核**：锚点命中候选逐题输出审核报告（`--report`），抽查确认 snippet 与
   问题匹配后 `--emit` 定版；
4. **拒答题**：25 道逐条手写，四类原因（OUT_OF_SCOPE 10 / NO_RETRIEVAL 8 /
   LOW_CONFIDENCE 4 / SAFETY 3），NO_RETRIEVAL 类经通读确认语料确实未含答案。

## 验收门自查（按标注指南 §6）

| # | 验收门 | 结果 |
|:-:|---|---|
| 1 | 题数 ≥ 150 | ✅ 150（125 可答 + 25 拒答），题目零重复 |
| 2 | 无指代语料结构措辞 | ✅ "这一节/本节/上文/下文/本段" = 0 |
| 3 | lexical:semantic ≈ 6:4 | ✅ 80:45 = 64%:36% |
| 4 | GT 关键词自查 | ✅ 锚点匹配即自查；GT 全部存在于 corpus-index，平均 8.1 chunks/题 |
| 5 | 拒答 25 道四类齐备 | ✅ 10/8/4/3 |
| 6 | 交叉复核一致率 ≥ 80% | ⚠️ 部分满足：出题与 GT 定位为同一标注人（AI），锚点报告经二次通读复核；**严格意义的双人独立标注仍需业务专家一轮** |
| 7 | eval.runner 校验 | ✅ 真实预测跑通（见 reports/） |

## category / difficulty 分布

| category | N | | difficulty | N |
|---|---:|---|---|---:|
| api | 27 | | easy | 22 |
| troubleshoot | 27 | | medium | 69 |
| data-structure | 26 | | hard | 59 |
| out-of-scope | 25 | | | |
| module | 23 | | | |
| config | 22 | | | |

> category 语义按学术语料映射：api=方法/算法/公式，config=参数/环境，
> data-structure=变量/矩阵/数据定义，troubleshoot=缺点/失效/实验效果，module=结构/流程/成果。

## 已知边界（如实声明）

1. **单标注人**：v2 由 AI 标注员独立完成出题与 GT 标注（含锚点复核），未经第二位
   业务专家盲标——门 6 的严格形态待补，方法见 `标注指南.md` §6 第③步；
2. **GT 偏向词面可定位事实**：锚点法天然偏好有特异短语的答案；纯推理型问题
   （需综合多段落）未纳入，这类问题本就不适合检索召回评估（指南 §1 原则三）；
3. **评估集锚定 "本科毕设语料 + V3 TechnicalChunker" 组合**：切分器升级或语料变更后
   chunk_id 失效，需重跑 `EvalCorpusIndexer` + `build_eval_set_v2.py --report` 重对齐。

## 跑评测

```bash
# 真实检索（入库 ES 独立评测索引 + 产品 HybridRetriever，混合/BM25-only 自适应）
set -a && source .env && set +a
java -cp "eval/scripts:$(cat /tmp/rag-cp.txt):backend/target/classes" EvalRetrievalRunner \
  eval/datasets/corpus-index.jsonl eval/datasets/eval-set-v2.jsonl \
  eval/predictions/predicted-v2-hybrid-$(date +%Y%m%d).jsonl

# 出报告
python3 -m eval.runner \
  --ground-truth eval/datasets/eval-set-v2.jsonl \
  --predicted eval/predictions/predicted-v2-hybrid-$(date +%Y%m%d).jsonl \
  --meta chunker=technical-chunker@v3 --meta corpus=本科毕设@885chunks \
  --output-md eval/reports/eval-v2-hybrid-$(date +%Y%m%d).md
```

完整链路说明见 [`docs/解析-切块-评估指南.md`](../../docs/解析-切块-评估指南.md)。
