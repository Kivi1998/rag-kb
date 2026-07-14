# rag-kb —— 企业技术文档知识库

面向内部技术团队的多租户 RAG 知识库。系统解决技术文档、接口说明、配置、故障记录和代码片段分散在群聊中、难以检索的问题。

当前 RAG 主链路为**自研 RAG Core**，不依赖 RAGFlow、LangChain、LlamaIndex 或 Dify 等高层编排框架。

## 当前能力

- 组织、团队、成员、JWT、RBAC 与知识库管理；
- MinIO/S3 预签名直传、幂等上传会话、文件魔数/大小/SHA-256 校验；
- PostgreSQL `ingestion_job` + 双 Worker 异步摄取、租约心跳、过期任务接管与失败重试；
- Markdown、代码、JSON/YAML/XML、DOCX、PPTX、文本 PDF、扫描 PDF、图片、字幕、音频和视频解析；
- 独立 Parser Gateway 提供 OCR、ASR、Office 图片提取和字幕时间戳；
- 结构化技术切块，保留标题、代码块、页码、行号、配置项和技术标识；
- Elasticsearch BM25 + kNN + RRF、可选 Rerank、服务端引用与 SSE 问答；
- 离线评测、查询审计、指标与生产同构验收栈。

## 技术架构

```text
Vue 前端
  └─ Spring Boot
       ├─ JWT / 多租户 / RBAC / 知识库 / 文档任务
       └─ ragcore（自研）
            ├─ Parser / TechnicalChunker
            ├─ Embedding / Rerank / Generation Client
            ├─ Elasticsearch：BM25 + kNN + RRF
            ├─ 引用、拒答、SSE 与审计
            └─ Worker、重试、指标与评测

PostgreSQL：业务数据和任务
MinIO/S3：原文件与解析产物
Elasticsearch：Chunk、全文与向量
Redis：限流和缓存
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

完整 RAG 的真实模型召回质量、日均 5000 次查询容量、生产网络 TLS/CORS 和 24 小时稳定性仍应在目标环境单独验收。

## 文档入口

- [总体架构](docs/architecture.md)
- [自研 RAG 核心重构设计](docs/自研RAG核心重构架构设计.md)
- [上传、解析与部署验收手册](docs/自研RAG摄取部署与验收手册.md)
- [5000 份多模态文档生产验收报告](docs/文档上传与多模态解析生产验收报告.md)
- [验收环境复现说明](acceptance/README.md)

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
