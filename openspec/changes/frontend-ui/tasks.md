## 1. 后端前置修改（P1 Blocker）

- [ ] 1.1 `AuthService.login` 响应 Map 追加 `orgId` 字段：注入 `MemberRepository`，查询当前用户首个成员身份（`findFirstByUserIdOrderByCreatedAsc`），取 org UUID；用户无成员记录时 orgId 返回 null
- [ ] 1.2 更新 `AuthServiceTest`：补充 login 响应包含 orgId 的断言；补充 orgId=null（用户无组织）分支断言

## 2. 前端工程脚手架

- [ ] 2.1 用 `pnpm create vue@latest frontend` 初始化工程（Vue 3 + TypeScript + Vue Router + Pinia + Vitest），选择 `<script setup>` 语法
- [ ] 2.2 安装依赖：Element Plus、element-plus/icons-vue、Axios、@types/node
- [ ] 2.3 配置 `vite.config.ts`：proxy `/api` → `http://localhost:8080`，设置路径别名 `@` → `src/`
- [ ] 2.4 配置 `.env.development`（`VITE_API_BASE_URL=`）和 `.env.production`（`VITE_API_BASE_URL=`留空由部署配置注入）
- [ ] 2.5 配置 Element Plus 全局注册（`main.ts`）和图标组件自动导入
- [ ] 2.6 创建目录结构：`src/api/`、`src/stores/`、`src/views/`、`src/components/`、`src/types/`、`src/composables/`

## 3. 类型层（src/types/）

- [ ] 3.1 `src/types/auth.ts`：`LoginResponse { token, userId, orgId: string | null }`、`AuthState { token, userId, orgId }`
- [ ] 3.2 `src/types/kb.ts`：`KnowledgeBase { id, name, status: 'ACTIVE' | 'PENDING_CLEANUP', createdAt }`（无 DeleteKbResponse；删除结果由 response.code 判断，见 kbApi）
- [ ] 3.3 `src/types/document.ts`：`KbDocument { id, name, status: KbDocumentStatus, errorMessage?, createdAt }`、`KbDocumentStatus 枚举：UPLOADING / PARSING / READY / FAILED`（与后端 DocumentStatus 完全一致）
- [ ] 3.4 `src/types/query.ts`：`QueryChunkEvent { eventType, content, documentName, score, message }`、`Message { role, content, sources }`、`Source { documentName, content, score }`

## 4. HTTP 客户端与认证 Store

- [ ] 4.1 `src/api/http.ts`：创建 Axios 实例，baseURL 留空（Vite proxy），设置 timeout 15s
- [ ] 4.2 Axios **请求**拦截器：从 authStore 读取 token 和 orgId，注入 `Authorization: Bearer <token>` 和 `X-Org-Id: <orgId>`。**注意：此拦截器不覆盖 SSE 的原生 fetch 请求**，SSE 认证头由 queryApi.stream() 手动注入（见 9.1）
- [ ] 4.3 Axios **响应**拦截器（ApiResponse envelope 解包）：
  - HTTP 2xx + code=0：返回 `response.data.data` 作为业务数据
  - HTTP 2xx + code=202：透传 `{ code: 202, message }` 给调用方（PENDING_CLEANUP，不报错）
  - HTTP 2xx + code≠0 且 code≠202：`el-message.error(response.data.message)` 并 throw
  - HTTP 401：清除 authStore，`router.push('/login')`
  - HTTP 4xx/5xx/网络超时：`el-message.error(...)` 提示
- [ ] 4.4 `src/stores/authStore.ts`：state `{ token, username, orgId }`，sessionStorage 持久化；`login action`（调 authApi → 若 orgId=null 则 el-message 提示"账号未分配组织"且不存储 token；否则存储三个字段）；`logout action`（清除 sessionStorage + 跳 /login）
- [ ] 4.5 `src/api/authApi.ts`：`login(email, password)` → POST /api/v1/auth/login → LoginResponse

## 5. 路由与登录页

- [ ] 5.1 `src/router/index.ts`：定义 /login、/ → redirect /kb、/kb（懒加载），`beforeEach` 守卫：无 token 跳 /login，已登录访问 / 跳 /kb
- [ ] 5.2 `src/views/LoginView.vue`：el-form + el-form-item（邮箱 + 密码）、el-button（登录），表单校验、回车提交、加载状态、错误提示
- [ ] 5.3 顶部 `AppHeader` 组件：显示当前用户名 + 退出登录按钮，退出调用 authStore.logout()

## 6. 知识库 API 与 Store

- [ ] 6.1 `src/api/kbApi.ts`：`list()`、`create(name)`、`update(id, name)`、`remove(id)` → 对应 KB CRUD 接口；`remove` 返回值需保留原始 `{ code, message }`（由拦截器透传 code=202），调用方检查 code 决定行为
- [ ] 6.2 `src/stores/kbStore.ts`（**必须为 Pinia store**，selectedKbId 由 KbSidebar/DocumentTable/ChatPanel 三组件共享，不可改为组件内部状态）：state `{ kbs: KnowledgeBase[], selectedKbId: string | null }`；actions `loadKbs()`、`createKb(name)`、`renameKb(id, name)`、`deleteKb(id)`

## 7. KB 工作台布局与侧边栏

- [ ] 7.1 `src/views/KbWorkspaceView.vue`：左侧 220px el-menu 侧边栏 + 主内容区 el-tabs（文档管理/问答）
- [ ] 7.2 `src/components/KbSidebar.vue`：渲染 KB 列表，"新建知识库"按钮触发创建弹窗，每项操作菜单含重命名/删除；PENDING_CLEANUP 状态 KB 显示"待清理" el-tag
- [ ] 7.3 创建 KB 弹窗（el-dialog + el-form）：名称必填校验，调用 kbApi.create，成功后刷新列表并自动选中新 KB
- [ ] 7.4 重命名 KB 弹窗：回填当前名称，调用 kbApi.update
- [ ] 7.5 删除 KB 确认：el-message-box，调用 kbApi.remove，**检查 response.code**：code=0 → 从 kbStore 移除；code=202 → KB 状态改为 PENDING_CLEANUP，显示"待清理"标签，不移除

## 8. 文档管理

- [ ] 8.1 `src/api/docApi.ts`：`list(kbId)`、`get(kbId, docId)`（触发 PARSING→READY 刷新）、`upload(kbId, file: File)`、`remove(kbId, docId)`
- [ ] 8.2 `src/composables/useDocumentPolling.ts`：接收 kbId ref；存在 UPLOADING 或 PARSING 状态文档时每 3 秒轮询：1) 调 docApi.list 获取全量列表，2) 对每个 PARSING 状态文档额外调 docApi.get 触发 RAGFlow 状态刷新；轮询停止条件：全部文档为 READY 或 FAILED；10 分钟超时停止并设 timedOut=true；onUnmounted 清除定时器；返回 `{ docs, isPolling, timedOut }`
- [ ] 8.3 `src/components/DocumentTable.vue`：el-table 展示文档列表（名称/状态徽章/时间/操作列）；状态显示：UPLOADING→loading 图标，PARSING→蓝色"解析中"徽章，READY→绿色"就绪"徽章，FAILED→红色徽章+tooltip；el-upload 上传区；timedOut 时显示警告横幅
- [ ] 8.4 删除文档确认：el-message-box，调用 docApi.remove，成功后移除列表项

## 9. SSE 流式问答

- [ ] 9.1 `src/api/queryApi.ts`：`stream(kbId, question, signal: AbortSignal)` —
  1. 从 authStore 读取 token + orgId，在 fetch headers 手动设置 `Authorization: Bearer <token>` 和 `X-Org-Id: <orgId>`（Axios 拦截器不覆盖原生 fetch）
  2. `await fetch(...)` 后先检查 `response.ok`，否则 throw Error 触发 handleError
  3. 使用 ReadableStream 逐块解码 Uint8Array，累积缓冲区，按 `\n\n` 切分完整 SSE 事件块，按 event 类型 yield 事件对象
  4. reader.done=true 但未收到 done 事件时（服务端 5 分钟超时），调用 handleDone 清理状态
- [ ] 9.2 `src/stores/chatStore.ts`：state `{ histories: Record<kbId, Message[]>, streaming: boolean, currentAnswer: string, pendingSources: Source[], currentAbortController: AbortController | null }`；actions：`handleChunk(content)`、`handleSource(source)`、`handleDone()`、`handleError(msg)`、`switchKb(newKbId)`（顺序：abort currentAbortController → 清空 currentAnswer + streaming=false → 更新 kbStore.selectedKbId）
- [ ] 9.3 `src/components/ChatPanel.vue`：消息气泡列表（用户/助手），实时渲染 currentAnswer，输入框 + 发送按钮（streaming=true 时禁用），错误气泡（红色），来源卡片按 score 降序
- [ ] 9.4 `src/components/SourceCard.vue`：展示 documentName、引用片段（截断 200 字）、分数徽章

## 10. 测试

- [ ] 10.1 `authStore.test.ts`：login 成功存 token + orgId；login 失败不存储；logout 清除 sessionStorage；**login 返回 orgId=null 时显示错误提示且不存 token、不跳转**
- [ ] 10.2 `chatStore.test.ts`：多 kbId 历史隔离；chunk 事件拼接 currentAnswer；done 事件归档 Message + 清空 currentAnswer；**source 事件追加 pendingSources**；**error 事件插入错误气泡**；switchKb 按顺序 abort/clear/switch
- [ ] 10.3 `useDocumentPolling.test.ts`：存在 UPLOADING 或 PARSING 时触发轮询；全部 READY/FAILED 后停止；对 PARSING 文档额外调详情接口；10 分钟超时触发 timedOut；unmount 清定时器
- [ ] 10.4 `queryApi.test.ts`：SSE 多行格式解析（event:\ndata:\n\n）；chunk/source/done/error 四类事件正确识别；跨 chunk 边界累积缓冲区拼接；**HTTP 4xx（response.ok=false）触发 handleError 而非静默失败**；**stream 结束未收 done 事件时触发 handleDone**
- [ ] 10.5 `router.test.ts`：未登录访问 /kb 跳转 /login；已登录访问 / 重定向 /kb
- [ ] 10.6 运行 `pnpm test --coverage` 验证 stores/api/composables 覆盖率 ≥ 60%
