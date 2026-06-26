## Context

rag-kb 编排后端首个 change(tenant-kb-foundation)已完成,实现了三级租户模型 + 知识库 CRUD + JWT 认证占位。当前 JwtAuthFilter 的 subject 来自外部手写 JWT(无真实身份验证),需要替换为本地账号登录签发的 JWT。已有基础设施:Spring Security、BCrypt(随 starter 包含)、JWT 库(JJWT 0.12.6)、TenantContext + AOP Filter、Flyway。

## Goals / Non-Goals

**Goals:**

- 建立完整的本地账号体系(注册/登录/改密),让系统可真正投入使用
- 登录后由服务端签发 JWT,替换外部手写 JWT
- 保持已有的 TenantContext + AOP @Filter 机制不变,只换 JWT 的签发来源
- 密码修改后旧 JWT 失效(通过 Redis jti 黑名单)

**Non-Goals:**

- SSO/OIDC 对接(后续 change)
- MFA、邮箱验证、找回密码邮件发送
- 前端 UI

## Decisions

### 决策 1:JWT 签发与验证复用已有 JJWT 库 + 同一密钥

登录/注册成功后由服务端用 HMAC-SHA256 密钥签发 JWT(subject=userId, exp=可配置默认 24h)。JwtAuthFilter 保持现有结构,只是 JWT 来源从"外部传入"变为"本系统签发"。
- **理由**:已有 JJWT 依赖和密钥配置,复用零额外成本;过滤器结构不变,改动最小。
- **备选**:用 Spring Security OAuth2 Resource Server(过重,本期无外部 IdP)。

### 决策 2:密码用 BCrypt,登录失败限制用内存计数器

密码哈希用 Spring Security 的 `BCryptPasswordEncoder`(强度 10)。登录失败限制:用 `ConcurrentHashMap<email, FailureInfo>` 做内存计数(5 次/15 分钟锁定),应用重启计数清零(可接受)。
- **理由**:BCrypt 已随 spring-boot-starter-security 包含;内存计数对百人级够用,无需 Redis。
- **备选**:数据库记录失败次数(持久但每次登录多一次写);Redis(引入额外依赖)。

### 决策 3:密码修改后旧 JWT 失效——Redis token 黑名单

两层防护确保旧 JWT 失效:
- **用户自己改密**:将当前 JWT 的 jti 写入 Redis 黑名单(TTL=剩余有效期)。改密者自己的 token 立即失效。
- **管理员重置成员密码**:无法获知成员的 jti,改为递增 User 表的 `token_version`。JWT 签发时嵌入 `tv` claim,验证时比对 token_version,不匹配则拒绝(401)。
- **理由**:Redis jti 黑名单用于改密者自己的 token(精确到单个 token);token_version 用于管理员重置(影响该用户所有 token,无需知道 jti)。两者互补。
- **Redis 故障行为**:fail-close——Redis 不可达时拒绝所有请求返回 503(告警),toB 安全优先。

### 决策 4:注册只建账号,不自动创建组织

注册流程:创建 User → 签发 JWT → 返回。用户登录后自行创建或加入组织(调用已有的 OrganizationService.create 端点)。
- **理由**:用户可能需要先加入已有组织(而非自建),自动建组织会造成大量废弃组织。注册即登录,后续步骤由用户主动发起。
- **对比**:不自动建组织,用户多一步操作,但更灵活、更干净。

### 决策 5:User 表独立,与 Member 通过 subjectId 关联

新增 `user` 表(id, email, password_hash, display_name, status[ACTIVE/LOCKED], failed_login_count, locked_until, must_change_password BOOLEAN DEFAULT FALSE, token_version INT DEFAULT 0, created_at, updated_at)。`member.subject_id` 指向 `user.id`(UUID 类型,对齐已有设计)。Redis 用于改密后的 token 黑名单(key=`blacklist:jti:{jti}`,TTL=token 剩余有效期)。`token_version` 用于管理员重置密码场景:重置时 `token_version++`,JWT 嵌入 `tv` claim,验证时比对(不依赖知道被重置成员的 jti)。
- **理由**:User(账号主体)与 Member(组织内身份)一对多,已有模型不需要改,只加一张表。
- **备选**:把 User 字段合入 Member(会导致大量冗余,一个用户多组织时密码存多份)。

### 决策 6:保留 JwtAuthFilter 结构,只换签发端

不引入 Spring Security OAuth2 Login 或 formLogin。保留现有的 `JwtAuthFilter extends OncePerRequestFilter` 结构,仅在过滤器中增加"本系统签发的 JWT"验证逻辑。新增 `AuthController` 处理注册/登录/改密端点。
- **理由**:改动最小,已有的 13 个安全测试大部分不需要改(只需更新 JWT 生成方式)。
- **备选**:Spring Security formLogin + Session(不适合 REST API);OAuth2 Login(本期无外部 IdP)。

## Risks / Trade-offs

- [内存登录失败计数器重启清零] → 百人级下可接受;未来可迁移到 Redis 不影响接口。
- [JWT 24h 有效期较长] → 密码修改后通过 Redis jti 黑名单立即失效,弥补长有效期风险。
- [Redis 不可用时改密后旧 token 仍有效] → Redis 是核心基础设施,高可用由运维保障;极端情况下旧 token 最多存活 24h(有效期上限)。
- [管理员重置密码生成临时密码的安全性] → 临时密码 8 位随机,强制下次登录改密;暴力破解靠已有锁定机制防护。
- [注册不自动建组织,用户需多一步] → 用户可选创建或加入,比自动建更灵活。
