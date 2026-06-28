# frontend-member-mgmt Specification

## Purpose
rag-kb 成员管理前端：OWNER/ADMIN 可查看组织成员列表、邀请成员、修改角色、重置密码。

## Requirements

### Requirement: 成员列表

系统 SHALL 在 `/admin/members` 页面展示当前组织所有成员，MUST 显示邮箱、角色（owner/admin/member 角色标签）。列表通过 GET /api/v1/members 加载。

#### Scenario: 加载成员列表

- **WHEN** owner 或 admin 进入成员管理页
- **THEN** 调用 GET /api/v1/members 并以表格形式展示，每行含邮箱、角色标签、操作列

#### Scenario: 普通成员访问重定向

- **WHEN** role=member 的用户访问 `/admin/members`
- **THEN** 路由守卫重定向至 `/kb`，不渲染页面

### Requirement: 邀请成员

系统 SHALL 提供「新增成员」弹窗，MUST 收集 subjectId（用户 UUID）、角色（admin/member，不含 owner），通过 POST /api/v1/members 创建账号。

#### Scenario: 新增成员成功

- **WHEN** admin 填写 subjectId、角色并确认
- **THEN** 调用 POST /api/v1/members，成功后新成员出现在列表中并提示「添加成功」

#### Scenario: 成员已存在

- **WHEN** 提交的 subjectId 已是本组织成员
- **THEN** 后端返回错误，前端显示错误信息

### Requirement: 修改角色

系统 SHALL 允许 owner 在成员列表操作列通过下拉选择修改成员角色（owner 可设置 owner/admin/member；MUST NOT 允许降级最后一名 owner）。调用 PATCH /api/v1/members/{id}/role。

#### Scenario: 修改角色成功

- **WHEN** owner 为某成员选择新角色并确认
- **THEN** 调用 PATCH /api/v1/members/{id}/role，成功后列表角色标签更新，显示「角色已更新」

#### Scenario: admin 尝试修改角色被服务端拒绝

- **WHEN** admin 尝试修改他人角色（后端返回 403）
- **THEN** 前端显示「角色修改失败」提示，角色不变

### Requirement: 密码重置

系统 SHALL 允许 owner/admin 在操作列触发密码重置确认弹窗，后端生成临时密码并返回，前端展示临时密码供管理员告知用户。ADMIN 不可重置 OWNER 的密码（防特权提升）。

#### Scenario: 重置密码成功

- **WHEN** admin 确认重置密码操作
- **THEN** 调用 POST /api/v1/members/{id}/reset-password（无请求体），后端返回服务端生成的临时密码，前端弹窗展示临时密码

#### Scenario: admin 尝试重置 owner 密码被拒绝

- **WHEN** admin 对 role=owner 的成员触发重置密码
- **THEN** 重置密码按钮对 admin 不显示（前端防护），后端同步返回 403（纵深防御）
