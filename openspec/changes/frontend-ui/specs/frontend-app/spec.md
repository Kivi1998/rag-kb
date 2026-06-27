## ADDED Requirements

### Requirement: 前端工程脚手架

系统提供基于 Vue 3 + TypeScript + Element Plus + Pinia + Vue Router 4 + Vite + pnpm 的前端工程，目录结构包含 `src/api/`、`src/stores/`、`src/views/`、`src/components/`、`src/types/`、`src/composables/`。

#### Scenario: 开发环境启动

- **WHEN** 执行 `pnpm dev`
- **THEN** Vite 启动开发服务器，代理 `/api` 到 `http://localhost:8080`，页面可访问

#### Scenario: 生产构建

- **WHEN** 执行 `pnpm build` 并设置 `VITE_API_BASE_URL`
- **THEN** 输出 `dist/` 目录，API 请求使用配置的 base URL

### Requirement: TypeScript 类型层

`src/types/` 目录包含所有后端 DTO 映射类型：`auth.ts`（LoginResponse、AuthState）、`kb.ts`（KnowledgeBase、DeleteKbResponse）、`query.ts`（QueryChunkEvent、Message、Source）、`document.ts`（Document、DocumentStatus 枚举）。

#### Scenario: 类型导入

- **WHEN** 开发者在 api/ 或 stores/ 中引用后端 DTO
- **THEN** 可从 `@/types/*` 导入类型，TypeScript 无类型错误
