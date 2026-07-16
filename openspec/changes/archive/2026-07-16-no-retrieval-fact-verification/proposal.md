## Why

现有拒答机制（`HybridRetriever` 的 `MIN_RERANK_SCORE=0.06` 阈值，2026-07-14 用 150 题评估集校准）只对 LOW_CONFIDENCE、OUT_OF_SCOPE 两类拒答有效，对 NO_RETRIEVAL 类（检索到的 chunk 主题相关，但问题问的具体数值/事实恰好没写在里面，如"随机数种子设的多少"）完全无效——reranker 衡量的是主题相关性而非"该问题的具体答案是否存在于此内容"，是检索分数阈值天花板，需要生成阶段的事实核验来补上这个盲区，否则模型会在这类问题上编造答案。

## What Changes

- `PromptAssembler.systemPrompt()` 追加格式硬约束：生成模型必须先输出一行 JSON（`{"found":true}`/`{"found":false}`）判断参考资料是否包含问题的具体答案，换行后才是正文
- 新增 `FactVerificationGate` 组件（`ragcore/generation/`），拦截生成流：解析出 `found:false` 时丢弃缓冲内容并转为固定拒答话术，不产出正文；解析出 `found:true` 才放行正文与引用；200 字符内解析不出合法 JSON 时 fail-open（视为正常正文，不拒答）
- **BREAKING**（内部时序调整，非对外 API 变更）：`SOURCE` 引用事件的发送时机从"生成开始前"推迟到"`FactVerificationGate` 确认 `found:true` 之后"，避免"拒答了却已经展示引用来源"的自相矛盾
- `GenerationMetrics` 新增可空字段 `factVerificationRefusalReason`；`QueryController` 的审计状态判断相应更新，避免生成阶段拒答被误记为 `COMPLETED`
- 新增独立 Java 评测工具（仿照 `eval/scripts/EvalRetrievalRunner.java`），对 150 题评估集中 8 道 NO_RETRIEVAL 标注题 + 抽样应答题跑真实检索+生成回归，产出命中率/误伤率报告

## Capabilities

### New Capabilities

（无——本次不引入新的用户可见能力域，是在现有问答能力基础上补一道生成阶段防线）

### Modified Capabilities

- `rag-query`：新增"生成阶段事实核验拒答"场景（NO_RETRIEVAL 类），修改"正常流式问答"场景中 `source` 事件的发送时机语义

## Impact

- 后端：`PromptAssembler`、新增 `FactVerificationGate`、`QueryService.stream()`、`GenerationMetrics`、`QueryController`（审计状态判断）
- 不涉及：检索/rerank 阈值本身、多租户校验路径、前端（`refusal` 事件展示逻辑不变，仍是固定文案）
- Non-goals：不做 SAFETY 类拒答（独立内容安全分类器，超出本次范围）；不改动 `MIN_RRF_SCORE`/`MIN_RERANK_SCORE`；不做拒答原因结构化分类回填到前端（`RefusalReason` 枚举的 `reason` 字段目前无人填充，本次不新增）
