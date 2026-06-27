## ADDED Requirements

### Requirement: 文档列表

选中 KB 后，文档管理 Tab SHALL 展示 el-table 列表，字段 MUST 包含文件名、处理状态（KbDocumentStatus：UPLOADING/PARSING/READY/FAILED）、上传时间、操作列。UPLOADING 状态 SHALL 显示 loading 图标，PARSING 显示蓝色"解析中"徽章，READY 显示绿色徽章，FAILED 显示红色徽章和错误信息 tooltip。

#### Scenario: 进入文档 Tab

- **WHEN** 用户选中一个 KB 并点击"文档管理" Tab
- **THEN** 调用 GET /api/v1/knowledge-bases/{kbId}/documents 并渲染列表；若无文档显示"还没有文档"引导

### Requirement: 文档上传

用户 SHALL 通过 el-upload 组件上传文档（PDF/Word/PPT 等），MUST 支持多选，前端 MUST 校验文件类型和大小（≤ 50MB），超限 SHALL 拒绝并提示，不发请求。上传采用 multipart/form-data 调用 POST /api/v1/knowledge-bases/{kbId}/documents。

#### Scenario: 上传成功

- **WHEN** 用户选择合法文件并上传
- **THEN** 新文档以 UPLOADING 状态出现在列表，触发轮询

#### Scenario: 文件类型不合法

- **WHEN** 用户选择非支持格式文件
- **THEN** before-upload 钩子拦截，显示错误提示，不发送请求

### Requirement: 文档处理状态轮询

存在 UPLOADING 或 PARSING 状态文档时，useDocumentPolling SHALL 每 3 秒自动执行以下轮询策略：1) 调用 GET /api/v1/knowledge-bases/{kbId}/documents 刷新列表；2) 对每个 PARSING 文档 MUST 额外调用 GET /documents/{docId} 触发 RAGFlow 状态刷新（list 接口不触发 RAGFlow 查询）。轮询 MUST 在全部文档变为 READY 或 FAILED 时停止，或在 10 分钟超时时停止并显示警告。

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

用户 SHALL 通过二次确认（el-message-box）删除文档，系统 MUST 调用 DELETE /api/v1/knowledge-bases/{kbId}/documents/{docId}，成功后从列表移除该文档。

#### Scenario: 删除成功

- **WHEN** 用户确认删除
- **THEN** 调用删除接口，成功后列表移除该文档
