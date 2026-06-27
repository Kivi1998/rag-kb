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
