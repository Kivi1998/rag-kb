# frontend-app Specification

## Purpose
rag-kb 前端应用基础：工程脚手架、类型层、路由与权限守卫。
## Requirements
### Requirement: 前端工程脚手架

系统 SHALL 提供基于 Vue 3 + TypeScript + Element Plus + Pinia + Vue Router 4 + Vite + pnpm 的前端工程，目录结构 MUST 包含 `src/api/`、`src/stores/`、`src/views/`、`src/components/`、`src/types/`、`src/composables/`。

#### Scenario: 开发环境启动

- **WHEN** 执行 `pnpm dev`
- **THEN** Vite 启动开发服务器，代理 `/api` 到 `http://localhost:8080`，页面可访问

#### Scenario: 生产构建

- **WHEN** 执行 `pnpm build` 并设置 `VITE_API_BASE_URL`
- **THEN** 输出 `dist/` 目录，API 请求使用配置的 base URL

### Requirement: TypeScript 类型层

`src/types/` 目录 SHALL 包含所有后端 DTO 映射类型：`auth.ts`（LoginResponse、AuthState）、`kb.ts`（KnowledgeBase）、`query.ts`（QueryChunkEvent、Message、Source）、`document.ts`（KbDocument、KbDocumentStatus 枚举：UPLOADING/PARSING/READY/FAILED）。

#### Scenario: 类型导入

- **WHEN** 开发者在 api/ 或 stores/ 中引用后端 DTO
- **THEN** 可从 `@/types/*` 导入类型，TypeScript 无类型错误

### Requirement: 管理路由与权限守卫

系统 SHALL 新增 `/admin` 路由组（子路由 `/admin/members`、`/admin/teams`），MUST 在路由守卫中校验 `authStore.role`：role=owner 或 admin 方可进入；role=member 重定向 `/kb`；未登录重定向 `/login`。主导航 MUST 对 owner/admin 显示「管理」入口，对 member 隐藏。访问 `/admin` 本身时 MUST 重定向至 `/admin/members`。

#### Scenario: owner/admin 访问管理页

- **WHEN** role=owner 或 role=admin 的已登录用户访问 `/admin/members` 或 `/admin/teams`
- **THEN** 路由守卫放行，正常渲染目标页面，主导航显示「管理」入口

#### Scenario: member 访问管理页被重定向

- **WHEN** role=member 的已登录用户访问 `/admin/*` 任意路由
- **THEN** 路由守卫重定向至 `/kb`，不渲染管理页面，主导航不显示「管理」入口

#### Scenario: 未登录用户访问管理页

- **WHEN** 未登录用户（无有效 token）访问 `/admin/*` 任意路由
- **THEN** 路由守卫重定向至 `/login`

#### Scenario: 访问 /admin 根路由

- **WHEN** 已登录的 owner/admin 访问 `/admin`（不含子路径）
- **THEN** 自动重定向至 `/admin/members`

