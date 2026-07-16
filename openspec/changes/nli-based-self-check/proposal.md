## Why

`multi-passage-fusion-and-self-check`（PR #19）上线的 `AnswerSelfChecker` 复用 Reranker（`bge-reranker-v2-m3`）做生成后逐句核查是否有资料支撑。真实回归验证（`eval/reports/multi-passage-fusion-and-self-check-validation-20260716.md`）发现 Reranker 衡量的是"主题相关性"而非严格的"蕴含"关系——6 条真实测试句子只命中 4 条，对"部分相关的编造"（共享资料表面词汇但具体断言是编的）基本拦不住。用户明确要求换成真正的 NLI（自然语言推理）模型。实查硅基流动账号下 91 个可用模型，确认没有任何 NLI/entailment 分类模型，需要本机部署。

## What Changes

- 新增独立 `nli-gateway/` Python FastAPI 服务（结构参照已有的 `parser-gateway/`，但完全独立、不共享代码依赖），加载 `IDEA-CCNL/Erlangshen-Roberta-110M-NLI`（110M 参数，中文 NLI 专用微调，CPU 可跑），暴露 `POST /nli`（`premise`+`hypothesis` 进，`entailment`/`neutral`/`contradiction` 三分类概率出）
- 后端新增 `NliClient` 接口 + `HttpNliClient` 实现（`ragcore/nli/`），配置项 `RAG_NLI_ENDPOINT`/`rag.nli.enabled`，服务不可达时 fail-open
- `AnswerSelfChecker` 重构：核查"有引用句子"从调用 `RerankerClient.rerank()` 改为调用 `NliClient`（premise=引用资料原文，hypothesis=句子），取 `entailment_prob` 判定是否支撑；"无引用长句直接判定未标注"规则不变
- 阈值专门校准：扩大此前 6 条真实语料构造的测试样本到 20-30 条，跑真实 NLI 模型扫描候选阈值，产出校准报告，**校准报告产出前不得把占位数字写进生产代码**

## Capabilities

### New Capabilities

（无——是替换 `multi-passage-fusion-and-self-check` 里生成后自检的核查方式，不是新的用户可见能力域；`nli-gateway` 是内部实现细节，参照 `parser-gateway` 同样不单独建能力域）

### Modified Capabilities

- `rag-query`：`self_check_warning` 事件的判定依据从 Reranker 相关性分数改为 NLI entailment 概率，`refusal`/其他事件的场景不变

## Impact

- 后端：新增 `NliClient`/`HttpNliClient`，`AnswerSelfChecker` 构造参数与内部核查逻辑改动，`QueryService` 装配点相应调整
- 新增部署单元：`nli-gateway/`（独立 Python 服务，本机部署，可选开关，不影响未启用场景）
- 不涉及：`FactVerificationGate`（NO_RETRIEVAL 事实核验是生成前的整体判断，独立机制）、多租户校验路径、审计状态判断

Non-goals：不做批量 NLI 接口；不改动 `FactVerificationGate`；不改动"无引用长句判定"规则本身；不追求这次校准样本（20-30 条）达到统计意义上的结论，如实标注规模局限
