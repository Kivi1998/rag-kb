## Why

知识库文档摄取已就绪（文档可上传、解析并存入 RAGFlow），但成员无法向知识库提问——RAG 产品的核心价值尚未交付。本 change 打通检索问答链路，让知识库真正可用。

## What Changes

- 新增流式问答接口：`POST /api/v1/knowledge-bases/{kbId}/query`，以 SSE（`text/event-stream`）流式返回答案片段与引用溯源
- RAGFlow Chat Assistant 懒建：首次问答时自动为知识库创建 Chat Assistant，ID 持久化到 `knowledge_base.ragflow_chat_id`
- 每次问答创建临时 Session，问答完毕后异步删除（fire-and-forget）
- `RagFlowClient` 扩展：新增 `createChat` / `createSession` / `streamCompletion` / `deleteSession` 四个方法
- 专用异步线程池 `queryExecutor`，隔离流式长连接与普通请求

## Capabilities

### New Capabilities

- `rag-query`：基于知识库的流式检索问答——接收自然语言问题，调用 RAGFlow Chat API，以 SSE 流式推送答案 chunk 及引用来源（文档名、片段、相关度分数）

### Modified Capabilities

- `knowledge-base`：`knowledge_base` 表新增 `ragflow_chat_id` 列，实体类新增对应字段（数据结构扩展，已有需求不变）

## Impact

- **新 API**：`POST /api/v1/knowledge-bases/{kbId}/query`（SSE 流式，需认证）
- **DB 变更**：`knowledge_base` 表新增 `ragflow_chat_id VARCHAR(200)` 列（Flyway V004）
- **新文件**：`QueryController`、`QueryService`、`QueryRequest` DTO、`AsyncConfig`
- **扩展**：`RagFlowClient` 新增 4 个方法；`KnowledgeBase` 实体新增 `ragflowChatId` 字段
- **无新依赖**：使用现有 `spring-boot-starter-web` 的 `SseEmitter` + `RestTemplate`

## Non-goals

- 不维护对话历史（每次问答独立）
- 不做同步阻塞响应（只做 SSE 流式）
- 不做问答记录持久化与审计（留给后续 change）
- 不做答案评价/反馈接口
- 不做并发限流与配额计量（留给 quota-rate-limit change）
- 不做 URL 导入/网页问答（文档来源限已摄取文件）
