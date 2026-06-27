## Context

当前 rag-kb 有三层完整基础：多租户、本地账号认证、文档摄取（上传→RAGFlow→解析）。`KnowledgeBase` 实体已有 `ragflowDatasetId` 与 RAGFlow dataset 映射。`RagFlowClient` 封装了 dataset/文档操作。现在需要在此之上打通问答链路。

Spring Boot 使用 Servlet 栈（`spring-boot-starter-web`），无 WebFlux。RAGFlow 的 Chat API 支持 SSE 流式输出。

## Goals / Non-Goals

**Goals:**
- 流式问答接口（SSE），每次问答独立，不维护对话历史
- Chat Assistant 懒建，绑定知识库，ID 持久化复用
- 多租户强隔离，跨租户请求 404
- 无新依赖，复用现有 `SseEmitter` + `RestTemplate`

**Non-Goals:**
- 对话历史、多轮问答
- 同步阻塞响应
- 问答记录持久化/审计
- 并发限流与配额计量

## Decisions

### D1：使用 RAGFlow Chat API（不用 Retrieval API + 自建 LLM 调用）

RAGFlow Chat API 一次调用完成向量检索 + rerank + LLM 生成 + 引用溯源，符合「不自写 RAG 内核」原则。

备选：用 RAGFlow `/retrieval` 做纯检索，后端再调 MiMo 生成答案。这样后端掌控 LLM，但需维护提示词工程、管理 LLM 连接，超出本 change 范围。

### D2：每个知识库懒建一个 Chat Assistant，ID 存 DB

- `knowledge_base` 表加 `ragflow_chat_id` 列（Flyway V004）
- 首次查询时若为空则创建 Chat Assistant，绑定 `ragflowDatasetId`，写回 DB
- 并发保护：`synchronized (kbId.toString().intern())` + double-check
- 与现有 `ragflowDatasetId` 存储模式一致，零学习成本

备选：每次请求临时创建 Chat Assistant。额外开销大，且 RAGFlow 端会积累废弃对象。

### D3：每次问答创建临时 Session，fire-and-forget 删除

RAGFlow Chat 需要 Session 才能发消息。独立问答不需要历史，Session 用完即异步删除（`@Async` 线程 + catch 所有异常静默处理）。RAGFlow 端少量残留 Session 可接受，不影响正确性。

备选：每个 KB 预建复用 Session。多用户并发时 RAGFlow 端可能有上下文污染风险，不选。

### D4：SseEmitter + RestTemplate.execute() 消费 RAGFlow SSE 流

Servlet 栈无 WebFlux，`SseEmitter` 是标准流式方案：
- `QueryController` 同步完成校验 → 创建 `SseEmitter` → 立即返回 HTTP 200
- `QueryService` 在 `@Async("queryExecutor")` 线程中消费 RAGFlow SSE 流
- `RestTemplate.execute()` + `ResponseExtractor` 逐行读取，每行解析后 `emitter.send()`

专用线程池 `queryExecutor`（core=10, max=50, queue=200）隔离流式长连接，避免耗尽公共线程池。

### D5：校验在 SseEmitter 创建之前同步完成

租户校验（`getByIdAndCurrentOrg`）和参数校验（`@Valid`）必须在 `SseEmitter` 创建前同步执行。校验失败直接返回标准 HTTP 错误码（404/400），而非 SSE 流中的 error 事件。

### D6：SSE 事件协议

```
event: chunk   data: {"content":"答案片段"}
event: source  data: {"documentName":"xxx.pdf","content":"引用段落","score":0.92}
event: done    data: {}
event: error   data: {"message":"错误描述"}   ← 仅在流式阶段失败时发送
```

`source` 事件在答案生成完毕后发送（RAGFlow 在流末尾携带引用信息）。客户端收到 `done` 后关闭连接。

## Risks / Trade-offs

- **RAGFlow SSE 格式变更** → `streamCompletion` 解析逻辑集中在 `RagFlowClient`，变更只改一处
- **SseEmitter 超时** → 设置 3 分钟（`180_000L`），覆盖长文档问答；超时触发 `onTimeout` 回调记录日志
- **并发懒建 Chat Assistant** → `synchronized + double-check` 防重复创建；极端情况下 RAGFlow 端有少量重复 Chat，对账服务可清理
- **火-and-forget 删 Session 失败** → 静默忽略，RAGFlow 端残留 Session 不影响答案正确性，后续可加对账清理
- **线程池耗尽** → `queryExecutor` 队列满时抛 `RejectedExecutionException`，`GlobalExceptionHandler` 映射为 503

## Migration Plan

1. Flyway `V004__add_kb_ragflow_chat_id.sql`：`ALTER TABLE knowledge_base ADD COLUMN ragflow_chat_id VARCHAR(200)`
2. `KnowledgeBase` 实体加 `ragflowChatId` 字段
3. 新增 `AsyncConfig`、`QueryService`、`QueryController`、DTO
4. `RagFlowClient` 扩展四个方法
5. 无破坏性变更，无需回滚脚本；V004 可安全回滚（DROP COLUMN）

## Open Questions

- RAGFlow Chat API 的 SSE 流格式（`data:` 字段结构）需联调时确认；`streamCompletion` 解析逻辑预留适配点
- `topN` 参数名在 RAGFlow Chat 请求体中的字段名（`top_k`？`similarity_top_k`？）待联调确认
