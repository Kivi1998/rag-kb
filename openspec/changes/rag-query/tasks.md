## 1. 数据层：DB 迁移与实体扩展

- [ ] 1.1 编写 Flyway `V004__add_kb_ragflow_chat_id.sql`：`ALTER TABLE knowledge_base ADD COLUMN ragflow_chat_id VARCHAR(200)`
- [ ] 1.2 在 `KnowledgeBase` 实体新增 `@Column(name="ragflow_chat_id") String ragflowChatId` 字段

## 2. DTO 与配置

- [ ] 2.1 创建 `dto/QueryRequest.java`：`question`（`@NotBlank`）、`topN`（`@Min(1) @Max(20)`，默认值 5）
- [ ] 2.2 创建 `dto/QueryChunkEvent.java`：`content`（chunk 事件）、`documentName`/`content`/`score`（source 事件）、`message`（error 事件）—— 用 `@JsonInclude(NON_NULL)` 复用同一 DTO，由事件类型区分字段
- [ ] 2.3 创建 `config/AsyncConfig.java`：注册 `queryExecutor` 线程池（`corePoolSize=10`，`maxPoolSize=50`，`queueCapacity=200`，线程名前缀 `query-`）；`@EnableAsync`

## 3. RagFlowClient 扩展

- [ ] 3.1 新增 `createChat(String kbId, String datasetId)`：调用 `POST /api/v1/chats`，Chat 名称 `ragkb-chat:{kbId}`，返回 chatId
- [ ] 3.2 新增 `createSession(String chatId)`：调用 `POST /api/v1/chats/{chatId}/sessions`，返回 sessionId
- [ ] 3.3 新增 `streamCompletion(String chatId, String sessionId, String question, int topN, SseEmitter emitter)`：调用 `POST /api/v1/chats/{chatId}/sessions/{sessionId}/completion?stream=true`，用 `RestTemplate.execute()` + `ResponseExtractor` 逐行读 SSE 流，解析 `data:` 行分发 chunk/source/done 事件到 emitter
- [ ] 3.4 新增 `deleteSession(String chatId, String sessionId)`：调用 `DELETE /api/v1/chats/{chatId}/sessions`，异常静默忽略（fire-and-forget 专用）
- [ ] 3.5 新增 `deleteChat(String chatId)`：调用 `DELETE /api/v1/chats`，供知识库删除时级联清理 Chat Assistant

## 4. QueryService

- [ ] 4.1 创建 `service/QueryService.java`，核心方法 `query(UUID kbId, QueryRequest req, SseEmitter emitter)` 加 `@Async("queryExecutor")`
- [ ] 4.2 在 `query` 方法中实现懒建 Chat Assistant：`synchronized (kbId.toString().intern())` + double-check `kb.getRagflowChatId() == null` → 调 `createChat` → `kbRepository.save(kb)`
- [ ] 4.3 实现 Session 生命周期：`createSession` → `streamCompletion`（推流）→ finally 块中 `@Async` fire-and-forget `deleteSession`
- [ ] 4.4 在 `streamCompletion` 完成后 SseEmitter 异常处理：捕获所有异常，发送 `error` 事件，调用 `emitter.complete()`；设置 `onTimeout`（180s）回调记录日志

## 5. QueryController

- [ ] 5.1 创建 `controller/QueryController.java`：`POST /api/v1/knowledge-bases/{kbId}/query`，`produces = MediaType.TEXT_EVENT_STREAM_VALUE`
- [ ] 5.2 Controller 同步阶段：调 `@Valid` 校验 `QueryRequest` → 调 `knowledgeBaseService.getByIdAndCurrentOrg(kbId)`（跨租户 → 404）→ 创建 `SseEmitter(180_000L)` → 委托 `queryService.query(...)` → 立即返回 emitter
- [ ] 5.3 在 `KnowledgeBaseService.delete` 中调 `ragFlowClient.deleteChat(kb.getRagflowChatId())`（可为 null 时跳过），清理 Chat Assistant

## 6. 测试

- [ ] 6.1 正常流式问答：Mock `RagFlowClient` 返回 SSE 事件序列 → 断言 `SseEmitter` 收到 chunk + source + done 事件
- [ ] 6.2 跨租户访问被拒：请求其他组织 kbId → HTTP 404，`RagFlowClient` 未被调用
- [ ] 6.3 question 为空 → HTTP 400（SseEmitter 未创建）
- [ ] 6.4 topN=0 和 topN=21 → HTTP 400
- [ ] 6.5 RAGFlow 流式中断：Mock `streamCompletion` 抛 IOException → SseEmitter 收到 `error` 事件
- [ ] 6.6 Chat Assistant 懒建：首次问答时 `createChat` 被调用，chatId 写入 DB；第二次问答 `createChat` 不再被调用
- [ ] 6.7 并发懒建安全测试：两个线程同时首次查询同一知识库，`createChat` 只被调用一次
- [ ] 6.8 知识库删除时级联清理 Chat：`ragflowChatId` 非空时 `deleteChat` 被调用
