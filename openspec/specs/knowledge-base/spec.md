# knowledge-base Specification

## Purpose

企业知识库 CRUD 及多租户隔离——创建/查询/更新/删除知识库，强制跨组织隔离。知识库是自研 RAG Core 摄取与检索链路(Parser/Chunker/Embedding/Index/Retriever)的业务归属单元，不再关联任何外部黑盒系统的 dataset 或 chat assistant。

## Requirements
### Requirement: 知识库 CRUD

系统 SHALL 允许成员在其组织内创建、查询、更新、删除知识库。每个知识库 MUST 归属唯一组织,可选归属某团队。删除是纯业务记录删除,不触发任何外部系统调用。

#### Scenario: 创建知识库

- **WHEN** 成员在其组织内创建名为 X 的知识库
- **THEN** 系统持久化知识库(初始状态 `ACTIVE`),记录其组织归属与创建者

#### Scenario: 授权更新知识库

- **WHEN** 成员更新本组织知识库的名称
- **THEN** 系统持久化更新后的名称

#### Scenario: 删除知识库

- **WHEN** 成员删除一个知识库
- **THEN** 系统直接删除该知识库的业务记录,接口返回 200、`code=0`、`data="已删除"`

> **历史遗留(不是当前实际行为):** 项目早期知识库创建时会同步在 RAGFlow 创建一个专属 dataset,删除知识库要求"先删 RAGFlow dataset、再删业务记录",dataset 删除失败会把知识库标记 `PENDING_CLEANUP` 并转入对账。该机制已随 RAGFlow 退役被移除——`KnowledgeBaseService.delete()` 当前实现内部恒返回"已完全删除"。路由层与 `KbStatus.PENDING_CLEANUP` 枚举值、前端"待清理"标签仍保留了应对"未完全删除→202"的防御性分支,但在当前实现下没有任何代码路径会触发它(见 `backend-py/app/routers/knowledge_bases.py::delete`、`backend-py/app/services/knowledge_base_service.py::delete`)。`knowledge_base` 表中的 `ragflow_dataset_id`、`ragflow_chat_id`(早期"知识库懒建 RAGFlow Chat Assistant 并复用其 ID"设计遗留)两列因兼容旧数据而保留,自研链路(问答走自研 RAG Core 生成管线,不再有 Chat Assistant 概念)不再读写它们。

### Requirement: 知识库级权限

系统 SHALL 在每个知识库访问路径强制校验:调用者 MUST 属于知识库所属组织(见"知识库跨租户隔离")。

> **已知差异(未解决,待产品决策):** 早期设计曾要求"owner/admin 才能增删改,member 仅可读,越权返回 403"(角色分级管理)。经代码核查(`backend-py/app/services/knowledge_base_service.py::create/update/delete`、`backend-py/app/routers/knowledge_bases.py`),当前实现**没有任何角色校验**——只要是该组织成员(含 MEMBER),即可创建/重命名/删除组织内任意知识库,不存在返回 403 的代码路径。`docs/user-guide.md` 的权限对照表与此一致(MEMBER/ADMIN/OWNER 三行"创建/删除知识库"均为 ✅),但与本文件曾经的"越权 403"表述矛盾。这是"仅按组织隔离、组织内成员平权管理知识库"的产品决策,还是遗漏的角色校验实现缺口,尚未有人拍板——不是本次文档核查能直接判定对错的问题,已记录在 `TODOS.md`。

#### Scenario: 授权读取

- **WHEN** 组织内 member 读取本组织的知识库
- **THEN** 系统返回知识库内容

### Requirement: 知识库跨租户隔离(安全红线)

系统 MUST 确保成员无法访问、列举或操作其他组织的知识库。

#### Scenario: 跨组织访问知识库按不存在处理

- **WHEN** 组织 A 的成员按 ID 直取组织 B 的知识库
- **THEN** 系统返回 404(按"资源不存在"处理),绝不返回内容,不泄露其是否存在

#### Scenario: 列举仅限本组织知识库

- **WHEN** 成员列举知识库
- **THEN** 结果只包含其所属组织的知识库
