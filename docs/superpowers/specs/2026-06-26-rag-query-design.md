# RAG 检索问答（rag-query）设计文档

日期：2026-06-26

## 背景与目标

知识库文档摄取已完成（kb-document-ingest change），文档可上传、解析并存入 RAGFlow dataset。本 change 打通最后一公里：**用户向知识库提问，系统流式返回 AI 生成答案 + 引用溯源**。

### 目标

- 提供 `POST /api/v1/knowledge-bases/{kbId}/query` 接口
- 支持 SSE 流式输出（`text/event-stream`），逐 chunk 推送答案
- 答案生成完毕后推送引用来源（文档名 + 片段 + 相关度分数）
- 多租户安全：跨租户访问 → 404

### 非目标

- 不维护对话历史（每次问答独立）
- 不做同步阻塞响应（只做流式）
- 不做答案评价/反馈接口
- 不做问答记录持久化（审计留给后续 change）
- 不做并发限流（留给后续 quota-rate-limit change）

---

## 架构

```
Client
  │  POST /api/v1/knowledge-bases/{kbId}/query
  │  Accept: text/event-stream
  │  Body: { "question": "...", "topN": 5 }
  ▼
QueryController
  │  校验请求 → 创建 SseEmitter → 立即返回 → @Async 线程接手
  ▼
QueryService（@Async 线程）
  ├─ getByIdAndCurrentOrg(kbId)  ← 复用现有租户校验，跨租户 → 404
  ├─ 懒建 Chat Assistant（synchronized double-check，首次存 KB.ragflowChatId）
  ├─ createSession(chatId)
  ├─ RagFlowClient.streamCompletion(chatId, sessionId, question, topN)
  │    └─ RestTemplate.execute() + ResponseExtractor 逐行消费 RAGFlow SSE 流
  │         每个 content chunk → SseEmitter.send("chunk" event)
  │         最终 references     → SseEmitter.send("source" events)
  │         完成                → SseEmitter.send("done" event) + complete()
  └─ deleteSession（fire-and-forget，不阻塞主流程）
```

---

## SSE 事件协议

客户端接收到的 SSE 事件序列：

```
event: chunk
data: {"content":"根据文档，"}

event: chunk
data: {"content":"该功能的实现方式是..."}

event: source
data: {"documentName":"技术规范.pdf","content":"相关段落内容...","score":0.92}

event: source
data: {"documentName":"架构设计.docx","content":"另一段相关内容...","score":0.87}

event: done
data: {}
```

- `chunk`：答案文本片段，流式拼接
- `source`：引用来源，答案生成完毕后发送，可能有多条
- `done`：流结束信号，客户端收到后关闭连接
- `error`：RAGFlow 调用失败时发送 `{"message":"错误描述"}`，之后 complete

---

## 数据模型变更

### Flyway V004

```sql
-- V004__add_kb_ragflow_chat_id.sql
ALTER TABLE knowledge_base
    ADD COLUMN ragflow_chat_id VARCHAR(200);
```

`KnowledgeBase` 实体新增字段：

```java
@Column(name = "ragflow_chat_id", length = 200)
private String ragflowChatId;
```

### Chat Assistant 懒建策略

- 首次向知识库提问时，若 `KB.ragflowChatId == null`，创建 RAGFlow Chat Assistant 并持久化
- 并发保护：`synchronized (kbId.toString().intern())` + double-check（避免重复创建）
- Chat Assistant 名称：`ragkb-chat:{kbId}`，绑定对应 `ragflowDatasetId`

---

## 新增文件

| 文件 | 职责 |
|------|------|
| `dto/QueryRequest.java` | 请求体：`question`（@NotBlank）、`topN`（默认 5，范围 1-20） |
| `dto/QueryChunkEvent.java` | SSE payload DTO（content / documentName / score 等字段） |
| `service/QueryService.java` | 核心流式问答逻辑，`@Async("queryExecutor")` |
| `controller/QueryController.java` | 接收请求，返回 `SseEmitter`，委托 QueryService |
| `config/AsyncConfig.java` | 配置专用 `queryExecutor` 线程池（核心 10，最大 50，队列 200） |

### RagFlowClient 新增方法

| 方法 | RAGFlow API | 说明 |
|------|-------------|------|
| `createChat(kbId, datasetId)` | `POST /api/v1/chats` | 创建 Chat Assistant，返回 chatId |
| `createSession(chatId)` | `POST /api/v1/chats/{chatId}/sessions` | 创建临时 Session，返回 sessionId |
| `streamCompletion(chatId, sessionId, question, topN, emitter)` | `POST /api/v1/chats/{chatId}/sessions/{sessionId}/completion?stream=true` | 流式消费 SSE，逐行解析并推送到 SseEmitter |
| `deleteSession(chatId, sessionId)` | `DELETE /api/v1/chats/{chatId}/sessions` | fire-and-forget 清理 Session |

---

## 关键实现细节

### 流式消费（RestTemplate + ResponseExtractor）

```java
ragFlowRestTemplate.execute(url, HttpMethod.POST, requestCallback, response -> {
    BufferedReader reader = new BufferedReader(
        new InputStreamReader(response.getBody(), StandardCharsets.UTF_8));
    String line;
    while ((line = reader.readLine()) != null) {
        if (line.startsWith("data:")) {
            String json = line.substring(5).trim();
            // 解析 json，分发 chunk / source / done
            dispatchEvent(json, emitter);
        }
    }
    return null;
});
```

### SseEmitter 超时

- 默认超时 3 分钟（`new SseEmitter(180_000L)`），覆盖长文档问答场景
- 超时/断开时触发 `onTimeout` / `onError` 回调，记录 warn 日志

### 线程池

专用 `queryExecutor`（与 Spring 默认线程池隔离），避免大量流式连接耗尽公共线程池：
- `corePoolSize=10`，`maxPoolSize=50`，`queueCapacity=200`
- 线程名前缀：`query-`

---

## 错误处理

| 场景 | 行为 |
|------|------|
| kbId 不属于当前组织 | 抛 `ResourceNotFoundException` → HTTP 404（在 SseEmitter 返回前校验，直接返回 404） |
| question 为空 | `@Valid` 校验失败 → HTTP 400（在 SseEmitter 返回前校验） |
| RAGFlow 创建 Chat/Session 失败 | 发送 `error` SSE 事件后 complete |
| RAGFlow 流式调用中途断开 | 捕获 IOException，发送 `error` 事件后 complete |
| 异步线程中未捕获异常 | `onCompletion` 兜底记录 error 日志 |

**注意**：租户校验和参数校验必须在 `SseEmitter` 创建之前同步完成，确保校验失败时返回标准 HTTP 错误码而非 SSE 流。

---

## 测试覆盖

| 测试用例 | 验证点 |
|----------|--------|
| 正常流式问答 | Mock RagFlowClient → SseEmitter 收到 chunk + source + done |
| 跨租户访问 | 返回 404，SseEmitter 未被创建 |
| question 为空 | 返回 400 |
| RAGFlow 流式中断 | SseEmitter 收到 error 事件 |
| Chat Assistant 懒建 | 首次调用创建并持久化 chatId；并发首查不重复创建 |
| topN 超出范围（0 / 21） | 返回 400 |

---

## 依赖变更

**无新依赖**。`SseEmitter` 和 `RestTemplate.execute()` 均为 `spring-boot-starter-web` 现有能力。
