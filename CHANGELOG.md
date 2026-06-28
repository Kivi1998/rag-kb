# Changelog

## [0.2.0] - 2026-06-28

### 新增功能

- **成员管理** — OWNER/ADMIN 可邀请用户入组、修改成员角色、重置成员密码（显示临时密码）
- **团队管理** — OWNER/ADMIN 可创建团队，查看组织内团队列表
- **角色路由守卫** — 路由根据 OWNER/ADMIN/MEMBER 角色分级，MEMBER 无法访问 /admin/*
- **页面刷新守卫** — 刷新后异步 fetchRole 恢复角色状态，OWNER/ADMIN 不再被误重定向
- **强制改密流程** — 登录时后端标记 mustChangePassword，前端引导至 /change-password 完成后退出重登

### 安全修复

- **CRITICAL** — admin 不可重置 owner 的密码（防通过临时密码完成特权提升）；后端 MemberController + 前端按钮双重防护
- **HIGH** — TeamService.create() 在 role 为 null 时改抛 AccessDeniedException，不再产生未处理的 NPE 500 错误
- **HIGH** — /members/me 端点对 memberId 为 null 的情况返回 404，不再 NPE

### Bug 修复

- AppHeader 管理导航链接从普通变量改为 computed()，刷新后正确响应角色变化
- authStore 添加 roleFetched sentinel，fetchRole 失败后不再每次导航重试请求
- AdminMembersView/AdminTeamsView 操作失败时显示错误提示（之前静默失败）
- ChangePasswordView 移除未使用的 useRouter 引用
- MemberController 修正 ResourceNotFoundException 使用 fully-qualified 路径的问题

### 测试

- 新增路由守卫异步 fetchRole 测试用例（页面刷新后 OWNER 放行）
- 路由测试守卫与真实守卫对齐（async + roleFetched sentinel）
- 修正 form-validation 测试中误导性的测试名称
- 前端单元测试共 50 个，全部通过
