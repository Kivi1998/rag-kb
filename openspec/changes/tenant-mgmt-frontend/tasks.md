## 0. 后端前置改动（先于前端实现）

- [x] 0.1 `MemberController` 新增 `GET /api/v1/members/me`：通过 TenantContext.getMemberId() 返回当前用户的 Member 对象（含 role）
- [x] 0.2 `TeamService.create()` 加角色检查：仅 OWNER/ADMIN 可创建团队，MEMBER 抛出 AccessDeniedException

## 1. 类型定义与 API 层

- [x] 1.1 新增 `frontend/src/types/member.ts`：Member、MemberRole（'OWNER'|'ADMIN'|'MEMBER'，与后端枚举大写一致）、InviteMemberRequest（subjectId, role）、UpdateRoleRequest（role）
- [x] 1.2 新增 `frontend/src/types/team.ts`：Team、CreateTeamRequest（name）
- [x] 1.3 新增 `frontend/src/api/memberApi.ts`：list()、me()、invite({subjectId, role})、updateRole(id, role)、resetPassword(id) → 返回临时密码字符串
- [x] 1.4 新增 `frontend/src/api/teamApi.ts`：list()、create(name)

## 2. Store 层

- [x] 2.1 新增 `frontend/src/stores/memberStore.ts`：members ref、loadMembers、inviteMember(subjectId, role)、updateRole(id, role)、resetPassword(id) → 返回临时密码
- [x] 2.2 新增 `frontend/src/stores/teamStore.ts`：teams ref、loadTeams、createTeam(name)

## 3. 路由与导航

- [x] 3.1 在 `frontend/src/router/index.ts` 新增 `/admin` 路由（redirect → `/admin/members`）及 `/admin/members`、`/admin/teams` 子路由，引用懒加载组件
- [x] 3.2 路由守卫：`/admin/*` 路由检查 `authStore.role`，MEMBER 重定向 `/kb`，未登录重定向 `/login`
- [x] 3.3 在 `AppHeader.vue` 中，对 OWNER/ADMIN 显示「管理」导航入口

## 4. 成员管理页面

- [x] 4.1 新增 `frontend/src/views/AdminMembersView.vue`：el-table 展示成员列表（subjectId、角色标签、操作列）
- [x] 4.2 新增「添加成员」弹窗（el-dialog）：subjectId 输入框 + 角色下拉（ADMIN/MEMBER），提交调 memberStore.inviteMember
- [x] 4.3 操作列「修改角色」：el-select 行内下拉，仅 OWNER 可见（ADMIN 看不到），提交调 memberStore.updateRole
- [x] 4.4 操作列「重置密码」：确认后调 memberStore.resetPassword，成功弹窗展示临时密码（提示管理员告知用户）
- [x] 4.5 错误处理：后端 4xx 显示后端返回的错误消息（权限不足、成员已存在等），列表加载失败显示错误提示 + 重试按钮

## 5. 团队管理页面

- [x] 5.1 新增 `frontend/src/views/AdminTeamsView.vue`：el-table 展示团队列表（名称、创建时间），列表加载失败显示错误提示 + 重试按钮
- [x] 5.2 新增「新建团队」弹窗（el-dialog）：名称必填，提交调 teamStore.createTeam
- [x] 5.3 空状态：无团队时显示引导提示

## 6. authStore 扩展

- [x] 6.1 `authStore` 新增 `role` ref（类型 MemberRole | null）；登录成功后调用 `GET /api/v1/members/me` 获取当前用户角色存入 store；若 orgId 为空则 role 保持 null
- [x] 6.2 登录成功后检测 `mustChangePassword`：若为 true 则重定向到 `/change-password` 路由（复用已有 `POST /api/v1/auth/change-password` 接口）

## 7. 收尾

- [x] 7.1 TypeScript 无类型错误（`pnpm build` 通过）
- [ ] 7.2 提交所有变更到 `feat/tenant-mgmt-frontend` 分支

## 8. 测试

- [x] 8.1 路由守卫单元测试：role=MEMBER 访问 /admin/* → 重定向 /kb；role=OWNER|ADMIN → 放行；未登录 → /login
- [x] 8.2 memberStore 单元测试：inviteMember 成功/失败、updateRole 成功、resetPassword 成功返回临时密码
- [x] 8.3 teamStore 单元测试：createTeam 成功/名称为空
- [x] 8.4 表单校验测试：添加弹窗 subjectId 必填、新建团队名称必填
