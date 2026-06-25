# rag-kb — 企业级文档知识库（RAG）

面向团队的 **toB 企业级知识库产品**：成员上传各类文档（PDF / Word / PPT / 网页 / 公众号文章等），系统自动解析、切块、向量化，提供**高精度检索问答**与基于知识库的 AI 对话。目标支持 **百人级团队** 协作使用。

## 核心能力（规划）

- **多类型文档摄取**：上传 → 解析（DeepDoc / MinerU）→ 切块 → 向量化 → 入库
- **高精度检索**：向量召回 + **rerank 重排** + 引用溯源
- **团队知识库**：组织 / 团队 / 成员多租户，知识库级权限（RBAC）
- **AI 问答**：基于知识库的检索增强问答，标注来源
- **企业要求**：SSO/OIDC、审计、配额限流、数据隔离、可观测

## 技术选型

| 层 | 选型 | 说明 |
|----|------|------|
| 编排后端 | **Spring Boot** | 认证/RBAC/多租户/审计/调用编排，对齐企业生态 |
| RAG 引擎 | **RAGFlow** | 外部引擎，DeepDoc 文档解析 + 检索 + rerank + 引用，REST 调用 |
| 模型服务 | **Xinference** | 统一托管 bge-m3（embedding）+ bge-reranker-large（rerank）+ 可选本地 LLM |
| LLM | **DeepSeek-V3 / R1** | 云端 API；或本地 vLLM |
| 文档解析 | **MinerU / DeepDoc** | PDF→结构化文本 |
| 业务存储 | **PostgreSQL + Redis** | 业务数据 + 缓存 |
| 摄取流水线 | **消息队列**（Kafka / RabbitMQ / Redis Stream） | 百人级并发上传削峰 |
| 向量/全文 | RAGFlow 内部（ES / Infinity） | 由引擎托管 |

> 架构细节见 [`docs/architecture.md`](docs/architecture.md)。

## 开发流程（OpenSpec + Superpowers + gstack）

本项目用 **AI 增强开发三件套**：
- **OpenSpec**：需求 → 规格（proposal / specs / design / tasks），见 `openspec/`
- **Superpowers**：开发纪律（先澄清、TDD、子 Agent 执行）
- **gstack**：交付闭环（Review / Browser QA / Ship / Retro）

## 状态

🚧 立项阶段 — 架构选型已定，规格待编写。

## 开发者

- Hao Jia · jiahao@diit.cn
