# 用真实 NLI 模型重构生成后自检

## 背景

`multi-passage-fusion-and-self-check` change 上线的 `AnswerSelfChecker` 复用现有 Reranker（`bge-reranker-v2-m3`）对生成正文逐句核查是否有资料支撑。真实回归验证（`eval/reports/multi-passage-fusion-and-self-check-validation-20260716.md`）发现：Reranker 衡量的是"主题相关性"，不是严格的"蕴含"判断——6 条真实测试句子里，能拦住"完全文不对题"的编造（分数低至 0.00003），但拦不住"部分相关的编造"（共享资料表面词汇，但具体断言是编的，分数 0.15–0.53，远高于复用的 0.06 阈值），只命中 4/6。

用户明确要求换成真正的 NLI（自然语言推理）模型，不再用 Reranker 顶替。硅基流动账号下的 91 个可用模型里没有任何 NLI/entailment 分类模型（已实查确认），需要本机部署一个真实的开源 NLI 模型。

## Goals / Non-Goals

**Goals：**
- 用真正的 NLI 模型（蕴含/矛盾/中立三分类）替代 Reranker 做"句子是否有资料支撑"的核查
- 不依赖硅基流动等云端 API（本机部署，模型选型明确要求"很小"）
- 阈值必须经过真实校准，不能再犯"直接借用一个未为该场景校准的数字"的错误——这正是这次重构要解决的问题本身

**Non-Goals：**
- 不改动"无引用长句直接判定未标注"这条规则（不涉及 NLI，保持不变）
- 不做批量 NLI 接口（当前每次自检最多几句话，单句对单句调用足够，不为尚不存在的性能问题预先优化）
- 不影响 `FactVerificationGate`（NO_RETRIEVAL 事实核验）——那是生成前的整体判断，跟这次生成后逐句自检是两套独立机制

## 架构

### 新增 `nli-gateway/`（Python FastAPI 服务，独立于 `parser-gateway/`）

- 模型：`IDEA-CCNL/Erlangshen-Roberta-110M-NLI`（110M 参数，中文 NLI 专用微调，CPU 可跑）
- 接口：`POST /nli`
  - 请求：`{"premise": "...", "hypothesis": "..."}`（premise = 检索到的资料原文，hypothesis = 生成的句子；判断"资料原文是否蕴含这句话"）
  - 响应：`{"label": "entailment"|"neutral"|"contradiction", "entailment_prob": 0.xx, "neutral_prob": 0.xx, "contradiction_prob": 0.xx}`
- 单句对单句，不做批量；启动方式仿照 `parser-gateway/` 的项目结构（独立 `requirements.txt`、独立启动脚本），但职责完全独立，不共享代码/依赖

### 后端接入

```
AnswerSelfChecker.check(answerText, citations)
  → 按句切分（不变）
  → 每句提取 [资料N] 标记（不变）
  → 无引用 + 够长 → "疑似未标注断言"（不变，不涉及 NLI）
  → 有引用 → 原来调用 RerankerClient.rerank()，改为调用 NliClient：
       对每个引用的资料，NliClient.check(premise=资料原文, hypothesis=句子)
       取多次调用里 entailment_prob 最高的一次
       entailment_prob < 阈值（校准得出）→ "标注了引用但相关性较低"
```

新增：
- `NliClient` 接口（`ragcore/nli/`，与 `RerankerClient`/`EmbeddingClient` 同级风格）
- `HttpNliClient`：HTTP 调用本机 `nli-gateway` 的实现
- `AnswerSelfChecker` 构造参数从 `RerankerClient` 改为 `NliClient`
- 配置：`RAG_NLI_ENDPOINT`（如 `http://localhost:8082/nli`），`rag.nli.enabled` 开关；未启用/服务不可达时自检直接跳过（fail-open，与原 Reranker 异常时行为一致，不影响主问答流程）

### 阈值校准

沿用决策 7（`MIN_RERANK_SCORE`）当初的方法论，但这次专门为 NLI 场景做，不借用任何其他场景的数字：

1. 扩大此前 6 条真实语料构造的测试样本到 20-30 条，继续从真实语料（`rag_chunks_eval_v3` 对应的本科毕设语料）摘取资料原文，人工构造"准确复述"与"编造"（覆盖完全无关/部分相关/张冠李戴三种编造程度）句子对
2. 跑真实 `nli-gateway`，记录每对的 `entailment_prob`
3. 扫描候选阈值，选 F1 最优点（仿照 `eval/scripts/analyze_refusal_threshold.py`）
4. 产出校准报告，格式仿照 `refusal-threshold-calibration-20260714.md`

**实现顺序的明确约束（避免重蹈"先随便写个数字再说"的覆辙）**：`nli-gateway`/`NliClient`/校准脚本必须先落地并跑出真实校准报告，拿到具体数字后，才把这个数字写进 `AnswerSelfChecker` 的阈值常量；不得在校准完成前，为了让代码先跑起来而临时写一个拍脑袋的占位阈值到生产代码里（哪怕注释里写"待校准"也不行——上次的教训就是"临时"的数字最后没人回来改）。

## 测试

**单元测试**：
- `AnswerSelfCheckerTest` 里原来针对 `RerankerClient` 的用例改为 `NliClient`（stub 实现），验证 entailment_prob 高/低两种情形的判定；`NliClient` 调用异常时 fail-open 行为不变
- 新增 `HttpNliClientTest`（如有必要，验证 HTTP 请求/响应解析）

**真实验证**：跑扩大后的 20-30 条真实样本，产出校准报告；再跑一遍此前用过的 6 条样本作为回归对照，确认新阈值下这 6 条的命中情况是否改善（如实记录，不预设一定变好）

## Risks / Trade-offs

- **[Risk] 本机部署引入新的运行时依赖**（Python + transformers + 模型权重下载） → Mitigation：独立服务、独立启动，`rag.nli.enabled` 关闭时完全不影响现有功能；fail-open 保证服务未启动时自检静默跳过，不阻断问答主流程
- **[Risk] 110M 参数的小模型精度是否够用，未知** → Mitigation：这正是校准阶段要验证的问题，如实记录真实命中率，不预设"用了 NLI 就一定比 Reranker 准"
- **[Risk] 20-30 条样本规模仍然有限，不构成统计意义上的结论** → Mitigation：与决策 7 当初的 150 题规模相比明显更小，如实标注这一点，不夸大校准结果的置信度
