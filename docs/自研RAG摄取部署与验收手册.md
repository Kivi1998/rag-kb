# 自研 RAG 摄取、检索与问答部署验收手册

> 适用范围：P1 摄取与索引、P2 混合检索与 SSE 问答（T003、T101–T107、T201–T203）。
>
> 目标：让技术文档可靠经历“上传 → `QUEUED` → 解析 → 切块 → 向量化 → ES Bulk → `READY`”，并在删除时不再被检索命中。

## 1. 当前实现边界

本手册对应自研 RAG Core，不依赖 RAGFlow、LangChain、LlamaIndex 或 Dify。

已经实现：

- PostgreSQL `ingestion_job`、文档对象键、失败信息和重试次数迁移；
- 本地文件系统与 MinIO/S3 兼容对象存储；
- 管理员/Owner 上传、查询任务、重试和删除 API；
- 数据库条件更新领取任务，避免多 Worker 重复处理同一 `QUEUED` 任务；
- Markdown、TXT、代码、YAML/JSON/XML、DOCX、文本型 PDF 的解析与结构化切块；
- OpenAI 兼容 Embedding/Rerank/Chat Completions HTTP 客户端；
- 共享 ES 索引 `rag_chunks_v1` 的 mapping、Bulk Upsert、按 org/kb/document 三重过滤删除；
- `DELETING` 删除补偿：优先删除 ES chunk，再删除对象与数据库元数据，失败自动重试。
- ES 原生 BM25 与 kNN 双路召回、RRF 融合、可选 Rerank、低置信度拒答；
- `POST /api/v1/knowledge-bases/{kbId}/query` SSE 接口，稳定输出 `chunk/source/refusal/done/error` 五类事件；
- 服务端引用卡片：从最终 chunk 和本租户文档元数据构造，不向前端暴露对象存储路径；
- Embedding 故障时退化为 BM25，Rerank 故障时退化为 RRF，空召回不调用生成模型。

尚未实现：问答前端页面/取消交互、端到端真实模型验收、离线评测、压测、索引重建与发布回归；这些属于 T204–T207、T301、T303–T306。

## 2. 运行依赖

| 组件 | 用途 | 最小要求 |
|---|---|---|
| PostgreSQL | 文档元数据、任务状态与无正文查询审计 | 已执行 Flyway V006 |
| MinIO/S3 | 原始文件 | Bucket 已创建，应用账号可读写该 Bucket |
| Elasticsearch 8.x | `rag_chunks_v1` 与向量/BM25 索引 | 向量维度与 Embedding 模型一致 |
| Embedding 网关 | 批量向量 | OpenAI `POST /v1/embeddings` 兼容协议 |
| Rerank 网关 | 后续检索精排 | 可选；支持 `query/documents/results` 协议 |
| Generation 网关 | SSE 答案生成 | OpenAI Chat Completions 流式兼容协议 |

ES Java REST Client 采用 8.17 分支。应将客户端主版本与实际 ES 主版本保持一致；本项目不使用 Spring Data Elasticsearch 或 RAG 编排框架。

## 3. 必需配置

生产环境不要使用默认本地对象存储，也不要将 API Key 写进仓库。以下变量由部署密钥管理系统或 `application-secret.yml` 提供。

```bash
# 对象存储
RAG_STORAGE_TYPE=minio
MINIO_ENDPOINT=https://minio.example.internal
MINIO_BUCKET=rag-kb
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...

# Embedding（必须开启，Worker 才能从 QUEUED 进入 READY）
RAG_EMBEDDING_ENABLED=true
RAG_EMBEDDING_ENDPOINT=https://model.example.internal/v1/embeddings
RAG_EMBEDDING_API_KEY=...
RAG_EMBEDDING_MODEL=bge-m3
RAG_EMBEDDING_BATCH_SIZE=32
RAG_EMBEDDING_TIMEOUT_MS=15000

# ES（向量维度必须与 bge-m3/实际模型输出完全一致）
RAG_ES_ENABLED=true
RAG_ES_ENDPOINT=https://es.example.internal:9200
RAG_ES_API_KEY=...
RAG_ES_INDEX_NAME=rag_chunks_v1
RAG_ES_VECTOR_DIMENSIONS=1024

# 只有以上依赖均可用时才开启 Worker
RAG_INGESTION_WORKER_ENABLED=true
RAG_INGESTION_POLL_INTERVAL_MS=1000
RAG_INGESTION_CLEANUP_ENABLED=true

# 检索与 SSE 问答（所有依赖均就绪后再开启）
RAG_RETRIEVAL_ENABLED=true
RAG_RERANK_ENABLED=true
RAG_RERANK_ENDPOINT=https://model.example.internal/v1/rerank
RAG_RERANK_API_KEY=...
RAG_RERANK_MODEL=bge-reranker-v2-m3
RAG_GENERATION_ENABLED=true
RAG_GENERATION_ENDPOINT=https://model.example.internal/v1/chat/completions
RAG_GENERATION_API_KEY=...
RAG_GENERATION_MODEL=your-chat-model
RAG_GENERATION_TIMEOUT_MS=60000
# 标准 OpenAI 流的最终 data 块携带 prompt/completion tokens；不兼容网关可关闭。
RAG_GENERATION_INCLUDE_USAGE=true
RAG_QUERY_ENABLED=true
RAG_QUERY_STREAM_TIMEOUT_MS=120000
RAG_QUERY_WORKER_THREADS=8
```

启动保护：当 `RAG_INGESTION_WORKER_ENABLED=true` 而 Embedding/ES Bean 未配置时，或 `RAG_QUERY_ENABLED=true` 而 Retriever/Generation Bean 未配置时，Spring Boot 会启动失败；这是故意的 fail-fast，不能关闭后伪造 `READY` 或提供未过滤的问答入口。

## 4. API 与权限

所有接口均要求 JWT 和 `X-Org-Id`；资源查询额外用 org/kb 条件过滤，跨组织资源按不存在处理。

| 操作 | 路径 | 权限 | 说明 |
|---|---|---|---|
| 上传 | `POST /api/v1/documents/upload?kbId=` | Owner/Admin | 仅保存原文件并创建 `QUEUED` 任务 |
| 列表 | `GET /api/v1/documents?kbId=&status=` | 已认证成员 | 返回文档摄取状态 |
| 任务查询 | `GET /api/v1/documents/jobs/{jobId}?kbId=` | 已认证成员 | 返回状态、错误与可重试性 |
| 失败重试 | `POST /api/v1/documents/jobs/{jobId}/retry?kbId=` | Owner/Admin | 仅 `FAILED` 且未超过最大尝试次数 |
| 删除 | `DELETE /api/v1/documents/{documentId}?kbId=` | Owner/Admin | 标记 `DELETING` 并执行/重试补偿 |
| 流式问答 | `POST /api/v1/knowledge-bases/{kbId}/query` | 已认证成员 | 服务端锁定 org/kb，返回 SSE；不接收客户端 ES 过滤条件 |

SSE 的 `data:` 是 JSON，严格对应前端已冻结的五类事件：

| event | data | 说明 |
|---|---|---|
| `chunk` | `{ "content": "..." }` | 模型文本增量 |
| `source` | `{ "citation": { ... } }` | 文档名、标题路径、页码/行号、片段与分数 |
| `refusal` | `{ "message": "..." }` | 正常业务拒答，不调用 Generation |
| `done` | `{}` | 正常收尾 |
| `error` | `{ "message": "..." }` | 上游模型或 SSE 异常；消息已脱敏 |

## 5. 状态机与失败处理

```text
QUEUED → PARSING → CHUNKING → EMBEDDING → INDEXING → READY
  任意处理中状态 ───────────────────────────────→ FAILED
FAILED → QUEUED（管理员重试，且 attempt < maxAttempts）
QUEUED/PARSING/CHUNKING/EMBEDDING/INDEXING/FAILED/READY → DELETING
```

- Worker 以 `UPDATE ... WHERE status=QUEUED` 原子领取任务；返回 0 表示已被其他实例领取。
- 所有 Worker 输入是不可变 `IngestionTask`，不跨事务携带 JPA 懒加载实体。
- 单个阶段异常会写入 `ingestion_job.error_message`、`document.last_error` 和 `FAILED`。
- `attempt` 在领取时递增；达到 `max_attempts` 的失败任务保留为死信状态，管理员不能无限重试。
- 删除优先清除 ES 内容，避免内部文档在删除请求后继续作为问答引用出现；对象存储或 ES 暂时故障时保留 `DELETING`，由 `DocumentDeletionWorker` 幂等重试。

## 6. 真实环境验收步骤

### 6.1 迁移与启动

1. 备份生产数据库并检查 Flyway 历史。
2. 先以 `RAG_INGESTION_WORKER_ENABLED=false` 启动，确认 V005 执行成功。
3. 确认 MinIO Bucket、Embedding 网关和 ES 连接可用，再开启 Worker。
4. 检查日志中没有模型 Key、MinIO Secret 或文档正文。

### 6.2 Markdown 验收

上传一份包含标题、代码围栏、类名和配置项的脱敏 Markdown。

验收证据：

```sql
select id, status, retry_count, last_error from document where id = :document_id;
select id, status, attempt, error_message, started_at, finished_at from ingestion_job where document_id = :document_id;
```

预期文档和任务均为 `READY`，任务有 `started_at`/`finished_at`，错误字段为空。

```bash
curl -H "Authorization: ApiKey $RAG_ES_API_KEY" \
  "$RAG_ES_ENDPOINT/rag_chunks_v1/_search?q=document_id:$DOCUMENT_ID&pretty"
```

预期至少有一个 chunk，且每条包含正确的 `org_id`、`kb_id`、`document_id`、`content_vector`、定位 metadata 和模型版本。

### 6.3 PDF 验收

上传一份文本型 PDF，确认 `READY` 后检查 chunk 中至少有 `page_no`。再上传一份扫描 PDF：它必须 `FAILED` 或明确质量不足，不能静默标记 `READY`。

### 6.4 删除验收

删除已 `READY` 的文档：

1. 文档先进入 `DELETING`；
2. ES 查询按该 documentId 返回 0 条；
3. 对象键不存在；
4. 最终 `document` 与关联 `ingestion_job` 记录被删除；
5. 若任一步失败，记录保持 `DELETING`，等待下一次 cleanup，而不是返回伪成功。

### 6.5 混合检索与 SSE 验收

使用已完成摄取的脱敏 Markdown，包含类名、错误码、配置项和普通说明文字。

1. 开启 `RAG_RETRIEVAL_ENABLED`、`RAG_GENERATION_ENABLED` 和 `RAG_QUERY_ENABLED` 后启动应用；确认没有缺失 Bean 的启动异常。
2. 使用有效 JWT 与 `X-Org-Id` 调用：

```bash
curl -N -X POST "http://localhost:8080/api/v1/knowledge-bases/$KB_ID/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Org-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"question":"SearchService 启动失败如何排查？"}'
```

3. 预期先收到一个或多个 `source`，再收到连续 `chunk`，最后收到 `done`；每个 `source.citation.documentName` 必须是原始文件名，不得是 `org/...` 对象键。
4. 使用不存在的问题，预期收到 `refusal` 和 `done`，且 Generation 网关没有请求日志。
5. 临时断开 Rerank，预期仍返回 RRF 结果；临时断开 Embedding，若 BM25 有命中则仍返回基于 BM25 的结果。两类降级均需记录告警但不得输出 Key、Prompt 或文档正文。
6. 使用另一组织的 Token/`X-Org-Id` 查询相同 `KB_ID`，预期 HTTP 404；不得返回任何 `source`、文档名或分数。

### 6.6 审计与可观测性验收

每次问答响应头都应返回 `X-RAG-Trace-Id`。用该值同时查询应用日志和 PostgreSQL：

```sql
select trace_id, org_id, kb_id, member_id, status, retrieval_latency_ms,
       generation_latency_ms, total_latency_ms, embedding_fallback, rerank_fallback,
       generation_model, prompt_tokens, completion_tokens, output_characters, error_code
from rag_query_audit
where trace_id = :trace_id;
```

验收标准：

1. 结构化日志 `rag_query_audit` 与数据库记录含同一 `traceId`；`status` 必须可区分 `COMPLETED`、`REFUSED`、`FAILED`、`CANCELLED`。
2. 命中 chunk ID、文档 ID、最终分数和 Embedding/Rerank 降级标记可追踪；若上游支持标准 `stream_options.include_usage`，应记录 prompt/completion token 数。
3. `rag_query_audit` 表、应用日志和异常堆栈中不得出现问题、模型回答、Prompt、文档片段、MinIO 对象键、API Key 或 Authorization 值。
4. 审计落库失败只能记录服务端错误，不能中断已开始的 SSE 响应。

## 7. 回滚与故障处置

| 场景 | 操作 |
|---|---|
| 模型服务故障 | 关闭 `RAG_INGESTION_WORKER_ENABLED`，保留 `QUEUED/FAILED` 任务；服务恢复后按失败原因手动重试 |
| ES 不可用 | 保持 Worker 关闭，避免重复失败；ES 恢复后重新开启 Worker，不删除原始对象 |
| ES mapping 配错 | 新建版本索引（如 `rag_chunks_v2`）并修改 `RAG_ES_INDEX_NAME`，完成重建与评测后再切换查询 |
| 删除补偿堆积 | 查 `document.status='DELETING'` 与日志；修复 ES/MinIO 后保持 cleanup worker 开启直到清空 |
| 回退应用版本 | 关闭 Worker；V005 不回滚历史字段和任务表，旧版本必须忽略新增字段 |

## 8. 自动化验证

```bash
cd backend
JAVA_HOME=$(/usr/libexec/java_home -v 17) PATH="$JAVA_HOME/bin:$PATH" mvn test
```

当前覆盖：上传权限和白名单、任务原子领取、失败与手动重试、删除清理、Parser/Chunker、模型客户端分批/超时、ES mapping/Bulk/三重过滤、RRF 与两类模型降级、Prompt 上游流解析、五类 SSE 载荷、引用构造、空召回拒答不调用生成模型、无正文审计字段与 token 用量、以及现有认证/租户回归。

自动化测试不替代真实依赖验收：必须按第 6 节完成一份 Markdown、一份文本型 PDF 的真实 `READY` 验收和一轮真实 SSE 问答后，才可宣告 P1/P2 可部署。
