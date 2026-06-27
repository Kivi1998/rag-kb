## Context

rag-kb 后端已具备完整 REST API（认证/KB CRUD/文档摄取/SSE 流式问答），技术栈 Spring Boot + RAGFlow + Xinference。前端为全新 greenfield 工程，无历史包袱。

多租户安全约束：后端每个受保护接口均强制校验 `X-Org-Id` 请求头（JwtAuthFilter），login 响应需返回 orgId；前端 Axios 拦截器必须同时注入 Authorization 和 X-Org-Id 两个请求头，否则所有接口 401。

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

## Decisions

**D1 — Token 存储：sessionStorage**
理由：比 localStorage 更小的 XSS 暴露窗口（标签关闭即清除）；toB 场景用户无跨标签持久化诉求。

**D2 — orgId 获取方式：login 响应**
后端 JwtAuthFilter 要求每个受保护请求携带 `X-Org-Id` 头，但 login 响应原本无 orgId。MVP 单组织假设下最简方案是后端在 login 响应 Map 中追加 `orgId`。替代方案（/me/memberships 接口）多一次网络往返，延后讨论。

**D3 — HTTP 客户端：Vite proxy + 相对路径**
开发期 Axios baseURL 为空，所有请求 `/api/v1/...` → Vite proxy → `localhost:8080`，绕过 CORS。生产通过 `VITE_API_BASE_URL` 环境变量前缀控制。SSE 使用原生 fetch（Axios 不支持流式读取）。

**D4 — SSE 流：原生 fetch + ReadableStream + AbortController**
Spring SseEmitter 产出多行格式 `event:\ndata:\n\n`，原生 fetch 逐行解析最直接。AbortController 支持切换 KB 时取消进行中请求，取消顺序：abort → 清空 currentAnswer → 更新 selectedKbId。

**D5 — 类型层：src/types/**
所有后端 DTO 映射放 `src/types/`（auth.ts / kb.ts / query.ts），与 api/ 层解耦，测试可独立 import。

**D6 — 文档轮询：10 分钟超时上限**
`useDocumentPolling` 每 3 秒拉取一次文档列表；超过 10 分钟后停止轮询并显示"处理超时"提示，防止后端解析卡死导致前端永久轮询。

**D7 — KB 删除 202 处理**
后端删除 KB 时若 RAGFlow dataset 删除失败，返回 HTTP 200 但 `data.deleted = false`。前端检查该字段：true → 移除列表；false → 显示"待清理"标签。

## Risks / Trade-offs

- **后端 login 响应依赖**：前端 auth 功能强依赖后端 `AuthService.login` 追加 orgId。若后端未改，前端所有受保护接口均失败。→ 后端先改，再开始前端开发。
- **SSE 多行解析**：浏览器 ReadableStream 按 Uint8Array chunk 分发，可能在 event/data 行中间切断。→ 实现累积缓冲区，逐块追加后按 `\n\n` 切分完整事件。
- **内存聊天历史**：刷新后历史丢失。MVP 可接受，后续可引入 indexedDB 持久化。
- **Vite proxy 仅开发可用**：生产需 Nginx/CDN 反向代理或配置 `VITE_API_BASE_URL`。→ 部署文档需说明。
