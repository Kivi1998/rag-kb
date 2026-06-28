## ADDED Requirements

### Requirement: 知识库导航侧边栏

系统 SHALL 在左侧 220px 固定宽度侧边栏（el-menu）展示当前用户所在组织的知识库列表，MUST 包含"新建知识库"入口。选中 KB SHALL 高亮显示，切换 KB 时主内容区 MUST 同步更新。无 KB 时 SHALL 显示空状态引导。

#### Scenario: 初始加载

- **WHEN** 用户进入 `/kb` 页面
- **THEN** 自动拉取 GET /api/v1/knowledge-bases 并渲染列表；若列表为空则显示"暂无知识库"引导

#### Scenario: 选择知识库

- **WHEN** 用户点击侧边栏某个 KB
- **THEN** 该 KB 高亮，主内容区切换为对应 KB 的文档和聊天数据

### Requirement: 创建知识库

用户 SHALL 通过弹窗（el-dialog + el-form）输入知识库名称创建新 KB，名称 MUST 必填校验。

#### Scenario: 创建成功

- **WHEN** 用户填写名称并确认
- **THEN** 调用 POST /api/v1/knowledge-bases，成功后新 KB 出现在侧边栏并自动选中

#### Scenario: 名称为空提交

- **WHEN** 用户未填写名称点击确认
- **THEN** 表单校验报错，不提交

### Requirement: 重命名知识库

用户 SHALL 通过右键菜单或操作按钮触发弹窗对已有 KB 进行重命名，MUST 回填当前名称。

#### Scenario: 重命名成功

- **WHEN** 用户修改名称并确认
- **THEN** 调用 PATCH /api/v1/knowledge-bases/{id}，成功后侧边栏名称更新

### Requirement: 删除知识库

用户 SHALL 通过二次确认（el-message-box）删除 KB。系统 MUST 检查响应 `code` 字段（0=已删除，202=待清理）区分完全删除和 PENDING_CLEANUP 状态，不可依赖 `data.deleted` 字段（该字段不存在）。

#### Scenario: 删除成功（data.deleted = true）

- **WHEN** 后端返回 HTTP 200 且 `data.deleted = true`
- **THEN** 从侧边栏移除该 KB，若为当前选中则取消选中

#### Scenario: 删除部分成功（data.deleted = false）

- **WHEN** 后端返回 HTTP 200 且 `data.deleted = false`（RAGFlow dataset 删除失败，标记 PENDING_CLEANUP）
- **THEN** 该 KB 在侧边栏显示"待清理"标签，不从列表移除，提示用户联系管理员
