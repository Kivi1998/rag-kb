# 自研 RAG 文档上传、多模态解析与全链路验收手册

> 适用范围：生产级文档上传与多模态解析、P1 摄取与索引、P2 混合检索与 SSE 问答。
>
> 目标：分别给出“文档上传/解析”与“完整 RAG”的实现、部署和验收边界，防止把解析通过误写成 `QUEUED → READY` 全链路通过。

## 1. 当前实现边界

本手册对应自研 RAG Core，不依赖 RAGFlow、LangChain、LlamaIndex 或 Dify。

已经实现：

- PostgreSQL `ingestion_job`、文档对象键、失败信息和重试次数迁移；
- 本地文件系统与 MinIO/S3 兼容对象存储；
- MinIO/S3 预签名直传会话、幂等键、有效期、对象大小回调校验和过期对象分批清理；
- 管理员/Owner 上传、查询任务、重试和删除 API；
- 数据库条件更新领取任务、租约故障接管和长任务心跳，避免多 Worker 重复处理同一 `QUEUED` 任务；
- Markdown、TXT、代码、YAML/JSON/XML、DOCX、文本型 PDF 的解析与结构化切块；
- 独立非 root 多模态解析网关：扫描 PDF/图片 OCR、PPTX 文本与图片 OCR、Word 段落/标题/表格、音视频 ASR 和字幕时间戳；
- 解析产物版本化保存到对象存储，后续 Embedding/索引重试不重复执行高成本 OCR/ASR；
- OpenAI 兼容 Embedding/Rerank/Chat Completions HTTP 客户端；
- 共享 ES 索引 `rag_chunks_v1` 的 mapping、Bulk Upsert、按 org/kb/document 三重过滤删除；
- `DELETING` 删除补偿：优先删除 ES chunk，再删除对象与数据库元数据，失败自动重试。
- ES 原生 BM25 与 kNN 双路召回、RRF 融合、可选 Rerank、低置信度拒答；
- `POST /api/v1/knowledge-bases/{kbId}/query` SSE 接口，稳定输出 `chunk/source/refusal/done/error` 五类事件；
- 服务端引用卡片：从最终 chunk 和本租户文档元数据构造，不向前端暴露对象存储路径；
- Embedding 故障时退化为 BM25，Rerank 故障时退化为 RRF，空召回不调用生成模型。

当前准确状态如下：

| 范围 | 状态 | 可以对外宣称 | 不可以宣称 |
|---|---|---|---|
| MinIO/S3 预签名上传、大小/魔数/SHA-256 校验、幂等完成 | 已通过本机真实依赖技术验收 | 直传能力已实现并通过 5000 次对象生命周期测试 | 生产环境网络/TLS/CORS 已签字 |
| Parser Gateway 与 Java 后端解析集成 | 已通过本机真实依赖技术验收 | 5000 份 DOCX 网关调度测试、单样本 OCR/Office/ASR 功能验证已通过 | 5000 份多格式长文档或 OCR/ASR 生产容量已通过 |
| 解析产物缓存、任务租约/心跳/失败重试 | 已实现并有自动化回归 | 高成本 OCR/ASR 可在后续阶段重试时复用 | 多节点生产故障演练已签字 |
| `QUEUED → READY` 与完整 RAG 问答 | 已实现，尚未完成真实依赖全链路验收 | 可进入下一阶段联调 | 完整 RAG 已达生产级 |

因此，本轮的结论是“上传与多模态解析完成本机真实依赖技术验收”，不是“完整 RAG 生产验收”。

## 2. 运行依赖

| 组件 | 用途 | 最小要求 |
|---|---|---|
| PostgreSQL | 文档、上传会话、任务、解析产物元数据与查询审计 | 已执行 Flyway V001–V010 |
| MinIO/S3 | 原始文件与版本化解析产物 | Bucket 已创建，应用账号可读写该 Bucket |
| Parser Gateway | OCR、PPTX/Word 深度解析、音视频 ASR | `parser-gateway` 镜像 `/ready` 为 `UP` |
| Elasticsearch 8.x | `rag_chunks_v1` 与向量/BM25 索引 | 向量维度与 Embedding 模型一致 |
| Embedding 网关 | 批量向量 | OpenAI `POST /v1/embeddings` 兼容协议 |
| Rerank 网关 | 后续检索精排 | 可选；支持 `query/documents/results` 协议 |
| Generation 网关 | SSE 答案生成 | OpenAI Chat Completions 流式兼容协议 |

ES Java REST Client 采用 8.17 分支。应将客户端主版本与实际 ES 主版本保持一致；本项目不使用 Spring Data Elasticsearch 或 RAG 编排框架。

## 3. 分阶段配置

生产环境不要使用默认本地对象存储，也不要将 API Key 写进仓库。以下变量由部署密钥管理系统或 `application-secret.yml` 提供。

```bash
# 对象存储
RAG_STORAGE_TYPE=minio
MINIO_ENDPOINT=https://minio.example.internal
MINIO_BUCKET=rag-kb
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...

# 上传与解析必需
RAG_DIRECT_UPLOAD_TTL_SECONDS=900
RAG_UPLOAD_MAX_SIZE_BYTES=536870912
RAG_MULTIMODAL_PARSER_ENABLED=true
RAG_MULTIMODAL_PARSER_ENDPOINT=http://parser-gateway:8081/v1/parse
RAG_MULTIMODAL_PARSER_API_KEY=...
RAG_MULTIMODAL_PARSER_TIMEOUT_MS=600000
RAG_METRICS_TOKEN=...

# 索引阶段必需（本轮验收不开启）
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
RAG_INGESTION_WORKER_CONCURRENCY=4
RAG_INGESTION_WORKER_BATCH_SIZE=16
RAG_INGESTION_WORKER_LEASE_DURATION_MS=1800000
RAG_INGESTION_CLEANUP_ENABLED=true

# 检索与 SSE 问答（本轮验收不开启）
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
| 上传 | `POST /api/v1/documents/upload?kbId=` | Owner/Admin | 仅保存原文件并创建 `QUEUED` 任务，返回 `documentId` 与 `jobId` |
| 发起直传 | `POST /api/v1/documents/uploads` | Owner/Admin | 携带 `Idempotency-Key`，返回短期 PUT URL；适合大文件和弱网环境 |
| 完成直传 | `POST /api/v1/documents/uploads/{sessionId}/complete` | Owner/Admin | 锁定会话并校验对象大小，原子创建文档与唯一摄取任务 |
| 列表 | `GET /api/v1/documents?kbId=&status=` | 已认证成员 | 返回文档摄取状态与最近 `jobId`；不返回对象存储路径 |
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

## 4.1 前端工作区行为

`/kb` 工作区已接入自研 RAG API：左侧选择知识库；右侧同时显示文档面板与聊天面板。

- 文档面板支持白名单文件上传、摄取状态轮询、失败原因、基于服务端 `jobId` 的重试与删除；普通成员的管理操作由后端 RBAC 拒绝，前端不伪造权限判断。
- 聊天面板原生解析 `chunk/source/refusal/done/error`；来源卡片只使用服务端 `source` 事件；支持取消当前 fetch/SSE 请求，切换知识库时自动清空会话与取消旧请求。
- 文档对象键、ES 查询条件和模型凭证均不进入浏览器。前端仅发送 JWT、`X-Org-Id`、路径中的 `kbId` 和问题文本。

## 5. 状态机与失败处理

```text
QUEUED → PARSING → CHUNKING → EMBEDDING → INDEXING → READY
  任意处理中状态 ───────────────────────────────→ FAILED
FAILED → QUEUED（管理员重试，且 attempt < maxAttempts）
QUEUED/PARSING/CHUNKING/EMBEDDING/INDEXING/FAILED/READY → DELETING
```

- Worker 以 `UPDATE ... WHERE status=QUEUED` 原子领取任务；返回 0 表示已被其他实例领取。
- Worker 在租约周期的三分之一处使用独立线程续租；进程崩溃后，过期租约可由其他实例重新排队或转为死信。
- 所有 Worker 输入是不可变 `IngestionTask`，不跨事务携带 JPA 懒加载实体。
- OCR/ASR 成功后写入 `*.parsed-v1.json`；后续阶段失败重试优先复用同版本产物，损坏或版本不匹配时自动重新解析。
- 单个阶段异常会写入 `ingestion_job.error_message`、`document.last_error` 和 `FAILED`。
- `attempt` 在领取时递增；达到 `max_attempts` 的失败任务保留为死信状态，管理员不能无限重试。
- 删除优先清除 ES 内容，避免内部文档在删除请求后继续作为问答引用出现；对象存储或 ES 暂时故障时保留 `DELETING`，由 `DocumentDeletionWorker` 幂等重试。

## 6. 真实环境验收步骤

### 6.1 迁移与启动

#### 6.1.1 Parser Gateway 独立部署

```bash
cd parser-gateway
cp .env.example .env
# 使用密钥管理系统写入 PARSER_API_KEY，不要把真实 .env 提交到 Git。
# ASR 验收必须显式确认下列基线；任一命令无输出即停止部署。
grep -E '^PARSER_PRELOAD_WHISPER=true$' .env
grep -E '^PARSER_REQUIRE_ASR_READY=true$' .env
grep -E '^PARSER_WHISPER_MODEL=small$' .env
grep -E '^PARSER_WHISPER_DEVICE=cpu$' .env
grep -E '^PARSER_WHISPER_COMPUTE_TYPE=int8$' .env
docker compose -f compose.production.yml config --quiet
docker compose -f compose.production.yml build --pull
docker compose -f compose.production.yml up -d
docker compose -f compose.production.yml ps
docker compose -f compose.production.yml logs --tail=200 parser-gateway

curl -fsS http://127.0.0.1:8081/ready
docker compose -f compose.production.yml exec parser-gateway id
```

验收预期：`/ready` 返回 `{"status":"UP","asrLoaded":true}`，`id` 显示 uid `10001`。网关使用只读根文件系统、`/tmp` tmpfs、持久化模型缓存卷、能力删除与资源上限。

生产需根据实际文档规模设置 `PARSER_MAX_FILE_BYTES`、`PARSER_MAX_CONCURRENCY`、`PARSER_TMPFS_SIZE`、CPU/内存上限和 Whisper 模型。CPU 环境建议从 `small + int8 + concurrency=2` 起步；启用 GPU 前需另外制作带 CUDA 的锁定版本镜像。后端的 `RAG_MULTIMODAL_PARSER_API_KEY` 必须与 `PARSER_API_KEY` 完全一致。

本手册的标准宿主机端口统一为 `8081`：本机部署时后端端点为 `http://127.0.0.1:8081/v1/parse`；同一 Docker 网络中使用 `http://parser-gateway:8081/v1/parse`。升级时必须用不可变镜像标签/摘要；回滚时恢复上一镜像标签并重新 `up -d`，模型缓存卷不删除。

#### 6.1.2 后端迁移与启动

1. 备份数据库，检查 `flyway_schema_history`，并确认本版本使用 V001–V010。
2. 先以 `RAG_INGESTION_WORKER_ENABLED=false`、`RAG_QUERY_ENABLED=false` 启动后端，确认迁移和健康检查通过。

**终端 A（保持运行）：**

```bash
cd backend
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
export PATH="$JAVA_HOME/bin:$PATH"
RAG_INGESTION_WORKER_ENABLED=false RAG_QUERY_ENABLED=false \
  mvn spring-boot:run
```

**终端 B（待终端 A 显示 `Started` 后执行）：**

```bash
curl -fsS http://127.0.0.1:8080/actuator/health
```

3. 确认 MinIO Bucket 和 Parser Gateway 可用后，只开启上传/解析相关能力。要让任务进入 `READY`，还必须同时完成 Embedding 与 ES 联调；未完成前不以 `READY` 作本轮验收条件。
4. 检查日志中没有模型 Key、MinIO Secret、Authorization 或文档正文。

#### 6.1.3 浏览器直传网络前置条件

- `MINIO_ENDPOINT` 签发的 URL 必须能被浏览器所在网络解析和访问，不能使用仅容器内可见的主机名。
- MinIO/S3 必须配置允许业务前端 Origin 的 `PUT`、`Content-Type` 和预检 CORS；对外地址使用 TLS 与可验证证书。
- 反向代理不应中转大文件 PUT；若必须中转，同步调整 body 上限、超时与禁用请求缓冲。

#### 6.1.4 直传端到端复验

```bash
export API_BASE=http://127.0.0.1:8080
export FILE=/absolute/path/to/acceptance.pdf
export FILE_SIZE=$(stat -f%z "$FILE")

curl -fsS -o /tmp/upload-session.json \
  -X POST "$API_BASE/api/v1/documents/uploads" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Org-Id: $ORG_ID" \
  -H "Idempotency-Key: acceptance-$(date +%s)" \
  -H "Content-Type: application/json" \
  -d "{\"kbId\":\"$KB_ID\",\"fileName\":\"acceptance.pdf\",\"sizeBytes\":$FILE_SIZE}"

export SESSION_ID=$(jq -r '.data.sessionId' /tmp/upload-session.json)
export UPLOAD_URL=$(jq -r '.data.uploadUrl' /tmp/upload-session.json)
curl -fsS -X PUT "$UPLOAD_URL" -H 'Content-Type: application/pdf' --data-binary "@$FILE"

curl -fsS -o /tmp/upload-complete.json \
  -X POST "$API_BASE/api/v1/documents/uploads/$SESSION_ID/complete" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Org-Id: $ORG_ID"

export DOCUMENT_ID=$(jq -r '.data.documentId' /tmp/upload-complete.json)
export JOB_ID=$(jq -r '.data.jobId' /tmp/upload-complete.json)
curl -fsS "$API_BASE/api/v1/documents/jobs/$JOB_ID?kbId=$KB_ID" \
  -H "Authorization: Bearer $TOKEN" -H "X-Org-Id: $ORG_ID" | jq .
```

完成回调会在服务端重新读取对象，校验字节数、文件魔数并计算 SHA-256，随后在同一数据库事务内创建文档和唯一摄取任务。相同幂等键重复发起应返回同一会话，相同会话重复 complete 应返回同一 `documentId/jobId`。

另外必须在环境中负向复验：过期 URL、实际大小与声明不一致、PDF 扩展名伪装非 PDF 内容、重复幂等键、并发 complete。前三类不得创建文档或任务，并发 complete 最终只能存在一份文档和一个任务。

> **状态警示：6.2、6.3 是后续 `QUEUED → READY` 完整索引链路的验收步骤，本轮未执行、不参与“上传/解析”签字。**

### 6.2 后续完整索引链路：Markdown 验收（未执行）

上传一份包含标题、代码围栏、类名和配置项的脱敏 Markdown。

验收证据：

```sql
select id, status, retry_count, last_error from document where id = :document_id;
select id, status, attempt, error_message, started_at, finished_at from ingestion_job where document_id = :document_id;
```

预期文档和任务均为 `READY`，任务有 `started_at`/`finished_at`，错误字段为空。

```bash
curl -H "Authorization: ApiKey $RAG_ES_API_KEY" \
  "$RAG_ES_ENDPOINT/$RAG_ES_INDEX_NAME/_search?q=document_id:$DOCUMENT_ID&pretty"
```

预期至少有一个 chunk，且每条包含正确的 `org_id`、`kb_id`、`document_id`、`content_vector`、定位 metadata 和模型版本。

### 6.3 后续完整索引链路：PDF 验收（未执行）

上传一份文本型 PDF，确认 `READY` 后检查 chunk 中至少有 `page_no`。再上传一份扫描 PDF：它必须经 OCR 返回正文，并在解析 metadata 中标记 `ocr=true`、`ocrPageCount>=1`；OCR 无文本时必须明确失败，不能静默标记 `READY`。

### 6.4 上传与解析技术验收结果（2026-07-13）

本轮在本机 Docker 真实依赖上完成，不是 Mock 或接口占位。这是技术验收，不等于生产集群签字。

| 环境项 | 值 |
|---|---|
| 机器 | Apple M1 Pro，10 CPU，16 GiB RAM，arm64 |
| 容器引擎 | Docker 28.1.1 |
| Parser 镜像 | `sha256:c262f36185744b2e749b0c56666d6cf14970af7f084a608edb7948fcdf8d9f6a` |
| 解析压测并发 | 4 |
| MinIO 压测并发 | 8 |
| 样本 | DOCX 36,829 bytes；MinIO 对象 4,096 bytes；OCR/ASR 为单功能脱敏样本 |

| 验收项 | 数据集/操作 | 结果 | 性能证据 |
|---|---:|---:|---:|
| MinIO 对象生命周期 | 5000 个预签名 PUT + stat + delete | 5000/5000，成功率 100% | 5.184s，964.463 次/s，P95 12ms，P99 16ms |
| Parser Gateway 调度与 DOCX 解析 | 5000 份含标题、正文、表格的 DOCX | 5000/5000，成功率 100% | 35.933s，139.147 份/s，P95 49.397ms，P99 61.017ms |
| 扫描 PDF OCR | 图片型 PDF | 识别 `RAG PRODUCTION OCR ACCEPTANCE 2026` | metadata 含 `ocr=true` |
| PPTX | 标题、正文 | 页码、标题路径和正文返回正确 | 真实容器通过 |
| Word | 标题、段落、表格 | 结构化 section 返回正确 | 真实容器通过 |
| 音频 ASR | WAV 英文语音 | 文本完整，带字幕时间戳 | `00:00:00.000 --> 00:00:04.760` |
| Java → Parser Gateway | HTTP/1.1 二进制流 | 真实扫描 PDF 解析通过 | 集成测试通过 |

准确结论：系统已具备 5000+ 文档的对象存储与解析队列工程基础，已证明 5000 份 DOCX 网关调度能力和单样本多格式功能。当前没有证明“5000 份多格式长文档已全部通过生产容量测试”。

生产签字前还需完成：

- 经后端 `/uploads → PUT → complete → 解析产物` 的多格式混合数据集容量测试；
- 仅含图片文字的 PPTX OCR 样本、MP4/MOV/MKV 真实视频容器与编解码兼容测试；
- 按真实页数、分辨率、音视频时长与生产 CPU/GPU 分层的 OCR/ASR 容量测试；
- 生产同构环境的 TLS/CORS、多 Worker 故障接管、日志脱敏、告警与 24 小时稳定性测试。

可复验命令：

```bash
# 真实 MinIO：5000 次 PUT/stat/delete
cd backend
JAVA_HOME=$(/usr/libexec/java_home -v 17) \
RAG_MINIO_TEST_ENDPOINT=http://127.0.0.1:19000 \
RAG_MINIO_TEST_ACCESS_KEY="$RAG_MINIO_TEST_ACCESS_KEY" \
RAG_MINIO_TEST_SECRET_KEY="$RAG_MINIO_TEST_SECRET_KEY" \
RAG_MINIO_LOAD_TEST_COUNT=5000 RAG_MINIO_LOAD_TEST_CONCURRENCY=8 \
mvn -q -Dtest=MinioObjectStorageIT test

# Parser Gateway：5000 份 DOCX
cd ../parser-gateway
python3 scripts/load_test.py --endpoint http://127.0.0.1:8081/v1/parse \
  --api-key "$PARSER_API_KEY" --file /absolute/path/to/load-sample.docx \
  --total 5000 --concurrency 4
```

> **状态警示：6.5–6.7 依赖真实 ES、Embedding 和 Generation，均是下一阶段验收方案，本轮未执行。**

### 6.5 后续完整 RAG：删除验收（未执行）

删除已 `READY` 的文档：

1. 文档先进入 `DELETING`；
2. ES 查询按该 documentId 返回 0 条；
3. 对象键不存在；
4. 最终 `document` 与关联 `ingestion_job` 记录被删除；
5. 若任一步失败，记录保持 `DELETING`，等待下一次 cleanup，而不是返回伪成功。

### 6.6 后续完整 RAG：混合检索与 SSE 验收（未执行）

使用已完成摄取的脱敏 Markdown，包含类名、错误码、配置项和普通说明文字。

1. 开启 `RAG_RETRIEVAL_ENABLED`、`RAG_GENERATION_ENABLED` 和 `RAG_QUERY_ENABLED` 后启动应用；确认没有缺失 Bean 的启动异常。
2. 使用有效 JWT 与 `X-Org-Id` 调用：

```bash
curl -N -D /tmp/rag-query.headers -X POST "http://localhost:8080/api/v1/knowledge-bases/$KB_ID/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Org-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"question":"SearchService 启动失败如何排查？"}'
```

3. 预期收到一个或多个 `source`、连续 `chunk` 并以 `done` 正常收尾；客户端不应依赖 `source` 与 `chunk` 的绝对顺序。每个 `source.citation.documentName` 必须是原始文件名，不得是 `org/...` 对象键。
4. 使用不存在的问题，预期收到 `refusal` 和 `done`，且 Generation 网关没有请求日志。
5. 临时断开 Rerank，预期仍返回 RRF 结果；临时断开 Embedding，若 BM25 有命中则仍返回基于 BM25 的结果。两类降级均需记录告警但不得输出 Key、Prompt 或文档正文。
6. 使用另一组织的 Token/`X-Org-Id` 查询相同 `KB_ID`，预期 HTTP 404；不得返回任何 `source`、文档名或分数。

### 6.7 后续完整 RAG：审计与可观测性验收（未执行）

每次问答响应头都应返回 `X-RAG-Trace-Id`。用该值同时查询应用日志和 PostgreSQL：

```sql
select trace_id, org_id, kb_id, member_id, status, retrieval_latency_ms,
       generation_latency_ms, total_latency_ms, embedding_fallback, rerank_fallback,
       generation_model, prompt_tokens, completion_tokens, output_characters, error_code
from rag_query_audit
where trace_id = :trace_id;
```

验收标准：

1. 应用结构化日志事件与数据库表 `rag_query_audit` 的记录含同一 `traceId`；`status` 必须可区分 `COMPLETED`、`REFUSED`、`FAILED`、`CANCELLED`。
2. 命中 chunk ID、文档 ID、最终分数和 Embedding/Rerank 降级标记可追踪；若上游支持标准 `stream_options.include_usage`，应记录 prompt/completion token 数。
3. `rag_query_audit` 表、应用日志和异常堆栈中不得出现问题、模型回答、Prompt、文档片段、MinIO 对象键、API Key 或 Authorization 值。
4. 审计落库失败只能记录服务端错误，不能中断已开始的 SSE 响应。
5. Prometheus 使用 `X-Metrics-Key: $RAG_METRICS_TOKEN` 拉取 `/actuator/prometheus`；至少应包含 `rag_upload_sessions_total`、`rag_ingestion_queue_depth`、`rag_ingestion_in_flight`、`rag_ingestion_stage_duration_seconds`。未配置密钥返回 503，错误密钥返回 401。

监控端点复验：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/actuator/prometheus
curl -sS -o /dev/null -w '%{http_code}\n' -H 'X-Metrics-Key: wrong' \
  http://127.0.0.1:8080/actuator/prometheus
curl -fsS -H "X-Metrics-Key: $RAG_METRICS_TOKEN" \
  http://127.0.0.1:8080/actuator/prometheus \
  | grep -E 'rag_upload_sessions_total|rag_ingestion_queue_depth|rag_ingestion_in_flight|rag_ingestion_stage_duration_seconds'
```

Prometheus 需使用支持自定义 HTTP Header 的密钥注入方式；若所用版本的原生 `scrape_config` 不支持自定义 Header，在内网反向代理/ServiceMonitor 中注入 `X-Metrics-Key`，不将密钥写进仓库。Parser Gateway 的 `/ready` 应被独立健康监控，容器 CPU、内存、tmpfs 和 GPU 指标由容器/节点监控采集。

生产初始告警建议（上线后按基线调整）：

| 信号 | 初始阈值 | 处置 |
|---|---|---|
| Parser `/ready` | 连续 2 分钟非 200 | 停止扩大摄取，检查模型缓存/tmpfs |
| `rag_ingestion_queue_depth` | 连续 15 分钟增长 | 区分 Parser、Embedding、ES 瓶颈后扩容 |
| `rag_ingestion_in_flight` | 长时间不下降且无心跳 | 查租约、Worker 线程和对象存储超时 |
| 阶段失败率 | 5 分钟 > 5% | 按 parser/embedding/indexing 分组告警 |
| `FAILED` 达最大重试 | 任意新增 | 进入死信处理清单，不自动无限重试 |
| `DELETING` | 超过 30 分钟 | 检查 ES/MinIO 并验证不再被检索 |

## 7. 回滚与故障处置

| 场景 | 操作 |
|---|---|
| Parser 故障 | 暂停摄取 Worker，保留原文件；网关 `/ready` 恢复后筛选 parsing 失败任务手动重试 |
| Embedding 故障 | 暂停摄取 Worker，不影响已 `READY` 文档的 BM25 降级检索；恢复后批量重试 embedding 失败任务 |
| Rerank 故障 | 不关闭摄取 Worker，查询自动降级为 RRF，同时告警 |
| Generation 故障 | 不关闭摄取 Worker，暂停/降级问答入口，不影响上传和索引 |
| ES 不可用 | 暂停 Worker 避免重复失败；ES 恢复后先筛选 `status='FAILED'` 且 `error_message` 为索引阶段的任务，调用管理员 retry，再开启 Worker |
| ES mapping 配错 | 新建版本索引（如 `rag_chunks_v2`）并修改 `RAG_ES_INDEX_NAME`，完成重建与评测后再切换查询 |
| 删除补偿堆积 | 查 `document.status='DELETING'` 与日志；修复 ES/MinIO 后保持 cleanup worker 开启直到清空 |
| 回退应用版本 | 关闭 Worker；Flyway V006–V010 为向前兼容的表/字段/索引增量变更，不在事故中直接删列回滚。旧应用必须已验证可忽略新列；否则不允许回退，只能向前修复 |

## 8. 自动化验证

```bash
cd backend
JAVA_HOME=$(/usr/libexec/java_home -v 17) PATH="$JAVA_HOME/bin:$PATH" mvn test

# 真实 Parser Gateway 集成测试（需先启动网关）
JAVA_HOME=$(/usr/libexec/java_home -v 17) \
RAG_MULTIMODAL_TEST_ENDPOINT=http://127.0.0.1:8081/v1/parse \
RAG_MULTIMODAL_TEST_API_KEY="$PARSER_API_KEY" \
mvn -q -Dtest=MultimodalGatewayIT test

# 真实 MinIO 生命周期（容量参数未设置时，5000 次用例会明确 skip）
JAVA_HOME=$(/usr/libexec/java_home -v 17) \
RAG_MINIO_TEST_ENDPOINT=http://127.0.0.1:19000 \
mvn -q -Dtest=MinioObjectStorageIT test
```

默认 `mvn test` 仅能证明自动化单元/应用集成回归；真实 MinIO、Parser Gateway、OCR/ASR 和容量脚本必须按上述命令显式启动依赖并传入环境变量，不得把 skip 计为通过。

当前覆盖：上传权限和白名单、预签名直传幂等与完成回调、字节数/魔数/SHA-256 完整性、真实 MinIO 生命周期与容量、任务原子领取/租约/心跳、失败与手动重试、解析产物版本缓存、删除清理、Parser/Chunker、真实 OCR/ASR 网关联调、Prometheus 密钥、模型客户端分批/超时、ES mapping/Bulk/三重过滤、RRF 与两类模型降级、五类 SSE 载荷、引用构造、空召回拒答、审计字段与现有认证/租户回归。

本轮可以宣告“文档上传与多模态解析完成本机真实依赖技术验收”；生产同构环境签字和“完整 RAG 问答链路”验收仍需按本手册的未验收清单继续执行。
