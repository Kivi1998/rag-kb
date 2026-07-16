## Context

`HybridRetriever.retrieveWithDecision()` 目前唯一的拒答依据是 rerank 相关性分数阈值（`MIN_RERANK_SCORE=0.06`，见 [拒答阈值校准报告](../../../eval/reports/refusal-threshold-calibration-20260714.md)）。按拒答子类型细分后，这道阈值对 LOW_CONFIDENCE（4/4 全中）、OUT_OF_SCOPE（10/9）有效，但对 NO_RETRIEVAL 类完全无效——8 道标注题的 rerank 分数普遍在 0.178–0.921，因为 reranker 衡量"主题相关性"，而 NO_RETRIEVAL 的特征恰恰是主题相关但具体事实缺失。这是检索分数机制的天花板，不是调参能解决的，需要在生成阶段补一道事实核验。

完整背景与逐节确认过程见 [brainstorming 设计文档](../../../docs/superpowers/specs/2026-07-16-no-retrieval-fact-verification-design.md)（已提交，本 design.md 是其在 OpenSpec 流程下的提炼版）。

## Goals / Non-Goals

**Goals：**
- 生成模型在正文之前先判断"检索到的资料是否包含这个问题的具体答案"，判断为否时不编造，转为规范拒答
- 不引入额外的 LLM 调用（复用同一次生成请求的结构化输出）
- 用 8 道 NO_RETRIEVAL 标注题 + 抽样应答题做真实回归验证，量化命中率与误伤率

**Non-Goals：**
- SAFETY 类拒答（独立内容安全分类器，超出本次范围）
- 修改 `MIN_RRF_SCORE`/`MIN_RERANK_SCORE` 阈值本身（本机制是阈值判断"未拒答"之后追加的第二道防线）
- 拒答原因的结构化分类回填到前端（`RefusalReason` 的 `reason` 字段目前无人填充，本次不新增）

## Decisions

### 决策 1：生成模型自判 + JSON 前缀，而非独立核验 LLM 调用

**选择**：让同一次生成调用先输出一行 `{"found": true|false}`，而非在生成前单独发起一次核验请求。

**理由**：独立核验调用需要多花一次完整的 LLM 往返延迟和 token 成本，且核验模型看到的上下文与生成模型完全相同，判断逻辑不会更准。用户在澄清阶段明确选择了这个方案（"让生成模型自己判断，输出特殊标记后端解析"），权衡的是延迟/成本 vs. 对模型格式遵循度的信任——若后续真实回归验证显示模型格式遵循度差、fail-open 触发频繁，需要重新评估退回独立调用方案（见 Risks）。

**备选**：生成前单独一次窄范围核验调用——更可靠但翻倍延迟/成本，本次不采用。

### 决策 2：结构化 JSON 前缀，而非固定文本标记

**选择**：用 `{"found": true/false}` 而非类似 `[NOT_FOUND]` 的固定文本标记。

**理由**：JSON 结构对模型更符合其训练分布中的工具调用/结构化输出模式，解析时用标准 JSON 解析器而非脆弱的字符串匹配，扩展性更好（未来若要加字段不需要改解析逻辑）。用户在澄清阶段明确选择此方案。

### 决策 3：`SOURCE` 引用事件延迟到 `found:true` 确认后发送

**选择**：`QueryService.stream()` 现有的"生成前就发 `SOURCE`"时序改为"`FactVerificationGate` 确认 `found:true` 后才发 `SOURCE`"。

**理由**：这是本设计发现的一个真实架构冲突——如果拒答判断发生在生成阶段，但引用来源已经在生成开始前推给前端，就会出现"给了参考来源却说没查到"的自相矛盾。必须让引用展示与拒答判断在时序上互斥。

### 决策 4：固定拒答话术，而非模型自己生成的理由

**选择**：`found:false` 时统一用"未在当前知识库中检索到该问题的具体答案"，不采用模型在这一行之后可能自己补充的解释。

**理由**：与现有两类拒答文案风格一致、可预测；不依赖模型在拒答场景下的格式化输出可靠性——模型只需要准确输出 `found:false` 这个判断本身，具体话术由后端控制。用户在澄清阶段明确选择"固定话术"。

### 决策 5：200 字符缓冲 fail-open，而非阻塞等待合法 JSON

**选择**：`FactVerificationGate` 缓冲首行直到遇到换行符，或缓冲超过 200 字符仍无换行/无法解析出合法 JSON 时，直接 fail-open——把已缓冲内容全部当正文透传，正常发 `SOURCE`，不拒答。

**理由**：`{"found": true}` 这类判断行正常情况下远小于 200 字符（约 16-20 字符）；把兜底行为设计成"退化到机制关闭前的原有行为"而非"报错/卡住"，保证格式异常时不会让用户体验比没有这个机制更差，也不会引入新的误伤。

### 决策 6：审计状态需要跟着生成阶段拒答改（自查发现的必改项）

**选择**：`GenerationMetrics` 新增可空字段 `factVerificationRefusalReason`；`QueryController` 的审计状态判断从只看 `prepared.refusalReason()` 改为同时检查这个新字段。

**理由**：`QueryController.query()` 目前按 `prepare()` 阶段（早于生成）固化的 `prepared.refusalReason()` 决定 `COMPLETED`/`REFUSED`。`FactVerificationGate` 的判定发生在生成阶段之后，如果不改，事实核验触发的拒答会被误记为 `COMPLETED`——审计系统说"正常完成"，用户实际看到的是拒答。这是设计自查（对照现有 `QueryController.java` 代码）发现的问题，不是预先设想的，必须一并修复才能让本机制的拒答被审计正确追踪。

## Risks / Trade-offs

- **[Risk] DeepSeek 对"先一行 JSON 再正文"格式的遵循度未知** → Mitigation：200 字符 fail-open 兜底；真实回归验证（见 tasks）直接测出遵循度；若实测遵循度差（解析失败率高、频繁 fail-open），需要重新评估退回独立核验调用方案（决策 1 的备选）——本设计不锁定这条退路一定不会走
- **[Risk] 首个 chunk 展示因缓冲判断行而延迟** → Mitigation：正常情况下判断行很短（约 16-20 字符），延迟应为毫秒级，用户无感知
- **[Risk] 误伤应答题（把答得出的问题误判为拒答）** → Mitigation：回归验证专门统计这个指标；抽样应答题覆盖不同难度，不只测容易题；若误伤率超出可接受范围，需要调整 prompt 措辞或收紧"具体答案"的判断标准

## Migration Plan

- 纯代码变更，不涉及数据库迁移或数据回填
- 灰度方式：先在真实回归验证（8 道 NO_RETRIEVAL + 抽样应答题）上验证命中率/误伤率达标后再合并主干；无需 feature flag——机制内建 fail-open 兜底，格式异常时自动退化为原有行为，风险可控
- 回滚：还原 `PromptAssembler`/`FactVerificationGate`/`QueryService`/`GenerationMetrics`/`QueryController` 相关改动即可，无状态迁移需要清理

## Open Questions

- 若真实回归验证显示 DeepSeek 格式遵循度不理想，是否需要切换到决策 1 的备选方案（独立核验调用）？留待验证结果出来后再决定，不阻塞本次实现
