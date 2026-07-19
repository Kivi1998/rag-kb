# rag-kb RAG 重构可复用资产清单

> 文档性质：**重构前的选型与代码来源记录**，用于追溯 rag1/rag2/rag3 的复用依据，不是当前
> 代码结构或开发任务清单。当前实现入口以 [`README.md`](../README.md) 和
> [总体架构](architecture.md) 为准；已经落地的类名、解析方案和 Milvus 可选向量投影可能与本文
> 当时的目标命名不同。
>
> 目标：在不使用 RAGFlow、LangChain、LlamaIndex 等高层 RAG 编排框架的前提下，最大化复用 `rag1`、`rag2`、`rag3` 的成熟资产，减少 rag-kb 自研 RAG Core 的开发量。
>
> 适用范围：内部技术文档知识库（Markdown、代码、配置、PDF、DOCX）。
>
> 配套设计：[自研 RAG 核心重构架构设计](自研RAG核心重构架构设计.md)。本文只回答“复用什么、如何复用、什么不能复用”。

## 1. 先读结论

最省工的组合不是复制某一个项目，而是按以下分工组合：

| 来源 | 应承担的角色 | 复用方式 |
|---|---|---|
| rag1 | 本公司既有工业化 Java 服务能力：模型调用、ES 批写、降级、SSE、缓存与配置模式 | 作为第一优先级，允许直接复制后最小化改造；必须清理旧业务耦合与敏感配置 |
| rag2 | 开源教学项目：自建 ES 混合检索、字段设计、查询逻辑、解析能力清单与踩坑经验 | 复用设计、查询语义和测试案例；源码移植前补齐对应上游许可证信息，不要把 Python/RAGFlow 衍生代码整包搬入 |
| rag3 | 模块边界、结构化切块、RRF、拒答、单元测试模式 | 按 MIT 许可移植算法到 Java，并保留许可声明 |
| rag0 | 多租户、RBAC、知识库、文档状态、SSE 前端与业务 API | 保留，作为新 RAG Core 的应用外壳 |

**推荐优先级：**先直接复用 rag1 的 Java 基础设施代码，再按 rag3 的 MIT 实现移植核心算法，最后用 rag2 验证 ES 字段与混检索细节。不要把 rag2 的 DeepDOC/RAGFlow 衍生目录整体引入，也不要把 rag3 的 ChromaDB 作为生产向量库。

## 2. 代码与许可边界（必须先执行）

### 2.1 当前发现

| 来源 | 语言 | 后端源码许可情况 | 复用规则 |
|---|---|---|---|
| rag1 | Java | 本公司自有 RAG 系统，按项目确认可在公司内部复用 | 允许直接复制和改造；需删除旧业务 DTO、内网地址、密钥和不必要中间件耦合，并登记来源 |
| rag2 | Python | 你确认其为开源教学项目；当前工作区快照未见覆盖 `swxy/backend` 的独立 LICENSE 文件，其中含 RAGFlow/DeepDOC 衍生代码 | 可复用教学算法和非衍生代码；正式复制前须在上游仓库补充许可证链接/文本，DeepDOC 衍生目录仍不整体复制 |
| rag3 | Python | 根目录明确为 MIT License | 可复制、修改和分发；移植或复制文件时必须保留 MIT 版权与许可声明 |

### 2.2 强制规则

1. 建立 `docs/第三方与内部代码来源登记.md`，记录每个复制文件的来源、所有者、许可、修改人和日期。
2. rag1 是本公司自有资产，可直接复制后改造；复制前必须移除旧业务 DTO、内网地址、密钥和 RAGFlow 耦合。
3. rag2 是开源教学项目，但当前快照缺少后端许可证文本；复制前补充上游许可证登记。`deepdoc/`、`rag/` 目录不得整体复制，其中混合 RAGFlow 上游代码、模型资源和重型依赖。
4. rag3 的 Python 实现不应直接作为 Java 生产代码依赖；应移植算法，并在目标 Java 文件头保留 MIT 许可说明或在 NOTICE 中登记。
5. 严禁复用任何硬编码密钥、内网地址、默认密码、测试账号、真实文档和带敏感内容的测试数据。

## 3. 可复用资产总表

标记说明：

- **A：可直接复用**：权限确认后可复制或小改。
- **B：可移植复用**：复用算法、接口或测试，按 rag0 技术栈重写。
- **C：仅参考**：学习设计，不得直接接入。
- **D：禁止复用**：与目标冲突、存在安全/许可/架构风险。

| 优先级 | 来源 | 资产与路径 | 等级 | 复用到 rag0 的目标模块 | 直接收益 | 处理要求 |
|---|---|---|---|---|---|---|
| P0 | rag1 | `model/.../service/EmbeddingService.java`、`impl/EmbeddingServiceImpl.java` | A | `ragcore.embedding.OpenAiEmbeddingClient` | 复用批量 Embedding、失败降级、模型配置思路 | 直接复制后删除现有业务耦合、内网地址和旧 DTO；统一为 rag0 配置 |
| P0 | rag1 | `model/.../service/ReRankingService.java`、`impl/ReRankingServiceImpl.java` | A | `ragcore.rerank.RerankerClient` | 复用 Rerank 服务调用、候选批量处理和失败降级 | 设为可选能力；不可用时返回 RRF 结果 |
| P0 | rag1 | `model/.../core/elasticsearch/client/VectorContentClient.java` | A | `ragcore.index.EsChunkIndex` | 复用 ES 建索引、Bulk 写入、批次处理、失败统计思路 | 改为 rag0 的统一 chunk 索引和 org/kb 过滤字段 |
| P0 | rag1 | `model/.../service/retrieval/RetrievalStrategy.java`、`RetrievalStrategyFactory.java` | A | `ragcore.engine.RagEngine`、`Retriever` | 复用策略接口、可用性检查、降级结构 | 不要保留 `ragflow` 默认实现；将其仅作为迁移期 Feature Flag |
| P0 | rag1 | `model/.../service/retrieval/impl/ElasticsearchRetrievalStrategy.java` | A/B | `ragcore.retrieval.HybridRetriever` | 复用 ES 检索服务分层、候选处理和异常降级模式 | 检索 DSL 改用 rag2 的 BM25+kNN+RRF 方案 |
| P0 | rag3 | `rag_project/src/chunker.py` | B | `ragcore.chunk.TechnicalChunker` | 结构边界、句子边界、overlap、chunk metadata 的完整基线 | 移植为 Java；扩展 Markdown 标题、代码块、配置节和类/方法边界 |
| P0 | rag3 | `rag_project/src/retriever.py` | B | `ragcore.retrieval.RrfFusion` | RRF 融合、候选去重、BM25 测试思路 | 生产 BM25 交给 ES；保留 RRF 和纯内存测试实现 |
| P0 | rag3 | `rag_project/src/generator.py` | B | `ragcore.generation.PromptAssembler`、`CitationBuilder` | 空上下文拒答、参考资料编号、服务端来源输出的基线 | Prompt 改为技术文档助手；来源由服务端生成，不只依赖模型编号 |
| P1 | rag1 | `model/.../util/PromptTemplates.java` | A/B | `ragcore.generation.PromptTemplates` | Java Prompt 组织、上下文拼接和防幻觉约束 | 删除与旧业务、思维链展示相关内容；加技术文档格式要求 |
| P1 | rag1 | `model/.../core/mineru/MinerUService*.java`、`MinerUConfiguration.java` | A/B | `ragcore.parser.MinerUParserAdapter` | 复用外部 OCR/Markdown 解析服务的调用封装 | 作为复杂 PDF 可选适配器，不进入第一阶段主链路 |
| P1 | rag3 | `rag_project/src/reranker.py` | B | `ragcore.rerank` 测试与行为规范 | Cross-Encoder 批量重排的接口与 topK 语义 | Java 侧调用独立模型服务，不在 Spring Boot 内加载 Python 模型 |
| P1 | rag3 | `rag_project/src/query_processor.py` | B | `ragcore.query.QueryNormalizer` | 规则清洗、LLM 改写失败降级设计 | 技术文档首期默认关闭 LLM Rewrite，避免破坏类名/错误码/配置 key |
| P1 | rag2 | `app/service/core/rag/nlp/search_v2.py` | B/C | `ragcore.retrieval.EsQueryBuilder` | 全文 + 向量双路召回、阈值二次尝试、重排后字段组织 | 先补上游许可证登记；优先重写查询语义，不把 Python 运行时直接引入 Java |
| P1 | rag2 | `app/service/core/rag/conf/mapping.json` | B/C | ES mapping 设计 | `*_vec`、全文、keyword、metadata 的字段分类经验 | 补许可证登记后可借鉴配置结构；基于 rag0 数据模型重新设计，不照搬动态模板和旧字段名 |
| P1 | rag2 | `app/service/core/rag/nlp/model.py` | B/C | `EmbeddingClient` 行为测试 | 批量大小、Embedding/Rerank 客户端调用模式 | 补许可证登记后可移植测试；`retrieval2.py` 含硬编码敏感配置，禁止使用 |
| P1 | rag2 | `app/service/core/file_parse.py` | B/C | `IngestionService` 流程 | 解析→切块→向量化→Bulk 入索引的顺序与失败点 | 补许可证登记后可移植其中无 RAGFlow 耦合的工具方法；整体改成异步任务，禁止保留同步 HTTP 全流程 |
| P2 | rag2 | `app/service/core/deepdoc/parser/*` | C | Parser 能力需求清单 | 可了解 PDF/DOCX/XLSX/HTML/MD/JSON/PPTX 的能力边界 | 不直接搬运；优先使用 Java 原生库或独立解析服务 |
| P2 | rag2 | `app/service/core/rag/nlp/__init__.py` 的 `naive_merge` | C | 切块回归对照 | 可作为“简单 token 切块”的性能/效果对照基线 | 不作为正式策略；其无语义分块与 overlap 不满足目标 |
| P2 | rag3 | `rag_project/tests/smoke_test.py` | B | Java 单测 | 结构切块、混检索、拒答、引用的最小回归用例结构 | 移植测试结构，替换保险样例为真实技术文档脱敏样例 |
| P2 | rag3 | `rag_project/tests/sample_qa.jsonl` | C | 评测集格式 | 问题、标准答案、来源文件的评测数据组织方式 | 仅复用 JSONL 格式；不能复用保险领域内容作为业务指标 |
| P3 | rag1 | `model/.../service/impl/ChatServiceImpl.java` | C | SSE/异常处理参考 | 线程池、SSE 生命周期、错误事件、引用事件设计 | 文件过大且业务耦合强，不直接复制 |
| P3 | rag1 | Redis 检索缓存相关实现 | C | `ragcore.cache.RetrievalCache` | 查询签名、TTL、缓存失效思路 | 先完成正确性；评测后再加缓存，防止旧知识返回 |
| D | rag1 | RAGFlow 检索策略、RAGFlow dataset/chat/session 主链路 | D | 无 | 与“去 RAGFlow 自建内核”目标冲突 | 仅作为迁移期只读/回滚兼容，不得成为新默认链路 |
| D | rag2 | `app/service/core/retrieval2.py` | D | 无 | 无 | 含硬编码敏感配置且为旧检索实现，禁止复制 |
| D | rag2 | `deepdoc/vision/` 模型、词典、RAGFlow 衍生资源 | D | 无 | 无 | 重、许可来源不清、难维护，禁止整体搬入 |
| D | rag3 | `rag_project/src/vectorstore.py`、ChromaDB 持久库 | D | 无 | 无 | rag0 已选 Elasticsearch；引入 Chroma 会造成双索引和运维复杂度 |

## 4. 按功能模块复用的具体方案

### 4.1 模型调用：优先复用 rag1 Java 代码

**推荐直接改造：**

- `EmbeddingServiceImpl.java`
- `ReRankingServiceImpl.java`
- `EmbeddingConfig.java`
- `ReRankingConfig.java`

**目标形态：**

1. 拆出与具体业务无关的接口：`EmbeddingClient.embedBatch(texts)` 与 `RerankerClient.rerank(query, candidates)`。
2. 配置只保留模型名、接口地址、超时、批大小、维度、启用状态。
3. Embedding 必须批量调用、记录模型版本、失败可重试；Rerank 不可用时必须可降级。
4. 所有 API Key 从 `application-secret.yml` 或环境变量注入，不能保留 rag1/rag2 的任何现成值。

**预计节省：**模型 HTTP 协议、批量失败处理和配置绑定约 2–4 人日。

### 4.2 ES 索引与批写：复用 rag1 工程模式，采用 rag2 检索语义

**推荐组合：**

- 以 rag1 的 `VectorContentClient.java` 为 ES 客户端、Bulk 写入和失败统计参考。
- 以 rag2 的 `search_v2.py` 为“全文召回 + 向量召回 + 二次阈值尝试”的查询语义参考。
- 以 rag3 的 `retriever.py` 实现 RRF 融合，而非沿用 rag2 固定权重 `0.05/0.95`。

**必须重写的部分：**

- ES index 名称、mapping、`org_id/kb_id/document_id` 强制过滤；
- 技术文档字段：`symbol_names`、`config_keys`、`error_codes`、`source_path`、`line_start/line_end`；
- 删除、重建、版本迁移、Bulk 幂等逻辑；
- 所有 ES 查询必须在服务端注入租户过滤条件。

**预计节省：**ES 接入、批写、检索候选处理约 3–5 人日；同时避免从零试错 ES DSL。

### 4.3 技术文档切块：以 rag3 为代码算法基线

`rag3/rag-from-zero/rag_project/src/chunker.py` 是最值得移植的核心文件。它已实现：

- 标题/条款优先切分；
- 句子边界回退；
- overlap 对齐，避免半句话；
- 稳定的 `source + chunk_id + metadata` 数据结构。

**在 rag0 中必须增加：**

- Markdown 标题树；
- 代码围栏完整性；
- Java/Python/SQL/YAML/JSON 的类、方法、函数和配置节边界；
- PDF 页码、DOCX 标题、文件路径和行号元数据；
- `parent_chunk_id`，用于关联解释文字与代码块。

**预计节省：**切块算法设计、边界测试和元数据模型约 2–3 人日。

### 4.4 检索融合与拒答：直接采用 rag3 的透明算法

**应移植：**

- `retriever.py`：候选去重、RRF 公式、排序语义；
- `generator.py`：无上下文不调用 LLM、结构化参考资料、来源列表输出；
- `smoke_test.py`：检索命中、引用构造、拒答回归测试结构。

**为什么不用 rag2 的固定加权融合：**全文 BM25 和向量相似度的分数量纲不同，固定权重在不同文档集与模型下需要反复调参。RRF 只基于排名，第一阶段更稳定、可解释。

**技术文档特别规则：**对错误码、类名、接口路径、配置 key 命中时，关键词召回应强制进入候选池；不要先做 LLM Query Rewrite。

### 4.5 文档解析：只复用“能力地图”，不要复制 rag2 DeepDOC

rag2 给出的格式能力与处理路径可作为验收清单：PDF、DOCX、XLSX、PPTX、TXT、MD、HTML、JSON、老 DOC。

**rag0 第一阶段实现顺序：**

1. Markdown、TXT、代码、YAML/JSON/XML；
2. DOCX；
3. 文本型 PDF；
4. XLSX/PPTX；
5. 扫描 PDF、复杂表格、OCR。

**建议：**Java 侧使用对应文档解析库或独立 Parser Adapter。只有复杂 PDF 需求确实存在时，才通过 `MinerUParserAdapter` 调用外部服务；不要把 rag2 的 DeepDOC 目录和模型文件直接复制到 rag0。

## 5. 最小复用落地包（建议直接分配给开发 Agent）

### 包 A：模型与 ES 基础设施

- 来源：rag1。
- 复制/改造：Embedding、Rerank、ES Bulk 客户端、检索策略接口。
- 产出：`EmbeddingClient`、`RerankerClient`、`EsChunkIndex`、`RagEngine`。
- 前置：清理 rag1 的旧业务耦合、敏感配置和 RAGFlow 调用。

### 包 B：结构化切块与检索融合

- 来源：rag3。
- 移植：`chunker.py`、`retriever.py`、`generator.py`、`smoke_test.py` 的算法和测试结构。
- 产出：`TechnicalChunker`、`RrfFusion`、`PromptAssembler`、核心单测。
- 前置：目标 Java 文件/NOTICE 中保留 MIT 许可信息。

### 包 C：ES 查询与技术字段设计

- 来源：rag2。
- 参考：`search_v2.py`、`mapping.json`、`file_parse.py`。
- 产出：ES mapping、BM25/kNN Query Builder、索引字段清单、摄取状态机。
- 前置：补齐 rag2 上游许可证登记；将同步入库改为异步任务表。

### 包 D：解析适配器

- 来源：rag2 的格式覆盖经验 + rag1 MinerU Adapter。
- 产出：Markdown/代码/DOCX/PDF Parser，复杂 PDF 的可选 MinerU Adapter。
- 前置：必须为每种格式建立脱敏样例与失败状态测试。

### 包 E：应用层接入与灰度切换

- 来源：rag0 现有 `DocumentService`、`QueryService`、前端聊天与来源卡片。
- 产出：Feature Flag、文档任务状态、SSE `source/refusal` 事件、回滚路径。
- 前置：新引擎完成跨租户和评测测试。

## 6. 禁止直接复制的内容

1. rag1 的完整 `ChatServiceImpl`：文件大、耦合 Kafka/Redis/旧业务 DTO，复制会把历史复杂度带入 rag0。
2. rag1 的 RAGFlow 检索、Chat Assistant、dataset/session 管理：与去 RAGFlow 目标冲突。
3. rag2 的 `retrieval2.py`：含硬编码敏感配置且为废弃检索路径。
4. rag2 的 `deepdoc/vision`、模型权重、词典和 RAGFlow 衍生资源：即使其教学项目可用，也会引入上游依赖、体积和维护负担，禁止整体复制。
5. rag2 的同步 HTTP 全链路入库模式：大文档会阻塞请求，与 rag0 的任务化摄取设计冲突。
6. rag3 的 ChromaDB `VectorStore`：与 Elasticsearch 双索引会增加一致性和运维成本。
7. 任意项目中的 API Key、密码、IP、数据库名、测试 PDF 和真实业务数据。

## 7. 开发顺序与预估节省

| 顺序 | 工作 | 主要复用来源 | 自研比例 | 预期节省 |
|---|---|---|---|---|
| 1 | 模型 Client、ES 客户端、配置与降级接口 | rag1 | 低 | 2–4 人日 |
| 2 | 结构化切块、RRF、拒答、核心单测 | rag3 | 中 | 3–5 人日 |
| 3 | ES mapping、BM25+kNN 查询、技术字段 | rag2 + rag1 | 中 | 3–5 人日 |
| 4 | 异步摄取、MinIO、状态机、删除补偿 | rag0 为主 | 高 | 无法安全跳过 |
| 5 | 解析器、复杂 PDF/OCR | rag2/rag1 参考 | 中高 | 视文件类型决定 |
| 6 | 评测、审计、限流、灰度与回滚 | rag0 + rag3 测试模式 | 高 | 无法安全跳过 |

保守估计，按上述复用方式可减少约 8–14 人日的重复基础开发，但多租户隔离、异步任务、评测和生产安全不能为了“复用”而跳过。

## 8. 给开发 Agent 的执行约束

1. 先阅读本文件和 `自研RAG核心重构架构设计.md`，再开始创建代码。
2. 所有新代码放在 `com.diit.ragkb.ragcore` 下；禁止 Controller 直接调用 ES/模型服务。
3. 任何复用文件必须在 PR 描述中写明来源、复用等级、许可/授权结论和修改内容；rag1 标注“公司内部资产”，rag2/rag3 标注对应上游许可证。
4. 先写单元测试：切块不截断代码、RRF 去重、空召回拒答、引用定位、跨组织过滤。
5. RAGFlow 只能保留为迁移期 Feature Flag，不允许新增业务功能继续依赖它。
6. rag1 可直接复制后改造；rag2 复制前补齐上游许可证登记；rag3 移植/复制时保留 MIT 版权与许可声明。
7. 每个任务完成后必须更新评测结果；没有真实技术文档评测集，不得宣称“高精度”。

## 9. 完成定义

本清单的价值不在于复制文件数量，而在于让新系统在最短路径上获得：

- rag1 的工程稳定性；
- rag2 的 ES 自建检索经验；
- rag3 的透明算法、拒答和测试纪律；
- rag0 已有的企业权限与业务能力。

最终目标是一个没有高层 RAG 框架锁定、但具备工业级数据隔离、可追溯引用、可评测质量和可替换模型能力的技术文档 RAG 系统。
