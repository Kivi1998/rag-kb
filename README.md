# rag-kb — 企业级文档知识库（RAG）

面向团队的 **toB 企业级知识库产品**：成员上传各类文档，系统自动解析、切块、向量化，提供高精度检索问答与基于知识库的 AI 对话。目标支持百人级团队协作使用。

> **系统使用说明书** → [`docs/user-guide.md`](docs/user-guide.md)
> **架构设计** → [`docs/architecture.md`](docs/architecture.md)

---

## 目录

- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [本地开发环境搭建](#本地开发环境搭建)
- [AI 增强开发三件套](#ai-增强开发三件套)
- [开发规范](#开发规范)
- [测试](#测试)
- [已知待办事项](#已知待办事项)
- [版本历史](#版本历史)

---

## 技术栈

后端从 Spring Boot（Java）全量迁移到 FastAPI（Python）后，`backend-py/` 是**唯一**后端；
Java 版 `backend/` 已于 2026-07-21 退役删除。RAG Core 全程自研，不依赖 RAGFlow、
LangChain、LlamaIndex、Dify 等高层编排框架。

| 层 | 选型 | 版本/说明 |
|----|------|---------|
| 后端框架 | FastAPI | Python 3.13，端口 **8090** |
| RAG Core | 自研（`backend-py/app/ragcore`） | 解析 → 切块（V3 结构感知）→ 索引 → 混合检索 → 生成，全流程自建 |
| 多模态解析 | 进程内本地模块 | deepdoc（OCR/版面分析/表格结构识别，移植自 RAGFlow deepdoc，Apache 2.0）；原独立 `parser-gateway` 微服务已合并进程内并删除；音视频（ASR）支持已于 2026-09 移除 |
| 业务数据库 | PostgreSQL 16 | SQLAlchemy（async, asyncpg 驱动）；schema 由历史 Flyway 迁移固化，当前无在用的迁移工具（见 [已知待办事项](#已知待办事项)） |
| 缓存 | Redis 7 | JWT 黑名单、临时文档、会话记忆各用独立逻辑 DB |
| 会话记忆存储 | MongoDB 7 | 多轮对话短期/长期记忆 |
| 检索引擎 | Elasticsearch 8.13 | 原生 BM25 + kNN 双路召回 + RRF 融合，可选 Rerank，低置信度拒答 |
| 向量检索（可选） | Milvus | 三模式切流：`elasticsearch`（默认）/ `shadow`（影子对比）/ `milvus`（主检索），详见 `docs/Milvus向量检索迁移设计.md` |
| 对象存储 | MinIO/S3 兼容 | 原始文件与版本化解析产物；本地开发同构生产 |
| Embedding / Rerank | 硅基流动（SiliconFlow） | `BAAI/bge-m3` / `BAAI/bge-reranker-v2-m3`，OpenAI 兼容 HTTP 协议 |
| 生成模型 | DeepSeek | `deepseek-chat`，OpenAI 兼容 Chat Completions 流式协议 |
| 前端框架 | Vue 3 + TypeScript | Vite，端口 **5173** |
| UI 组件库 | Element Plus | |
| 状态管理 | Pinia | |
| 路由 | Vue Router 4 | |
| HTTP 客户端 | Axios | |
| 包管理 | pnpm | |
| 前端测试 | Vitest | |
| 后端测试 | pytest + pytest-asyncio | |

**多租户隔离**：组织 → 团队/成员，知识库级 RBAC（OWNER/ADMIN/MEMBER）。租户上下文用
`contextvars.ContextVar`（不是 ThreadLocal——FastAPI/asyncio 不是一个请求一个线程），每个
查询路径强制按 `org_id` 过滤，语义对应 Java 版 Hibernate `@Filter tenantFilter`。

**认证**：本地邮箱 + 密码 + JWT（非 SSO/OIDC）。`JWT_SECRET` 未配置或长度不足时服务
**拒绝启动**（fail-fast，`app/core/jwt_service.py`），不存在空密钥被静默接受的风险。

---

## 目录结构

```
rag-kb/
├── README.md                        # 开发说明书（本文件）
├── CHANGELOG.md                     # 版本变更记录（手动维护）
├── TODOS.md                         # 延后工作项（含已知缺口）
├── CLAUDE.md                        # Claude AI 项目级指令（AI 读取，人工维护）
├── compose.dev.yml                  # 本地开发依赖组：Postgres/Redis/MongoDB/MinIO/ES/Kibana
├── .gitignore
│
├── backend-py/                      # FastAPI 后端（唯一后端）
│   ├── pyproject.toml
│   ├── .env.example
│   └── app/
│       ├── main.py                  # 入口 + lifespan（Worker/记忆清理任务的启停）
│       ├── core/                    # 配置、JWT、DB engine、租户上下文、安全依赖
│       ├── models/                  # SQLAlchemy ORM 模型
│       ├── schemas/                 # Pydantic 请求/响应模型
│       ├── repositories/            # 数据访问层
│       ├── services/                # 业务编排层
│       ├── routers/                 # REST 路由（auth/documents/query/... 九个模块）
│       └── ragcore/                 # 自研 RAG 核心
│           ├── parser/              # 文档解析器 + deepdoc（OCR/版面/表格）
│           ├── chunk/                # TechnicalChunker V3（结构感知切块）
│           ├── embedding/ rerank/ generation/  # 模型客户端（OpenAI 兼容协议）
│           ├── retrieval/           # 混合检索（BM25/kNN/RRF/Milvus 候选源）
│           ├── ingestion/           # 摄取任务状态机、Worker、删除补偿
│           ├── memory/              # 多轮对话记忆
│           ├── quickdocument/       # 会话内临时文档问答
│           └── index/               # ES/Milvus 索引适配
│
├── frontend/                        # Vue 3 前端
│   ├── src/
│   │   ├── views/ components/ stores/ api/ router/
│   └── package.json
│
├── nli-gateway/                     # 独立 Python 微服务：NLI 自检（自然语言推理）
│
├── eval/                             # 离线评测框架
│   ├── datasets/                    # 人工标注评估集（150 题 v2）
│   ├── fixtures/                    # 切块/解析测试样本
│   ├── runner.py metrics.py         # Recall@k / MRR / 拒答 F1
│   └── scripts/                     # 语料预处理（xlsx_to_md.py 等）
│
├── acceptance/                      # 生产同构 Docker Compose 全链路验收（测试 backend-py）
│
├── deploy/
│   └── milvus/                      # Milvus 部署配置
│
├── docs/                            # 人工可读文档
│   ├── architecture.md              # 架构设计
│   ├── 自研RAG核心重构架构设计.md      # 阶段性实施设计
│   ├── 解析指南.md 切块指南.md 评估指南.md  # 解析/切块/评估三环节权威入口
│   ├── 混合检索指南.md Embedding指南.md 重排与检索优化指南.md
│   ├── Milvus向量检索迁移设计.md
│   ├── user-guide.md                # 系统使用说明书
│   └── superpowers/specs/           # ⚙️ Superpowers brainstorming 生成的设计文档
│
├── openspec/                        # 规格驱动开发（OpenSpec CLI 管理）
│   ├── config.yaml                  # 项目背景（自动注入给 AI）
│   ├── specs/                       # ✅ 主规格库（change 归档后提升至此）
│   └── changes/archive/             # ⚙️ 已归档的 change（含 proposal/design/tasks）
│
└── .claude/
    ├── commands/opsx/                # /opsx:* 命令定义
    └── skills/                       # openspec-* skill 定义
```

### 目录职责速查

| 目录 | 谁创建 | 什么时候更新 |
|------|--------|------------|
| `docs/superpowers/specs/` | Superpowers AI 工具 | 每次 `/brainstorming` 或设计讨论后自动生成 |
| `openspec/changes/archive/` | OpenSpec CLI + Claude | 每个 feature change 归档时（`/opsx:archive`）写入 |
| `openspec/specs/` | OpenSpec CLI | 归档时从 change delta spec 提升到此 |
| `CHANGELOG.md` | Claude Code | 每个版本发布时触发更新 |
| `TODOS.md` | Claude Code + 开发者 | 评审后记录延后工作项 |

---

## 本地开发环境搭建

### 1. 前置依赖

| 工具 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.13+ | 后端 |
| uv 或 pip | 最新版 | Python 依赖管理（推荐 `uv`，deepdoc 依赖较重，装起来更快） |
| Node.js | 20+ | 前端构建 |
| pnpm | 9+ | 前端包管理（`npm install -g pnpm`） |
| Docker + Docker Compose | 最新版 | 本地依赖组（Postgres/Redis/MongoDB/MinIO/ES） |

### 2. 启动本地依赖组

```bash
docker compose -f compose.dev.yml up -d
docker compose -f compose.dev.yml ps   # 确认 6 个容器都 healthy
```

端口对照：Postgres `5433`、Redis `6380`、MongoDB `27018`、MinIO API `9010` / 控制台 `9011`、
Elasticsearch `9200`、Kibana `5602`（可选，观测用）。这套依赖是 rag-kb 专属容器组，不与
本机其他项目共用任何实例。

### 3. 后端配置与启动

```bash
cd backend-py
python3.13 -m venv .venv    # 或 uv venv --python 3.13
cp .env.example .env
```

编辑 `.env`，至少确认以下几组变量（完整字段清单见 `app/core/config.py` 的 `Settings` 类）：

```bash
JWT_SECRET=<至少 32 字节随机字符串，用 openssl rand -base64 48 生成>
DB_URL=postgresql+asyncpg://ragkb:ragkb-local-dev@127.0.0.1:5433/ragkb
REDIS_HOST=127.0.0.1
REDIS_PORT=6380

RAG_STORAGE_TYPE=minio
MINIO_ENDPOINT=http://127.0.0.1:9010
MINIO_BUCKET=rag-kb
MINIO_ACCESS_KEY=ragkb
MINIO_SECRET_KEY=<compose.dev.yml 里的 MINIO_ROOT_PASSWORD>

RAG_ES_ENABLED=true
RAG_ES_ENDPOINT=http://127.0.0.1:9200

# 真实模型 API（会产生真实调用费用；不填则对应能力自动关闭，不影响不需要它的功能）
RAG_EMBEDDING_ENABLED=true
RAG_EMBEDDING_ENDPOINT=https://api.siliconflow.cn/v1/embeddings
RAG_EMBEDDING_API_KEY=<你的硅基流动 key>
RAG_EMBEDDING_MODEL=BAAI/bge-m3

RAG_GENERATION_ENABLED=true
RAG_GENERATION_ENDPOINT=https://api.deepseek.com/v1/chat/completions
RAG_GENERATION_API_KEY=<你的 DeepSeek key>
RAG_GENERATION_MODEL=deepseek-chat

RAG_INGESTION_WORKER_ENABLED=true
RAG_MULTIMODAL_PARSER_ENABLED=true   # 本地 OCR，首次调用会懒加载模型
```

```bash
.venv/bin/pip install -e .   # 或 uv pip install -e .
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8090 --reload
```

- 服务端口：**8090**
- 健康检查：`curl http://127.0.0.1:8090/health`

> ⚠️ 数据库表结构目前是历史 Flyway 迁移固化的产物，`backend-py` 不会自己建表。全新环境
> 需要先跑一遍 Flyway（或直接从现有环境 `pg_dump`/`restore`）。下一次真的需要改 schema
> 时的迁移工具选型是已知待办事项，见下文。

### 4. 启动前端

```bash
cd frontend
pnpm install        # 首次
pnpm dev
```

- 开发端口：**5173**（Vite 默认）
- `/api` 请求自动代理到 `http://localhost:8090`
- 访问：`http://localhost:5173`

### 5. 初始账号

系统无自助注册，账号由管理员创建（`POST /api/v1/auth/register` 需要已有账号邀请，或直接
用测试脚本调用注册接口创建首个账号）。

---

## AI 增强开发三件套

本项目使用三套 AI 工具协作，**各有明确职责，按阶段路由**，详见 `CLAUDE.md`。

### 工具职责对照

| 阶段 | 权威所有者 | 主要命令 |
|------|------|---------|
| 探索/头脑风暴 | **Superpowers** | `brainstorming`（自动触发） |
| 编写规格 | **OpenSpec CLI + Claude** | `/opsx:propose` |
| 规格评审（强制） | **gstack** | `/plan-eng-review`；安全相关加 `/cso` |
| 实现 | **Superpowers TDD + 子 Agent** | `/opsx:apply` 当任务追踪 |
| 代码评审（强制） | **gstack** | `/review` + `/codex`（跨模型第二意见）+ `/cso` |
| 交付 | **gstack** | `/ship` + `/document-release` |
| 归档 | **OpenSpec CLI** | `/opsx:archive` |
| 反思 | **gstack** | `/retro` |

### OpenSpec — 规格驱动开发

```bash
openspec new change <name>         # 创建新 change（自动生成目录骨架）
openspec status --change <name>    # 查看 change 的 artifact 完成状态
openspec list --json               # 列出所有活跃 change
```

**在本项目的典型用法（Claude Code slash command）：**

```
/opsx:propose <change-name>   # 探索+规格：生成 proposal / design / tasks
/opsx:apply <change-name>     # 按 tasks.md 逐项实现
/opsx:archive <change-name>   # 归档：将 delta spec 提升到 openspec/specs/
```

### gstack — 评审/交付/回顾

```
/plan-eng-review   # 规格阶段工程评审（架构/数据流/边界）
/review            # 代码评审
/codex             # 跨模型第二意见（依赖 cc-switch 本地代理常驻，端口 15721）
/cso               # 安全审计（OWASP/STRIDE，多租户红线必查）
/ship              # 创建 PR，含自动评审门检查
/retro             # 工程回顾
```

代码评审需要三轮都过：`/review` + `/codex` + `/cso`。任何 CRITICAL/HIGH 发现必须在入库前
修复。

### Superpowers — 设计探索 + TDD 实现

- 探索阶段：苏格拉底式追问，生成的设计文档保存到 `docs/superpowers/specs/`
  （`YYYY-MM-DD-<topic>-design.md`）
- 实现阶段：TDD 内循环 + 子 Agent 分工，配合 `openspec/changes/<name>/tasks.md` 逐项推进

---

## 开发规范

### Git 工作流（强制）

**所有功能开发走"分支 → 实现 → 合并 → 提交"流程，禁止直接在 `main` 上提交功能性改动。**

1. **建分支**：从最新 `main` 切出，命名 `<type>/<简述>`，`type` ∈ `feat`/`fix`/`docs`/`chore`/`refactor`
   - 一个 OpenSpec change 对应一个分支
2. **在分支上实现**：完成功能并跑通测试（多租户/权限改动必须含安全测试）
3. **评审门**：通过 `/review` + `/codex` + `/cso` 三轮评审，修复所有 CRITICAL/HIGH 发现
4. **提交 + 推送分支**：`git push -u origin <分支>`
5. **创建 PR**：`gh pr create`
6. **合并 PR**：评审通过后合并，切回 `main` 并 `git pull`
7. **清理**：删除已合并分支，`/opsx:archive` 归档规格

### Commit 规范

```
<type>: <中文简述>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

`type` ∈ `feat` / `fix` / `chore` / `docs` / `refactor`

### 编码约定

- 注释、commit message、文档用**中文**；代码标识符用**英文**
- 密钥放 `.env`，**严禁硬编码与提交**
- RAG Core 必须自研并保持模块化；不得重新引入 RAGFlow、LangChain、LlamaIndex、Dify 等高层
  编排框架

### 多租户隔离（toB 红线）

本项目是 toB 产品，**数据绝对不允许跨组织泄露**。

**机制：**

```
HTTP 请求
  → require_tenant 依赖：解析 JWT，提取 userId
  → 查询 Member 表，确认 orgId、memberId、role
  → 写入 contextvars.ContextVar 租户上下文（每个 asyncio task 独立，不是 ThreadLocal）
  → 请求结束时中间件无条件清理租户上下文（防止 task/连接池复用导致跨请求串号）
  → 所有 Repository 查询显式带 org_id 过滤条件
```

**开发新功能时的必做检查：**
1. 新表加 `org_id` 字段
2. 新 Repository 不能有不带 `org_id` 参数的通用查询方法
3. 新接口必须有对应的跨租户访问安全测试
4. `/cso` 审计通过后才能入库

---

## 测试

### 后端测试

```bash
cd backend-py
.venv/bin/python -m pytest -q
```

覆盖：认证、多租户隔离、文档上传（含直传两阶段校验）、摄取任务状态机与 Worker 租约/心跳、
文档解析（Markdown/代码/JSON-YAML-XML/DOCX/PPTX/PDF/字幕）、本地多模态解析（deepdoc OCR）、
切块（TechnicalChunker V3）、混合检索（BM25/kNN/RRF）、生成（事实核验闸门 + 生成后自检）、
会话记忆、临时文档问答、查询审计等。

### 前端测试

```bash
cd frontend
pnpm test          # 运行所有测试（Vitest）
pnpm test:coverage # 生成覆盖率报告（coverage/index.html）
```

### 生产同构验收

`acceptance/` 是一套独立的 Docker Compose 全链路验收（真实 HTTP 直传 → 解析 → 索引 → ES
写入），针对 `backend-py` 构建镜像。用法见 `acceptance/README.md`。

---

## 已知待办事项

见 [`TODOS.md`](TODOS.md)，当前记录的主要项：

- 数据库迁移工具处于空白状态（Flyway 已随 Java 一起移除，Alembic 未初始化）
- 3 个非阻塞的后台任务缺口（文档删除补偿循环、过期上传会话清理、Prometheus `/metrics` 端点）
- Milvus 向量检索的观察期验收项（真实环境压测、召回质量对比）未做

---

## 版本历史

见 [`CHANGELOG.md`](CHANGELOG.md)。

---

## 开发者

Hao Jia · jiahao@diit.cn · DIIT
