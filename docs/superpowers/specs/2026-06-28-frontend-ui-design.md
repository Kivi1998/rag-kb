# rag-kb 前端 UI 设计文档

**日期**: 2026-06-28  
**状态**: 已批准  
**技术栈**: Vue 3 + TypeScript + Element Plus + Pinia + Vue Router 4 + Axios + Vite + pnpm

---

## 一、背景与目标

为 rag-kb 企业文档知识库系统构建前端 UI，覆盖三个核心域：

- **知识库管理**：创建、重命名、删除知识库
- **文档管理**：上传文档、查看处理状态、删除文档
- **流式问答**：向知识库提问，实时流式展示答案与引用来源

目标用户：**管理员和业务用户并重**，两种角色在同一界面内通过标签页切换工作模式。

---

## 二、技术栈

| 类别 | 选型 | 说明 |
|------|------|------|
| 框架 | Vue 3 Composition API + TypeScript | `<script setup>` 语法 |
| UI 组件库 | Element Plus | 全局注册，企业级风格 |
| HTTP 客户端 | Axios（常规接口）+ 原生 fetch（SSE） | SSE 接口不支持 axios 流式读取 |
| 状态管理 | Pinia | 按功能模块拆分 store |
| 路由 | Vue Router 4 | 懒加载 + 路由守卫 |
| 构建工具 | Vite + pnpm | |
| 测试 | Vitest + Vue Test Utils | 覆盖 stores/api/hooks |

---

## 三、页面与路由

```
/login   → LoginView.vue      （未登录强制跳转）
/        → 重定向 → /kb
/kb      → KbWorkspaceView.vue（需登录，主工作区）
```

**路由守卫**：`router.beforeEach` 检查 `authStore.token`，未登录跳 `/login`。

---

## 四、布局方案

采用「左侧 KB 导航 + 主区标签页」方案：

```
┌──────────────────────────────────────────────────────┐
│  顶部栏：Logo  |  当前用户名  |  退出登录              │
├──────────────┬───────────────────────────────────────┤
│  左侧边栏     │  主内容区                              │
│  ──────────  │  ┌─────────────────────────────────┐  │
│  + 新建知识库 │  │  [📄 文档管理]  [💬 问答]  Tab  │  │
│              │  ├─────────────────────────────────┤  │
│  ● KB-1      │  │                                 │  │
│  ● KB-2      │  │  Tab 内容区                     │  │
│  ● KB-3      │  │  （文档表格 / 聊天气泡）          │  │
│              │  │                                 │  │
│  (无选中时)   │  └─────────────────────────────────┘  │
│  显示空状态   │  （无选中 KB 时显示引导空状态）          │
└──────────────┴───────────────────────────────────────┘
```

- 左侧边栏：固定宽度 220px，`el-menu` 实现，可折叠
- 选中 KB 高亮，主内容区切换对应 KB 数据
- 默认激活「文档管理」Tab
- 切换 KB 时问答历史隔离保留

---

## 五、目录结构

```
frontend/
├── src/
│   ├── api/
│   │   ├── http.ts            # axios 实例（JWT 拦截器 + 统一错误处理）
│   │   ├── authApi.ts         # login / register / changePassword
│   │   ├── kbApi.ts           # KB CRUD
│   │   ├── docApi.ts          # 文档上传/列表/删除
│   │   └── queryApi.ts        # SSE 流式问答（原生 fetch + ReadableStream）
│   ├── components/
│   │   ├── KbSidebar.vue      # 左侧知识库列表
│   │   ├── DocumentTable.vue  # 文档管理表格（含上传 + 轮询状态）
│   │   ├── ChatPanel.vue      # 问答聊天区（气泡 + 流式渲染）
│   │   └── SourceCard.vue     # 引用来源卡片
│   ├── router/
│   │   └── index.ts
│   ├── stores/
│   │   ├── authStore.ts       # token + 用户信息（localStorage 持久化）
│   │   └── chatStore.ts       # 每个 KB 的对话历史（内存，刷新重置）
│   ├── utils/
│   │   └── polling.ts         # 文档状态轮询工具
│   └── views/
│       ├── LoginView.vue
│       └── KbWorkspaceView.vue
├── .env.development           # VITE_API_BASE_URL=http://localhost:8080
└── vite.config.ts             # proxy /api → localhost:8080
```

---

## 六、数据流与状态管理

### authStore

```typescript
state:  token: string | null, username: string | null
action: login(username, password)  // 调 authApi → 存 token → localStorage
action: logout()                   // 清 token → 跳 /login
```

Axios 请求拦截器自动注入 `Authorization: Bearer <token>`。

### chatStore

```typescript
state:
  histories: Record<kbId, Message[]>   // 按 KB 隔离
  streaming: boolean                    // 是否正在推流
  currentAnswer: string                 // 流式拼接中的答案

type Message = {
  role: 'user' | 'assistant'
  content: string
  sources: Source[]
}
type Source = { documentName: string; content: string; score: number }
```

### 文档轮询（useDocumentPolling hook）

```
进入文档 Tab → 拉取文档列表
若存在 status=UPLOADING 的文档 → 每 3 秒重新 GET 文档列表
直到全部 ACTIVE/ERROR → 停止轮询
onUnmounted / 切换 KB → clearInterval，防内存泄漏
```

### SSE 流式问答数据流

```
用户提交问题
→ chatStore 追加 user message
→ queryApi.stream(kbId, question) 返回 ReadableStream
→ 逐行解析 SSE：
    chunk  → 拼接 currentAnswer（界面实时渲染）
    source → 收集到临时 sources 数组
    done   → 将 answer + sources 存入 history，streaming = false
    error  → 聊天区显示错误气泡，streaming = false
→ AbortController 支持切换 KB 时取消进行中的请求
```

---

## 七、错误处理

### HTTP 错误（Axios 响应拦截器）

| 状态码 | 处理 |
|--------|------|
| 401 | 清 token → 跳 /login → `el-message.error("登录已过期")` |
| 403 | `el-message.error("无权限")` |
| 404 | `el-message.error("资源不存在")` |
| 5xx | `el-message.error("服务异常，请稍后重试")` |
| 网络超时 | `el-message.error("网络连接失败")` |

### 文档上传错误

- `el-upload` `before-upload` 钩子前端校验文件类型/大小
- 轮询到 `status=ERROR`：行内红色标签 + `errorMessage` tooltip

### SSE 错误

- 收到 `error` 事件 / fetch 抛异常：聊天区插入红色错误气泡
- 切换 KB 时 `AbortController.abort()` 中止当前请求

### 空状态引导

| 场景 | 提示文案 |
|------|---------|
| 未选中 KB | 请从左侧选择或新建知识库 |
| KB 下无文档 | 还没有文档，点击上传开始使用 |
| 问答历史为空 | 向知识库提问，开始对话 |

---

## 八、测试策略

工具：**Vitest + Vue Test Utils**，目标覆盖率 stores/api/hooks ≥ 60%。

| 测试目标 | 测试内容 |
|---------|---------|
| `authStore` | login 存 token、logout 清 token、localStorage 持久化 |
| `chatStore` | 多 kbId 历史隔离、SSE chunk 拼接、done 事件归档 |
| `useDocumentPolling` | 有 UPLOADING 时触发轮询、全 ACTIVE 后停止、卸载清定时器 |
| `queryApi.stream` | SSE 行解析（chunk/source/done/error 正确区分） |
| 路由守卫 | 未登录跳 /login、已登录跳 /kb |

不测：Element Plus 组件渲染细节、样式、具体 DOM 结构。

---

## 九、后端 API 对照

| 功能 | Method | Path |
|------|--------|------|
| 登录 | POST | `/api/v1/auth/login` |
| 创建 KB | POST | `/api/v1/knowledge-bases` |
| 列出 KB | GET | `/api/v1/knowledge-bases` |
| 更新 KB | PATCH | `/api/v1/knowledge-bases/{id}` |
| 删除 KB | DELETE | `/api/v1/knowledge-bases/{id}` |
| 上传文档 | POST | `/api/v1/knowledge-bases/{kbId}/documents` (multipart) |
| 列出文档 | GET | `/api/v1/knowledge-bases/{kbId}/documents` |
| 删除文档 | DELETE | `/api/v1/knowledge-bases/{kbId}/documents/{docId}` |
| 流式问答 | POST | `/api/v1/knowledge-bases/{kbId}/query` (SSE) |

---

## 十、plan-eng-review 评审决议

### 第一轮评审决议（架构/代码质量/测试）

| # | 问题 | 决议 |
|---|------|------|
| 1 | JWT token 存储位置 | 改用 **sessionStorage**（非 localStorage），减小 XSS 暴露窗口 |
| 2 | KB 切换时清理顺序 | 明确顺序：先 `AbortController.abort()` → 再清空 `currentAnswer` → 最后更新 `selectedKbId` |
| 3 | HTTP 客户端 URL 模式 | 开发用 **Vite proxy 模式**：Axios baseURL 留空，所有请求路径以 `/api/v1/...` 开头；生产由 `VITE_API_BASE_URL` 前缀控制 |
| 4 | TypeScript DTO 类型位置 | 新建 **`src/types/`** 目录，存放所有后端 DTO 映射类型（KnowledgeBase、Document、DocumentStatus、QueryChunkEvent 等） |
| 5 | SSE 解析测试格式 | 测试用 `event:\ndata:\n\n` 多行格式（非单行），补充多事件连续解析用例 |

### 外部评审决议（Outside Voice）

| # | 问题（严重度） | 决议 |
|---|--------------|------|
| 6 | **[P1 Blocker]** X-Org-Id 请求头缺失 | 后端 `AuthService.login` 响应加 `orgId` 字段；`authStore` 存 `{ token, username, orgId }`；Axios 拦截器同时注入 `Authorization` 和 `X-Org-Id: <orgId>` |
| 7 | **[P2]** 注册 + 组织 Bootstrap UI 缺失 | MVP 不包含，管理员手动通过后端 API 创建组织和成员；录入 TODOS.md 待后续迭代 |
| 8 | **[P2]** 文档轮询无超时上限 | `useDocumentPolling` 加最大轮询时长 **10 分钟**；超时后停止轮询并显示"处理超时，请手动刷新"提示 |
| 9 | **[P2]** KB 删除 202 部分成功未处理 | 删除 KB 后检查响应体 `data.deleted` 字段：`true` → 从列表移除；`false` → 显示"KB 已转入待清理"标签，不从列表移除 |
| 10 | **[P3]** SSE 取消后后端资源泄漏 | 前端侧无法控制，已知问题。后端需在 `SseEmitter.onError/onTimeout` 回调中取消 RAGFlow 请求。NOT IN SCOPE（前端设计）|

### 目录结构（更新后）

```
frontend/
├── src/
│   ├── api/
│   │   ├── http.ts            # axios 实例（注入 Authorization + X-Org-Id）
│   │   ├── authApi.ts
│   │   ├── kbApi.ts
│   │   ├── docApi.ts
│   │   └── queryApi.ts        # SSE（原生 fetch + ReadableStream）
│   ├── components/
│   │   ├── KbSidebar.vue
│   │   ├── DocumentTable.vue
│   │   ├── ChatPanel.vue
│   │   └── SourceCard.vue
│   ├── composables/
│   │   └── useDocumentPolling.ts  # 轮询，含 10 分钟超时
│   ├── router/
│   │   └── index.ts
│   ├── stores/
│   │   ├── authStore.ts       # { token, username, orgId }，sessionStorage 持久化
│   │   └── chatStore.ts
│   ├── types/
│   │   ├── auth.ts            # LoginResponse, AuthState
│   │   ├── kb.ts              # KnowledgeBase, DeleteKbResponse
│   │   └── query.ts           # QueryChunkEvent, Message, Source
│   ├── utils/
│   └── views/
│       ├── LoginView.vue
│       └── KbWorkspaceView.vue
├── .env.development
└── vite.config.ts
```

---

## 十一、TODOS.md 待办项

以下事项 MVP 不实现，待后续迭代：

- [ ] **注册页面**（`/register`）+ 注册后引导创建组织流程
- [ ] **组织管理 UI**：创建组织、邀请成员（当前由管理员通过 API 手动操作）
- [ ] **后端 SSE 资源清理**：`SseEmitter.onError/onTimeout` 回调取消 RAGFlow 请求
- [ ] **多组织切换**：单用户属于多个组织时的切换 UI

---

## 十二、GSTACK REVIEW REPORT

**评审类型**: plan-eng-review（前端 UI 设计文档）  
**评审日期**: 2026-06-28  
**评审轮次**: 1

### 评审摘要

| 维度 | 结论 |
|------|------|
| 架构可行性 | 通过（含 5 条修订） |
| 代码质量预设 | 通过（加 src/types/ 目录） |
| 测试覆盖计划 | 通过（加 SSE 多行解析测试） |
| 性能 | 通过（MVP 阶段可接受） |
| 外部评审（Outside Voice） | 发现 1 个 P1 Blocker + 4 个 P2/P3 问题 |

### P1 Blocker（已解决）

- **X-Org-Id 请求头缺失**：后端 `JwtAuthFilter` 对所有受保护接口强制校验 `X-Org-Id` 请求头；原设计 `authStore` 无 `orgId` 字段，Axios 拦截器也未注入该头。已决策：后端 login 响应追加 `orgId`；前端 `authStore` + Axios 拦截器同步修改。

### 已解决问题清单（9 条）

见「十、plan-eng-review 评审决议」章节。

### 未解决 / NOT IN SCOPE

- SSE 取消后后端资源泄漏（前端侧无法控制，需后端修复）
- 注册 + 组织 Bootstrap UI（MVP 范围外，录入 TODOS.md）

### 评审结论

**设计文档已通过评审，可进入实现阶段。** 实现前需先对 `AuthService.login` 做后端小改（追加 `orgId` 响应字段），再启动前端开发。
