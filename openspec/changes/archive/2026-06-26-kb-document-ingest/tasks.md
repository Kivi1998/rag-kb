## 1. 数据层:Document 表与实体

- [x] 1.1 编写 Flyway `V003__create_document_table.sql`:创建 `document` 表(id/kb_id/org_id/name/content_type/size_bytes/ragflow_doc_id/status/error_message/created_by/created_at/updated_at),为 `org_id` 添加索引
- [x] 1.2 创建 `DocumentStatus` 枚举:`UPLOADING / PARSING / READY / FAILED`(`UPLOADING` 用于"已落库、文件正在推送/触发解析"阶段,上传+解析触发成功后翻 `PARSING`)
- [x] 1.3 创建 `Document` JPA 实体,添加 Hibernate `@Filter(name="tenantFilter")`,org_id 冗余字段
- [x] 1.4 创建 `DocumentRepository`:新增 `findByKbIdAndOrgId`、`findByIdAndOrgId`

## 2. RAGFlow 客户端扩展

- [x] 2.1 在 `RagFlowClient` 新增 `uploadDocument(datasetId, fileName, fileResource, contentType)`:调用 `POST /api/v1/datasets/{datasetId}/documents`(multipart),**入参用 `Resource`/`InputStreamResource` 流式传输,不读成 byte[]**,返回 ragflowDocId
- [x] 2.2 在 `RagFlowClient` 新增 `parseDocument(datasetId, ragflowDocId)`:上传后单独触发 RAGFlow 解析(接口路径联调确认;若 RAGFlow 上传即自动解析,则此方法退化为空操作)
- [x] 2.3 在 `RagFlowClient` 新增 `getDocumentStatus(datasetId, ragflowDocId)`:调用 RAGFlow 查询接口,返回状态字符串
- [x] 2.4 在 `RagFlowClient` 新增 `deleteDocument(datasetId, ragflowDocId)`:调用 RAGFlow 删除接口

## 3. Service 层

- [x] 3.1 创建 `DocumentService.upload(kbId, orgId, uploaderId, file)`:**先调 `KnowledgeBaseService.getByIdAndCurrentOrg(kbId)` 校验 KB 归属(跨租户 → 404)** → 校验文件类型(**扩展名为主白名单 + MIME 辅助校验**)和大小(≤50MB)→ 持久化文档记录(状态=`UPLOADING`)→ 流式推送 RAGFlow → 触发 RAGFlow 解析 → 成功后翻状态=`PARSING`;任一步失败置 `FAILED`
- [x] 3.2 实现 `DocumentService.listByKb(kbId, orgId)`:**先校验 KB 归属(跨租户 → 404)** → 列出知识库下文档列表,依赖 Hibernate Filter 租户过滤;**列表只返回存储状态,不对 `PARSING` 文档触发 RAGFlow 查询**
- [x] 3.3 实现 `DocumentService.getById(docId, orgId)`:查时刷新策略——若状态=`PARSING` 则调 RAGFlow 更新状态(含 `PARSING → FAILED` 转换并记录错误摘要);终态直接返回
- [x] 3.4 实现 `DocumentService.delete(docId, orgId, callerRole)`:**先校验 KB 归属(跨租户 → 404)** → 校验 owner/admin(member → 403)→ 先删 RAGFlow → 再删 DB;RAGFlow 失败时置状态 `FAILED` 并保留记录,返回 500

## 4. Controller 层与 multipart 配置

- [x] 4.1 创建 `DocumentController`:
  - `POST /api/v1/knowledge-bases/{kbId}/documents`(multipart/form-data,需认证)
  - `GET /api/v1/knowledge-bases/{kbId}/documents`(需认证)
  - `GET /api/v1/knowledge-bases/{kbId}/documents/{docId}`(需认证)
  - `DELETE /api/v1/knowledge-bases/{kbId}/documents/{docId}`(需认证,owner/admin)
- [x] 4.2 `application.yml` 新增 multipart 配置:`spring.servlet.multipart.max-file-size=50MB`、`max-request-size=52MB`
- [x] 4.3 在 `GlobalExceptionHandler` 新增 `@ExceptionHandler(MaxUploadSizeExceededException)` → 返回 **413 Payload Too Large**(否则默认映射 500)

## 5. 测试

- [x] 5.1 正常上传测试:合法文件类型 → 201 + docId + 状态 `PARSING`
- [x] 5.2 非法文件类型上传 → 400
- [x] 5.3 文件超限上传 → 413(`MaxUploadSizeExceededException` handler 生效)
- [x] 5.4 文档列表测试:只返回本组织知识库文档
- [x] 5.5 文档状态查询:PARSING 状态触发 RAGFlow 查询(Mock RagFlowClient)
- [x] 5.6 文档删除:admin 成功删除;member 删除 → 403
- [x] 5.7 跨租户安全测试:跨组织上传/查询/删除均返回 404
- [x] 5.8 RAGFlow 上传失败测试:Mock RagFlowClient 上传抛异常 → 返回 500
- [x] 5.9 RAGFlow 解析触发失败测试:Mock `parseDocument` 抛异常 → 返回 500
- [x] 5.10 状态查询 `PARSING → FAILED` 转换:Mock RAGFlow 返回失败 → 状态置 `FAILED` 并记录错误摘要,接口返回 `FAILED`
- [x] 5.11 删除时 RAGFlow 失败测试:Mock `deleteDocument` 抛异常 → 返回 500
- [x] 5.12 列表不刷新测试:库中存在 `PARSING` 文档,调用列表接口断言**不触发** RagFlowClient 查询、直接返回存储状态
