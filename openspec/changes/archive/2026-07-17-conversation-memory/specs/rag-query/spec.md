## MODIFIED Requirements

### Requirement: 成员可向知识库发起流式问答

系统 SHALL 提供 `POST /api/v1/knowledge-bases/{kbId}/query` 接口，接受自然语言问题与必填的 `sessionId`，以 SSE（`text/event-stream`）流式返回自研混合检索链路（BM25+kNN+RRF+可选 Rerank）生成的答案及引用来源。接口需认证（JWT），跨租户访问 SHALL 返回 404。响应 SHALL 依次包含 `chunk`（答案片段）、`source`（引用来源）、`refusal`（低置信度拒答，检索结果不足时代替 chunk/source 输出）、`done`（流结束）、`error`（异常）五类事件之一的组合。

#### Scenario: 正常流式问答

- **WHEN** 已认证成员携带合法 `sessionId` 向本组织知识库发起问答请求（question 非空）
- **THEN** 系统立即返回 HTTP 200 并开始 SSE 流，依次推送 `chunk` 事件（答案片段）、`source` 事件（引用来源，含文档名/片段/相关度）、最终 `done` 事件

#### Scenario: 问题为空

- **WHEN** 请求体 `question` 为空字符串或缺失
- **THEN** 系统同步返回 HTTP 400，不创建 SseEmitter

#### Scenario: sessionId 缺失

- **WHEN** 请求体缺少 `sessionId` 或 `sessionId` 不属于当前认证成员
- **THEN** 系统同步返回 HTTP 400/404，不创建 SseEmitter

#### Scenario: 跨租户访问被拒

- **WHEN** 已认证成员请求不属于本组织的知识库 kbId
- **THEN** 系统同步返回 HTTP 404，不创建 SseEmitter，不执行检索

#### Scenario: 检索结果不足触发拒答

- **WHEN** 混合检索融合后最高分低于拒答阈值，或 Rerank 后最高相关性低于门槛
- **THEN** 系统推送 `refusal` 事件（含拒答原因），不推送 `chunk`/`source`，随后推送 `done`

#### Scenario: 模型服务调用异常

- **WHEN** Embedding/生成模型调用过程中抛出异常或连接中断
- **THEN** 系统向 SseEmitter 发送 `error` 事件（含用户可读的错误描述），记录审计日志后 complete

## REMOVED Requirements

### Requirement: Chat Assistant 懒建与复用

**Reason**：本要求描述的是已废弃的 RAGFlow 外部编排架构（`knowledge_base.ragflow_chat_id`、RAGFlow Chat Assistant API）。项目已完成向自研 RAG Core 的迁移，检索与生成完全由 `HybridRetriever`/`AnswerGenerator` 等自研组件完成，不存在"Chat Assistant"这个概念。此前的 spec 未随迁移同步更新，属于历史遗留。

**Migration**：无需迁移——该能力在当前代码中已不存在，本次一并从规格中移除，避免继续误导后续开发。

### Requirement: 临时 Session 管理

**Reason**：同上，描述的是 RAGFlow 侧的临时 Session（每次问答创建、完成后 fire-and-forget 删除），与本 change 引入的 `sessionId`（rag-kb 自己的多轮会话概念，持久化、跨多轮问答复用）是完全不同的两个概念，容易混淆。RAGFlow 侧临时 Session 机制在当前代码中不存在。

**Migration**：无需迁移。本 change 引入的会话概念详见 `conversation-memory` 能力规格，与此处移除的 RAGFlow 临时 Session 无继承关系。
