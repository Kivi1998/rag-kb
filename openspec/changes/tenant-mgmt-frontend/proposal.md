## Why

后端已实现组织/成员/团队的完整 CRUD API，但目前缺少对应的前端管理界面，管理员（owner/admin）无法通过 UI 完成成员邀请、角色调整、团队创建等日常运营操作，制约了多租户系统的实际可用性。

## What Changes

- 新增「成员管理」页面：列表展示、邀请成员、修改角色、密码重置
- 新增「团队管理」页面：团队列表、新建团队
- 在主导航新增「管理」入口，仅 owner/admin 可见
- 新增前端 API 层、Store、类型定义对接后端已有接口

## Capabilities

### New Capabilities

- `frontend-member-mgmt`：成员管理 UI——邀请（POST /api/v1/members）、列表（GET /api/v1/members）、修改角色（PATCH /api/v1/members/{id}/role）、密码重置（POST /api/v1/members/{id}/reset-password）
- `frontend-team-mgmt`：团队管理 UI——列表（GET /api/v1/teams）、新建团队（POST /api/v1/teams）

### Modified Capabilities

- `frontend-app`：主导航新增「管理」路由入口，按角色（owner/admin）控制可见性

## Impact

- 仅影响 `frontend/src/` 目录：新增 views/Admin*、api/memberApi、api/teamApi、stores/memberStore、stores/teamStore、types/member.ts、types/team.ts
- 调用现有后端 API，无需改动 Spring Boot 代码
- 路由守卫需读取 authStore.role 做权限过滤

## Non-goals

- 不实现组织创建/切换（用户在登录后固定归属一个组织）
- 不实现成员删除（后端暂无该端点）
- 不实现团队成员关联管理（团队与成员关联的 API 尚未开放）
- 不实现超级管理员跨组织视图
