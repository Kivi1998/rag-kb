## Why

知识库已建立基础骨架(CRUD + 权限 + RAGFlow dataset 映射),但无法向其中写入内容——成员目前无法上传文档,知识库形同空壳。文档摄取是 RAG 问答的前提,是 toB 知识库产品的核心功能。

## What Changes

- 新增文档上传接口:成员上传文件(PDF/DOCX/TXT/Markdown)至指定知识库
- 新增文档状态追踪:后端推送文件至 RAGFlow 后异步轮询解析状态(`UPLOADING → PARSING → READY / FAILED`)
- 新增文档列表/删除接口:管理已上传文档
- RAGFlow REST 调用:上传文件到 dataset、查询文档解析状态、删除文档
- 多租户校验:每个文档访问路径强制校验 org_id,文档隶属于知识库进而隶属于组织

## Capabilities

### New Capabilities

- `document-management`: 文档 CRUD(上传/列表/详情/删除)及与 RAGFlow dataset 的文件同步

### Modified Capabilities

- `knowledge-base`: 新增"知识库下文档数量"关联关系;创建知识库时 dataset 已在,无需改变现有需求

## Impact

- **新 API**: `POST /api/v1/knowledge-bases/{kbId}/documents`、`GET /api/v1/knowledge-bases/{kbId}/documents`、`DELETE /api/v1/knowledge-bases/{kbId}/documents/{docId}`
- **新表**: `document`(记录文件元数据 + 解析状态)
- **新依赖**: Spring Boot 文件上传(`multipart/form-data`)、RAGFlow 文件上传/查询 REST 接口(扩展 `RagFlowClient`)
- **现有影响**: `KnowledgeBaseService` 增加文档关联查询;`RagFlowClient` 新增 upload/delete/status 接口

## Non-goals

- 不做流式进度推送(WebSocket/SSE),只提供轮询接口
- 不做本地文档解析(全部委托 RAGFlow DeepDoc)
- 不做文档版本控制/覆盖更新
- 不做文档内容预览/下载
- 不做消息队列摄取(留给后续 change)
- 不做文档权限细化(继承知识库 RBAC 即可)
