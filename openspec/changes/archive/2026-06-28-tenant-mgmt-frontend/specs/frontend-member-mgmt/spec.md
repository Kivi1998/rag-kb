## ADDED Requirements

### Requirement: 成员列表

系统 SHALL 在 `/admin/members` 页面展示当前组织所有成员，MUST 显示邮箱、角色（owner/admin/member 角色标签）。列表通过 GET /api/v1/members 加载。

#### Scenario: 加载成员列表

- **WHEN** owner 或 admin 进入成员管理页
- **THEN** 调用 GET /api/v1/members 并以表格形式展示，每行含邮箱、角色标签、操作列

#### Scenario: 普通成员访问重定向

- **WHEN** role=member 的用户访问 `/admin/members`
- **THEN** 路由守卫重定向至 `/kb`，不渲染页面

### Requirement: 邀请成员

系统 SHALL 提供「新增成员」弹窗，MUST 收集邮箱、初始密码、角色（admin/member，不含 owner），通过 POST /api/v1/members 创建账号。

#### Scenario: 新增成员成功

- **WHEN** admin 填写邮箱、密码、角色并确认
- **THEN** 调用 POST /api/v1/members，成功后新成员出现在列表中并提示「添加成功」

#### Scenario: 邮箱已存在

- **WHEN** 提交的邮箱已被注册
- **THEN** 后端返回错误，前端在弹窗内显示错误信息，不关闭弹窗

### Requirement: 修改角色

系统 SHALL 允许 owner 在成员列表操作列通过下拉选择修改成员角色（owner 可设置 admin/member；MUST NOT 允许降级最后一名 owner）。调用 PATCH /api/v1/members/{id}/role。

#### Scenario: 修改角色成功

- **WHEN** owner 为某成员选择新角色并确认
- **THEN** 调用 PATCH /api/v1/members/{id}/role，成功后列表角色标签更新

#### Scenario: admin 尝试修改角色被服务端拒绝

- **WHEN** admin 尝试修改他人角色（后端返回 403）
- **THEN** 前端显示「权限不足」提示，角色不变

### Requirement: 密码重置

系统 SHALL 允许 owner/admin 在操作列触发密码重置弹窗，输入新密码后调用 POST /api/v1/members/{id}/reset-password。

#### Scenario: 重置密码成功

- **WHEN** admin 输入新密码并确认
- **THEN** 调用 POST /api/v1/members/{id}/reset-password，成功后提示「密码已重置」
