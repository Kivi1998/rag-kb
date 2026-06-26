## Why

当前认证是最小 JWT 占位(手动生成 token,无真实身份验证),只能开发调试用。需要一套完整的本地账号体系:用户注册、登录、密码管理,让系统可以真正投入使用,不依赖外部 IdP。后续可扩展接入 SSO/OIDC。

## What Changes

- 新增本地账号模型:User 表(用户名/邮箱/密码哈希/状态)
- 新增注册端点:邮箱注册 + 密码哈希存储(BCrypt)
- 新增登录端点:邮箱+密码登录,返回 JWT(复用已有 TenantContext 机制)
- 新增密码修改/重置(基础版)
- 新增账号与 member 的绑定:一个 User(subject)可加入多个组织(复用已有的 subject↔member 模型,只是 subject 来源从手写 JWT 变为注册的真实用户);注册只建账号,用户登录后自行创建或加入组织
- 新增 Redis 依赖:用于改密后的 JWT token 黑名单(jti→TTL)
- 修改已有 tenant-management spec:认证来源改为本地账号登录

## Capabilities

### New Capabilities

- `local-auth`: 本地账号注册/登录/密码管理、JWT 签发与刷新、User 表与 subject↔member 映射

### Modified Capabilities

- `tenant-management`: 认证来源从"JWT 占位"改为"本地账号登录",subject 来源变为 User 表的真实用户 ID

## Non-goals(非目标)

- SSO/OIDC 对接(后续 change,本期先用本地账号跑通)
- 多因素认证(MFA)
- 邮箱验证/找回密码邮件发送(本期密码重置仅限管理员操作)
- 前端登录/注册页面 UI
- 社交登录(微信/GitHub 等)

## Impact

- 新增 Flyway 迁移:user 表
- 替换 JwtAuthFilter:从"手写 JWT 外部传入"改为"登录后由服务端签发 JWT"
- 新增 AuthController(注册/登录/改密)
- 新增 UserService + UserRepository
- 新增依赖:BCrypt(已随 spring-boot-starter-security 包含)
