# NLI 阈值校准记录（2026-07-16）—— 负面结果，如实记录

## 背景

`multi-passage-fusion-and-self-check` 上线的 `AnswerSelfChecker` 复用 Reranker 做生成后自检，真实验证发现命中率不足（4/6）。本次按用户要求换成真正的 NLI 模型（`IDEA-CCNL/Erlangshen-Roberta-110M-NLI`，本机部署的 `nli-gateway`），本报告是给这次替换定阈值的真实校准过程。

## 方法

新增 26 条测试样本（`eval/datasets/nli-self-check-calibration-set.jsonl`），从真实语料（`rag_chunks_eval_v3` 对应的本科毕设语料）摘取 8 段真实资料原文，覆盖 4 类：

- **accurate**（8 条）：准确复述资料内容，期望 `entailment_prob` 高（判定"支撑"）
- **unrelated**（6 条）：完全无关的编造，期望低
- **partial**（7 条）：分享资料表面词汇/主题，但具体断言是编的，期望低
- **misattributed**（5 条）：真实存在的事实，但被错误地安到不相关的资料头上，期望低

跑真实 `nli-gateway`（`analyze_nli_threshold.py`），记录每条的 `entailment_prob`，扫描候选阈值选 F1 最优点。

## 结果：形式上有"最优阈值"，但校准本身不可信

| 阈值扫描结果 | 数值 |
|---|---:|
| 最佳阈值 t | 0.195 |
| F1 | 0.837 |
| 精确率 | 0.720 |
| 召回率 | 1.000 |
| 命中"不支撑" | 18/18 |
| 误伤"应支撑" | 7/8 |

**这个 F1=0.837 具有误导性，不能作为可信的校准结果**：`accurate`（应判定支撑）8 条样本的 `entailment_prob` 全部很低（0.0006–0.2418），**多数被模型直接判成 `contradiction` 而不是 `entailment`**——包括逐字逐句复述原文的 c-01（entailment_prob=0.0315，判成 contradiction）。真正应该被支撑的样本和不该被支撑的样本，`entailment_prob` 分布高度重叠，都挤在接近 0 的区间；t=0.195 这个"最优阈值"实际上是被 c-06（0.2418）和 c-22（0.1935）两个孤立的偏高点撑起来的，不是真实的判别信号。

用此前 `multi-passage-fusion-and-self-check` 报告里的 6 条样本重新跑一遍做回归对照，同样的模式复现：3 条准确复述的 `entailment_prob` 是 0.0019/0.0216/0.0315，同样全部很低，同样多数被判成 contradiction；F1 只有 0.667（还不如上次 Reranker 的 4/6）。

## 排查：确认不是截断/工程 bug

用真实 tokenizer 检查最长的一对 premise+hypothesis，总长度只有 134 token，远低于任何合理上限，且 `tokenizer.decode()` 确认文本完整无截断——问题不在工程实现，是模型本身在"长篇技术性中文段落（矩阵符号、专业术语）"这个领域上的判别力不足。`Erlangshen-Roberta-110M-NLI` 大概率是在偏日常对话/短句的中文 NLI 数据集（CMNLI/OCNLI 等）上训练的，这类语料的句子长度和领域用词与本科毕设的地震数据处理技术文本差异很大，是真实的分布外（out-of-domain）问题，不是可以靠调阈值解决的。

## 结论

- **不建议把 t=0.195 这个阈值写进 `AnswerSelfChecker` 生产代码**——它是在一个几乎没有真实区分度的分数分布里挑出来的"最优点"，样本稍微换一批就可能完全失效（6 条回归样本已经证明了这一点：F1 从 0.837 掉到 0.667）
- 110M 参数的 `Erlangshen-Roberta-110M-NLI` 对这个技术文档场景不够用，比 Reranker（bge-reranker-v2-m3，更大且经过更广泛语料训练）表现更差，不是"用了 NLI 就一定比 Reranker 准"这个假设的反例证据——恰恰相反，这次真实验证证伪了这个假设
- 这是本次设计 Risk 部分预先写明的"110M 参数的小模型精度是否够用，未知"这条风险的真实兑现，如实记录，不美化，不能因为"已经做了这么多工作"就勉强把一个不可信的阈值塞进生产代码
