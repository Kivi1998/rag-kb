# TODOS

延后但已记录的工作项。每项注明动机、现状与起点,避免日后丢失上下文。

## 文档列表分页(deferred from kb-document-ingest 评审)

- **What:** 给 `GET /api/v1/knowledge-bases/{kbId}/documents` 加分页(Spring Data `Pageable`)。
- **Why:** 当前 `DocumentService.listByKb` 一次返回知识库下全部文档;文档数极大时响应体过大、内存与传输开销高。
- **Pros:** 限制单次返回规模,支撑大知识库;前端可滚动加载。
- **Cons:** 改 Controller/Service 签名与 spec,略扩范围;需定分页参数与默认页大小。
- **Context:** kb-document-ingest 评审(Issue 9)确认本 change 不做,以专注上传摄取闭环。实现时:`DocumentRepository.findByKbIdAndOrgId` 加 `Pageable` 重载,Controller 接 `page/size`,spec 文档列表 requirement 补分页 scenario。
- **Depends on / blocked by:** kb-document-ingest 落地(Document 实体/Repository/Controller 就位)后再做。

## 角色感知删除按钮隐藏(deferred from frontend-ui 评审)

- **What:** 删除 KB / 文档操作需 admin/owner 权限（DocumentService/KnowledgeBaseService 均有校验），但前端目前无角色控制，普通 member 可见删除按钮并点击，收到 403。
- **Why:** MVP 单组织假设下普通 member 数量少，403 有 el-message 提示可接受；引入角色感知需 login 响应返回 role，改动较大。
- **Pros:** 消除无效操作，改善普通 member 体验。
- **Cons:** 需后端 login 响应追加 role 字段，authStore 加 role，删除按钮 v-if 判断。
- **Context:** frontend-ui 评审（Issue 13）确认 MVP 不做，以保持 login 响应改动最小（仅加 orgId）。实现时：authStore 加 role 字段，KbSidebar/DocumentTable 的删除操作 `v-if="authStore.isAdminOrOwner"`。
- **Depends on / blocked by:** frontend-ui 落地后再做。

## mustChangePassword 流程(deferred from frontend-ui 评审)

- **What:** 后端 login 响应返回 `mustChangePassword: boolean`，标记强制改密用户（管理员重置密码后）。前端目前忽略该字段，强制改密用户可直接进入应用。
- **Why:** MVP 单组织 toB 场景，强制改密场景罕见；实现需要独立改密页面和路由守卫。
- **Pros:** 完整的账号安全闭环；防止临时密码长期使用。
- **Cons:** 需新增 /change-password 路由和页面，路由守卫加 mustChangePassword 分支，改密接口。
- **Context:** frontend-ui 评审确认 MVP 不做。实现时：LoginResponse 加 mustChangePassword，authStore 存储，router.beforeEach 检查并跳转 /change-password。
- **Depends on / blocked by:** frontend-ui 落地后再做。
