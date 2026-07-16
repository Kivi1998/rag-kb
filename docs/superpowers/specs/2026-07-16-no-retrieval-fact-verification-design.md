# NO_RETRIEVAL 拒答的事实核验机制设计

## 背景

`HybridRetriever.retrieveWithDecision()` 现有拒答机制只有一道基于 rerank 相关性分数的阈值判断（`MIN_RERANK_SCORE=0.06`，2026-07-14 用 150 题人工标注评估集校准，见 [拒答阈值校准报告](../../../eval/reports/refusal-threshold-calibration-20260714.md)）。这道阈值只对两类拒答有效：

- **LOW_CONFIDENCE**（检索本来就没什么相关内容）——4/4 全中
- **OUT_OF_SCOPE**（问题完全不在知识库范围内）——10 中 9

对 **NO_RETRIEVAL** 类完全无效：检索到的 chunk 主题高度相关（确实在讲对应的算法/程序/模块），但问题里问的具体数值/事实/参数恰好没写在检索到的内容里（如"随机数种子设的多少""滤波器长度取了多少"）。校准报告里 8 道 NO_RETRIEVAL 测试题的 rerank 分数普遍在 0.5 以上（0.178–0.921），因为 reranker 衡量的是"主题相关性"，不是"该问题的具体答案是否存在于此内容"——这是模型能力边界，不是调参能解决的，需要生成阶段的事实核验。

**SAFETY 类拒答**（检索到的内容本身没问题，但组织后外发涉及合规判断）**明确不在本次范围内**，需要独立的内容安全分类器，留待后续。

## Goals / Non-Goals

**Goals：**
- 生成模型在真正回答前，先判断"检索到的资料是否包含这个问题的具体答案"，判断为否时不编造，转成规范的拒答响应
- 判断机制不引入额外的 LLM 调用（复用同一次生成请求的结构化输出，而非单独一次核验调用）
- 用现有 150 题评估集的 8 道 NO_RETRIEVAL 标注题 + 抽样应答题做真实回归验证，量化命中率与误伤率，不是"感觉应该有效"

**Non-Goals：**
- 不做 SAFETY 类拒答（内容安全分类器，超出本次范围）
- 不改动 RRF/rerank 阈值本身（`MIN_RRF_SCORE`/`MIN_RERANK_SCORE` 保持不变，这套机制是在阈值判断"未拒答"之后追加的第二道防线）
- 不做拒答原因的结构化分类回填（`RefusalReason` 前端枚举里的 `reason` 字段目前无人填充，本次也不新增填充逻辑——现有 UI 对 `reason` 无差异化展示，属于投机性扩展，YAGNI）

## 架构

```
HybridRetriever.retrieveWithDecision()（rerank 阈值判断，不拒答）
  → QueryService.prepare() 组装 PreparedQuery（含 citations，但先不发送）
  → QueryService.stream()
       → FactVerificationGate 包装 eventConsumer
       → answerGenerator.streamWithMetrics(question, contexts, ..., gate)
            模型输出流：第一行 {"found": true|false}，换行后才是正文
       → FactVerificationGate 拦截：
            - 缓冲首行直到遇到换行符，或缓冲超过 200 字符仍无换行（fail-open）
            - {"found": false} → 丢弃缓冲内容，只发一条 REFUSAL 事件，不发 SOURCE、不发正文
            - {"found": true} → 此时才发 SOURCE 引用事件，再把换行后的正文当 CHUNK 转发，
              之后转入直通模式（后续 chunk 事件原样转发，不再缓冲）
            - 无法在 200 字符内解析出合法 JSON（模型未遵守格式）→ fail-open，
              把已缓冲内容全部当正文透传、正常发 SOURCE，不拒答
```

**关键联动**：现有 `QueryService.stream()` 在调用生成模型 *之前* 就把 `SOURCE` 引用事件发给前端。这与本机制冲突——如果生成模型事后判断"资料里没有具体答案"要拒答，但引用卡片已经提前展示了，会造成"给了参考来源却说没查到"的自相矛盾。因此 `SOURCE` 事件的发送时机必须推迟到 `FactVerificationGate` 确认 `found:true` 之后。

## 组件

### `PromptAssembler.systemPrompt()` 改造

在现有基础 prompt（"只能依据给出的参考资料回答"）后追加格式硬约束：

> 回答前必须先用且仅用一行 JSON 判断参考资料里是否包含这个问题的**具体**答案：包含则输出 `{"found": true}`，资料主题相关但没写这个具体数值/事实则输出 `{"found": false}`。这一行之后换行，`found` 为 true 时才继续输出正文；为 false 时不要输出任何其他内容。

`found:false` 时的拒答文案统一使用固定话术"未在当前知识库中检索到该问题的具体答案"，不采用模型自己生成的理由——保持与现有两类拒答文案风格一致、可预测，不依赖模型在拒答场景下的格式化输出可靠性。

### `FactVerificationGate`（新增，`backend/src/main/java/com/diit/ragkb/ragcore/generation/`）

包装 `Consumer<QueryEvent>` 的有状态类，持有：
- 下游真实 consumer
- 本轮的 `citations` 列表（用于延迟发送）
- 内部缓冲区（`StringBuilder`）与已解析状态（未解析 / 直通正文 / 已拒答丢弃）

对外暴露 `Consumer<QueryEvent> asConsumer()`，`QueryService.stream()` 里原来直接传给 `answerGenerator.streamWithMetrics()` 的 consumer 改为先包一层这个 Gate。

## 数据流：三种结局

1. **正常回答**（`found:true`）：SOURCE 事件（延迟发出）→ CHUNK 事件（换行后正文，含首个 chunk 的剩余部分 + 后续直通）→ DONE
2. **事实核验拒答**（`found:false`）：REFUSAL 事件（固定文案）→ DONE，不发 SOURCE、不发任何正文；`recordTurn`/审计记录该轮为拒答（复用现有 `refusalReason` 字段传递机制）
3. **格式异常兜底**（fail-open）：模型未按格式输出 JSON 前缀 → 200 字符缓冲耗尽仍找不到合法首行 → 把已缓冲内容当正文，正常发 SOURCE + CHUNK，等同于机制关闭前的原有行为，不引入新的拒答误伤

## 测试

**单元测试**（`FactVerificationGateTest`）：
- JSON 跨多个 chunk 事件被切开仍能正确拼出完整判断
- `found:true` → 先 SOURCE 后正文，正文包含换行后的剩余内容
- `found:false` → 只有一条 REFUSAL，不发 SOURCE、不发正文
- 缓冲超过 200 字符无换行 → fail-open 全部当正文，不拒答
- 模型输出不含合法 JSON（如直接开始正常作答）→ fail-open

**真实回归验证**：新增 Java 小工具（复用 `HybridRetriever`/`AnswerGenerator` 生产代码，仿照 `EvalRetrievalRunner` 风格，不经 HTTP），对 8 道 NO_RETRIEVAL 标注题 + 抽样 20-30 道应答题跑真实检索+生成：
- NO_RETRIEVAL 题命中拒答的比例（越高越好）
- 抽样应答题被误判为拒答的比例（这是核心回归指标，不能为了防幻觉把答得对的题也拒了）
- 产出实验报告（格式仿照 `refusal-threshold-calibration-20260714.md`），如实记录数字，不确定/效果不佳的地方直接写出来，不美化

## Risks / Trade-offs

- **[风险] DeepSeek 对"先一行 JSON 再正文"格式的遵循度未知** → 缓解：fail-open 兜底（200 字符缓冲耗尽仍无法解析时全部当正文），且真实回归验证会直接测出遵循度如何；如果实测遵循度很差（解析失败率高、频繁需要 fail-open），需要考虑退回到"生成前单独一次窄范围核验调用"的方案（brainstorming 阶段讨论过的备选方案），本设计文档不锁定这条退路一定不会走
- **[风险] 首个 chunk 的展示延迟** → 缓解：只延迟到看到第一个换行符或 200 字符上限，正常情况下 JSON 判断行很短（`{"found": true}` 约 16 字符），延迟应该是毫秒级、用户感知不到
- **[风险] 误伤应答题（把答得出的问题误判为拒答）** → 缓解：回归验证专门统计这个指标；抽样应答题覆盖不同难度，不只测容易题
