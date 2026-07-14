# TODOS

延后但已记录的工作项。每项注明动机、现状与起点,避免日后丢失上下文。

## 文档列表分页(deferred from kb-document-ingest 评审)

- **What:** 给 `GET /api/v1/knowledge-bases/{kbId}/documents` 加分页(Spring Data `Pageable`)。
- **Why:** 当前 `DocumentService.listByKb` 一次返回知识库下全部文档;文档数极大时响应体过大、内存与传输开销高。
- **Pros:** 限制单次返回规模,支撑大知识库;前端可滚动加载。
- **Cons:** 改 Controller/Service 签名与 spec,略扩范围;需定分页参数与默认页大小。
- **Context:** kb-document-ingest 评审(Issue 9)确认本 change 不做,以专注上传摄取闭环。实现时:`DocumentRepository.findByKbIdAndOrgId` 加 `Pageable` 重载,Controller 接 `page/size`,spec 文档列表 requirement 补分页 scenario。
- **Depends on / blocked by:** 无（kb-document-ingest 早已落地，随时可做；2026-07-14 复核 `DocumentController` 仍无 `Pageable`，此项仍未实现）。

## 角色感知删除按钮隐藏(deferred from frontend-ui 评审)

- **What:** 删除 KB / 文档操作需 admin/owner 权限（DocumentService/KnowledgeBaseService 均有校验），但前端目前无角色控制，普通 member 可见删除按钮并点击，收到 403。
- **Why:** MVP 单组织假设下普通 member 数量少，403 有 el-message 提示可接受。
- **Pros:** 消除无效操作，改善普通 member 体验。
- **Cons:** 需给 `KbSidebar.vue`/`DocumentPanel.vue` 的删除按钮加 `v-if` 判断。
- **Context:** frontend-ui 评审（Issue 13）确认 MVP 不做。**2026-07-14 更新**：原先的阻塞条件（login 响应需返回 role）已解决——`authStore.ts` 现已有 `role` 字段（供 `AppHeader`/`AdminMembersView` 使用），实现成本已降为纯前端改动：`KbSidebar.vue`/`DocumentPanel.vue` 的删除按钮加 `v-if="authStore.role === 'OWNER' || authStore.role === 'ADMIN'"` 即可，不再需要后端改动。
- **Depends on / blocked by:** 无（已解除阻塞，可随时实现）。

## ~~mustChangePassword 流程~~（已完成，2026-06-28 落地）

已在 0.2.0 版本实现：`LoginResponse` 返回 `mustChangePassword`，`ChangePasswordView.vue` + 路由守卫已上线（见 CHANGELOG [0.2.0]）。

## 后端安全加固（deferred from /cso 审计 2026-06-28）

以下 5 项安全发现在 /cso 审计中识别。2026-07-14 复核代码：3 项已在后续 RAG Core 重构（PR #4 冻结安全基线）中修复，2 项仍未处理，正式上线前必须完成。

### 已修复（2026-07-14 复核确认）

- ~~S1 — JWT_SECRET 空默认值~~：`JwtService` 已在密钥缺失或短于 32 字节时抛 `IllegalStateException`，启动即失败。
- ~~A01-1 — isBootstrapEndpoint() 路径混淆~~：`JwtAuthFilter.isBootstrapEndpoint()` 已改为 `request.getRequestURI().equals("/api/v1/organizations")` 精确匹配。
- ~~A05-2 — Actuator health 泄露基础设施信息~~：`application.yml` 已设置 `management.endpoint.health.show-details: never`。

### A07-1/A07-2 — login/register 无速率限制 [HIGH/MEDIUM]（仍开放）

- **What:** `POST /auth/login` 和 `POST /auth/register` 完全公开且无请求频率限制，可暴力破解密码、批量注册垃圾账户。
- **Fix:** 引入 Bucket4j + Redis 速率限制（同 IP 5 次/分钟 for login；同邮箱 3 次/小时 for register）。
- **Context:** 实现时参考 `spring-bucket4j` 自动配置或手写 `RateLimitFilter`。

### A09-1 — 认证失败无安全审计日志 [MEDIUM]（仍开放）

- **What:** `JwtAuthFilter.sendError()` 只返回 HTTP 401，无 `log.warn` 记录 IP/路径/原因。攻击者暴力破解/token 重放攻击不留痕迹。
- **Fix:** 在 `sendError()` 前追加 `log.warn("AUTH_FAILURE ip={} path={} reason={}", request.getRemoteAddr(), request.getRequestURI(), message);`
- **File:** `backend/src/main/java/com/diit/ragkb/security/JwtAuthFilter.java`（sendError 方法）

## RAG 检索质量（deferred from 2026-07-13 真实模型联调）

- **What:** 查询侧调用 `embeddingClient.embed()` 时直接传入用户问题原文，未加 BGE 系列模型官方建议的检索指令前缀（如 `为这个句子生成表示以用于检索相关文章：`）。
- **Why:** BGE 是非对称检索模型，只对 query 侧加指令、passage/chunk 侧不加；不加指令召回率会明显下降（不影响跑通，只影响效果）。
- **Fix:** 在 `HybridRetriever.java`（约第 44 行 `embeddingClient.embed(List.of(query))`）调用前，按配置的 embedding 模型族决定是否拼接指令前缀。
- **Context:** 2026-07-13 用真实 Xinference `bge-large-zh-v1.5` + DeepSeek 生成模型联调时发现，当时优先级是先跑通链路，此项留到下一轮检索质量优化。
