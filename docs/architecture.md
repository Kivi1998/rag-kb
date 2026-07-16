# rag-kb 架构设计

> 当前状态：旧 RAGFlow 摄取与问答实现已下线，项目进入自研 RAG Core 重构阶段。
>
> 详细实施设计见：[自研 RAG 核心重构架构设计](自研RAG核心重构架构设计.md)。

## 一、定位与边界

- 面向内部技术团队的企业级技术文档知识库；
- 解决文档、配置、接口说明和代码片段分散在群聊中、难以检索的问题；
- 保留组织、团队、成员、RBAC、知识库等企业应用能力；
- 自研解析、切块、索引、混合检索、重排、引用与问答主链路；
- 不使用 RAGFlow、LangChain、LlamaIndex、Dify 等高层 RAG 编排框架。

## 二、目标架构

```text
Vue 前端
  └─ Spring Boot 应用层
       ├─ JWT / 组织团队 / RBAC / 审计
       ├─ 知识库与文档任务管理
       └─ ragcore（自研）
            ├─ 文档解析与技术切块
            ├─ Embedding / Rerank / LLM Client
            ├─ Elasticsearch：BM25 + kNN + RRF
            ├─ Conversation Memory：滑动窗口 / 指代消解 / 用户画像 / 会话历史列表（2026-07-15 新增）
            ├─ 引用构造、拒答与 SSE 输出
            └─ 评测、重试与可观测性

基础设施：PostgreSQL（业务、任务与会话元数据）/ MinIO（原文件）/
Elasticsearch（chunk、全文、向量；统一记忆索引）/
Redis（JWT 黑名单 + 会话记忆滑动窗口，逻辑 DB 隔离）/
MongoDB（会话消息长期存档 + 用户画像，只服务记忆子系统）/
硅基流动（Embedding/Rerank）+ DeepSeek（生成模型）
```

> 注：限流尚未实现（此前版本图里的"限流"是规划态描述，代码中未落地）。

## 三、关键技术决策

### 决策 1：保持 Spring Boot 单体模块化

- 现有认证、租户与权限代码保留；
- RAG Core 放在 `com.diit.ragkb.ragcore`，以接口隔离 Parser、Chunker、Index、Retriever、Reranker 与 Generator；
- 在真正出现独立扩缩容需求前，不拆微服务、不引入消息队列全家桶。

### 决策 2：直接使用基础设施，不使用高层 RAG 框架

- Elasticsearch 提供 BM25、过滤和向量 kNN；
- OpenAI 兼容客户端对接 Embedding、Rerank 和 LLM；
- MinIO 保存原始文件，PostgreSQL 保存元数据和摄取任务；
- 技术策略、Prompt、引用、拒答和评测全部在本项目代码中实现。

### 决策 3：技术文档优先

- Markdown、代码、YAML/JSON/XML、DOCX 和文本型 PDF 为第一阶段范围；
- 切块保留标题层级、代码块、类/方法、配置路径、页码和行号；
- 错误码、类名、方法名、接口路径与配置 key 优先走关键词精确召回，避免过早 Query Rewrite 损坏技术标识。

### 决策 4：应用层强制多租户隔离

- 所有检索请求先完成组织、知识库和角色校验；
- Elasticsearch 查询由服务端强制注入 `org_id` 与 `kb_id` 过滤；
- 跨组织访问按资源不存在处理，并作为自动化测试发布门禁；
- 会话生命周期（`chat_session`）额外强制 `kb_id` 归属校验（2026-07-15 review 修复：此前 `GET .../messages` 只校验 org/member，未核对 URL 里的 kbId 与会话真实归属 kb 是否一致，同组织同成员可跨 kb 读取对话历史）；
- MongoDB 层（`ChatMessageRepository`/`MemoryItemStoreImpl`）不完全信任上游 Elasticsearch 过滤结果，读回文档后二次比对 `org_id`/`member_id`，作为纵深防御，防止未来 ES 过滤逻辑出 bug 时直接跨租户泄露数据。

### 决策 5：多轮对话记忆是学习性质的能力储备，非当前刚需

- 短期记忆（滑动窗口+语义历史检索+摘要压缩）与长期记忆（用户画像+读时衰减遗忘机制）已实现，详见 [brainstorming 设计文档](superpowers/specs/2026-07-15-conversation-memory-design.md)；
- 存储引入 Redis 专属实例（与 JWT 黑名单逻辑隔离）+ MongoDB（只服务本子系统），当前规模（单节点、日均 5000 次查询）本不需要这套复杂度，是为学习生产级架构、给未来用户规模增长预先建设；
- 画像内容只影响生成阶段的 System 上下文，不影响 `HybridRetriever` 的检索排序/过滤参数；但指代消解后的 `resolvedQuestion` 向量本身，在画像检索阶段算好后会通过 `MemoryContext`/`RetrievalOptions` 带给检索阶段直接复用（纯粹是避免同一句话被调用两次 Embedding 的效率优化，不构成"画像影响检索"）；
- 会话生命周期管理（`ChatSessionService`）不受 `rag.memory.enabled` 开关门控、常驻注册——因为 `sessionId` 在 `QueryRequest` 上始终必填，即使记忆子系统（Redis 滑动窗口/MongoDB 长期存档/ES 语义检索）关闭，会话归属校验也必须生效，不能变成摆设；
- 同样不引入 LangChain/LlamaIndex 等编排框架，指代消解/摘要压缩/画像提炼均为自研 prompt + 现有模型客户端。

### 决策 6：历史会话列表——标题写时算好存库，硬删除而非软删除

- 前端此前每次刷新/重新进入知识库都无条件新建会话，未消费已有的会话生命周期与长期存档能力；新增 `GET .../sessions` 列表接口与前端历史侧边栏补齐这一消费侧，详见 [brainstorming 设计文档](superpowers/specs/2026-07-15-conversation-history-list-design.md)；
- 会话标题（首条用户消息前 30 字）在写入时算好存 `chat_session.title`，而非列表查询时对每个会话现查 MongoDB——避免列表接口产生 N+1 跨存储查询；
- 删除会话选择硬删除（级联清理 Elasticsearch→MongoDB/Redis→Postgres），而非软删除标记：用户对"删除"的直觉预期就是清除，且没有强需求要保留已删除会话用于审计/恢复；删除不影响 `memory_items` 用户画像（画像是 member 维度长期记忆，与会话生命周期无关）；
- 前端用 `localStorage` 记录每个知识库最后活跃的会话 ID 实现"刷新回到刚才那个对话"，而非引入路由级 `sessionId` 参数——因为当前 `kbId` 本身就不是路由参数（由 `kbStore.selectedKbId` 驱动），引入 URL 级会话参数需要同时改造 kbId 的路由方式，改动面明显更大。

## 四、当前重构边界

- 已删除：RAGFlow Client、RAGFlow dataset/chat/session 管理、旧文档摄取、旧 SSE 问答、相关前后端页面与测试；
- 保留：认证、组织、团队、成员、知识库 CRUD 和应用外壳；
- 历史 Flyway 迁移保留，确保已部署环境可以演进；新逻辑不得继续使用其中的 RAGFlow 字段；
- 新实现遵循“任务表 + Worker”异步摄取，完成压测后再决定是否引入消息队列。

## 五、企业级必备能力

- 多租户与 RBAC；
- 文档摄取状态、失败重试、幂等和删除补偿；
- 引用溯源、拒答、评测集与回归指标；
- 查询审计、延迟、Token 与模型版本可观测；
- 登录限流、密钥 fail-fast、健康检查脱敏与认证失败审计。
