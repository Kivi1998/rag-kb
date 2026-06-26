## Why

rag-kb 的一切能力(文档摄取、检索问答)都建立在"谁能访问哪个知识库"之上。多租户隔离是 toB 红线——租户间数据绝不能串。首个 change 先夯实地基:租户模型 + 知识库归属 + 访问控制,后续能力才能安全挂载。这也是架构里最高优先级的 POC(RAGFlow 多租户隔离)。

## What Changes

- 新增组织→团队→成员三级租户模型,含成员归属与角色(owner/admin/member)
- 新增知识库 CRUD;每个知识库绑定一个**独立 RAGFlow dataset**,实现物理隔离
- 在每个访问路径**强制 RBAC 校验**:跨租户访问按"不存在"处理(404,不泄露存在性),同租户内越权拒绝(403)
- 提供请求级"当前租户上下文"解析(基于已认证主体)

## Capabilities

### New Capabilities

- `tenant-management`: 组织/团队/成员模型、成员归属与角色、请求级租户上下文解析
- `knowledge-base`: 知识库 CRUD、知识库↔RAGFlow dataset 映射、知识库级 RBAC 与跨租户隔离

### Modified Capabilities

(无 —— 项目首个 change,暂无既有 spec)

## Non-goals(非目标)

- 文档摄取(上传/解析/切块/向量化)与检索问答 —— 后续提案
- 完整 SSO/OIDC 对接 —— 本期仅用最小认证占位提供"已认证主体",真正接入单列提案
- 配额限流、完整审计体系、前端 UI

## Impact

- 新建/补全 Spring Boot 工程骨架:统一响应格式、全局异常、RBAC 拦截器
- 新增 PostgreSQL 表:`organization` / `team` / `member` / `knowledge_base` 及关联
- 新增 RAGFlow dataset 管理的 Feign 客户端(创建/删除 dataset)
- 安全测试必须覆盖跨租户访问被拒
