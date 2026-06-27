## Purpose

企业知识库 RAG 流式问答——通过 SSE 流式返回 AI 生成答案及引用来源，支持 Chat Assistant 懒建复用和临时 Session 管理。

## Requirements

### Requirement: 成员可向知识库发起流式问答

系统 SHALL 提供 `POST /api/v1/knowledge-bases/{kbId}/query` 接口，接受自然语言问题，以 SSE（`text/event-stream`）流式返回 AI 生成答案及引用来源。接口需认证（JWT），跨租户访问 SHALL 返回 404。

#### Scenario: 正常流式问答

- **WHEN** 已认证成员向本组织知识库发起问答请求（question 非空，topN 合法）
- **THEN** 系统立即返回 HTTP 200 并开始 SSE 流，依次推送 `chunk` 事件（答案片段）、`source` 事件（引用来源，含文档名/片段/分数）、最终 `done` 事件

#### Scenario: 问题为空

- **WHEN** 请求体 `question` 为空字符串或缺失
- **THEN** 系统同步返回 HTTP 400，不创建 SseEmitter

#### Scenario: topN 超出范围

- **WHEN** 请求体 `topN` 小于 1 或大于 20
- **THEN** 系统同步返回 HTTP 400

#### Scenario: 跨租户访问被拒

- **WHEN** 已认证成员请求不属于本组织的知识库 kbId
- **THEN** 系统同步返回 HTTP 404，不创建 SseEmitter，不调用 RAGFlow

#### Scenario: RAGFlow 流式调用失败

- **WHEN** RAGFlow Chat API 在流式传输过程中抛出异常或连接中断
- **THEN** 系统向 SseEmitter 发送 `error` 事件（含错误描述），然后 complete

### Requirement: Chat Assistant 懒建与复用

系统 SHALL 在首次向某知识库发起问答时，自动为该知识库在 RAGFlow 创建 Chat Assistant，并将 ID 持久化到 `knowledge_base.ragflow_chat_id`；后续问答复用同一 Chat Assistant。

#### Scenario: 首次问答自动创建 Chat Assistant

- **WHEN** 知识库 `ragflow_chat_id` 为空时收到第一个问答请求
- **THEN** 系统调用 RAGFlow 创建 Chat Assistant，将返回的 chatId 写入数据库，并使用该 chatId 完成本次问答

#### Scenario: 并发首查不重复创建

- **WHEN** 同一知识库同时有多个首次问答请求（ragflow_chat_id 均为空）
- **THEN** 系统通过同步锁保证只创建一个 Chat Assistant，其余请求复用已创建的 chatId

#### Scenario: 已有 Chat Assistant 直接复用

- **WHEN** 知识库 `ragflow_chat_id` 已有值
- **THEN** 系统跳过创建步骤，直接使用已有 chatId 发起问答，不再调用 RAGFlow 创建接口

### Requirement: 临时 Session 管理

系统 SHALL 为每次独立问答创建临时 RAGFlow Session，问答完成后异步删除（fire-and-forget）。

#### Scenario: 问答结束后异步删除 Session

- **WHEN** 一次完整问答流（chunk + source + done）发送完毕
- **THEN** 系统在异步线程中调用 RAGFlow 删除 Session 接口，删除失败静默忽略（不影响答案正确性）
