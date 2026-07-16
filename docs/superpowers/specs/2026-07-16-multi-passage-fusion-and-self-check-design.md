# 多段融合与生成后自检设计

## 背景

对照"回答控制：不只是'答'，还要会'不答'和'取舍'"这张示意图逐项核对现有实现后，发现两处缺口（SAFETY 类拦截明确不在本次范围，用户已确认跳过）：

- **多段融合**：检索回来多个片段时，模型天然会综合作答，但 prompt 里没有一句话明确指示"片段矛盾时优先采信更相关的资料"；同时 `HybridRetriever` 目前只用 `MIN_RERANK_SCORE` 检查排名第一的片段是否达标，第 2 名之后哪怕分数很低也会原样进入 prompt，没有对"低可信片段"做主动过滤。
- **自检（生成后独立验证）**：现有 `FactVerificationGate`（`no-retrieval-fact-verification` change）只在生成前做一次粗粒度判断"整体有没有答案"，不会在生成后检查"已经生成的正文里，有没有具体某句话是没有资料支撑的断言"。这正是"两道闸"里缺失的第二道——目前只有 prompt 约束（第一道），没有独立于生成模型之外的验证/过滤（第二道），而图里强调的核心风险"模型偶尔会自信地越界"恰恰是第一道闸单独扛不住的。

## Goals / Non-Goals

**Goals：**
- 生成的 prompt 明确指示片段矛盾时的取舍原则，并在检索结果里主动剔除排名靠后但分数不达标的低可信片段
- 生成完成后，用一个独立于生成模型的机制（复用现有 Reranker，不引入新的 LLM 调用）核查正文里每句话是否有资料支撑，发现问题时追加一条提醒，而不是让用户毫无察觉地read到编造内容
- 保持现有 SSE 实时流式输出体验不变，自检是"事后追加"，不是"事中打断"

**Non-Goals：**
- SAFETY 类拦截（敏感/越权问题的安全话术），用户已明确本次跳过
- 不做内联逐句标注（不在具体句子旁边直接插入修正标记），自检结果以一条独立提醒消息呈现
- 不重新校准 `MIN_RERANK_SCORE` 本身的数值，只是把它应用到更多地方（每个片段，而不只是排名第一）
- 自检阈值本次先复用 `MIN_RERANK_SCORE=0.06` 起步，不代表这个数字对"句子-资料语义支撑度"这个新场景是最优的——本次不做专门校准实验，只做真实回归验证摸底（类似 NO_RETRIEVAL 当初摸底但不代表最终结论）

## 架构

### 多段融合

```
HybridRetriever.retrieveWithDecision()
  → fused/rerank 结果 selected（已按 finalScore 降序）
  → 现有检查：selected.get(0).finalScore() < MIN_RERANK_SCORE → 整体拒答（不变）
  → 新增检查：reranked 模式下，对 selected 中每一项（含第 0 项）过滤掉
    finalScore() < MIN_RERANK_SCORE 的片段（不只检查第 0 项）
  → 过滤后为空 → 走既有"未检索到足够依据"拒答分支
  → 过滤后非空 → 返回剩余片段（citations 与 prompt 内容保持一致，
    被过滤掉的片段既不进 prompt 也不出现在"参考来源"卡片里）
```

`PromptAssembler.systemPrompt()` 追加一句：参考资料已按相关性排序；片段之间如有出入，优先采信排序更靠前、相关性更高的资料，不要简单罗列矛盾说法。

### 自检（`AnswerSelfChecker`，新增于 `ragcore/generation/`）

依赖：`RerankerClient`（复用现有 硅基流动 bge-reranker-v2-m3，无新增外部依赖）。

```
QueryService.stream()
  → FactVerificationGate 判定 found:true，生成完整正文（answerBuilder）
  → gate.flush() 之后（仅当未被事实核验拒答时）：
       AnswerSelfChecker.check(正文全文, query.citations())
         1. 按中文句末标点（。！？\n）切句
         2. 每句正则提取 [资料N] 标记
            - 有标记：句子文本作为 rerank query，标记对应的
              Citation.snippet() 构造成候选 chunk，调用
              RerankerClient.rerank() 打分；低于阈值 → 记为
              "标注了引用但相关性偏低"
            - 无标记 且 句子长度 ≥ 6 字（过滤"总的来说"这类
              过渡句）→ 直接记为"疑似未标注断言"，不占用一次
              rerank 调用
         3. 有问题的句子 → 拼一条提醒消息；没有 → 不发任何东西
  → 有提醒消息 → eventConsumer.accept(QueryEvent.selfCheckWarning(msg))
  → （原有）发送 done
```

新增 `QueryEventType.SELF_CHECK_WARNING`（wireName `self_check_warning`）与 `QueryEvent.selfCheckWarning(String message)` 工厂方法，`QueryController.payload()` 的 switch 补一个分支。

**与审计状态、会话记忆的边界（自查澄清，避免重复 NO_RETRIEVAL 那次遗漏审计字段的问题）**：自检提醒不改变 `QueryController` 的审计状态判断——只要 `FactVerificationGate` 判定 `found:true`，本轮审计仍记 `COMPLETED`，`self_check_warning` 只是附加的质量信号，不是拒答，不新增审计状态枚举值。同理，`ConversationMemoryOrchestrator.recordTurn()` 写入的 `answerBuilder` 内容不包含自检提醒文本——自检是在 `answerBuilder` 已经收集完正文之后才运行的独立步骤，天然不会混入；这里明确写出来是为了防止后续实现时"顺手"把提醒也拼进 answer 文本存进会话记忆。

**提醒消息格式（示例）**：
```
⚠️ 自检提示：以下内容未在参考资料中找到明确支撑，请以资料原文为准核实：
- "……"（未标注引用来源）
- "……"（标注了 [资料3]，但相关性较低）
```

**前端**：新增一种展示样式（警示色调，区别于普通回答气泡与"参考来源"卡片），收到 `self_check_warning` 事件时渲染在回答下方。

## 数据流：自检的三种结局

1. **无问题**：不发送 `self_check_warning` 事件，用户体验与本次改动之前完全一致
2. **发现疑似未支撑的句子**：正文照常完整展示，随后追加一条黄色警示提醒，列出具体存疑内容
3. **自检本身调用 Reranker 失败**（网络异常等）：fail-open，不发送提醒（不能因为自检失败而拖慢或打断已经成功返回的答案），只记日志

## 测试

**单元测试**（`AnswerSelfCheckerTest`）：
- 句子切分正确处理中英文混排标点
- 带 `[资料N]` 标记的句子正确提取编号并映射到对应 Citation
- 无标记且够长的句子被标记为"疑似未标注断言"
- 无标记但很短的过渡句不被误判
- Reranker 调用异常时 fail-open，不抛出、不发提醒
- 全文无问题时不产出任何提醒

**`HybridRetrieverTest` 补充用例**：
- 排名第 2 名之后分数低于 `MIN_RERANK_SCORE` 的片段被过滤，不出现在返回结果里
- 排名第 1 名达标、其余全部不达标时，最终只剩第 1 名

**真实回归验证**：人工构造一批"编造但标了引用"和"正常引用"的对照样本（参考 NO_RETRIEVAL 当初用标注题摸底的方式），跑真实 Reranker 统计命中率/误伤率，如实记录结果——这是全新场景，没有先例数据，不承诺一定有效。

## Risks / Trade-offs

- **[风险] 复用 `MIN_RERANK_SCORE=0.06` 未必适合"句子-资料语义支撑度"场景** → 缓解：真实回归验证会摸出实际效果；如果命中率/误伤率不理想，需要单独校准一个新阈值，本设计不假定 0.06 在这个新场景也最优
- **[风险] 句子切分/过渡句阈值（6 字）是启发式规则，不是精确的自然语言理解** → 缓解：先用简单规则跑真实数据看效果，如果误伤率高（把正常的简短陈述句也当断言标记），后续再调整阈值或规则
- **[风险] 自检增加生成完成后的额外延迟**（若干次 Reranker 调用） → 缓解：不阻塞已经完成的正文展示，只是"追加"一条消息的时间差；异常时 fail-open 不拖慢主流程
- **[风险] 前端需要新增一种事件类型的渲染**，如果前端遗漏处理会导致新事件被忽略（不会报错，但提醒失效） → 缓解：任务清单里包含前端改动，实现阶段需要真实浏览器验证确认警示样式正确展示
