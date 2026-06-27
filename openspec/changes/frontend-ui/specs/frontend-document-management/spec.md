## ADDED Requirements

### Requirement: 文档列表

选中 KB 后，文档管理 Tab 展示 el-table 列表，字段包含文件名、处理状态（UPLOADING/ACTIVE/ERROR）、上传时间、操作列。UPLOADING 状态显示 loading 图标，ACTIVE 显示绿色徽章，ERROR 显示红色徽章和错误信息 tooltip。

#### Scenario: 进入文档 Tab

- **WHEN** 用户选中一个 KB 并点击"文档管理" Tab
- **THEN** 调用 GET /api/v1/knowledge-bases/{kbId}/documents 并渲染列表；若无文档显示"还没有文档"引导

### Requirement: 文档上传

用户通过 el-upload 组件上传文档（PDF/Word/PPT 等），支持多选，前端校验文件类型和大小（≤ 50MB）。上传采用 multipart/form-data 调用 POST /api/v1/knowledge-bases/{kbId}/documents。

#### Scenario: 上传成功

- **WHEN** 用户选择合法文件并上传
- **THEN** 新文档以 UPLOADING 状态出现在列表，触发轮询

#### Scenario: 文件类型不合法

- **WHEN** 用户选择非支持格式文件
- **THEN** before-upload 钩子拦截，显示错误提示，不发送请求

### Requirement: 文档处理状态轮询

存在 UPLOADING 状态文档时，useDocumentPolling 每 3 秒自动调用 GET /api/v1/knowledge-bases/{kbId}/documents 刷新列表，直至所有文档变为 ACTIVE 或 ERROR，或达到 10 分钟超时上限。

#### Scenario: 文档处理完成

- **WHEN** 所有文档状态变为 ACTIVE 或 ERROR
- **THEN** 轮询自动停止，列表更新为最终状态

#### Scenario: 轮询超时（10 分钟）

- **WHEN** 10 分钟内仍有文档处于 UPLOADING 状态
- **THEN** 停止轮询，列表顶部显示"部分文档处理超时，请手动刷新"警告

#### Scenario: 切换 KB 或组件卸载

- **WHEN** 用户切换到其他 KB 或离开页面
- **THEN** 当前轮询定时器立即清除，不产生内存泄漏

### Requirement: 文档删除

用户可删除文档，需二次确认。成功后从列表移除，调用 DELETE /api/v1/knowledge-bases/{kbId}/documents/{docId}。

#### Scenario: 删除成功

- **WHEN** 用户确认删除
- **THEN** 调用删除接口，成功后列表移除该文档
