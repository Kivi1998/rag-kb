## Context

rag-kb 前端已有 KB 管理、文档管理、问答三个核心页面（Vue 3 + Element Plus + Pinia）。后端租户 API 已就绪：`/api/v1/members`（列表/邀请/改角色/重置密码）、`/api/v1/teams`（列表/新建）。本次在现有工程结构内新增管理页面，不引入新依赖。

## Goals / Non-Goals

**Goals:**
- owner/admin 通过 UI 完成成员邀请、角色调整、密码重置
- owner/admin 通过 UI 完成团队创建与浏览
- 路由级权限守卫：role=member 无法访问管理页

**Non-Goals:**
- 成员删除、团队成员关联、跨组织管理（后端暂不支持）
- 移动端适配

## Decisions

**D1 — 路由结构**：新增 `/admin` 路由，子路由 `/admin/members` 和 `/admin/teams`。导航栏对 role=owner|admin 显示「管理」入口；路由守卫从 `authStore.role` 读取，role=member 重定向 `/kb`。

**D2 — 角色信息来源**：登录时后端 JWT 已返回 role 字段，存入 `authStore.role`（sessionStorage）。无需额外请求，直接读取。若 role 字段缺失则视为 member（最低权限，安全降级）。

**D3 — Store 设计**：`memberStore`（list/invite/updateRole/resetPassword）和 `teamStore`（list/create）各自独立，与 `kbStore` 平级，不共享状态。

**D4 — 邀请成员方式**：后端 POST /api/v1/members 接受 `{email, password, role}`，即直接创建账号（非发邮件邀请）。前端以「新增成员」弹窗实现，字段：邮箱、初始密码、角色。

**D5 — 密码重置**：POST /api/v1/members/{id}/reset-password 接受 `{newPassword}`，由 admin/owner 在列表操作列触发弹窗输入新密码后提交。

## Risks / Trade-offs

- **角色 SSoT**：role 从 JWT 读取，若后端变更角色后用户不重新登录则前端显示旧角色——可接受，属已知限制，刷新登录即解决。
- **密码明文传输**：初始密码和重置密码在 HTTPS 下传输，开发环境 HTTP 有风险——记录为 TODOS，生产必须启用 HTTPS。
