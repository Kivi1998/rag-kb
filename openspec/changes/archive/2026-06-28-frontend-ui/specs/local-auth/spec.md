## MODIFIED Requirements

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
