## ADDED Requirements

### Requirement: 团队列表

系统 SHALL 在 `/admin/teams` 页面展示当前组织所有团队，通过 GET /api/v1/teams 加载，MUST 显示团队名称和创建时间。

#### Scenario: 加载团队列表

- **WHEN** owner 或 admin 进入团队管理页
- **THEN** 调用 GET /api/v1/teams 并以表格形式展示

### Requirement: 新建团队

系统 SHALL 提供「新建团队」弹窗，收集团队名称（必填），通过 POST /api/v1/teams 创建。

#### Scenario: 新建团队成功

- **WHEN** admin 输入团队名称并确认
- **THEN** 调用 POST /api/v1/teams，成功后团队出现在列表中

#### Scenario: 名称为空提交

- **WHEN** 用户未填写名称点击确认
- **THEN** 表单校验报错，不提交
