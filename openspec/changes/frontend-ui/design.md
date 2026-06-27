## Context

rag-kb 后端已具备完整 REST API（认证/KB CRUD/文档摄取/SSE 流式问答），技术栈 Spring Boot + RAGFlow + Xinference。前端为全新 greenfield 工程，无历史包袱。

多租户安全约束：后端每个受保护接口均强制校验 `X-Org-Id` 请求头（JwtAuthFilter），login 响应需返回 orgId；前端 Axios 拦截器必须同时注入 Authorization 和 X-Org-Id 两个请求头，否则所有接口 401。原生 fetch（用于 SSE）不经过 Axios，需手动从 authStore 读取 token + orgId 并写入 fetch headers。

设计文档详见：`docs/superpowers/specs/2026-06-28-frontend-ui-design.md`（含 plan-eng-review 全部决议）。

## Goals / Non-Goals

**Goals:**
- 交付端到端可用的 MVP 前端：登录 → KB 管理 → 文档管理 → 流式问答
- 正确注入双请求头（Authorization + X-Org-Id），打通多租户认证链路
- 覆盖 stores/api/composables 核心逻辑测试（目标 ≥ 60%）

**Non-Goals:**
- 注册页 / 组织 Bootstrap UI
- 多组织切换、SSO/OIDC
- 服务端持久化聊天历史
- 移动端适配 / 暗色主题
- 角色感知删除按钮隐藏（普通 member 会 403，录入 TODOS.md）
- mustChangePassword 流程（录入 TODOS.md）

## Decisions

**D1 — Token 存储：sessionStorage**
理由：比 localStorage 更小的 XSS 暴露窗口（标签关闭即清除）；toB 场景用户无跨标签持久化诉求。

**D2 — orgId 获取方式：login 响应**
后端 JwtAuthFilter 要求每个受保护请求携带 `X-Org-Id` 头，但 login 响应原本无 orgId。MVP 单组织假设下最简方案是后端在 login 响应 Map 中追加 `orgId`。authStore 同时存储 token、userId、orgId。登录响应 orgId=null（用户未加入组织）时，authStore.login() 不存储 token，直接展示"账号未分配组织，请联系管理员"，不跳转 /kb。

**D3 — HTTP 客户端：Vite proxy + 相对路径（SSE fetch 需手动注头）**
开发期 Axios baseURL 为空，所有请求 `/api/v1/...` → Vite proxy → `localhost:8080`，绕过 CORS。生产通过 `VITE_API_BASE_URL` 环境变量前缀控制。SSE 使用原生 fetch（Axios 不支持流式读取）。

重要：原生 fetch 完全绕过 Axios 拦截器，queryApi.stream() 必须手动从 authStore 读取 token + orgId，在 fetch headers 中显式设置 `Authorization: Bearer <token>` 和 `X-Org-Id: <orgId>`，否则 POST /query 返回 401。

**D4 — SSE 流：原生 fetch + ReadableStream + AbortController（存 chatStore state）**
Spring SseEmitter 产出多行格式 `event:\ndata:\n\n`，原生 fetch 逐行解析最直接。AbortController 实例存储在 chatStore state（`currentAbortController: AbortController | null`），由 chatStore 在发起问答时创建并持有。ChatPanel 从 chatStore 取 `currentAbortController.signal` 传给 queryApi.stream()。切换 KB 时 chatStore.switchKb() 直接调用 abort()，不经过组件层。取消顺序：abort → 清空 currentAnswer → 更新 selectedKbId。

fetch 额外要求：
1. 获取 Response 后先验证 `response.ok`，否则抛出 Error 触发 handleError（避免把 JSON 错误体当 SSE 解析）
2. stream 读取完毕（reader.done=true）但未收到 done 事件（后端 SseEmitter 5 分钟超时关闭连接）时，自动触发 handleDone，避免 streaming 状态卡死

**D5 — 类型层：src/types/（使用 KbDocument，避免 DOM 名称冲突）**
所有后端 DTO 映射放 `src/types/`（auth.ts / kb.ts / document.ts / query.ts），与 api/ 层解耦，测试可独立 import。文档类型命名为 `KbDocument`（避免与 DOM 全局 `Document` 接口冲突，Vite 项目默认包含 DOM lib）。状态枚举：`KbDocumentStatus { UPLOADING, PARSING, READY, FAILED }`（与后端 DocumentStatus 完全一致）。

目录结构：
```
src/
├── api/         # authApi.ts, kbApi.ts, docApi.ts, queryApi.ts
├── composables/ # useDocumentPolling.ts
├── stores/      # authStore.ts, chatStore.ts, kbStore.ts
├── views/       # LoginView.vue, KbWorkspaceView.vue
├── components/  # AppHeader.vue, KbSidebar.vue, DocumentTable.vue, ChatPanel.vue, SourceCard.vue
└── types/       # auth.ts, kb.ts, document.ts, query.ts
```

**D6 — 文档轮询：list + PARSING detail 双接口策略，10 分钟超时上限**
后端 `listByKb` 只返回存储状态，PARSING 状态不触发 RAGFlow 查询；仅 `GET /documents/{docId}` 才刷新 PARSING→READY（服务层注释明确）。轮询策略：
1. 每 3 秒调用 GET /documents 获取全量列表
2. 对列表中每个 PARSING 文档额外调用 GET /documents/{docId} 触发状态刷新
3. 轮询停止条件：全部文档状态为 READY 或 FAILED（无 UPLOADING/PARSING）
4. 超过 10 分钟后停止轮询并显示"部分文档处理超时，请手动刷新"警告，返回 `timedOut: true`

**D7 — KB 删除：检查 response.code 区分完全删除与 PENDING_CLEANUP**
后端 `ApiResponse<String>`：成功时 `{ code:0, data:"已删除" }`；RAGFlow dataset 删除失败时 `{ code:202, message:"..." }`（无 data 字段，`@JsonInclude(NON_NULL)` 省略 null）。**`data.deleted` 字段不存在**，不可依赖。前端检查 code：0 → 从列表移除；202 → 显示"待清理"el-tag 保留在列表。注意：Axios 响应拦截器对 code=202 不抛错误，直接透传原始 `{ code, message }` 给调用方判断。

**D8 — API 响应 envelope 解包：Axios 响应拦截器统一处理**
所有后端响应格式：`{ code: number, message: string, data: T | null }`（ApiResponse<T>）。Axios 响应拦截器解包规则：
- HTTP 2xx 且 code=0：返回 `response.data.data` 作为业务数据
- HTTP 2xx 且 code=202（PENDING_CLEANUP）：透传 `{ code, message }` 给调用方，不抛错
- HTTP 2xx 且 code≠0 且 code≠202：抛出含 code+message 的 Error，el-message 提示
- HTTP 401：清除 authStore，跳转 /login
- HTTP 4xx/5xx：el-message 提示 `response.data.message`

## Risks / Trade-offs

- **后端 login 响应依赖**：前端 auth 功能强依赖后端 `AuthService.login` 追加 orgId（任务 1.1）。若后端未改，前端所有受保护接口均失败。→ 后端先改，再开始前端开发。
- **SSE 多行解析**：浏览器 ReadableStream 按 Uint8Array chunk 分发，可能在 event/data 行中间切断。→ 实现累积缓冲区，逐块追加后按 `\n\n` 切分完整事件。
- **SSE 服务端 5 分钟超时**：后端 SseEmitter 超时后连接关闭，无 done 事件。→ reader.done=true 但未收 done 事件时，自动触发 handleDone 清理状态。
- **轮询 N+1**：PARSING 文档需额外调详情接口。MVP 百文档级别可接受；文档规模增大后建议改为 WebSocket 推送。
- **内存聊天历史**：刷新后历史丢失。MVP 可接受，后续可引入 indexedDB 持久化。
- **Vite proxy 仅开发可用**：生产需 Nginx/CDN 反向代理或配置 `VITE_API_BASE_URL`。→ 部署文档需说明。

---

## GSTACK REVIEW REPORT

**Reviewer:** gstack /plan-eng-review  
**Date:** 2026-06-28  
**Target:** OpenSpec change `frontend-ui`  
**Verdict:** APPROVED WITH REVISIONS（13 项决议，4 项 P1 Blocker 由外部评审新发现）

### 决议汇总

| # | Section | 问题 | 决议 |
|---|---------|------|------|
| 1 | Architecture | AbortController 归属未指定：chatStore.switchKb() 无法访问 ChatPanel 本地 controller | 存 chatStore.state.currentAbortController |
| 2 | Architecture | kbStore "或 KbSidebar 组件内管理" 歧义：selectedKbId 需三组件共享，组件层不可行 | 确定为 Pinia kbStore，删除歧义文字 |
| 3 | Architecture | SSE fetch 未检查 response.ok：4xx 时将 JSON 错误体当 SSE 解析 | 读 stream 前先检查 response.ok |
| 4 | Code Quality | Document 类型与 DOM 全局 Document 接口名称冲突（Vite 默认包含 DOM lib） | 改名为 KbDocument，状态枚举 KbDocumentStatus |
| 5 | Code Quality | kbStore.ts 未出现在 design.md 目录结构（与 tasks.md 不同步） | 追加 kbStore.ts 到目录结构 |
| 6 | Tests | chatStore handleSource/handleError 无独立测试 | 追加到 tasks.md 10.2 |
| 7 | Tests | authStore orgId=null 场景无测试 | 追加到 tasks.md 10.1 |
| 8 | Outside Voice (P1) | SSE 使用原生 fetch，完全绕过 Axios 拦截器 → POST /query 无认证头 → 401 | queryApi.stream() 手动注入 Authorization + X-Org-Id |
| 9 | Outside Voice (P1) | KB 删除合约错误：data.deleted 字段不存在，实际返回 ApiResponse<String> + code 字段 | 改为检查 response.code：0=已删除，202=待清理 |
| 10 | Outside Voice (P1) | 文档状态枚举错误（ACTIVE/ERROR 不存在）+ 轮询 list 接口无法看到 PARSING→READY 转变 | 状态改为 UPLOADING/PARSING/READY/FAILED；轮询 = list + PARSING 详情 |
| 11 | Outside Voice (P1) | Axios 拦截器未解包 ApiResponse envelope：前端 API 层直接收到 {code,message,data} 而非业务数据 | 拦截器解包 data，code≠0 报业务错误，202 透传 |
| 12 | Outside Voice | SSE 服务端 5 分钟超时后无 done 事件 → streaming 卡死 | stream 读完未收 done → 触发 handleDone |
| 13 | Outside Voice | 删除操作需 admin/owner 权限，但前端无角色控制 UI | MVP 录入 TODOS.md，403 时 el-message 提示 |

### NOT in scope for this change
- 注册页、组织 Bootstrap UI
- 多组织切换、SSO/OIDC
- 服务端聊天历史持久化
- 移动端响应式 / 暗色主题
- 角色感知删除按钮（TODOS.md）
- mustChangePassword 流程（TODOS.md）
- 文档列表分页（既有 TODOS.md）

### What already exists (backend)
- AuthController（POST /auth/login）
- KnowledgeBaseController（CRUD + delete with PENDING_CLEANUP）
- DocumentController（upload/list/delete + GET /{docId} 刷新状态）
- QueryController（POST /query SSE，SseEmitter 5 分钟超时）
- JwtAuthFilter（X-Org-Id 校验）
- ApiResponse<T> envelope（{code, message, data}）
- DocumentStatus 枚举（UPLOADING/PARSING/READY/FAILED）
- TenantContext（orgId/memberId/role RLS）

### Failure modes & mitigations
1. orgId=null 登录 → authStore 显示错误，不跳转 /kb
2. SSE 无认证头 401 → queryApi.stream() 手动注头（D3 决议）
3. PARSING 文档永不变 READY → 轮询额外调详情接口（D6 决议）
4. KB 删除 code=202 误判为成功 → 检查 code 字段（D7 决议）
5. API 返回 {code,message,data} 被当 DTO 使用 → 拦截器统一解包（D8 决议）
6. SSE 超时无 done → reader.done 时自动 handleDone（D4 决议）
7. SSE response.ok=false 静默失败 → response.ok 检查 throw（D3+D4 决议）

### Worktree 并行化建议
- **WT-1**（先跑）：Task group 1（后端 orgId）+ 2（脚手架）+ 3（类型层）+ 4（HTTP client）
- **WT-2**（WT-1 完成后）：Task group 5（路由/登录）+ 6（KB API/store）+ 7（KB 工作台）
- **WT-3**（与 WT-2 并行）：Task group 8（文档管理）
- **WT-4**（与 WT-2/3 并行）：Task group 9（SSE 问答）
- **WT-5**（最后）：Task group 10（测试）
