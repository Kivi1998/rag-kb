# frontend-document-management Specification

## Purpose

知识库技术文档的前端管理界面——通过独立路由页(`/kb/:kbId/documents`,由知识库侧边栏右键菜单的"技术文档"项进入)承载文档列表、上传、摄取进度轮询与删除,展示自研 RAG Core 摄取流水线(`QUEUED → PARSING → CHUNKING → EMBEDDING → INDEXING → READY`,失败进入 `FAILED`,删除中进入 `DELETING`)的实时状态,不再依赖任何外部黑盒系统。

## Requirements
### Requirement: 文档列表

用户通过知识库侧边栏右键菜单的"技术文档"项进入 `/kb/:kbId/documents` 独立路由页(`DocumentsView.vue` + `DocumentPanel.vue`),SHALL 展示 el-table 列表,列 MUST 包含文件名、大小、摄取状态、失败原因、操作列。8 种摄取状态均以徽章展示:`QUEUED`(灰色"排队中")、`PARSING`/`CHUNKING`/`EMBEDDING`/`INDEXING`(橙色,分别显示对应阶段文案)、`READY`(绿色"可检索")、`FAILED`(红色"失败",失败原因单独一列展示、非徽章 tooltip)、`DELETING`(橙色"删除中")。

#### Scenario: 进入文档管理页

- **WHEN** 用户在知识库侧边栏对某个 KB 触发右键菜单并点击"技术文档"
- **THEN** 路由跳转到 `/kb/:kbId/documents`,调用 `GET /api/v1/documents?kbId={kbId}` 并渲染列表;若无文档,el-table 显示"暂无文档，请上传技术资料"空状态

### Requirement: 文档上传

用户 SHALL 通过隐藏的原生 `<input type="file" multiple>`(点击"上传文档"按钮触发)一次选择多个文件,加入本地上传队列后按并发上限(当前为 3)逐个调用 `POST /api/v1/documents/upload`(multipart/form-data,字段为 `file` + `kbId`)。前端 `accept` 属性仅用于筛选文件选择器里可见的候选文件,不构成强校验;文件类型、大小、文件名等校验完全由后端在收到请求后执行,前端当前没有独立的 before-upload 拦截逻辑,不合法文件会被发送到后端后依据后端返回的 400 错误在该上传队列项上展示失败原因。

#### Scenario: 上传成功

- **WHEN** 用户选择合法文件,上传队列项进度达到 100%
- **THEN** 该队列项标记为"已上传",列表刷新后新文档以 `QUEUED` 状态出现,触发摄取状态轮询

#### Scenario: 文件被后端拒绝

- **WHEN** 用户选择的文件不满足后端的类型/大小/内容校验(如扩展名不在白名单、超过大小上限、文件头与扩展名不符)
- **THEN** 上传请求返回 400,对应的上传队列项标记为失败并展示错误原因,用户可对该项点击"重试"重新提交,不影响队列中其他文件

### Requirement: 摄取状态轮询

`DocumentPanel.vue` 内联维护一个轮询定时器(不是独立的 `useDocumentPolling` composable):每次文档列表刷新完成后,若列表中存在任意处于 `QUEUED`/`PARSING`/`CHUNKING`/`EMBEDDING`/`INDEXING` 或 `DELETING` 状态的文档,SHALL 启动(或重置)一个 3 秒间隔的定时器,到期后静默重新调用一次 `GET /api/v1/documents?kbId={kbId}` 刷新整份列表;列表接口本身已直接返回数据库最新状态,轮询 MUST NOT 对单个文档发起额外的详情请求。当刷新后不再存在上述状态的文档时,下一次 `resetPolling` 调用 MUST 清除定时器,轮询自然停止;当前实现没有 10 分钟超时或"部分文档处理超时"警告逻辑。

#### Scenario: 文档处理完成后轮询自动停止

- **WHEN** 一轮轮询刷新后,列表中所有文档状态均为 `READY` 或 `FAILED`
- **THEN** 定时器被清除,轮询停止,列表保持最终状态

#### Scenario: 组件卸载时清理定时器

- **WHEN** 用户离开文档管理页(组件卸载)
- **THEN** `onBeforeUnmount` 清除当前轮询定时器,不产生内存泄漏

#### Scenario: 同一路由切换到另一 KB 的文档页

- **WHEN** 用户从当前 KB 的文档页跳转到另一 KB 的文档页(路由参数变化,组件实例被 Vue 复用而非卸载重建)
- **THEN** 组件监听 `kbId` 变化,清空本地上传队列、重置分页并重新加载新 KB 的文档列表(连带重置轮询定时器),不会把切换前 KB 的上传队列/轮询状态带入新 KB

### Requirement: 文档删除

用户 SHALL 通过二次确认(`ElMessageBox.confirm`,提示"删除后将清理原文件和检索索引")删除文档,确认后系统调用 `DELETE /api/v1/documents/{documentId}?kbId={kbId}`。由于删除是"标记 DELETING + 异步补偿清理"流程,接口成功只表示删除请求已被接受,不代表清理已彻底完成;界面提示"已提交删除请求"并刷新列表,文档在被后端彻底清理干净前会以 `DELETING` 状态短暂保留在列表中(该状态下删除按钮被禁用),随后续轮询消失。

#### Scenario: 删除成功

- **WHEN** 用户确认删除
- **THEN** 调用删除接口成功后提示"已提交删除请求"并刷新列表;文档在数据库中被彻底清理后从列表消失
