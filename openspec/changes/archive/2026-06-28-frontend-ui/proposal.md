## Why

rag-kb 已完成后端三层架构（认证/KB管理/文档摄取/流式问答），但缺少前端界面，管理员和业务用户只能通过 API 工具操作，无法投入实际使用。本次变更交付 MVP 前端 UI，使产品具备完整的端到端可用性。

## What Changes

- 新增 `frontend/` 目录，Vue 3 + TypeScript + Element Plus + Pinia + Vue Router + Vite 工程
- 登录页（JWT 认证，sessionStorage 存 token + orgId）
- 知识库工作台（左侧 KB 导航 + 标签页切换文档管理 / 问答）
- 文档管理：上传、列表、处理状态轮询（含 10 分钟超时）、删除
- 流式问答：SSE 实时渲染、多轮历史（内存，按 KB 隔离）、引用来源卡片
- Axios 拦截器统一注入 `Authorization` + `X-Org-Id` 请求头
- **后端小改**：`AuthService.login` 响应追加 `orgId` 字段（前端获取 orgId 的唯一途径）

## Capabilities

### New Capabilities

- `frontend-app`: Vue 3 前端应用工程脚手架（src/api、stores、views、types、composables 完整目录结构）
- `frontend-auth`: 登录 UI + JWT/orgId 存取 + 路由守卫 + Axios 双头注入
- `frontend-kb-management`: 知识库 CRUD + 左侧导航（创建/重命名/删除，含删除 202 部分成功处理）
- `frontend-document-management`: 文档上传/列表/删除 + 处理状态轮询（含超时）
- `frontend-chat`: SSE 流式问答 + 历史管理 + 引用来源卡片

### Modified Capabilities

- `local-auth`: login 响应追加 `orgId` 字段（仅响应体扩展，无行为变更）

## Impact

- 新增 `frontend/` 目录（~19 个文件，约 1,500 LOC）
- 后端 `AuthService.login` 修改一处（追加 orgId 到响应 Map）
- 无破坏性 API 变更；后端其他接口仅新增 `X-Org-Id` 请求头校验（已存在于 JwtAuthFilter）
- 依赖：pnpm、Node ≥ 20、Vite 5、Vue 3.5、Element Plus 2.x

## Non-goals（非目标）

- 注册页面与组织 Bootstrap UI（管理员通过 API 手动创建）
- 多组织切换（MVP 单组织视图）
- SSO/OIDC 集成
- 服务端持久化聊天历史（内存存储，刷新重置）
- 暗色主题 / 响应式移动端适配
