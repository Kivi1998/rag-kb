# frontend-team-mgmt Specification

## Purpose
rag-kb 团队管理前端：OWNER/ADMIN 可查看组织内团队列表、创建新团队。

## Requirements

### Requirement: 团队列表

系统 SHALL 在 `/admin/teams` 页面展示当前组织所有团队，通过 GET /api/v1/teams 加载，MUST 显示团队名称和创建时间。无团队时显示空状态引导提示。

#### Scenario: 加载团队列表

- **WHEN** owner 或 admin 进入团队管理页
- **THEN** 调用 GET /api/v1/teams 并以表格形式展示

#### Scenario: 无团队时显示空状态

- **WHEN** 组织内尚无团队
- **THEN** 显示 el-empty 空状态提示，引导用户创建第一个团队

### Requirement: 新建团队

系统 SHALL 提供「新建团队」弹窗，收集团队名称（必填），通过 POST /api/v1/teams 创建。MEMBER 角色无权创建团队（后端 403）。

#### Scenario: 新建团队成功

- **WHEN** admin 输入团队名称并确认
- **THEN** 调用 POST /api/v1/teams，成功后团队出现在列表中，显示「团队创建成功」

#### Scenario: 名称为空提交

- **WHEN** 用户未填写名称点击确认
- **THEN** 表单校验报错，不提交

#### Scenario: 创建失败

- **WHEN** 后端返回错误（如 MEMBER 角色调用）
- **THEN** 显示「团队创建失败，请重试」错误提示
