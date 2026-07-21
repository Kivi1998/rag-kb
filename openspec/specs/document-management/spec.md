## Purpose

企业知识库文档生命周期管理——涵盖文档上传(落原文件到对象存储 + 创建摄取任务,由自研 RAG Core 摄取 Worker 异步完成解析/切块/向量化/索引)、摄取任务状态查询(状态直接来自数据库,由 Worker 实时写入,无任何外部黑盒系统的"查时刷新")、文档列表浏览、文档删除(标记 DELETING + 幂等清理 + 失败自动转入后台补偿重试)。所有路径强制多租户隔离,跨组织访问返回 404。

> 本文件描述的是当前自研 RAG Core 摄取链路;项目早期曾用 RAGFlow 作为解析/检索黑盒(上传即"推送到 RAGFlow dataset"、状态用"查时刷新策略实时查 RAGFlow"、删除是"先删 RAGFlow 再删 DB"),该机制已被自研 Parser/Chunker/Embedding/Index/Retriever 完全替换,不再有任何 RAGFlow 调用。

## Requirements

### Requirement: 文档上传

系统 SHALL 允许知识库所属组织的 owner 或 admin 上传文档文件(md/markdown/txt/pdf/docx/pptx/srt/vtt/json/yaml/yml/xml、常见图像/音视频、常见代码与配置文件等扩展名白名单)。上传时系统 MUST 先校验目标知识库属于调用者组织(跨租户返回 404)。上传接口只负责"落原文件到对象存储 + 创建摄取任务",立即返回文档 ID 与摄取任务 ID;文档初始状态为 `QUEUED`,真正的解析/切块/向量化/索引由摄取 Worker 异步完成,按 `QUEUED → PARSING → CHUNKING → EMBEDDING → INDEXING → READY` 顺序推进,任一阶段可转入 `FAILED`。文件类型校验 MUST 以扩展名白名单为主,并 MUST 通过读取文件头字节对常见格式(PDF/DOCX/PPTX/PNG/JPEG/TIFF 等)做魔数嗅探,与扩展名不符时拒绝。单文件大小上限 MUST 为配置项 `rag_upload_max_size_bytes`(当前配置值为 536,870,912 字节,即 512MB);不支持类型或超过大小上限 MUST 返回 400(当前实现中,文件大小/类型/文件名等全部上传前置校验统一通过 `ValueError` 映射为 400,没有单独的 413 分支)。

#### Scenario: 正常上传

- **WHEN** owner 或 admin 以 `multipart/form-data` 上传允许类型的文件(≤ 512MB)到其组织内某知识库
- **THEN** 系统持久化文档记录(状态 = `QUEUED`)与摄取任务记录、将原文件写入对象存储,返回文档元数据(documentId/name/status/jobId 等)

#### Scenario: 不支持的文件类型

- **WHEN** owner 或 admin 上传 `.exe`、`.zip` 等不在扩展名白名单的文件
- **THEN** 系统返回 400,不写入数据库,不写入对象存储

#### Scenario: 文件内容与扩展名不符

- **WHEN** owner 或 admin 上传一个扩展名为 `.pdf`/`.docx`/`.pptx`/`.png`/`.jpg`/`.tiff` 等格式,但文件头字节魔数与该扩展名不匹配的伪装文件
- **THEN** 系统在写入对象存储前(或已写入时先清理已写入内容)拒绝该文件,返回 400

#### Scenario: 文件超过大小上限

- **WHEN** owner 或 admin 上传大于 `rag_upload_max_size_bytes`(当前为 512MB)的文件
- **THEN** 系统返回 400,提示文件大小超过上传策略限制

#### Scenario: 写入对象存储或创建摄取任务失败

- **WHEN** 文件校验通过后,写入对象存储或创建摄取任务记录时发生异常
- **THEN** 系统清理已写入对象存储的部分内容、不提交本次上传事务(不留下半成品文档记录),返回 500

#### Scenario: 跨租户上传被拒

- **WHEN** owner 或 admin 向不属于自己组织的知识库上传文档
- **THEN** 系统返回 404(不泄露其他组织知识库的存在)

#### Scenario: member 无权上传被拒

- **WHEN** 组织内普通 member(非 owner/admin)尝试上传文档
- **THEN** 系统返回 403

#### Scenario: 未登录上传被拒

- **WHEN** 未登录请求上传文档接口
- **THEN** 系统返回 401

---

### Requirement: 文档列表

系统 SHALL 允许组织内任意成员查询指定知识库下的文档列表,可选按摄取状态过滤。列表 MUST 仅包含调用者所在组织的知识库下的文档,不得返回其他组织文档。

#### Scenario: 正常列表

- **WHEN** member 查询其组织内某知识库的文档列表
- **THEN** 系统返回该知识库下所有文档(documentId/name/size/contentType/status/errorMessage/retryable/uploadedAt/jobId 等),所有状态字段(`QUEUED`/`PARSING`/`CHUNKING`/`EMBEDDING`/`INDEXING`/`READY`/`FAILED`/`DELETING`)均取数据库存储值,不查询任何外部系统

#### Scenario: 按状态过滤

- **WHEN** member 携带 `status` 查询参数请求文档列表
- **THEN** 系统只返回状态等于该值的文档

#### Scenario: 跨租户列表被过滤

- **WHEN** member 查询不属于自己组织的知识库下的文档
- **THEN** 系统返回 404

---

### Requirement: 摄取任务状态查询

系统 SHALL 提供摄取任务详情接口,返回该任务(及其对应文档)的当前摄取状态。状态值 MUST 直接来自数据库(由摄取 Worker 处理过程中实时写入),接口 MUST NOT 查询任何外部系统获取最新状态。`FAILED` 状态的任务在未达最大重试次数时 MUST 标记为可重试(retryable),owner 或 admin 可调用重试接口使其重新进入 `QUEUED` 排队。

#### Scenario: 查询进行中的任务

- **WHEN** member 查询状态为 `QUEUED`/`PARSING`/`CHUNKING`/`EMBEDDING`/`INDEXING` 的摄取任务
- **THEN** 系统直接返回数据库中的当前状态,不发起任何外部调用

#### Scenario: 查询已就绪的任务

- **WHEN** member 查询状态为 `READY` 的摄取任务
- **THEN** 系统直接返回数据库中的状态

#### Scenario: 查询失败的任务

- **WHEN** 摄取过程中任一阶段失败
- **THEN** Worker 将任务与对应文档状态更新为 `FAILED` 并记录错误信息,接口返回 `FAILED` 状态、错误摘要及是否可重试(retry_count < max_attempts)

#### Scenario: owner/admin 重试失败任务

- **WHEN** owner 或 admin 对一个 `FAILED` 且未达最大重试次数的任务调用重试接口
- **THEN** 系统将任务状态置回 `QUEUED`、清空错误信息、重试次数 +1,由 Worker 重新处理;非 owner/admin 调用重试接口 MUST 返回 403

#### Scenario: 跨租户查询被拒

- **WHEN** member 查询不属于自己组织知识库下的摄取任务
- **THEN** 系统返回 404

---

### Requirement: 文档删除

系统 SHALL 允许 owner 或 admin 删除知识库内的文档。删除 MUST 采用"标记删除中 + 幂等补偿清理"流程:请求到达后先将文档及其摄取任务状态置为 `DELETING`(可从 `QUEUED`/`PARSING`/`CHUNKING`/`EMBEDDING`/`INDEXING`/`FAILED` 中的任一状态打断),随后立即尝试一次幂等清理(依次尝试:词法索引下线可见性 → 删除向量索引 → 删除词法索引物理记录 → 删除对象存储原文件与解析产物 → 删除任务与文档数据库记录)。清理全部成功则文档彻底消失并返回 200;若清理中途失败,文档 MUST 保持 `DELETING` 状态,HTTP 接口仍返回 200(不因外部清理暂时失败而报错或阻塞调用方),由独立的删除补偿 Worker 定期(当前实现每 30 秒一批)重新尝试清理直至成功。

> **已知局限:** 当前 HTTP 路由实际装配的删除服务未接入词法/向量索引清理器,生产路径中删除只清理对象存储原文件与数据库记录,ES/Milvus 中的向量索引残留暂未清理(见 `backend-py/app/routers/documents.py` 顶部注释)。

#### Scenario: 正常删除

- **WHEN** owner 或 admin 删除其组织知识库内的文档
- **THEN** 系统将文档标记 `DELETING` 并立即执行一次清理,清理成功后文档从数据库与列表中消失,接口返回 200

#### Scenario: 清理失败转入后台补偿

- **WHEN** 首次清理尝试中某一步骤失败(如对象存储瞬时不可用)
- **THEN** 文档保持 `DELETING` 状态,接口仍返回 200,由删除补偿 Worker 之后重试直至清理成功

#### Scenario: member 无权删除

- **WHEN** member(非 admin/owner)尝试删除文档
- **THEN** 系统返回 403

#### Scenario: 跨租户删除被拒

- **WHEN** member 尝试删除不属于自己组织知识库下的文档
- **THEN** 系统返回 404

---

### Requirement: 文档多租户隔离

系统 MUST 在每个文档访问路径(上传/列表/摄取任务查询/删除)强制校验 org_id,确保跨租户数据不串。文档的 org_id MUST 与其所属知识库的 org_id 严格一致。

#### Scenario: 仓储层显式按 org_id 过滤

- **WHEN** 系统执行任意文档或摄取任务查询
- **THEN** 仓储方法(如 `find_by_knowledge_base_id_and_org_id`)MUST 显式携带从请求级租户上下文(`contextvars.ContextVar`,按 asyncio task 隔离;历史 Java 版用 Hibernate `@Filter` 实现的等价能力,自研 Python 后端改为显式参数化查询)读出的 org_id 条件,跨租户文档不会出现在结果中

#### Scenario: 直接按 ID 查询跨租户文档

- **WHEN** member 提供另一组织文档或摄取任务的 UUID 直接访问
- **THEN** 系统返回 404,不泄露资源存在性

#### Scenario: 同组织跨知识库访问被拒

- **WHEN** member 通过 KB-A 的请求参数访问属于 KB-B 的文档(同组织内)
- **THEN** 系统返回 404,文档查询/删除均同时绑定 kbId + orgId 双重校验
