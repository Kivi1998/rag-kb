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
       ├─ JWT / 组织团队 / RBAC / 审计 / 限流
       ├─ 知识库与文档任务管理
       └─ ragcore（自研）
            ├─ 文档解析与技术切块
            ├─ Embedding / Rerank / LLM Client
            ├─ Elasticsearch：BM25 + kNN + RRF
            ├─ 引用构造、拒答与 SSE 输出
            └─ 评测、重试与可观测性

基础设施：PostgreSQL（业务与任务）/ MinIO（原文件）/
Elasticsearch（chunk、全文、向量）/ Redis（限流与缓存）/
Xinference 或 vLLM（模型服务）
```

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
- 跨组织访问按资源不存在处理，并作为自动化测试发布门禁。

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
