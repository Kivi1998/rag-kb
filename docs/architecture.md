# rag-kb 架构设计

> 立项阶段架构基线。详细规格走 OpenSpec（`openspec/`）。

## 一、定位与边界

- **toB 企业级**文档知识库，目标支持百人级团队
- 多类型文档上传 + 高精度检索问答 + 团队协作
- 全新独立产品（与 Commute 项目无关）

## 二、整体架构

```
┌─ 应用编排后端（Spring Boot）──────────────────────────┐
│  认证(SSO/OIDC) · RBAC · 多租户(组织/团队) · 文档权限    │
│  配额限流 · 审计 · 可观测(命中哪些doc/token/延迟)        │
│        │ 只用 REST/Feign 调下游，不自己写 RAG 内核        │
└────────┼────────────────────────────────────────────┘
         ▼
┌─ RAG 引擎 RAGFlow（外部，全包）─────────────────────┐
│  DeepDoc 文档解析 · 切块 · 检索 · rerank · 引用溯源    │
│  内部：ES/Infinity(向量) + MySQL + MinIO + Redis      │
└────────┬────────────────────────────────────────────┘
         ▼
┌─ 模型服务 Xinference ──────────────────────────────┐
│  Embedding: bge-m3   Rerank: bge-reranker-large      │
│  LLM: DeepSeek-V3/R1（云）或本地 vLLM                 │
└───────────────────────────────────────────────────┘

摄取流水线：上传 → 解析(MinerU/DeepDoc) → 切块 → embed → 入库
            ↑ 百人级挂消息队列(Kafka/RabbitMQ/Redis Stream) + worker 削峰
```

## 三、关键技术决策

### 决策 1：编排后端用 Spring Boot
- **理由**：toB 核心负担是企业安全（SSO/RBAC/多租户/审计），Spring Security 生态最成熟；可复用同组同事的 Spring Boot + RAGFlow 集成经验；编排层是 I/O 密集 REST 胶水，Go 的性能优势用不上。
- **备选**：Go（企业认证轮子少，自己搭）；Python/FastAPI（企业安全弱）。

### 决策 2：RAG 引擎用 RAGFlow（外部引擎）
- **理由**：需求关键词命中其强项——多类型文档（DeepDoc 解析强）+ 高精度（内置 rerank + 引用溯源）；同事已验证。
- **备选**：Dify（偏 AI 应用/工作流，复杂 PDF 解析弱）；自建 Milvus/Qdrant（过早优化）。

### 决策 3：模型服务用 Xinference 统一托管
- **理由**：embedding/rerank/LLM 统一 OpenAI 兼容接口，模型服务与 RAG 引擎解耦，可独立扩缩容、共享 GPU。

### 决策 4：多租户隔离在应用层强制
- **方案**：RAGFlow 每租户独立知识库(dataset)，应用层 RBAC 强制访问控制。
- **风险**：RAGFlow 隔离模型需 POC 实测，确保百人下绝不串租户（toB 红线）。

## 四、待验证（POC 优先级）

1. **RAGFlow 多租户隔离** —— 能否保证租户间数据绝不泄露（最高优先级）
2. **检索精度** —— bge-m3 + bge-reranker 在中文文档上的召回/精度
3. **摄取吞吐** —— 百人并发上传，队列 + worker 的处理能力与 GPU 需求
4. **部署形态** —— RAGFlow + Xinference 全家桶资源占用与 GPU 规划

## 五、企业级必备（区别于内部工具）

- 多租户：组织 → 团队 → 成员，知识库级权限
- 认证授权：SSO/OIDC + RBAC
- 异步摄取：队列削峰 + 处理进度可见
- 可观测：查询溯源、token 计量、延迟监控
- 配额限流：按租户计量与限流
- 数据隔离与审计：toB 采购硬门槛
