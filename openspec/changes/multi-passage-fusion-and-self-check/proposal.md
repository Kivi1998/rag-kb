## Why

对照"回答控制"审计现有实现后确认两处缺口：`HybridRetriever` 只检查排名第一的片段是否达标，低分片段哪怕排名靠后也会原样进 prompt，且 prompt 没有"矛盾时如何取舍"的指令；`FactVerificationGate`（`no-retrieval-fact-verification`）只在生成前做一次粗粒度判断，生成后没有任何独立机制核查已生成正文里具体某句话是否真有资料支撑——这是防幻觉"两道闸"里缺失的第二道，第一道 prompt 约束单独扛不住"模型偶尔自信越界"的风险。

## What Changes

- `HybridRetriever.retrieveWithDecision()`：把 `MIN_RERANK_SCORE` 检查从只看排名第一的片段，扩展到检查全部候选片段，低于阈值的一律过滤（不进 prompt、不出现在参考来源里）
- `PromptAssembler.systemPrompt()` 追加一句：片段矛盾时优先采信排序更靠前、相关性更高的资料
- 新增 `AnswerSelfChecker`（`ragcore/generation/`）：生成完成后，复用现有 `RerankerClient` 对正文逐句核查是否有资料支撑，发现问题时通过新事件类型追加一条提醒，不做内联标注、不影响已有实时流式输出
- 新增 `QueryEventType.SELF_CHECK_WARNING`（wireName `self_check_warning`），前端新增对应展示样式

## Capabilities

### New Capabilities

（无——是在现有问答能力上补两道防线，不是新的用户可见能力域）

### Modified Capabilities

- `rag-query`：新增"低可信片段过滤"、"矛盾片段取舍指令"、"生成后自检提醒"三个场景，`refusal`/`chunk`/`source`/`done`/`error` 五类事件之外新增 `self_check_warning` 事件

## Impact

- 后端：`HybridRetriever`、`PromptAssembler`、新增 `AnswerSelfChecker`、`QueryEvent`/`QueryEventType`、`QueryService.stream()`
- 前端：新增 `self_check_warning` 事件的展示组件（警示样式，区别于普通回答和参考来源卡片）
- 不涉及：审计状态判断（自检提醒不改变 `COMPLETED`/`REFUSED` 判断）、会话记忆（提醒文本不计入 `recordTurn` 的 answer）、多租户校验路径

Non-goals：SAFETY 类拦截（敏感/越权问题的安全话术，用户已明确本次跳过）；不重新校准 `MIN_RERANK_SCORE` 数值本身；不做内联逐句标注；不专门校准自检阈值（本次先复用 0.06 起步做真实回归验证摸底，不代表这个值对这个新场景最优）
