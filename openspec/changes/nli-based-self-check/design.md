## Context

`AnswerSelfChecker`（`multi-passage-fusion-and-self-check`）复用 Reranker 做生成后逐句自检，真实验证显示 Reranker 的"主题相关性"打分对"部分相关的编造"命中率不足（4/6）。硅基流动账号下没有 NLI 模型，需要本机部署一个真实的开源中文 NLI 模型。完整背景与设计过程见 [brainstorming 设计文档](../../../docs/superpowers/specs/2026-07-16-nli-based-self-check-design.md)。

## Goals / Non-Goals

**Goals：**
- 用真正的 NLI（蕴含/矛盾/中立三分类）模型替代 Reranker 做"句子是否有资料支撑"的核查
- 本机部署，不依赖云端 API
- 阈值经过真实校准，不借用其他场景未经验证的数字

**Non-Goals：**
- 不做批量 NLI 接口
- 不改动 `FactVerificationGate`（生成前的整体判断，独立机制）
- 不改动"无引用长句直接判定未标注"规则

## Decisions

### 决策 1：新增独立 `nli-gateway/` 服务，不复用/扩展 `parser-gateway/`

**选择**：新建独立的 Python FastAPI 服务，仿照 `parser-gateway/` 的项目结构（独立 `requirements.txt`、独立启动脚本），但不共享代码或依赖。

**理由**：`parser-gateway` 的职责是文档解析（OCR/ASR/Office 提取），与 NLI 推理是完全正交的关注点；用户在澄清阶段明确选择独立服务而非塞进 parser-gateway，保持职责单一，互不干扰部署/依赖升级。

### 决策 2：模型选 `IDEA-CCNL/Erlangshen-Roberta-110M-NLI`

**选择**：110M 参数的中文 NLI 专用微调模型（IDEA 研究院封神榜项目，4 个中文 NLI 数据集微调）。

**理由**：用户要求"很小的模型"，实查确认这是真实存在、体量最小的中文 NLI 专用模型选项（对比 325M 的 MacBERT 版本），CPU 可跑，不需要 GPU 部署门槛。

### 决策 3：判定规则用 entailment 概率 + 校准阈值，不用 argmax

**选择**：不直接取三分类里概率最高的标签做判定，而是用 `entailment_prob` 设一个校准过的阈值。

**理由**：用户在澄清阶段明确选择"需要校准的阈值"而非 argmax——这与整个项目"阈值必须真实校准，不能拍脑袋"的一贯原则一致（决策参照 `MIN_RERANK_SCORE` 当初的做法）。虽然 argmax 工程上更简单（不需要额外校准实验），但用户认为校准后的阈值更可控、更适合按业务需要调整误伤/漏检的平衡点。

### 决策 4：先出校准报告拿到真实数字，才允许把阈值写进生产代码

**选择**：任务执行顺序上，`nli-gateway`/`NliClient`/校准脚本必须先完成并跑出真实校准报告，取得具体阈值数字后，才把这个数字写进 `AnswerSelfChecker` 的常量。

**理由**：这是本次设计自查阶段主动加的约束，直接针对上一轮的教训——`AnswerSelfChecker` 最初复用 `MIN_RERANK_SCORE=0.06` 这个从未为"句子-资料语义支撑度"场景校准过的数字，真实验证证明了这个数字不合适。这次不允许重复"先写个占位数字'待校准'，实际上从来没人回来改"的模式。

## Risks / Trade-offs

- **[Risk] 本机部署引入新的运行时依赖**（Python + transformers + 模型权重下载，需要网络下载 HuggingFace 模型或提前缓存） → Mitigation：`rag.nli.enabled` 开关默认允许关闭，关闭/服务不可达时自检直接跳过（fail-open），不影响现有问答主流程
- **[Risk] 110M 参数的小模型精度未知，可能不如更大的 NLI 模型准** → Mitigation：这正是校准阶段要验证的问题；如实记录真实校准结果，不预设"用了 NLI 就一定比 Reranker 准"
- **[Risk] 20-30 条校准样本规模有限，不构成统计意义上的结论** → Mitigation：如实标注这一点在校准报告里，不夸大置信度；后续如果发现命中率不理想，需要考虑扩大样本规模或换更大的 NLI 模型，本设计不锁定当前模型/样本规模为最终方案
