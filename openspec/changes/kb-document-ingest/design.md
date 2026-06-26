## Context

当前 rag-kb 有三层租户模型、知识库 CRUD、RAGFlow dataset 映射、本地账号认证,但知识库内没有文档——无法上传内容,问答链路无从启动。

`RagFlowClient` 已封装 dataset 的创建/删除,`RestTemplate` 配置已就绪。现在需要在 dataset 基础上支持文件上传、解析状态追踪、列表与删除。

## Goals / Non-Goals

**Goals:**
- 成员可向知识库上传文件(PDF/DOCX/TXT/Markdown),后端推送至 RAGFlow dataset
- 文档解析状态异步可见(`UPLOADING → PARSING → READY / FAILED`)
- 文档列表/删除
- 每个操作路径强制多租户校验

**Non-Goals:**
- 消息队列异步摄取(同步上传 → RAGFlow,状态轮询即可)
- 流式进度推送(WebSocket/SSE)
- 本地文档解析
- 文档版本控制、内容预览/下载
- 文档级细粒度权限(继承知识库 RBAC)

## Decisions

### D1: 同步上传 + 客户端轮询状态(不引入消息队列)

本 change 采用**同步上传到 RAGFlow + 客户端轮询状态**模式:
- `POST /documents` → 先校验 KB 归属(`getByIdAndCurrentOrg(kbId)`,跨租户 404)→ 多部分上传 → 持久化文档行(状态=`UPLOADING`)→ 调 RAGFlow 上传接口 → **调 RAGFlow 解析触发接口** → 成功后置状态=`PARSING` → 返回 docId
- 客户端定期 `GET /documents/{id}` 轮询状态,后端每次查 RAGFlow 刷新状态再返回
- 消息队列摄取留给后续 `kb-ingest-pipeline` change

**状态机:** `UPLOADING`(已落库,文件正在推送/触发解析)→ `PARSING`(RAGFlow 已接收并开始解析)→ `READY` / `FAILED`(终态)。上传或解析触发任一步失败 → `FAILED`。

**关键前提:** RAGFlow 上传接口只存文件、不自动解析,解析需单独触发(见 D3 与 Open Questions)。若省略触发步骤,文档永远停在已上传未解析状态,RAG 问答无从启动。

**不选"上传后由队列消费"的原因:** 引入 Kafka/RabbitMQ 会显著增大本次 change 范围,轮询足以支撑当前阶段需求。

### D2: 文档元数据持久化到 PostgreSQL `document` 表

新增 `document` 表,字段:
```
id UUID PK, kb_id UUID FK(knowledge_base), org_id UUID FK(organization),
name VARCHAR, content_type VARCHAR, size_bytes BIGINT,
ragflow_doc_id VARCHAR, status VARCHAR (UPLOADING/PARSING/READY/FAILED),
error_message TEXT, created_by UUID, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ
```

`org_id` 冗余存储(与 KB 同租户)以便 Hibernate @Filter 直接过滤,无需 join。

### D3: RagFlowClient 新增文件上传/解析/查询/删除四个方法

在现有 `RagFlowClient` 上扩展:
- `uploadDocument(datasetId, fileName, fileResource, contentType)` → `ragflowDocId`
  - **流式传输:** 入参用 `org.springframework.core.io.Resource`(或 `InputStreamResource` 包装 multipart 临时文件),不读成 `byte[]`。避免 50MB 文件全量进堆,百人团队并发上传时不致 OOM。
- `parseDocument(datasetId, ragflowDocId)` → 触发 RAGFlow 解析(上传后单独调用)
- `getDocumentStatus(datasetId, ragflowDocId)` → `status` 字符串
- `deleteDocument(datasetId, ragflowDocId)`

RAGFlow 文件上传接口为 `POST /api/v1/datasets/{datasetId}/documents`,使用 `multipart/form-data`;解析触发接口待联调确认(见 Open Questions)。

### D4: 文件大小限制 50MB,类型白名单(扩展名 + MIME 双校)

Spring Boot 全局 multipart 配置限制单文件 50MB。允许类型:`pdf、docx、doc、txt、md、pptx、xlsx`。

**类型校验:以文件扩展名为主白名单,MIME(`Content-Type`)为辅助校验。** multipart 的 `Content-Type` 由客户端提供、可伪造且常为 `application/octet-stream`,单靠它不可靠;扩展名白名单更稳,两者结合提高边界覆盖。不支持类型返回 400。

**超限返回 413:** 超过 50MB 时 Spring 抛 `MaxUploadSizeExceededException`(默认映射 500),必须在 `GlobalExceptionHandler` 显式加 `@ExceptionHandler` 映射为 **413 Payload Too Large**(HTTP 语义正确)。

### D5: 状态刷新采用"查时刷新"策略(仅详情接口)

每次 `GET /documents/{id}` 时,若状态为 `PARSING`,则实时查 RAGFlow 刷新状态后再返回。避免引入独立的状态同步调度器。`READY`/`FAILED` 状态不再查询(终态)。

**列表接口不刷新(明确决策):** `GET /documents` 列表只返回数据库中的存储状态,**不**对每个 `PARSING` 文档触发 RAGFlow 查询——否则列表会退化为 N 次远程调用。客户端通过轮询单文档详情来刷新状态。此行为需有测试断言列表返回存储状态。

## Risks / Trade-offs

- **RAGFlow 上传/解析触发超时** → 后端设置 60s 超时,任一步失败时将文档状态置为 `FAILED`,前端可重试上传
- **大文件内存压力** → multipart 解析先写临时文件(Spring Boot 默认行为),并以 `Resource` 流式传给 RagFlowClient(D3),**不读成 byte[]**,避免 50MB×并发进堆
- **轮询开销** → 轮询频率由客户端控制,服务端无额外开销
- **文档删除不原子** → 先删 RAGFlow,成功后再删 DB;RAGFlow 删除失败时 DB 记录保留,状态置 `FAILED`,便于排查。反向边界(RAGFlow 删成功但 DB 删失败 → 残留指向已删 RAGFlow 文件的孤儿行)概率低,本 change 不专门处理,记为已知失败模式

## Migration Plan

1. Flyway `V003__create_document_table.sql` 新增 `document` 表
2. 新增 `Document` 实体、`DocumentRepository`、`DocumentService`、`DocumentController`
3. 扩展 `RagFlowClient`:新增三个方法
4. `application.yml` 新增 multipart 配置(`max-file-size: 50MB`)
5. 无破坏性变更,无需回滚脚本

## Open Questions

- **RAGFlow 上传后是否需单独触发解析?接口路径与入参待联调确认**(D1/D3 已按"需触发"设计;若实际为上传即自动解析,则 `parseDocument` 退化为空操作,状态直接进 `PARSING`)
- RAGFlow 的文档解析状态字段名称需在真实联调时确认(`status`? `progress`?)
- 是否需要支持 URL 导入(网页/公众号)?留给后续 change

## NOT in scope(本次评审确认延后)

- **文档列表分页**:`listByKb` 暂不分页,文档数极大时一次返回全部。本 change 专注上传摄取闭环,分页独立性高,留给后续 change 加 `Pageable`(已记入 TODOS)
- 消息队列异步摄取、流式进度推送(SSE/WebSocket)、本地解析、版本控制、内容预览/下载、文档级细粒度权限(见 Goals/Non-Goals)
- 删除非原子的反向边界(RAGFlow 删成功 + DB 删失败的孤儿行)不专门补偿
