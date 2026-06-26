## 1. 工程骨架

- [x] 1.1 初始化 Spring Boot 工程(Web、Validation、Data JPA、PostgreSQL 驱动、Flyway)
- [x] 1.2 统一响应格式(`ApiResponse<T>`)与全局异常处理(`@RestControllerAdvice`),约定 401/403/400 语义
- [x] 1.3 配置 `.env`/`application-secret` 加载,数据库与 RAGFlow 端点用占位密钥,确认无硬编码、不进 git

## 2. 数据模型与迁移

- [x] 2.1 设计并编写 Flyway 建表脚本:`organization`、`team`、`member`(subject_id、org_id、role,唯一约束 `(subject_id, org_id)`)、`knowledge_base`(org_id、team_id?、ragflow_dataset_id、status)
- [x] 2.2 编写对应 JPA 实体与 Repository,补外键与唯一约束(团队归属唯一组织、成员归属唯一组织)
- [x] 2.3 引入元数据层第二保险:对租户表启用 PostgreSQL RLS 或 Hibernate `@TenantId`,由 TenantContext 自动套 org 过滤(决策 5)
- [x] 2.4 安全测试:绕过/遗漏应用层过滤直接查 Repository,断言 DB 层兜底仍只返回本组织数据

## 3. 认证占位与租户上下文

- [x] 3.1 实现最小认证占位:从请求头/JWT 解析"已认证主体(subject 标识)",claim 字段对齐未来 OIDC 映射;**org_id/role 一律按 (subject, 目标组织) 查 member 得出,不采信客户端自报;subject 在目标组织无 member → 404**
- [x] 3.2 实现 `TenantContext`(组织 ID/成员 ID/角色)+ 过滤器注入;无有效主体返回 401;**过滤器 `finally` 块无条件清理 ThreadLocal**
- [x] 3.3 安全测试:无凭证/伪造主体 → 401;**主体真实但自报他组织 org_id/更高 role → 不被采信,越权被拒**
- [x] 3.4 安全测试:同一容器线程连发组织 A、组织 B 两个请求 → 断言第二个不残留 A 的上下文(线程复用不串租户)

## 4. 租户管理(tenant-management)

- [x] 4.1 组织/团队 CRUD Service + Controller;"创建组织"端点**免租户上下文**(仅需有效 subject),创建后为该 subject 在新组织建 role=owner 的 member;创建团队校验父组织等于当前上下文(跨组织建团队 → 400)
- [x] 4.2 成员邀请与角色分配(owner/admin/member)
- [x] 4.3 角色层级矩阵落地(owner 全权;admin 管 member 但不可设/改 owner;member 不可改角色)+ "组织始终至少一名 owner"守卫
- [x] 4.4 团队/成员列举仅返回当前组织数据
- [x] 4.5 安全测试:跨组织按 ID 访问团队/成员 → **404 不泄露存在性**;列举不含他组织数据;member 改角色 → 403
- [x] 4.6 安全测试:admin 自我/他人提权为 owner → 403;降级或移除最后一名 owner → 拒绝(400/409)

## 5. 知识库 + RAGFlow dataset 映射(knowledge-base)

- [x] 5.1 实现 RAGFlow Feign 客户端:创建/删除 dataset(端点、鉴权、错误映射);创建带归属前缀/标签(`ragkb:<org_id>:<kb_id>`)且**幂等**(幂等键/重试前查重)
- [x] 5.2 知识库创建:先建 dataset 再落库,保存 id↔dataset_id 映射;dataset 失败则整体回滚
- [x] 5.3 知识库查询/更新(改名等,dataset 绑定不变)
- [x] 5.4 知识库删除:按"先删 dataset → 再删记录"顺序;删 dataset 失败则记录置 `PENDING_CLEANUP` 转对账,不留悬挂
- [x] 5.5 知识库列举仅返回当前组织数据

## 6. RBAC 与跨租户隔离(安全红线)

- [x] 6.1 在知识库每个访问路径强制校验:调用者属于知识库所属组织 + 角色满足操作(owner/admin 可写,member 只读)
- [x] 6.2 安全测试:组织 A 成员按 ID 直取组织 B 知识库 → **404 不泄露存在性**,且不访问对方 dataset;列举仅本组织
- [x] 6.3 安全测试:member 删除/修改知识库 → 403
- [x] 6.4 集成测试:验证不同知识库映射到不同 dataset,确认无共用

## 7. 数据一致性与验证

- [x] 7.1 孤儿 dataset 对账任务:仅扫描**带本产品归属前缀/标签**、无有效映射、且**超过 grace period**(避开创建中竞态)的 dataset 清理;一并处理 `PENDING_CLEANUP` 记录
- [x] 7.2 隔离测试基线夹具:统一构造"组织 A / 组织 B 各一套成员+KB",供所有跨租户用例复用,确保 POC #1 隔离验证可回归
- [x] 7.3 端到端冒烟:建组织(创建者成 owner)→建知识库(自动开 dataset)→读→删(连带删 dataset),全链路跑通
- [x] 7.4 跑全部测试,确认多租户隔离用例全绿;补 README/运行说明(本地启动、RAGFlow 依赖)
