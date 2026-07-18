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
- Elasticsearch BM25 + kNN + RRF、可选 Rerank、服务端引用与 SSE 问答；向量检索可切流至 Milvus（ES/Milvus/影子三模式，默认仍为 ES kNN，2026-07-18 新增，观察期内未默认启用）；
- 多轮对话与记忆管理：滑动窗口+语义历史检索+摘要压缩、用户画像+读时衰减遗忘机制、指代消解（2026-07-15 新增，学习性质的能力储备，当前规模非刚需驱动）；历史会话列表：切换/删除历史对话，刷新页面自动恢复上一次会话；
- 生成阶段防幻觉：NO_RETRIEVAL 事实核验（生成模型自判 `{"found":true/false}`）+ 生成后自检（复用 Reranker 逐句核查资料支撑，已知对"部分相关的编造"拦截力不足，见 TODOS）；
- 引用溯源：点击正文里的 `[资料N]` 在右侧抽屉展示对应来源的文档名/定位/原文片段，历史会话恢复后同样可点击（2026-07-17 起持久化到消息记录，此前上线的旧消息不回填）；
- 知识库管理：列表项右键菜单（重命名/删除/查看技术文档），技术文档改为独立页面（`/kb/:kbId/documents`），问答区占满工作区主区域；
- 单文档直接问答（临时文档，长上下文直接塞入，2026-07-18 新增）：会话内上传的临时文档不写入知识库、不切块不索引，会话级共享 15000 字符总额度池，超额拒绝新上传；知识库检索触发拒答阈值但当前会话存在临时文档时不拒答，改用临时文档内容回答；
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
Elasticsearch：Chunk、全文与向量（默认）；统一记忆索引（rag_memory_v1）
Milvus：可选向量投影（rag_chunks_vector_v1，`rag.vector.provider` 切流，默认关闭）
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

切分与检索质量已完成正式离线评测：150 题人工标注评估集（`eval/datasets/eval-set-v2.jsonl`，26 篇本科毕设真实文档 / 885 个 V3 切块）× 产品完整混合检索链（BM25 + bge-m3 kNN + RRF + bge-reranker-v2-m3，含已校准的 rerank 分数拒答门槛），实测 **Recall@1 = 0.816、Recall@5 = 0.904、MRR = 0.849、拒答 F1 = 0.564**（硅基流动在线模型，报告见 `eval/reports/eval-v2-calibrated-20260714.md`）。拒答门槛对"检索真找不到相关内容"（OUT_OF_SCOPE/LOW_CONFIDENCE）有效；"主题相关但事实缺失"（NO_RETRIEVAL）类已通过生成阶段事实核验补上（8/8 命中，见第 9 章）；"内容合规"（SAFETY）类拒答仍无方案，需独立内容安全分类器（详见 TODOS）。评估集为 AI 单标注人构建，业务专家盲标复核待补。方法论与完整状态见 [评估指南](docs/评估指南.md)。

以下仍需在目标环境单独验收：日均 5000 次查询容量、拒答/降级/跨组织隔离的自动化用例、生产网络 TLS/CORS 和 24 小时稳定性。

## 文档入口

按 RAG 链路分 10 章索引；**每章引用属于自己的专属文档**（一份文档只被一章展开完整细节，
个别内容横跨阶段的文档允许被其他章节简要引用并指回权威章节），每章先列权威文档，再列
核心代码，直接对应到最新实现。

### 第 1 章 RAG 整体架构

- 文档：[总体架构](docs/architecture.md)（决策 1~12：单体模块化、不用高层 RAG 框架、技术文档优先、多租户隔离、记忆子系统、拒答阈值、事实核验、引用展示、单文档问答、Milvus 向量检索迁移等）、[自研 RAG 核心重构设计](docs/自研RAG核心重构架构设计.md)（分阶段实施设计、试点验收线与 P95/QPS 观测记录）、[RAG 重构可复用资产清单](docs/RAG重构可复用资产清单.md)（第三方/内部代码复用与许可边界）

### 第 2 章 文档上传

支持的文档类型：Markdown、代码、JSON/YAML/XML、DOCX、PPTX、文本 PDF、扫描 PDF、图片、
字幕、音频和视频（扫描件/图片/音视频经独立 Parser Gateway 走 OCR/ASR）。

- 文档：[上传摄取部署与验收手册](docs/上传摄取部署与验收手册.md)（预签名直传、幂等会话、字节数/魔数/SHA-256 校验、任务租约与失败重试、部署与验收步骤）、[5000 份多模态文档生产验收报告](docs/文档上传与多模态解析生产验收报告.md)、[验收环境复现说明](acceptance/README.md)
- 代码：[`DocumentDirectUploadService.java`](backend/src/main/java/com/diit/ragkb/service/DocumentDirectUploadService.java)（MinIO/S3 预签名直传）、[`DocumentIngestionService.java`](backend/src/main/java/com/diit/ragkb/service/DocumentIngestionService.java)（`ingestion_job` 状态机、双 Worker 租约与失败重试）、[`ragcore/upload/`](backend/src/main/java/com/diit/ragkb/ragcore/upload)、[`ragcore/storage/`](backend/src/main/java/com/diit/ragkb/ragcore/storage)

### 第 3 章 文档解析与切分

覆盖解析 → 切块 → 用 QA 评估集量化切分效果三个子环节：

- **解析策略（按文档类型）**：[解析指南](docs/解析指南.md)（各格式解析策略、deepdoc 集成、能力边界与已知限制、Parser Gateway 独立部署）；代码：[`ragcore/parser/`](backend/src/main/java/com/diit/ragkb/ragcore/parser)（`DocumentParser` 接口 + 按格式实现）、[`HttpMultimodalDocumentParser.java`](backend/src/main/java/com/diit/ragkb/ragcore/parser/impl/HttpMultimodalDocumentParser.java)、[`parser-gateway/`](parser-gateway)（Python OCR/ASR/Office 图片提取服务）
- **切分策略**：[切块指南](docs/切块指南.md)（V3 结构感知五招式：多风格标题层级识别、递归多级级联、表格分组+表头重复、句子边界重叠、chunk 元数据 sectionPath/contentType/isKeyClause/prev-nextChunkId）、[V3 实现计划](docs/superpowers/plans/2026-07-14-structure-aware-chunking-v3.md)；代码：[`Chunker.java`](backend/src/main/java/com/diit/ragkb/ragcore/chunk/Chunker.java)（接口）、[`TechnicalChunker.java`](backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/TechnicalChunker.java)（V3 实现）
- **用 QA 评估集量化切分效果**：核心方法论——没有评估集的切分优化都是自嗨，做法是人工出题+标注 ground-truth chunk，对比不同切分策略下 Recall@k/MRR 横向变化；权威基线 **Recall@1=0.816 / Recall@5=0.904 / MRR=0.849**（150 题人工标注集 `eval-set-v2`，26 篇真实文档/885 个 V3 切块）。完整方法论、评估集构建流程与全部数字来源见第 10 章「系统评估与上线优化」的 [评估指南](docs/评估指南.md)（本章不重复展开）

### 第 4 章 Embedding 与向量存储

- **Embedding 模型选择**：[Embedding 指南](docs/Embedding指南.md)（选型过程：bge-large-zh-v1.5→bge-m3 切换实录与 512 token 报错、降级行为、指令前缀待办）；代码：[`EmbeddingClient.java`](backend/src/main/java/com/diit/ragkb/ragcore/embedding/EmbeddingClient.java)（接口）、[`OpenAiCompatibleEmbeddingClient.java`](backend/src/main/java/com/diit/ragkb/ragcore/embedding/OpenAiCompatibleEmbeddingClient.java)（OpenAI 兼容实现，当前对接硅基流动 `BAAI/bge-m3`）
- **向量维度选择**：1024 维（`bge-m3` 原生维度），ES `dense_vector`/Milvus `FLOAT_VECTOR(1024)` 两端一致；切换模型或维度不兼容时按新 Collection/新索引处理，不原地覆盖（见下）
- **向量库（Milvus）+ ANN 索引**（2026-07-18 新增，默认关闭）：向量投影可从 ES 切流至 Milvus 独立承载，Collection `rag_chunks_vector_v1` 只存向量与最小过滤字段（`chunk_id`/`embedding`/`org_id`/`kb_id`/`document_id`/`retrieval_ready`），首版索引参数 HNSW + COSINE + `M=16`/`efConstruction=200`/查询 `ef=128`（全部可配置）；文档：[Milvus 向量检索迁移设计](docs/Milvus向量检索迁移设计.md) D3（Collection Schema 与 HNSW 参数）；代码：[`MilvusCollectionManager.java`](backend/src/main/java/com/diit/ragkb/ragcore/index/MilvusCollectionManager.java)（Collection/索引创建与兼容性校验）、[`MilvusVectorIndex.java`](backend/src/main/java/com/diit/ragkb/ragcore/index/MilvusVectorIndex.java)（写入/暂存/激活/删除）、[`RagMilvusProperties.java`](backend/src/main/java/com/diit/ragkb/config/RagMilvusProperties.java)（endpoint/collection/维度/HNSW 参数配置）；查询期怎么在 ES/Milvus/影子模式间路由见第 5 章
- **微调 Embedding 模型**：**未实现**，如实记录——当前 Embedding 全部使用硅基流动在线 API 提供的通用模型（`bge-m3`），没有针对本项目语料做过微调或领域适配，属于后续可探索方向，未立项、未评估

### 第 5 章 检索召回·混合检索

- 文档：[混合检索指南](docs/混合检索指南.md)（BM25+kNN+RRF 实现结构、关键参数与实验数字来源、降级行为、Milvus 向量检索切流）、[Milvus 向量检索迁移设计](docs/Milvus向量检索迁移设计.md)（D1-D7 关键决策：ES/Milvus 分工、双端可见性闸门、三种 Provider 模式、三次租户过滤）；OpenSpec 归档：`openspec/changes/archive/2026-07-18-migrate-vector-retrieval-to-milvus/`；主规格：`openspec/specs/milvus-vector-index/`、`openspec/specs/rag-query/`
- 代码：[`HybridRetriever.java`](backend/src/main/java/com/diit/ragkb/ragcore/retrieval/HybridRetriever.java)（编排：词法+向量召回→RRF 融合→可选 Rerank→拒答判定）、[`LexicalCandidateSource`/`VectorCandidateSource`/`ChunkHydrator`](backend/src/main/java/com/diit/ragkb/ragcore/retrieval/)（拆分端口，ES 与 Milvus 各自实现，`HybridRetriever` 不直接依赖数据库 SDK）、[`ProviderVectorCandidateSource.java`](backend/src/main/java/com/diit/ragkb/ragcore/retrieval/ProviderVectorCandidateSource.java)（ES/Milvus/影子三模式路由与故障回退）、[`MilvusVectorIndex.java`](backend/src/main/java/com/diit/ragkb/ragcore/index/MilvusVectorIndex.java)（Milvus 暂存/激活/关闭可见性/删除）、[`ElasticsearchChunkHydrator.java`](backend/src/main/java/com/diit/ragkb/ragcore/retrieval/ElasticsearchChunkHydrator.java)（Milvus 命中回查 ES 补齐正文+二次租户校验）、[`RrfFusion.java`](backend/src/main/java/com/diit/ragkb/ragcore/retrieval/RrfFusion.java)（倒数排名融合）、[`RetrievalOptions.java`](backend/src/main/java/com/diit/ragkb/ragcore/retrieval/RetrievalOptions.java)（候选池大小/topK/documentIds 过滤等可调参数）
- **已知限制（记录于 TODOS）**：历史 ES 向量批量回填 Milvus、真实环境集成验收、150 题 ES/Milvus 对比评测、目标并发压测均未做，默认配置仍是纯 ES 模式

### 第 6 章 重排（Rerank）与检索优化

- 文档：[重排与检索优化指南](docs/重排与检索优化指南.md)（拒答阈值 `MIN_RERANK_SCORE=0.06` 的完整校准过程与机制性局限、阈值扩展到全部候选、候选池调优）
- 代码：[`RerankerClient.java`](backend/src/main/java/com/diit/ragkb/ragcore/rerank/RerankerClient.java)（接口）、[`OpenAiCompatibleRerankerClient.java`](backend/src/main/java/com/diit/ragkb/ragcore/rerank/OpenAiCompatibleRerankerClient.java)（Cross-Encoder 兼容实现，当前对接硅基流动 `BAAI/bge-reranker-v2-m3`）

### 第 7 章 Query 理解与改写

- 文档：[Query 理解与改写现状](docs/Query理解与改写现状.md)——**如实记录：已实现的只有指代消解**；Query 扩写/重写/HYDE/意图识别均为评估后明确暂缓（每项的理由与启动条件见文内与 `TODOS.md`），不假装有功能
- 代码：[`DeepSeekCoreferenceResolver.java`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/impl/DeepSeekCoreferenceResolver.java)（窄范围指代消解，fail-open）

### 第 8 章 多轮对话与记忆管理

- 文档：[记忆管理设计文档](docs/superpowers/specs/2026-07-15-conversation-memory-design.md)（短期滑动窗口+长期画像的架构决策与备选方案对比）、[历史会话列表设计文档](docs/superpowers/specs/2026-07-15-conversation-history-list-design.md)；OpenSpec 归档：`openspec/changes/archive/2026-07-17-conversation-memory/`、`openspec/changes/archive/2026-07-17-conversation-history-list/`；主规格：`openspec/specs/conversation-memory/`、`openspec/specs/conversation-history/`
- 代码（记忆）：[`ConversationMemoryOrchestrator.java`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/ConversationMemoryOrchestrator.java)（编排入口）、[`SlidingWindowAssembler.java`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/SlidingWindowAssembler.java)（token 预算滑动窗口+摘要压缩）、[`MemoryItemStoreImpl.java`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/impl/MemoryItemStoreImpl.java)（用户画像语义去重+读时衰减遗忘）、[`ElasticsearchMemoryIndex.java`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/impl/ElasticsearchMemoryIndex.java)（统一记忆索引 `rag_memory_v1`）
- 代码（会话）：[`ChatSessionService.java`](backend/src/main/java/com/diit/ragkb/service/ChatSessionService.java)（会话生命周期+历史列表+硬删除级联清理，始终校验 org/kb/member 三重归属）、[`ChatHistorySidebar.vue`](frontend/src/components/ChatHistorySidebar.vue)（历史列表切换/删除/新建）、`ChatPanel.vue`（`localStorage` 记录最后活跃会话，刷新自动恢复，懒创建）
- 存储：Redis（专属实例，逻辑 DB 1）+ MongoDB（`chat_messages`/`memory_items`）+ Elasticsearch（新索引）+ Postgres（`chat_session` 元数据）；`/review` 评审门修复 10 项问题（跨知识库会话泄露、画像租户二次校验等），详见 `git log`

### 第 9 章 上下文问答与引用溯源

- **生成阶段防幻觉（两道闸）**：[NO_RETRIEVAL 事实核验设计文档](docs/superpowers/specs/2026-07-16-no-retrieval-fact-verification-design.md)、[多段融合与自检设计文档](docs/superpowers/specs/2026-07-16-multi-passage-fusion-and-self-check-design.md)；代码：[`FactVerificationGate.java`](backend/src/main/java/com/diit/ragkb/ragcore/generation/FactVerificationGate.java)（生成模型先输出 `{"found": true|false}` 判断行，`found:false` 转固定话术拒答）、[`AnswerSelfChecker.java`](backend/src/main/java/com/diit/ragkb/ragcore/generation/AnswerSelfChecker.java)（生成后逐句核查资料支撑，`self_check_warning` SSE 事件）
- **真实回归验证与已知局限（如实记录）**：[NO_RETRIEVAL 验证报告](eval/reports/no-retrieval-fact-verification-validation-20260716.md) 8/8 命中；[自检验证报告](eval/reports/multi-passage-fusion-and-self-check-validation-20260716.md) 显示复用的 0.06 阈值对"部分相关的编造"基本拦不住（4/6 命中），NLI 替代尝试也未成功（`eval/reports/nli-threshold-calibration-20260716.md`），详见 TODOS
- **引用溯源**：[知识库右键菜单+独立文档页设计文档](docs/superpowers/specs/2026-07-16-kb-context-menu-and-docs-page-design.md)、[历史引用持久化设计文档](docs/superpowers/specs/2026-07-16-persist-citations-in-history-design.md)；正文 `[资料N]` 点击弹右侧抽屉展示来源（文档名/定位/原文片段/相关度），历史会话恢复后同样可点（citations 随消息持久化到 MongoDB，旧消息不回填）；代码：[`ChatPanel.vue`](frontend/src/components/ChatPanel.vue)、[`CitationBuilder`+`recordTurn()`](backend/src/main/java/com/diit/ragkb/ragcore/conversation/ConversationMemoryOrchestrator.java)
- **已知取舍**：知识库列表操作完全依赖右键（触屏/纯键盘用户无法触达）；模型未内联引用的资料无 UI 入口；引用文档被删除后历史记录不提示——均记录于 TODOS
- **单文档直接问答（长上下文直接塞入，绕过切块检索，2026-07-18 新增）**：OpenSpec 归档：`openspec/changes/archive/2026-07-18-quick-document-qa/`（proposal/design/specs/tasks）；会话内上传的临时文档不写入知识库、不切块不索引，复用现有 `DocumentParserFactory` 解析（含 OCR/ASR 网关兜底），全文包装成合成 `RetrievedChunk`（`finalScore` 固定给高分排最前），与知识库检索结果一起送入生成/引用/自检链路；会话级共享 15000 字符总额度池，超额拒绝新上传（不做静默截断挤占）；知识库检索触发拒答阈值但当前会话存在未过期临时文档时不拒答，改用临时文档内容照常回答，审计快照按最终决策结果重建（不会误记为"已拒答"）；上传接口同步阻塞（前端转圈等待），独立 Redis 逻辑 DB（DB 2，TTL 2 小时随会话活跃续期，不耦合 `rag.memory.enabled` 开关）。代码：[`QuickDocumentService.java`](backend/src/main/java/com/diit/ragkb/ragcore/quickdocument/QuickDocumentService.java)（上传解析+额度校验）、[`RedisQuickDocumentStore.java`](backend/src/main/java/com/diit/ragkb/ragcore/quickdocument/RedisQuickDocumentStore.java)（Redis 存取，自愈式索引清理）、[`QuickDocumentController.java`](backend/src/main/java/com/diit/ragkb/controller/QuickDocumentController.java)、`QueryService.java` 的 `buildQuickDocumentChunks()`（拒答豁免与合成 chunk 拼装）、[`QuickDocumentPanel.vue`](frontend/src/components/QuickDocumentPanel.vue)
- **已知取舍（记录于 TODOS）**：引用来源暂不区分"临时文档"与"知识库文档"的视觉标签（改动面涉及 `Citation` 记录跨多处，判断不值当，未做）；额度校验在并发上传下有窄幅竞态（评估过 Redis 原子计数器方案，因 TTL 自然过期不会触发计数器递减、会导致额度永久漂移，比现有问题更严重而放弃）；只有自动化测试，未做真实浏览器/真实 OCR 网关的端到端验证

### 第 10 章 系统评估与上线优化

- **离线评测**：[评估指南](docs/评估指南.md)（方法论、150 题 v2 评估集、权威基线 Recall@1=0.816/Recall@5=0.904/MRR=0.849/拒答F1=0.564 的完整来源与复现方式、后续待办）；框架与工具：[eval/README.md](eval/README.md) · [评估集说明](eval/datasets/README.md) · [构建工具](eval/scripts/README.md)
- **上线验收**：[检索与审计验收](docs/检索与审计验收.md)（混合检索+SSE 逐项验收清单、审计与可观测性验收标准、Prometheus 指标与告警建议）
- **性能与安全缺口**（记录于 [TODOS.md](TODOS.md)）：P95/P99/QPS 监控只有审计表原始数据（含一次性观测数字与测量 SQL）、登录限流与认证失败审计日志待补、压测未做

### 其他

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

以上均为本机开发环境地址，随本机 Docker/进程状态变化；生产环境地址由部署配置另行提供，见 [上传摄取部署与验收手册](docs/上传摄取部署与验收手册.md)。

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
