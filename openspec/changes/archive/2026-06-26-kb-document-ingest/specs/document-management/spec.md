## ADDED Requirements

### Requirement: 文档上传

系统 SHALL 允许有权限的成员向其组织内的知识库上传文档文件(PDF/DOCX/DOC/TXT/Markdown/PPTX/XLSX)。上传时系统 MUST 先校验目标知识库属于调用者组织(跨租户返回 404)。上传成功后系统 MUST 将文件推送到 RAGFlow dataset 并触发解析,返回文档 ID;状态从 `UPLOADING`(落库、推送/触发解析中)转为 `PARSING`(RAGFlow 已接收并解析中),解析由 RAGFlow 异步完成。文件类型校验 MUST 以扩展名为主白名单、MIME 为辅助。单文件大小上限 MUST 为 50MB;不支持类型 MUST 返回 400,超过大小上限 MUST 返回 413。

> **实现偏差:** MIME 辅助校验未实现。multipart 的 Content-Type 由客户端提供、可伪造且常为 application/octet-stream,单靠它不可靠;扩展名白名单已足够。此决策记录于 design.md D4。

#### Scenario: 正常上传

- **WHEN** member 以 `multipart/form-data` 上传允许类型的文件(≤50MB)到其组织内某知识库
- **THEN** 系统持久化文档记录(状态=`PARSING`)、推送文件至 RAGFlow dataset,返回文档元数据(id/name/status)

#### Scenario: 不支持的文件类型

- **WHEN** member 上传 `.exe`、`.zip` 等不在白名单的文件
- **THEN** 系统返回 400,不写入数据库,不调用 RAGFlow

#### Scenario: 文件超过 50MB

- **WHEN** member 上传大于 50MB 的文件
- **THEN** 系统返回 413(Payload Too Large),提示文件大小超限

#### Scenario: RAGFlow 上传失败

- **WHEN** 推送文件至 RAGFlow 时调用失败
- **THEN** 系统将文档状态置为 `FAILED`,记录错误信息,返回 500

#### Scenario: 跨租户上传被拒

- **WHEN** member 向不属于自己组织的知识库上传文档
- **THEN** 系统返回 404(不泄露其他组织知识库的存在)

#### Scenario: 无权限上传被拒

- **WHEN** 未登录请求上传文档接口
- **THEN** 系统返回 401

---

### Requirement: 文档列表

系统 SHALL 允许组织内任意成员查询指定知识库下的文档列表。列表 MUST 仅包含调用者所在组织的知识库下的文档,不得返回其他组织文档。

#### Scenario: 正常列表

- **WHEN** member 查询其组织内某知识库的文档列表
- **THEN** 系统返回该知识库下所有文档(id/name/status/size/createdAt),状态取数据库存储值,**不**对 `PARSING` 文档实时查询 RAGFlow(刷新仅在单文档详情接口进行)

#### Scenario: 跨租户列表被过滤

- **WHEN** member 查询不属于自己组织的知识库下的文档
- **THEN** 系统返回 404

---

### Requirement: 文档状态查询

系统 SHALL 提供单文档详情接口,返回文档元数据及当前解析状态。若状态为 `PARSING`,系统 MUST 实时查询 RAGFlow 刷新状态(查时刷新策略);`READY` 或 `FAILED` 为终态,不再查询 RAGFlow。

#### Scenario: 文档解析中

- **WHEN** member 查询状态为 `PARSING` 的文档
- **THEN** 系统实时查询 RAGFlow,将最新状态更新后返回

#### Scenario: 文档解析完成

- **WHEN** member 查询状态为 `READY` 的文档
- **THEN** 系统直接返回数据库中的状态,不再调用 RAGFlow

#### Scenario: 文档解析失败

- **WHEN** RAGFlow 报告解析失败
- **THEN** 系统将状态更新为 `FAILED` 并记录错误信息,接口返回 `FAILED` 状态与错误摘要

#### Scenario: 跨租户查询被拒

- **WHEN** member 查询不属于自己组织知识库下的文档
- **THEN** 系统返回 404

---

### Requirement: 文档删除

系统 SHALL 允许 owner 或 admin 删除知识库内的文档。删除 MUST 先从 RAGFlow dataset 中移除文件,成功后再删除数据库记录;RAGFlow 删除失败时 MUST 将文档状态置为 `FAILED` 并保留数据库记录。

#### Scenario: 正常删除

- **WHEN** admin 删除其组织知识库内的文档
- **THEN** 系统依次删除 RAGFlow 文件和数据库记录,返回 200

#### Scenario: RAGFlow 删除失败

- **WHEN** 调用 RAGFlow 删除文件接口失败
- **THEN** 系统不删除数据库记录,将文档状态置为 `FAILED`,返回 500

#### Scenario: member 无权删除

- **WHEN** member(非 admin/owner)尝试删除文档
- **THEN** 系统返回 403

#### Scenario: 跨租户删除被拒

- **WHEN** member 尝试删除不属于自己组织知识库下的文档
- **THEN** 系统返回 404

---

### Requirement: 文档多租户隔离

系统 MUST 在每个文档访问路径(列表/查询/删除)强制校验 org_id,确保跨租户数据不串。文档的 org_id MUST 与其所属知识库的 org_id 严格一致。

#### Scenario: Hibernate Filter 过滤跨租户文档

- **WHEN** 系统执行任意文档查询
- **THEN** Hibernate @Filter 自动附加 `org_id = :orgId` 条件,跨租户文档不会出现在结果中

#### Scenario: 直接按 ID 查询跨租户文档

- **WHEN** member 提供另一组织文档的 UUID 直接访问
- **THEN** 系统返回 404,不泄露文档存在性

#### Scenario: 同组织跨知识库访问被拒

- **WHEN** member 通过 KB-A 的 URL 访问属于 KB-B 的文档(同组织内)
- **THEN** 系统返回 404,文档查询/删除均绑定 kbId + orgId 双重校验
