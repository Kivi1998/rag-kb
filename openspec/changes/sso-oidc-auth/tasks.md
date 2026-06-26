## 1. Redis 集成

- [x] 1.1 pom.xml 新增 `spring-boot-starter-data-redis`;application.yml 配置 Redis 连接(环境变量 `${REDIS_HOST:localhost}` 等);测试配置用 embedded-redis 或 mock
- [x] 1.2 实现 `RedisService`(或直接用 `StringRedisTemplate`),封装 `setWithTTL(key, value, ttlSeconds)` 和 `exists(key)` 两个方法,供 token 黑名单使用

## 2. User 数据模型

- [x] 2.1 Flyway 迁移:新建 `user` 表(id UUID PK, email UNIQUE, password_hash, display_name, status VARCHAR[ACTIVE/LOCKED], failed_login_count INT DEFAULT 0, locked_until TIMESTAMPTZ NULL, must_change_password BOOLEAN DEFAULT FALSE, token_version INT DEFAULT 0, created_at, updated_at)
- [x] 2.2 JPA 实体 `User` + `UserRepository`(findByEmail, existsByEmail)

## 3. 注册与登录

- [x] 3.1 实现 `PasswordService`:BCryptPasswordEncoder Bean(强度 10),`hash(raw)` 和 `matches(raw, hash)` 方法
- [x] 3.2 实现 `JwtService`:签发 JWT(subject=userId, jti=UUID, tv=tokenVersion, exp=可配置默认 24h)和解析/验证 JWT(签名+有效期+tokenVersion 比对);配置 `jwt.expiration-seconds` 属性
- [x] 3.3 实现 `UserService.register(email, password, displayName)`:校验邮箱格式+唯一性(409)、密码强度(≥8 位含字母+数字,400)、BCrypt 哈希、创建 User、签发 JWT 返回
- [x] 3.4 实现 `UserService.login(email, password)` 核心流程:查 User→BCrypt 验证→must_change_password 检查→签发 JWT;密码错误/邮箱不存在统一 401(不泄露);账号已锁定→423
- [x] 3.4b 实现登录失败计数与锁定:failed_login_count++、达 5 次锁定 15 分钟(423);locked_until 过期自动解锁
- [x] 3.5 实现 `AuthController`:POST `/api/v1/auth/register`、POST `/api/v1/auth/login`(均免租户上下文,SecurityConfig 白名单)

## 4. 密码修改与 token 黑名单

- [x] 4.1 实现 `UserService.changePassword(userId, oldPassword, newPassword)`:验证旧密码(403)、校验新密码强度(400)、更新哈希、将当前 JWT jti 写入 Redis 黑名单(TTL=token 剩余有效期)
- [x] 4.2 实现管理员重置密码:PUT `/api/v1/members/{id}/reset-password`(仅 owner/admin 可操作);生成 8 位随机临时密码、更新哈希、递增被重置用户的 token_version(旧 JWT 全部失效)、设置 must_change_password=true
- [x] 4.3 实现 `AuthController.changePassword`(需认证)

## 5. JwtAuthFilter 改造

- [x] 5.1 改造 JwtAuthFilter:JWT 解析后增加三层检查:① Redis 黑名单(jti EXISTS → 401) ② token_version 比对(tv≠DB → 401) ③ Redis 不可达 → 503(fail-close);注册/登录端点 permitAll 免 JWT
- [x] 5.2 更新 SecurityConfig:注册(`/api/v1/auth/register`)和登录(`/api/v1/auth/login`)端点 permitAll;其余端点 authenticated

## 6. 安全测试

- [x] 6.1 注册测试:正常注册→200+JWT;重复邮箱→409;弱密码→400;空邮箱→400
- [x] 6.2 登录测试:正确登录→200+JWT;错误密码→401;不存在邮箱→401(不泄露);连续 5 次错误→423 锁定;锁定期内登录→423;must_change_password 用户登录→JWT 含标记
- [x] 6.3 JWT 安全测试:过期 token→401;篡改签名→401;jti 在黑名单→401;token_version 不匹配→401;Redis 不可达→503
- [x] 6.4 密码修改测试:正确旧密码→成功+旧 token 失效;错误旧密码→403;新密码弱→400;旧 token 再用→401
- [x] 6.5 管理员重置密码测试:owner 重置→成功+被重置用户的旧 token 全部失效(token_version 不匹配→401);member 重置他人→403
- [x] 6.6 回归测试:原有 13 个安全测试仍全部通过(用新签发的 JWT 替代旧的手写 JWT)
