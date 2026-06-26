## Context

rag-kb 是全新 toB 知识库产品,首个 change 要在 Spring Boot 编排后端落地多租户地基。当前仓库只有架构文档,无代码。最高风险是 RAGFlow 的多租户隔离能否守住——这是 toB 红线,本设计据此选择"每个知识库一个独立 RAGFlow dataset + 应用层强制 RBAC"的双重隔离。

约束:后端不自写 RAG 内核,只用 REST/Feign 调 RAGFlow;注释/文档/commit 用中文,标识符用英文;密钥进 `.env`/`application-secret`;每条访问路径强制租户校验。

## Goals / Non-Goals

**Goals:**

- 建立组织→团队→成员租户模型与请求级租户上下文
- 知识库 CRUD,且每个知识库绑定专属 RAGFlow dataset
- 在每个访问路径强制 RBAC,跨租户/越权一律拒绝
- 让"多租户隔离"可被自动化安全测试覆盖(验证架构 POC #1)

**Non-Goals:**

- 文档摄取、检索问答(后续 change)
- 完整 SSO/OIDC(本期仅最小认证占位)
- 配额限流、完整审计体系、前端 UI
- 知识库重命名同步 RAGFlow dataset 内部名称(仅改业务库展示名,dataset 标识不变)
- 列举分页(数据量治理留待容量/限流 change)

### 错误码统一约定

全 change 统一:**跨租户资源(他组织)→ 404(按不存在,不泄露存在性);同租户内角色不足 → 403;未认证 → 401;参数非法 → 400;业务不变量冲突(如降级最后一名 owner)→ 409。** 所有 spec 引用此约定,避免"403 暴露存在性"的红线漏洞与表述不一致。

## Decisions

### 决策 1:租户隔离 = 独立 dataset + 应用层强制校验(双保险)

每个知识库创建时在 RAGFlow 开一个**专属 dataset**(物理隔离),同时应用层在每个请求用当前组织上下文校验资源归属(逻辑隔离)。
- **理由**:RAGFlow 自身隔离模型未经实测,不能单点依赖;应用层校验是 toB 兜底红线。
- **备选**:仅靠 RAGFlow 内置权限(风险过高,POC 未过);全租户共用一个 dataset 加字段过滤(检索期易串租户,放弃)。

### 决策 2:租户上下文用 Servlet 过滤器/拦截器注入 + ThreadLocal 持有,请求级生命周期严格管理

认证后由过滤器解析主体→组织/成员/角色,存入请求级上下文(`TenantContext`,ThreadLocal),Service 层鉴权统一从中取。上下文生命周期四件事必须一起做:① 过滤器入口注入;② 归属/角色由服务端查库得出(见决策 3);③ **过滤器 `finally` 块无条件 `remove()` 清理**;④ 异步/线程池场景显式传递(本期同步为主,异步留待摄取 change)。
- **理由**:避免每个方法手传租户参数,集中校验点,降低漏判风险。
- **关键风险**:Servlet 容器线程池**复用线程**,若请求结束未清理,下一请求会读到上一租户上下文 → 同步请求即可串租户。故 `finally` 清理是硬性要求,并配套"同线程连发两租户请求不串"的安全测试。
- **备选**:每个方法显式传 tenantId(易遗漏,放弃)。

### 决策 3:区分 subject 与 member;最小认证占位,SSO 后置;归属与角色一律服务端解析

- **概念分层**:**subject** = 认证主体(自然人/账号,对应未来 OIDC 的 `sub`),全局唯一、不绑定组织;**member** = subject 在**某个组织内**的身份记录(含 org_id、role)。二者 **一对多**:一个 subject 可在多个组织各有一条 member 记录(即可创建/加入多组织)。本期用简单 JWT/请求头携带 **subject 标识** 作为已认证主体来源,契约对齐未来 OIDC claim 映射,真正 SSO 单列 change。
- **铁律**:受租户保护的请求,`TenantContext` 的 **org_id 与 role 必须由服务端用 (subject, 目标组织) 查 member 表得出,绝不采信客户端自报**。subject 在目标组织无 member 记录 → 按跨租户处理(404)。
- **org 创建端点免租户上下文**:创建组织属于 bootstrap,只要求有效 subject、**不要求**已有 member/租户上下文;创建成功后系统为该 subject 在新组织插入一条 role=owner 的 member 记录。除"创建组织"与少数账户级端点外,其余端点一律要求有效租户上下文。
- **理由**:消除"创建组织时无 member 故无法解析归属"的空洞;让租户/知识库独立开发与测试,不被 SSO 阻塞;占位期鉴权与正式期等价可信。

### 决策 4:知识库↔dataset 映射 + 创建失败回滚 + 删除对称补偿

业务库存 `knowledge_base(id, org_id, team_id?, name, ragflow_dataset_id, status, ...)`。
- **创建**:走"先建带归属标签的 dataset → 再落库",任一步失败整体回滚;dataset 创建幂等(幂等键/查重),超时重试不产生重复。
- **删除**(与创建对称):走"先删 dataset → 再删业务记录";若删 dataset 失败,则把记录标记 `status=PENDING_CLEANUP` 转入孤儿对账,绝不留下指向已失效 dataset 的悬挂记录。
- **理由**:避免没有 dataset 的知识库、没有知识库的孤儿 dataset、或指向失效 dataset 的悬挂记录。

### 决策 5:业务元数据隔离引入 DB 层第二保险

除"每个 Repository 查询注入 org_id 过滤"外,对 PostgreSQL 业务表(org/team/member/knowledge_base)引入 **Row-Level Security(RLS)或 Hibernate `@TenantId`/`@Filter`**,由 `TenantContext` 自动套用 org 过滤,作为元数据层的双保险(与 dataset 物理隔离对称)。
- **理由**:仅靠手写 `WHERE org_id` 与决策 2 想消除的"手传 tenantId 易遗漏"是同一风险,任一查询漏过滤即串租户;DB 层兜底可挡住代码遗漏。
- **备选**:仅应用层过滤(风险过高);本期至少落地 RLS 或 `@TenantId` 其一。

## Risks / Trade-offs

- [RAGFlow dataset 数量随知识库线性增长,百人级下可能很多] → 本期先验证隔离正确性;容量/配额留待摄取与限流 change。
- [创建/删除知识库跨两个系统(业务库 + RAGFlow),非原子] → 创建"先建 dataset 后落库 + 失败回滚",删除"先删 dataset 后删记录 + 失败转对账";引入对账任务(列入 tasks)。
- [最小认证占位可能被误当正式认证,或误信客户端自报归属] → 代码与文档显式标注占位;归属/角色一律服务端查库(决策 3);接口契约预留 OIDC claim 映射。
- [ThreadLocal 上下文:线程池**复用**时若不清理会串租户(同步即触发);异步场景会丢失] → 过滤器 `finally` 无条件清理 + "同线程连发两租户不串"安全测试;异步显式传递(摄取 change 处理)。
- [孤儿对账可能误删:无法区分本产品与他人 dataset / 与"创建中"请求竞态] → dataset 带归属前缀/标签做识别;仅清理"超过 grace period 且无映射"的 dataset,避开刚创建未落库的竞态。
- [业务表隔离漏写 `WHERE org_id` 即串租户] → 决策 5 引入 PostgreSQL RLS / Hibernate `@TenantId` 作 DB 层兜底。

## Migration Plan

全新项目,无存量迁移。部署:PostgreSQL 建表(Flyway/Liquibase 脚本),配置 RAGFlow 端点与密钥(`.env`/`application-secret`)。回滚:本 change 为新增能力,回滚即下线相关表与接口,不影响既有功能(无)。

## Open Questions

- RAGFlow dataset 的隔离强度需 POC 实测确认(架构 POC #1),若实测不达标,是否升级为"每租户独立 RAGFlow 实例/命名空间"?
- 团队级权限本期做到何粒度——仅"组织内可见"还是细到"团队私有知识库"?(本期先按组织隔离 + 可选团队归属,细粒度团队 ACL 视实测后续迭代)
