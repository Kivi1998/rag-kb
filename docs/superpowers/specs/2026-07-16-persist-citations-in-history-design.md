# 历史会话消息持久化引用来源（citations）

日期：2026-07-16
分支：`feat/citation-drawer-and-collapsible-docs`（在已有分支上继续，不新开分支）

## 背景

引用来源展示（PR #21/#22，`el-drawer`，点击正文里的 `[资料N]` 弹出对应来源的文档名/定位/
原文片段）目前只在**当次流式生成**时生效：`Citation` 通过 SSE 的 `source` 事件推给前端，
挂在 `message.citations` 上。用户切到"历史对话"恢复的消息（`getSessionMessages` 拉取）
只带 `role`/`content`/`createdAt`，没有 citations，导致历史消息里点 `[N]` 静默无反应——
跟当次生成的回答体验不一致。

本次目标：把每条 assistant 消息的 citations 持久化，历史接口把它带出来，让恢复历史会话后
点 `[N]` 的行为跟当次生成完全一致。

## 架构与数据流

`Citation`（`backend/src/main/java/com/diit/ragkb/ragcore/model/Citation.java`）保持不变，
作为唯一的引用数据结构，贯穿"生成时通过 SSE 推送"和"持久化到历史"两条路径。

**后端改动：**

1. `ChatMessageDocument`（MongoDB，`ragcore/conversation/ChatMessageDocument.java`）新增
   `List<Citation> citations` 字段，MongoDB 原生支持嵌套文档，不需要像 Postgres 那边
   `QueryAuditLog` 的 `chunk_ids_json` 那样手动序列化成 TEXT。只有 `role=assistant` 的消息
   会有值；`role=user` 的消息该字段恒为空。

2. `ChatMessage`（内存态 record，`ragcore/conversation/ChatMessage.java`）同步新增
   `citations` 字段。已确认这个 record 只有两处消费方：
   - `DeepSeekCoreferenceResolver.resolve()` / `DeepSeekConversationSummarizer.summarize()`：
     只提取 `.content` 文本拼成对话记录传给 LLM，不会把 citations 结构体传给模型，加字段
     不影响 prompt 内容/长度。
   - `ChatSessionController.getMessages()`：直接把 `List<ChatMessage>` 序列化为历史接口的
     响应体，加字段后 Jackson 自动带出来，不需要改 DTO 类型。

3. `ConversationMemoryOrchestrator.recordTurn()` 签名新增 `List<Citation> citations` 参数
   （只用于 assistant 消息那一条）。调用方 `QueryService.stream()`（line 133 附近）传入
   `query.citations()`——这个值在 `prepare()` 阶段就已经算好，调用点已经能直接拿到，
   不需要额外查询。

**前端改动：**

- `getSessionMessages()`（`frontend/src/api/queryApi.ts:300`）的响应类型和 `.map(...)`
  补上 `citations` 字段的映射，与流式生成时 `applyEvent()` 里 `source` 事件的处理方式
  保持同一个 `Citation` 类型（`frontend/src/types/citation.ts`）。
- `ChatPanel.vue` 不需要改：`handleCitationClick` 已经是通用逻辑，只要
  `message.citations` 有值就会正确工作。

## 错误处理

- `citations` 为空列表/`null`（旧数据、或该轮命中拒答没有真正生成答案）时，历史消息正常
  返回，前端 `message.citations` 就是空数组/`undefined`，点 `[N]` 行为跟现在完全一样
  （静默无反应），不引入新的报错路径。
- **明确不做历史数据回填**：这次新增字段只对以后新产生的消息生效，之前已经产生的历史
  消息不会补上引用（读取时直接视为没有引用）。回填需要用旧消息当时检索到的 chunk 重新
  定位，而知识库内容可能已经变动过，准确性无法保证，用户已确认接受这个取舍。
- `recordTurn()` 新增参数不设默认值，强制调用方显式传入；`QueryService.stream()` 是唯一
  调用点，直接传 `query.citations()`，没有遗漏风险。

## 测试

- 后端：`ConversationMemoryOrchestrator` 相关测试验证 `recordTurn()` 把 citations 正确
  写入 `ChatMessageDocument`；`ChatSessionService`/`ChatSessionController` 相关测试验证
  历史接口返回的 JSON 里带 citations 字段。
- 前端：`query.test.ts` 里 `getSessionMessages` 的映射测试补一个"历史消息带 citations
  时正确解析"的用例；`ChatPanel.test.ts` 补一个"恢复历史会话后点击 `[N]` 能正确弹出抽屉"
  的用例（复用已有的 `switchToSession` 相关测试结构）。
- 真实验证：跑一轮真实问答生成带引用的回答 → 刷新页面/切换到历史会话 → 点 `[N]` 确认
  抽屉弹出内容正确。

## Non-Goals

- 不回填历史数据（见"错误处理"一节）。
- 不改动 SSE 当次生成推送 citations 的机制（`CitationBuilder`/`source` 事件不变）。
- 不改动引用展示 UI（抽屉本身、点击交互逻辑已经是通用的，本次只是把数据补齐）。
