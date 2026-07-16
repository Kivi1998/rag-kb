# rag-kb —— 企业技术文档知识库

面向内部技术团队的多租户 RAG 知识库。系统解决技术文档、接口说明、配置、故障记录和代码片段分散在群聊中、难以检索的问题。

当前 RAG 主链路为**自研 RAG Core**，不依赖 RAGFlow、LangChain、LlamaIndex 或 Dify 等高层编排框架。

## 当前能力

- 组织、团队、成员、JWT、RBAC 与知识库管理；
- MinIO/S3 预签名直传、幂等上传会话、文件魔数/大小/SHA-256 校验；
- PostgreSQL `ingestion_job` + 双 Worker 异步摄取、租约心跳、过期任务接管与失败重试；
- Markdown、代码、JSON/YAML/XML、DOCX、PPTX、文本 PDF、扫描 PDF、图片、字幕、音频和视频解析；
- 独立 Parser Gateway 提供 OCR、ASR、Office 图片提取和字幕时间戳；
- 结构感知切块（V3）：多风格层级识别、递归多级级联、表格分组+表头重复、句子边界重叠、chunk 元数据（sectionPath/contentType/isKeyClause/prev-nextChunkId）；
- Elasticsearch BM25 + kNN + RRF、可选 Rerank、服务端引用与 SSE 问答；
- 多轮对话与记忆管理：滑动窗口+语义历史检索+摘要压缩、用户画像+读时衰减遗忘机制、指代消解（2026-07-15 新增，学习性质的能力储备，当前规模非刚需驱动）；历史会话列表：可折叠侧边栏切换/删除历史对话，刷新页面自动恢复上一次会话；
- 离线评测（Recall@k/MRR/拒答 F1 框架 + 150 题真实语料评估集 eval-set-v2）、查询审计、指标与生产同构验收栈。

## 技术架构

```text
Vue 前端
  └─ Spring Boot
       ├─ JWT / 多租户 / RBAC / 知识库 / 文档任务
       └─ ragcore（自研）
            ├─ Parser / TechnicalChunker
            ├─ Embedding / Rerank / Generation Client
            ├─ Elasticsearch：BM25 + kNN + RRF
            ├─ Conversation Memory：滑动窗口 / 指代消解 / 用户画像
            ├─ 引用、拒答、SSE 与审计
            └─ Worker、重试、指标与评测

PostgreSQL：业务数据、任务与会话元数据（chat_session）
MinIO/S3：原文件与解析产物
Elasticsearch：Chunk、全文与向量；统一记忆索引（rag_memory_v1）
Redis：JWT 黑名单（DB 0）+ 会话记忆滑动窗口（DB 1，rag-kb 专属实例）
MongoDB：会话消息长期存档 + 用户画像条目（只服务记忆子系统）
Parser Gateway：OCR / ASR / 多模态解析
模型服务：OpenAI 兼容的 Embedding / Rerank / LLM
```

## 目录说明

```text
frontend/        Vue 前端：知识库、文档上传、状态、聊天和引用
backend/         Spring Boot 应用与自研 ragcore
parser-gateway/  Python 多模态解析服务（OCR、ASR、音视频）
acceptance/      5000 份多模态文档生产同构验收环境与报告
eval/            离线评测集、Recall@K、MRR、拒答率脚本
docs/            架构、任务、验收与运行手册
openspec/        需求规格与变更记录
```

## 已验证范围

文档上传与解析已在本机生产同构环境完成 5000 份多模态文档全链路验收：5000/5000 最终 `READY`、0 失败，覆盖 OCR、ASR、MinIO、Elasticsearch、双 Worker 故障接管与 Embedding 瞬时 503 重试。

检索问答全链路（真实 Xinference Embedding/Rerank + DeepSeek 生成模型）已完成端到端人工验证：上传 → 解析 → 切块 → 向量化 → ES 索引 → BM25+kNN+RRF → Rerank → SSE 问答 → 引用，全部走通。

切分与检索质量已完成正式离线评测：150 题人工标注评估集（`eval/datasets/eval-set-v2.jsonl`，26 篇本科毕设真实文档 / 885 个 V3 切块）× 产品完整混合检索链（BM25 + bge-m3 kNN + RRF + bge-reranker-v2-m3，含已校准的 rerank 分数拒答门槛），实测 **Recall@1 = 0.816、Recall@5 = 0.904、MRR = 0.849、拒答 F1 = 0.564**（硅基流动在线模型，报告见 `eval/reports/eval-v2-calibrated-20260714.md`）。拒答门槛对"检索真找不到相关内容"（OUT_OF_SCOPE/LOW_CONFIDENCE）有效，对"主题相关但事实缺失"（NO_RETRIEVAL）和"内容合规"（SAFETY）类拒答存在机制性局限，需独立方案（详见指南与 TODOS）。评估集为 AI 单标注人构建，业务专家盲标复核待补。方法论与完整状态见 [解析-切块-评估指南](docs/解析-切块-评估指南.md)。

以下仍需在目标环境单独验收：日均 5000 次查询容量、拒答/降级/跨组织隔离的自动化用例、生产网络 TLS/CORS 和 24 小时稳定性。

## 文档入口

按处理流程分模块索引；每个模块先列**权威文档**，再列**核心代码**，直接对应到最新实现。

### 1. 文档上传

- 文档：[上传、解析与部署验收手册](docs/自研RAG摄取部署与验收手册.md)（预签名直传、幂等会话、字节数/魔数/SHA-256 校验、任务租约与失败重试）、[5000 份多模态文档生产验收报告](docs/文档上传与多模态解析生产验收报告.md)、[验收环境复现说明](acceptance/README.md)
- 代码：[`DocumentDirectUploadService.java`](backend/src/main/java/com/diit/ragkb/service/DocumentDirectUploadService.java)（预签名直传）、[`DocumentIngestionService.java`](backend/src/main/java/com/diit/ragkb/service/DocumentIngestionService.java)（对象存储键、摄取任务创建）、[`ragcore/upload/`](backend/src/main/java/com/diit/ragkb/ragcore/upload)（`DocumentUploadPolicy`/`UploadContentInspector` 白名单与内容校验）、[`ragcore/storage/`](backend/src/main/java/com/diit/ragkb/ragcore/storage)（`ObjectStorage` 接口 + `LocalObjectStorage`/`MinioObjectStorage` 双实现）

### 2. 文档解析

- 文档：[解析、切块与评估指南](docs/解析-切块-评估指南.md)（三环节权威入口：能力边界与当前状态）、[上传、解析与部署验收手册](docs/自研RAG摄取部署与验收手册.md)（Parser Gateway 部署与依赖）
- 代码：[`ragcore/parser/`](backend/src/main/java/com/diit/ragkb/ragcore/parser)（`DocumentParser` 接口 + `MarkdownParser`/`DocxParser`/`PdfParser`/`PptxParser`/`CodeParser`/`StructuredDataParser`/`TextParser`/`SubtitleParser` 等按格式实现）、[`HttpMultimodalDocumentParser.java`](backend/src/main/java/com/diit/ragkb/ragcore/parser/impl/HttpMultimodalDocumentParser.java)（对接独立解析网关）、[`parser-gateway/`](parser-gateway)（Python OCR/ASR/Office 图片提取服务）

### 3. 文档切块

- 文档：[解析、切块与评估指南](docs/解析-切块-评估指南.md)（V3 结构感知五招式权威说明）、[结构感知切分 V3 实现计划](docs/superpowers/plans/2026-07-14-structure-aware-chunking-v3.md)
- 代码：[`Chunker.java`](backend/src/main/java/com/diit/ragkb/ragcore/chunk/Chunker.java)（接口）、[`TechnicalChunker.java`](backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/TechnicalChunker.java)（V3 实现：层级识别、递归级联、表格分组、句子边界重叠、chunk 元数据）

### 4. Embedding

- 文档：[总体架构](docs/architecture.md)（决策 2：直接使用基础设施，不用高层 RAG 框架，含 Embedding/Rerank/LLM 客户端选型）
- 代码：[`EmbeddingClient.java`](backend/src/main/java/com/diit/ragkb/ragcore/embedding/EmbeddingClient.java)（接口）、[`OpenAiCompatibleEmbeddingClient.java`](backend/src/main/java/com/diit/ragkb/ragcore/embedding/OpenAiCompatibleEmbeddingClient.java)（OpenAI 兼容实现，当前对接硅基流动 `BAAI/bge-m3`）

### 5. 检索召回（混合检索）

- 文档：[总体架构](docs/architecture.md)、[上传、解析与部署验收手册](docs/自研RAG摄取部署与验收手册.md) 第 6.6 节（混合检索与 SSE 验收）
- 代码：[`HybridRetriever.java`](backend/src/main/java/com/diit/ragkb/ragcore/retrieval/HybridRetriever.java)（编排：BM25+kNN 召回→RRF 融合→可选 Rerank→拒答判定）、[`ElasticsearchHybridCandidateSource.java`](backend/src/main/java/com/diit/ragkb/ragcore/retrieval/ElasticsearchHybridCandidateSource.java)（ES 原生 BM25/kNN 双路 DSL）、[`RrfFusion.java`](backend/src/main/java/com/diit/ragkb/ragcore/retrieval/RrfFusion.java)（倒数排名融合）、[`ElasticsearchChunkIndex.java`](backend/src/main/java/com/diit/ragkb/ragcore/index/ElasticsearchChunkIndex.java)（`rag_chunks_v1` mapping 与 Bulk Upsert）、[`RetrievalOptions.java`](backend/src/main/java/com/diit/ragkb/ragcore/retrieval/RetrievalOptions.java)（候选池大小/topK/documentIds 过滤等可调参数）

### 6. Rerank 与检索优化

- 文档：[总体架构](docs/architecture.md)决策 7（拒答阈值 `MIN_RERANK_SCORE=0.06` 的实验方法与结论摘要）、[拒答阈值校准报告](eval/reports/refusal-threshold-calibration-20260714.md)（完整数据与阈值扫描表）、[复现脚本](eval/scripts/analyze_refusal_threshold.py)、[候选池大小调优实验](eval/reports/candidate-pool-size-tuning-20260715.md)（candidateLimit 从 50 降到 10/20/30 的 Recall/延迟实测对比）、[延后事项清单](TODOS.md)（RRF 融合动态权重等待办）
- 代码：[`RerankerClient.java`](backend/src/main/java/com/diit/ragkb/ragcore/rerank/RerankerClient.java)（接口）、[`OpenAiCompatibleRerankerClient.java`](backend/src/main/java/com/diit/ragkb/ragcore/rerank/OpenAiCompatibleRerankerClient.java)（Cross-Encoder 兼容实现，当前对接硅基流动 `BAAI/bge-reranker-v2-m3`）

### 7. 多轮对话与记忆管理

- 文档：[brainstorming 设计文档](docs/superpowers/specs/2026-07-15-conversation-memory-design.md)（架构决策与备选方案对比）、[OpenSpec change: conversation-memory](openspec/changes/conversation-memory/)（proposal/design/specs/tasks）
- 代码：[`ConversationMemoryOrchestrator.java`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/ConversationMemoryOrchestrator.java)（编排入口：滑动窗口→指代消解→画像检索/生成后持久化+异步提炼）、[`SlidingWindowAssembler.java`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/SlidingWindowAssembler.java)（token 预算滑动窗口+摘要压缩，压缩失败 fail-open）、[`DeepSeekCoreferenceResolver.java`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/impl/DeepSeekCoreferenceResolver.java)（窄范围指代消解）、[`MemoryItemStoreImpl.java`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/impl/MemoryItemStoreImpl.java)（用户画像语义去重+读时衰减遗忘机制，读回 MongoDB 后二次校验租户归属）、[`ElasticsearchMemoryIndex.java`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/impl/ElasticsearchMemoryIndex.java)（统一记忆索引 `rag_memory_v1`）、[`ChatSessionService.java`](backend/src/main/java/com/diit/ragkb/service/ChatSessionService.java)（会话生命周期，不受 `rag.memory.enabled` 门控、始终校验 org/kb/member 三重归属）、[`RagSessionPropertiesConfiguration.java`](backend/src/main/java/com/diit/ragkb/config/RagSessionPropertiesConfiguration.java)（把会话生命周期用到的配置从 `RagMemoryConfiguration` 的特性开关中解耦出来常驻注册）
- 存储：Redis（`rag-kb-dev-redis` 专属实例，逻辑 DB 1）+ MongoDB（`chat_messages`/`memory_items`）+ Elasticsearch（复用现有集群，新索引）+ Postgres（`chat_session` 元数据）
- `/review` 评审门发现并修复的 10 项问题（2026-07-15）：跨知识库会话消息泄露、记忆关闭时 sessionId 不校验、画像读取未二次核实租户、ES cosine 去重阈值未做 `(1+cos)/2` 归一化换算、摘要压缩失败缺 fail-open、画像生成 N+1 查询、同一问题重复调用 Embedding 等，详见 `git log` 中 `fix: 修复 /review 评审门发现的10项问题` 提交

### 8. 历史会话列表

- 文档：[brainstorming 设计文档](docs/superpowers/specs/2026-07-15-conversation-history-list-design.md)、[OpenSpec change: conversation-history-list](openspec/changes/conversation-history-list/)
- 背景：多轮对话记忆功能上线后，前端此前每次挂载/刷新都无条件新建会话、不消费已有的会话生命周期与长期存档能力，导致"刷新即清空对话"、也没有历史对话入口；本能力补齐前端消费侧
- 代码（后端）：`ChatSessionService.listSessions/deleteSession`（新增 `GET`/`DELETE .../sessions` 接口；标题为首条用户消息前 30 字，写入时算好存 `chat_session.title`，避免列表查询 N+1 现取）、`MemoryIndex.deleteBySession`/`ChatMessageRepository.deleteBySessionIdAndOrganizationIdAndMemberId`/`ConversationStore.deleteSession`（硬删除级联清理 ES→Mongo/Redis→Postgres，不影响 `memory_items` 长期画像）
- 代码（前端）：[`ChatHistorySidebar.vue`](frontend/src/components/ChatHistorySidebar.vue)（可折叠历史侧边栏：列表/切换/删除/新建对话）、`ChatPanel.vue` 用 `localStorage`（`rag-kb:last-session:{kbId}`）记录当前会话，刷新/重新进入时优先恢复历史而非总是新建，恢复失败（如已删除）时自动退回新建

### 评测框架（跨模块）

- [离线评测框架](eval/README.md) · [150 题评估集说明](eval/datasets/README.md)（`eval-set-v2.jsonl`，v1 已废弃） · [评测集构建工具](eval/scripts/README.md)
- 权威基线报告：[eval-v2-calibrated-20260714](eval/reports/eval-v2-calibrated-20260714.md)（Recall@1=0.816、Recall@5=0.904、MRR=0.849、拒答F1=0.564）

### 架构与其他

- [总体架构](docs/architecture.md) · [自研 RAG 核心重构设计](docs/自研RAG核心重构架构设计.md)（含各阶段完成状态）
- [RAG 重构可复用资产清单](docs/RAG重构可复用资产清单.md)（第三方/内部代码复用与许可边界）
- [变更记录](CHANGELOG.md)
- `docs/archive/` — 已完成阶段的历史规划稿（任务分工、迁移设计），仅供追溯，不代表当前状态

## 本地开发环境访问地址

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端 Vue dev server | http://localhost:5173 | `cd frontend && pnpm dev` |
| 后端 Spring Boot API | http://localhost:8090 | `/actuator/health` 查健康状态 |
| PostgreSQL | localhost:5432 | 本机 Homebrew `postgresql@17`（非容器），库名 `ragkb` |
| Elasticsearch | http://localhost:9200 | 容器 `rag-kb-dev-es`，索引 `rag_chunks_v1` |
| Kibana | http://localhost:5601 | 容器 `rag-kb-dev-kibana`，图形化查看 ES 索引/文档 |
| MinIO API | http://localhost:9010 | 容器 `rag-kb-dev-minio`，bucket `rag-kb` |
| MinIO 控制台 | http://localhost:9011 | 账号密码见本机 `.env` 的 `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` |
| Redis | localhost:6380 | 容器 `rag-kb-dev-redis`（rag-kb 专属，2026-07-15 起不再共用 `thxpace-redis-local`）；DB 0 = JWT 黑名单，DB 1 = 会话记忆滑动窗口 |
| MongoDB | localhost:27018 | 容器 `rag-kb-dev-mongo`，库 `rag_kb_memory`，只服务会话记忆子系统（`chat_messages`/`memory_items`），账号密码见 `.env` |
| Parser Gateway | http://localhost:8081 | `/v1/parse` 解析接口，`/health`/`/ready`/`/metrics` |

以上均为本机开发环境地址，随本机 Docker/进程状态变化；生产环境地址由部署配置另行提供，见 [上传、解析与部署验收手册](docs/自研RAG摄取部署与验收手册.md)。

## 开发流程

项目使用 OpenSpec 管理需求与变更，并通过自动化测试、验收环境和代码审查保障交付质量。

```bash
cd backend
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
export PATH="$JAVA_HOME/bin:$PATH"
mvn test
```

完整上传/解析验收步骤见 [acceptance/README.md](acceptance/README.md)。

## 开发者

Hao Jia · jiahao@diit.cn
