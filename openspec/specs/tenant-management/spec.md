# tenant-management Specification

## Purpose
TBD - created by archiving change tenant-kb-foundation. Update Purpose after archive.
## Requirements
### Requirement: 三级租户模型

系统 SHALL 以"组织(organization)→ 团队(team)→ 成员(member)"三级结构建模租户。每个团队 MUST 归属唯一组织;每个成员(member)MUST 归属唯一组织,并可加入该组织下的零个或多个团队。系统 SHALL 区分 **subject**(认证主体,全局唯一、不绑定组织)与 **member**(subject 在某组织内的身份记录,含角色);一个 subject MAY 在多个组织各有一条 member 记录。

#### Scenario: 创建组织与团队

- **WHEN** 管理员创建一个组织,并在其下创建团队
- **THEN** 系统持久化组织与团队,团队记录其所属组织 ID

#### Scenario: 创建组织者自动成为 owner(bootstrap,免租户上下文)

- **WHEN** 一个有效 subject 调用"创建组织"端点(该端点不要求已有 member/租户上下文)
- **THEN** 系统创建组织,并为该 subject 在新组织插入一条 role=owner 的 member 记录,初始租户由此开通(无需预先存在 owner)

#### Scenario: 无 member 访问受保护资源按不存在处理

- **WHEN** 一个 subject 访问某组织的受保护资源,但其在该组织无 member 记录
- **THEN** 系统按跨租户处理返回 404,不解析出任何归属/角色

#### Scenario: 团队不得跨组织

- **WHEN** 请求在当前组织上下文下创建团队,却指定父组织为另一组织
- **THEN** 系统拒绝(400),团队的组织归属必须与上下文一致

### Requirement: 成员角色与角色层级

系统 SHALL 为每个成员在其组织内分配角色:owner、admin 或 member。角色 MUST 遵循以下可操作矩阵:owner 可管理全部成员与角色(含设/撤 admin、转让 owner);admin 可管理 member(邀请、移除、读),但 MUST NOT 提升任何人(含自己)为 owner,也 MUST NOT 修改 owner;member 仅有被授予的读权限,MUST NOT 修改任何人角色。组织 MUST 始终至少保留一名 owner。

#### Scenario: 角色分配

- **WHEN** owner 邀请新成员并指定 admin 角色
- **THEN** 该成员以 admin 角色加入组织

#### Scenario: member 越权修改角色被拒

- **WHEN** member 角色的成员尝试修改他人角色
- **THEN** 系统返回 403,角色不被修改

#### Scenario: admin 自我提权为 owner 被拒

- **WHEN** admin 尝试把自己或他人提升为 owner
- **THEN** 系统返回 403,角色不被修改

#### Scenario: 不得降级最后一名 owner

- **WHEN** 对组织内最后一名 owner 执行降级或移除
- **THEN** 系统拒绝(400/409),保证组织始终至少有一名 owner

### Requirement: 请求级租户上下文解析

系统 SHALL 在每个受保护请求开始时,从已认证主体(subject)解析"当前租户上下文"(组织 ID、member ID、角色)。**subject 来源为已注册的本地账号(User 表),通过邮箱+密码登录获得 JWT 后携带在请求中**。上下文中的**组织归属与角色 MUST 由服务端用 (subject, 目标组织) 查 member 记录得出,绝不采信客户端自报的组织 ID 或角色**;subject 在目标组织无 member 记录时按跨租户处理(401)。无法解析有效上下文的请求 MUST 被拒绝(免租户上下文的注册/登录端点除外)。上下文 MUST 具有请求级生命周期:请求结束时无条件清理,绝不在复用的线程间残留。

#### Scenario: 解析成功(本地账号登录后访问)

- **WHEN** 已登录用户(持有有效 JWT)携带 X-Org-Id 请求头访问某组织资源
- **THEN** 系统从 JWT 提取 subject(userId),用 (subject, 该组织) 查 member 得出组织 ID 与角色并注入上下文

#### Scenario: 缺失凭证被拒

- **WHEN** 请求未携带有效 JWT
- **THEN** 系统返回 401,不进入业务处理

#### Scenario: JWT 过期被拒

- **WHEN** 请求携带已过期的 JWT
- **THEN** 系统返回 401(token 已过期),不进入业务处理

#### Scenario: 自报高权限不被采信

- **WHEN** 主体真实存在,但请求中自报了不属于自己的组织 ID 或更高角色
- **THEN** 系统忽略自报值,仅按服务端查得的真实归属/角色鉴权;越权操作被拒(401 跨租户 / 403 同租户越权)

#### Scenario: 线程复用不串上下文

- **WHEN** 同一容器线程先后处理组织 A 成员与组织 B 成员的两个请求
- **THEN** 第二个请求看到的上下文只属于组织 B,绝不残留组织 A 的上下文(请求结束已在 finally 中清理)

### Requirement: 跨租户隔离(安全红线)

系统 MUST 确保任一成员仅能感知与访问其所属组织内的资源。任何对其他组织资源的读、写、列举 MUST 被拒绝。

#### Scenario: 跨组织访问按不存在处理

- **WHEN** 组织 A 的成员按 ID 请求组织 B 的团队或成员资源
- **THEN** 系统返回 404(按"资源不存在"处理),绝不泄露该资源是否存在

#### Scenario: 列举仅限本组织

- **WHEN** 成员列举团队或成员
- **THEN** 结果只包含其所属组织的数据

