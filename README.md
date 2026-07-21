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
- [已知待修安全项](#已知待修安全项)
- [版本历史](#版本历史)

---

## 技术栈

| 层 | 选型 | 版本/说明 |
|----|------|---------|
| 后端框架 | Spring Boot | 3.3.6，端口 **8090** |
| 数据库 | PostgreSQL | 业务数据，Flyway 管理 DDL |
| 缓存 | Redis | 会话/限流 |
| RAG 引擎 | RAGFlow | 外部服务，端口 9380，REST 调用 |
| 模型服务 | Xinference | embedding / rerank / LLM |
| LLM | 小米 MiMo（优先） | 本地托管；备选 DeepSeek 云端 API |
| 前端框架 | Vue 3 + TypeScript | Vite，端口 **5173** |
| UI 组件库 | Element Plus | |
| 状态管理 | Pinia | |
| 路由 | Vue Router 4 | |
| HTTP 客户端 | Axios | |
| 包管理 | pnpm | |
| 前端测试 | Vitest | |
| 后端测试 | JUnit 5 + Spring Boot Test | |

---

## 目录结构

```
rag-kb/
├── README.md                        # 开发说明书（本文件）
├── CHANGELOG.md                     # 版本变更记录（手动维护）
├── TODOS.md                         # 延后工作项（含安全待修项）
├── CLAUDE.md                        # Claude AI 项目级指令（AI 读取，人工维护）
├── .env.example                     # 环境变量模板（进 git；复制为 .env 填真实值）
├── .gitignore
│
├── docs/                            # 人工可读文档
│   ├── architecture.md              # 架构设计（立项期手工编写）
│   ├── user-guide.md                # 系统使用说明书
│   └── superpowers/
│       └── specs/                   # ⚙️ Superpowers brainstorming 生成的设计文档
│           ├── 2026-06-26-rag-query-design.md
│           └── 2026-06-28-frontend-ui-design.md
│
├── openspec/                        # 规格驱动开发（OpenSpec CLI 管理）
│   ├── .openspec.yaml               # OpenSpec 项目配置
│   ├── specs/                       # ✅ 主规格库（change 归档后提升至此）
│   │   ├── auth/                    # 认证规格
│   │   ├── document-management/     # 文档管理规格
│   │   ├── frontend-app/            # 前端应用脚手架规格
│   │   ├── frontend-auth/           # 前端认证规格
│   │   ├── frontend-chat/           # 前端问答规格
│   │   ├── frontend-document-management/
│   │   ├── frontend-kb-management/
│   │   ├── frontend-member-mgmt/    # 成员管理规格
│   │   ├── frontend-team-mgmt/      # 团队管理规格
│   │   ├── knowledge-base/          # 知识库规格
│   │   ├── local-auth/              # 本地账号规格
│   │   ├── rag-query/               # 检索问答规格
│   │   ├── tenant-management/       # 租户管理规格
│   │   └── ...
│   └── changes/
│       └── archive/                 # ⚙️ 已归档的 change（含 proposal/design/tasks）
│           ├── 2026-06-26-tenant-kb-foundation/
│           ├── 2026-06-26-sso-oidc-auth/
│           ├── 2026-06-26-kb-document-ingest/
│           ├── 2026-06-27-rag-query/
│           ├── 2026-06-28-frontend-ui/
│           └── 2026-06-28-tenant-mgmt-frontend/
│
├── backend/                         # Spring Boot 后端
│   ├── pom.xml
│   └── src/
│       ├── main/
│       │   ├── java/com/diit/ragkb/
│       │   │   ├── RagKbApplication.java      # 入口
│       │   │   ├── common/
│       │   │   │   └── ApiResponse.java       # 统一响应体
│       │   │   ├── config/                    # Spring 配置
│       │   │   │   ├── AsyncConfig.java
│       │   │   │   ├── JacksonConfig.java
│       │   │   │   ├── RagFlowProperties.java
│       │   │   │   ├── RestTemplateConfig.java
│       │   │   │   ├── SecurityConfig.java    # Spring Security
│       │   │   │   ├── TenantFilterAspect.java        # 多租户 AOP
│       │   │   │   └── TenantHibernateFilterConfig.java # Hibernate @Filter 启用
│       │   │   ├── controller/                # REST 控制器
│       │   │   │   ├── AuthController.java
│       │   │   │   ├── DocumentController.java
│       │   │   │   ├── KnowledgeBaseController.java
│       │   │   │   ├── MemberController.java
│       │   │   │   ├── OrganizationController.java
│       │   │   │   ├── QueryController.java   # SSE 流式问答
│       │   │   │   └── TeamController.java
│       │   │   ├── dto/                       # 请求/响应 DTO
│       │   │   ├── exception/                 # 自定义异常 + 全局异常处理
│       │   │   ├── model/                     # JPA 实体
│       │   │   ├── repository/                # Spring Data JPA 仓库
│       │   │   ├── security/
│       │   │   │   ├── JwtAuthFilter.java     # JWT 认证过滤器（写入 TenantContext）
│       │   │   │   └── TenantContext.java     # ThreadLocal 租户上下文
│       │   │   └── service/
│       │   │       ├── ragflow/
│       │   │       │   └── RagFlowClient.java # RAGFlow REST 客户端
│       │   │       ├── AuthService.java
│       │   │       ├── DocumentService.java
│       │   │       ├── JwtService.java
│       │   │       ├── KnowledgeBaseService.java
│       │   │       ├── MemberService.java
│       │   │       ├── OrganizationService.java
│       │   │       ├── PasswordService.java
│       │   │       ├── QueryService.java      # SSE 流式问答编排
│       │   │       ├── RedisService.java
│       │   │       └── TeamService.java
│       │   └── resources/
│       │       ├── application.yml            # 公共配置（进 git）
│       │       ├── application-secret.yml     # 本地密钥（不进 git，需手动创建）
│       │       └── db/migration/              # Flyway 迁移脚本
│       │           ├── V001__create_tenant_tables.sql
│       │           ├── V002__create_user_table.sql
│       │           ├── V003__create_document_table.sql
│       │           └── V004__add_kb_ragflow_chat_id.sql
│       └── test/
│           └── java/com/diit/ragkb/
│               ├── AuthTest.java
│               ├── DocumentTest.java
│               ├── QueryTest.java
│               ├── TenantIsolationTest.java   # 跨租户隔离安全测试（关键）
│               └── ...
│
├── frontend/                        # Vue 3 前端
│   ├── package.json                 # 版本号在此维护
│   ├── vite.config.ts               # 开发代理配置（/api → localhost:8090）
│   ├── vitest.config.ts
│   ├── .env.development             # 开发环境变量（VITE_API_BASE_URL=）
│   ├── .env.production              # 生产环境变量
│   └── src/
│       ├── api/                     # Axios API 层（按资源分文件）
│       │   ├── http.ts              # Axios 实例 + 拦截器
│       │   ├── authApi.ts
│       │   ├── docApi.ts
│       │   ├── kbApi.ts
│       │   ├── memberApi.ts
│       │   ├── queryApi.ts          # SSE 流式问答
│       │   └── teamApi.ts
│       ├── components/              # 复用组件
│       │   ├── AppHeader.vue        # 顶部导航（含角色判断）
│       │   ├── ChatPanel.vue        # 问答面板（SSE）
│       │   ├── DocumentTable.vue    # 文档列表
│       │   ├── KbSidebar.vue        # 知识库侧边栏
│       │   └── SourceCard.vue       # 引用来源卡片
│       ├── composables/             # Vue 组合式逻辑
│       │   └── useDocumentPolling.ts # 文档状态轮询
│       ├── router/
│       │   └── index.ts             # 路由定义 + 权限守卫
│       ├── stores/                  # Pinia 状态
│       │   ├── authStore.ts         # 登录态 + 角色
│       │   ├── chatStore.ts         # 对话历史
│       │   ├── kbStore.ts           # 知识库列表
│       │   ├── memberStore.ts       # 成员管理
│       │   └── teamStore.ts         # 团队管理
│       ├── types/                   # TypeScript 类型（对应后端 DTO）
│       │   ├── auth.ts
│       │   ├── document.ts
│       │   ├── kb.ts
│       │   ├── member.ts
│       │   ├── query.ts
│       │   └── team.ts
│       └── views/                   # 页面组件
│           ├── LoginView.vue
│           ├── ChangePasswordView.vue
│           ├── KbWorkspaceView.vue  # 主工作区（知识库/文档/问答）
│           ├── AdminMembersView.vue # 成员管理（OWNER/ADMIN）
│           ├── AdminTeamsView.vue   # 团队管理（OWNER/ADMIN）
│           └── __tests__/           # 视图级测试
│
└── .claude/                         # Claude AI 工具配置（不是普通代码，勿手动编辑）
    ├── commands/opsx/               # /opsx:* slash command 定义
    └── skills/                      # OpenSpec skill 定义

```

### 目录职责速查

| 目录 | 谁创建 | 什么时候更新 |
|------|--------|------------|
| `docs/superpowers/specs/` | Superpowers AI 工具 | 每次 `/brainstorming` 或设计讨论后自动生成 |
| `openspec/changes/archive/` | OpenSpec CLI + Claude | 每个 feature change 归档时（`/opsx:archive`）写入 |
| `openspec/specs/` | OpenSpec CLI | 归档时从 change delta spec 提升到此 |
| `.context/retros/` | gstack `/retro` | 每次回顾后自动保存 JSON 快照 |
| `backend/src/main/resources/db/migration/` | 开发者手写 | 新增数据库变更时手动编写 Flyway 脚本 |
| `CHANGELOG.md` | Claude Code | 每个版本发布时触发更新 |
| `TODOS.md` | Claude Code + 开发者 | 评审后记录延后工作项 |

---

## 本地开发环境搭建

### 1. 前置依赖

| 工具 | 版本要求 | 说明 |
|------|---------|------|
| Java JDK | 21+ | Spring Boot 3.3 要求 |
| Maven | 3.9+（或用 `./mvnw`） | 后端构建 |
| Node.js | 20+ | 前端构建 |
| pnpm | 9+ | 前端包管理（`npm install -g pnpm`） |
| PostgreSQL | 15+ | 业务数据库 |
| Redis | 7+ | 缓存 |
| RAGFlow | 最新版 | RAG 引擎（Docker 部署，端口 9380） |

### 2. 数据库初始化

```sql
-- 连接 PostgreSQL 后执行
CREATE USER ragkb WITH PASSWORD 'your_password';
CREATE DATABASE ragkb OWNER ragkb;
```

> Flyway 会在后端首次启动时**自动执行** `db/migration/` 下的所有迁移脚本，无需手动建表。

### 3. 密钥配置

**方式 A — application-secret.yml（推荐本地开发）**

在 `backend/src/main/resources/` 下创建 `application-secret.yml`（已在 `.gitignore` 中，不会提交）：

```yaml
spring:
  datasource:
    password: your_db_password
  security:
    jwt:
      secret: <至少 32 字节的随机字符串，用 openssl rand -base64 48 生成>
  data:
    redis:
      password: ''      # 本地 Redis 无密码时留空

ragflow:
  api-key: your_ragflow_api_key
```

**方式 B — 环境变量（生产/CI 环境）**

参考根目录 `.env.example`，通过环境变量注入：

```bash
export JWT_SECRET=<至少32字节随机字符串>
export DB_PASSWORD=your_password
export RAGFLOW_API_KEY=your_key
```

> ⚠️ **重要**：`application.yml` 里 `JWT_SECRET` 有空默认值（`${JWT_SECRET:}`），空密钥下任何人可伪造 token。生产部署前必须修复（见 [已知待修安全项](#已知待修安全项)）。

### 4. 启动后端

```bash
cd backend
./mvnw spring-boot:run
# 或 IDE 运行 RagKbApplication.main()
```

- 服务端口：**8090**
- 首次启动 Flyway 自动建表，日志中可见 `Successfully applied N migrations`
- 健康检查：`curl http://localhost:8090/actuator/health`

### 5. 启动前端

```bash
cd frontend
pnpm install        # 首次
pnpm dev
```

- 开发端口：**5173**（Vite 默认）
- `/api` 请求自动代理到 `http://localhost:8090`
- 访问：`http://localhost:5173`

### 6. 初始账号

系统无自助注册，账号由管理员创建。本地开发测试账号（密码存为 BCrypt hash，通过数据库直接写入）：

| 邮箱 | 密码 | 角色 |
|------|------|------|
| `admin@test.com` | `542426` | OWNER |
| `test@test.com` | （BCrypt hash） | OWNER |
| `member@test.com` | （BCrypt hash） | MEMBER |

> 如需重置密码，参考 `TODOS.md` 中密码策略绕过方式或直接更新 `app_user.password_hash`。

---

## AI 增强开发三件套

本项目使用三套 AI 工具协作，**各有明确职责，按阶段路由**。

### 工具职责对照

| 阶段 | 工具 | 主要命令 |
|------|------|---------|
| 探索/头脑风暴 | **Superpowers** | `/brainstorming` |
| 编写规格 | **OpenSpec CLI + Claude** | `/opsx:propose` |
| 规格评审（强制） | **gstack** | `/plan-eng-review` |
| 实现 | **Claude Code + OpenSpec** | `/opsx:apply` |
| 代码评审（强制） | **gstack + codex + /cso** | `/review`、`/codex`、`/cso` |
| 交付 | **gstack** | `/ship` |
| 归档 | **OpenSpec CLI** | `/opsx:archive` |
| 回顾 | **gstack** | `/retro` |

### OpenSpec — 规格驱动开发

OpenSpec 管理从需求到归档的完整 change 生命周期：

```
openspec new change <name>         # 创建新 change（自动生成目录骨架）
openspec status --change <name>    # 查看 change 的 artifact 完成状态
openspec list --json               # 列出所有活跃 change
openspec instructions <artifact-id> --change <name> --json
                                   # 获取某 artifact 的生成指令（给 Claude）
```

**在本项目的典型用法（Claude Code slash command）：**

```
/opsx:propose <change-name>   # 探索+规格：生成 proposal / design / tasks
/opsx:apply <change-name>     # 按 tasks.md 逐项实现
/opsx:archive <change-name>   # 归档：将 delta spec 提升到 openspec/specs/
```

**`openspec/` 目录说明：**
- `changes/` 下的活跃 change：每项 feature 开发期间存放 proposal、design、tasks
- `changes/archive/`：change 归档后移入，历史可追溯
- `specs/`：主规格库，是各 capability 的权威规格来源，不直接手写

### gstack — 评审/交付/回顾

gstack skills 通过 Claude Code 的 `/` 命令触发，以下命令在本项目为**强制步骤**：

```
/plan-eng-review   # 规格阶段工程评审（架构/数据流/边界）
/review            # 代码评审（Claude 模型）
/cso               # 安全审计（OWASP/STRIDE，多租户红线必查）
/ship              # 创建 PR，含自动评审门检查
/retro             # 工程回顾，保存快照到 .context/retros/
```

> 代码评审需要三轮都过：`/review` + `/codex`（跨模型第二意见）+ `/cso`（安全专项）。任何 CRITICAL/HIGH 发现必须在入库前修复。

### Superpowers — 设计探索

Superpowers 用于功能立项阶段的苏格拉底式追问，生成的设计文档保存到 `docs/superpowers/specs/`（文件名格式 `YYYY-MM-DD-<topic>-design.md`）。

### `.claude/` 目录说明

```
.claude/
├── commands/opsx/     # /opsx:* 命令定义（Claude Code slash commands）
└── skills/            # openspec-* skill 定义
```

这些文件由 OpenSpec 安装程序生成，**不要手动编辑**。它们告诉 Claude Code 每个 `/opsx:*` 命令的执行逻辑。

---

## 开发规范

### Git 工作流（强制）

```
main ← 只接受 PR，禁止直接推送
  └── feat/<change-name>   每个 OpenSpec change 独立一个分支
  └── fix/<描述>
  └── chore/<描述>
```

**一个 change = 一个分支 = 一个 PR**，不允许跨 change 合并。

完整流程：
1. `git checkout -b feat/<name>` 从最新 main 切出
2. `/opsx:propose <name>` 生成规格，`/plan-eng-review` 评审
3. `/opsx:apply <name>` 实现，边实现边在 tasks.md 打勾
4. `/review` + `/codex` + `/cso` 三轮评审，修复所有 CRITICAL/HIGH
5. `/ship` 创建 PR（含自动评审门），用户合并
6. `git checkout main && git pull`，删除已合并分支
7. `/opsx:archive <name>` 归档规格

### Commit 规范

```
<type>: <中文简述>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

type：`feat` / `fix` / `chore` / `docs` / `refactor` / `security`

### 编码约定

- 注释、commit message、文档用**中文**；代码标识符用**英文**
- 密钥放 `application-secret.yml` 或环境变量，**严禁硬编码**
- 后端只用 REST/Feign 调 RAGFlow，**不自写 RAG 内核**

### 多租户隔离（toB 红线）

本项目是 toB 产品，**数据绝对不允许跨组织泄露**。

**机制：**

```
HTTP 请求
  → JwtAuthFilter 解析 JWT，提取 userId
  → 查询 Member 表，确认 orgId、memberId、role
  → 写入 TenantContext（ThreadLocal）
  → TenantFilterAspect 为当前请求的 Hibernate Session 激活 @Filter
  → 所有 Repository 查询自动附加 WHERE org_id = :orgId
```

**开发新功能时的必做检查：**
1. 新 Entity 加 `org_id` 字段，在 `package-info.java` 注册 Hibernate `@FilterDef`
2. 新 Repository 不能有不带 `orgId` 参数的 `findAll` 类方法
3. `TenantIsolationTest` 必须覆盖新接口的跨租户访问场景
4. `/cso` 审计通过后才能入库

---

## 测试

### 后端测试

```bash
cd backend
./mvnw test
```

| 测试文件 | 覆盖范围 |
|---------|---------|
| `AuthTest.java` | 注册、登录、JWT 验证 |
| `DocumentTest.java` | 文档上传、状态查询 |
| `QueryTest.java` | 流式问答接口 |
| `TenantIsolationTest.java` | 跨租户访问隔离（**安全核心测试**） |

### 前端测试

```bash
cd frontend
pnpm test          # 运行所有测试（Vitest）
pnpm test:coverage # 生成覆盖率报告（coverage/index.html）
```

| 测试文件 | 覆盖范围 |
|---------|---------|
| `router.test.ts` | 路由守卫（含页面刷新后 fetchRole 场景） |
| `authStore.test.ts` | 登录态、角色管理 |
| `kbStore.test.ts` | 知识库 CRUD |
| `memberStore.test.ts` | 成员管理 |
| `teamStore.test.ts` | 团队管理 |
| `chatStore.test.ts` | 对话历史 |
| `queryApi.test.ts` | SSE 流式问答 API |
| `useDocumentPolling.test.ts` | 文档状态轮询 |
| `form-validation.test.ts` | 表单校验逻辑 |

> 当前覆盖率：前端 ~8.5%，目标 30%+。每新增 Service 方法须同步编写对应单元测试。

---

## 已知待修安全项

以下 5 项来自 `/cso` 安全审计（2026-06-28），MVP 阶段暂缓，**正式上线前必须全部处理**：

| 编号 | 等级 | 描述 | 文件 |
|------|------|------|------|
| S1 | **HIGH** | `JWT_SECRET` 空默认值，空密钥可伪造任意 token | `application.yml` |
| A01-1 | MEDIUM | `isBootstrapEndpoint()` 用 `contains()` 而非精确匹配，可能被路径混淆绕过 | `JwtAuthFilter.java` |
| A07-1 | **HIGH** | `POST /auth/login` 无速率限制，可暴力破解密码 | — |
| A07-2 | MEDIUM | `POST /auth/register` 无速率限制，可批量注册垃圾账户 | — |
| A05-2 | MEDIUM | `/actuator/health` 泄露 DB/Redis 连接信息 | `application.yml` |
| A09-1 | MEDIUM | 认证失败无安全审计日志，攻击不留痕迹 | `JwtAuthFilter.java` |

> 详细修复方案见 `TODOS.md`。

---

## 数据库结构

| 表名 | 描述 | 关键字段 |
|------|------|---------|
| `organization` | 组织（租户顶层） | `id`, `name` |
| `team` | 团队（组织内分组） | `id`, `org_id`, `name` |
| `member` | 成员（subject 在某组织内的身份） | `id`, `subject_id`, `org_id`, `role` |
| `knowledge_base` | 知识库 | `id`, `org_id`, `ragflow_dataset_id`, `ragflow_chat_id` |
| `document` | 文档 | `id`, `kb_id`, `org_id`, `ragflow_doc_id`, `status` |
| `app_user` | 本地账号（认证主体） | `id`, `email`, `password_hash`, `must_change_password` |

> 所有业务表均带 `org_id`，Hibernate `@Filter` 在每次请求时自动注入过滤条件。

---

## 版本历史

见 [`CHANGELOG.md`](CHANGELOG.md)。

| 版本 | 日期 | 主要内容 |
|------|------|---------|
| 0.2.0 | 2026-06-28 | 成员管理、团队管理、角色路由守卫、安全修复 |
| 0.1.0 | 2026-06-26 | 初始版本：多租户基础、认证、文档摄取、流式问答、Vue3 前端 |

---

## 开发者

Hao Jia · jiahao@diit.cn · DIIT
