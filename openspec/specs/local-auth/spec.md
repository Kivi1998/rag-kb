# local-auth Specification

## Purpose
TBD - created by archiving change sso-oidc-auth. Update Purpose after archive.
## Requirements
### Requirement: 用户注册

系统 SHALL 允许通过邮箱+密码注册本地账号。密码 MUST 以 BCrypt 哈希存储,禁止明文。邮箱在同一系统内 MUST 唯一。注册成功后系统 SHALL 自动签发 JWT,用户可立即使用。

#### Scenario: 正常注册

- **WHEN** 用户提交未注册的邮箱和合法密码(≥8 位,含字母+数字)
- **THEN** 系统创建 User 记录(密码哈希存储),返回 JWT token

#### Scenario: 邮箱已存在

- **WHEN** 用户提交已注册的邮箱
- **THEN** 系统返回 409(业务冲突),不创建重复账号

#### Scenario: 弱密码被拒

- **WHEN** 用户提交少于 8 位或纯字母/纯数字的密码
- **THEN** 系统返回 400(参数非法),不创建账号

#### Scenario: 注册速率限制(邮箱枚举防护)

- **WHEN** 同一 IP 短时间内(5 分钟)提交超过 10 次注册请求
- **THEN** 系统返回 429(请求过多),防止通过 409 枚举已注册邮箱

### Requirement: 用户登录

系统 SHALL 允许通过邮箱+密码登录，验证成功后返回 JWT token，同时返回 `userId` 和 `orgId`（用户所属组织 ID）。`orgId` 是前端注入 `X-Org-Id` 请求头的唯一来源，缺失将导致所有受保护接口 401。

变更点：原响应 `{ token, userId }` → 新响应 `{ token, userId, orgId }`。仅当用户已加入恰好一个组织时 orgId 有值；如用户尚未加入任何组织，orgId 为 null，前端应提示用户联系管理员。

#### Scenario: 正常登录（用户已有组织）

- **WHEN** 用户提交正确邮箱和密码，且已加入至少一个组织
- **THEN** 返回 `{ token, userId, orgId }`（orgId 为该组织的 UUID），HTTP 200

#### Scenario: 正常登录（用户尚无组织）

- **WHEN** 用户提交正确邮箱和密码，但未加入任何组织
- **THEN** 返回 `{ token, userId, orgId: null }`，HTTP 200；前端展示"账号未分配组织，请联系管理员"

#### Scenario: 密码错误

- **WHEN** 用户提交错误密码
- **THEN** 返回 401，不返回 token 或 orgId

### Requirement: JWT 签发与验证

系统 SHALL 在登录/注册成功后签发 JWT。JWT MUST 由服务端密钥(HMAC-SHA256)签名,包含 subject(用户 ID)、jti(唯一标识)、tv(token 版本号)和 exp(过期时间)。token 有效期 MUST 为可配置(默认 24 小时)。系统 SHALL 在每个受保护请求中验证 JWT 签名、有效期、jti 是否在 Redis 黑名单中、以及 tv 是否等于 User 表的 token_version。Redis 不可达时系统 MUST 拒绝所有请求返回 503(fail-close,告警)。

#### Scenario: JWT 过期

- **WHEN** 请求携带已过期的 JWT
- **THEN** 系统返回 401(token 已过期)

#### Scenario: JWT 签名无效

- **WHEN** 请求携带签名被篡改的 JWT
- **THEN** 系统返回 401(无效 token)

#### Scenario: JWT 版本不匹配(token 被管理员重置后失效)

- **WHEN** 请求携带的 JWT 的 tv 字段不等于 User 表的 token_version
- **THEN** 系统返回 401(token 已失效),不进入业务处理

#### Scenario: Redis 不可达

- **WHEN** Redis 连接失败
- **THEN** 系统拒绝所有请求返回 503(服务不可用),并记录告警日志

### Requirement: 密码修改

系统 SHALL 允许已登录用户修改自己的密码(需验证旧密码)。管理员 SHALL 可重置本组织内成员的密码(无需旧密码)。密码修改/重置成功后系统 SHALL 将当前 JWT 的 jti 写入 Redis 黑名单,旧 token 立即失效。

#### Scenario: 用户自己改密

- **WHEN** 已登录用户提交旧密码和新密码
- **THEN** 旧密码验证通过后更新为新密码哈希,当前 JWT 的 jti 写入 Redis 黑名单,旧 token 立即失效

#### Scenario: 管理员重置成员密码

- **WHEN** admin/owner 重置本组织某成员的密码
- **THEN** 系统生成临时密码并返回,递增被重置用户的 token_version(旧 JWT 全部失效),设置 must_change_password=true

#### Scenario: 强制改密用户登录

- **WHEN** must_change_password=true 的用户登录
- **THEN** 系统签发 JWT(含 must_change_password 标记),用户在首次调用业务 API 前必须先改密(未改密时业务请求返回 423 + 提示改密)

#### Scenario: 旧密码验证失败

- **WHEN** 用户提交错误的旧密码
- **THEN** 系统返回 403,密码不被修改

### Requirement: User 与 Member 映射

系统 SHALL 将 User(账号主体)与 Member(组织内身份)关联。一个 User MAY 在多个组织各有一条 Member 记录(subjectId = userId)。注册只创建账号,用户登录后自行创建组织或加入已有组织。

#### Scenario: 用户创建新组织

- **WHEN** 已登录用户调用创建组织端点
- **THEN** 系统创建组织,用户以 owner 角色加入(复用已有 bootstrap 逻辑)

#### Scenario: 用户加入已有组织(FUTURE)

- **WHEN** 已登录用户通过管理员邀请加入某组织(邀请机制作为后续 change 实现)
- **THEN** 系统在该组织为该用户创建 Member 记录(角色由邀请者指定)

> 注:本期只实现"创建新组织"(bootstrap),加入已有组织的邀请机制留待后续 change。

### Requirement: 账号安全(跨账号隔离)

系统 MUST 确保用户只能访问自己所属组织的资源。一个用户的 JWT 只能操作其 Member 记录所在的组织,不能通过伪造 orgId 访问其他组织。

#### Scenario: 跨组织操作被拒

- **WHEN** 用户 A 的 JWT 请求操作用户 B 所属组织的资源(且 A 在该组织无 Member)
- **THEN** 系统返回 401(该主体在此组织无成员身份),不泄露资源是否存在

