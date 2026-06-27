## ADDED Requirements

### Requirement: 登录页面

系统 SHALL 提供 `/login` 路由，展示邮箱 + 密码表单（el-form），MUST 支持回车提交，显示登录中状态和错误提示。

#### Scenario: 登录成功

- **WHEN** 用户输入正确邮箱和密码并提交
- **THEN** token 和 orgId 存入 sessionStorage，跳转到 `/kb`

#### Scenario: 登录失败

- **WHEN** 用户输入错误凭据
- **THEN** 表单下方显示错误提示，不跳转

#### Scenario: 已登录用户访问登录页

- **WHEN** sessionStorage 中已有有效 token 的用户访问 `/login`
- **THEN** 自动重定向到 `/kb`

### Requirement: JWT + orgId 双头认证

authStore SHALL 维护 `{ token, username, orgId }`，持久化到 sessionStorage。Axios 请求拦截器 MUST 在每个 Axios 请求上自动注入 `Authorization: Bearer <token>` 和 `X-Org-Id: <orgId>` 两个请求头；SSE 的原生 fetch 请求 SHALL 由 queryApi.stream() 手动注入相同双头。

#### Scenario: 受保护接口请求

- **WHEN** 前端发起任意受保护 API 请求
- **THEN** 请求头包含 Authorization 和 X-Org-Id，后端返回 200

#### Scenario: token 过期

- **WHEN** 服务端返回 401
- **THEN** Axios 响应拦截器清除 sessionStorage，显示"登录已过期"，跳转 `/login`

### Requirement: 路由守卫

Vue Router beforeEach 守卫 SHALL 检查 authStore.token：无 token 时 MUST 强制跳转 `/login`；已登录访问根路径时重定向 `/kb`。

#### Scenario: 未登录访问受保护路由

- **WHEN** 未登录用户直接访问 `/kb`
- **THEN** 跳转到 `/login`，完成登录后返回原路由

### Requirement: 退出登录

系统 SHALL 在顶部导航栏提供退出登录按钮，点击后 MUST 清除 sessionStorage 中的 token 和 orgId，跳转 `/login`。

#### Scenario: 用户退出

- **WHEN** 用户点击退出登录
- **THEN** sessionStorage 清空，页面跳转至 `/login`
