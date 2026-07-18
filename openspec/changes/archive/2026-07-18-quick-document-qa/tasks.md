## 1. 配置与 Redis 装配

- [x] 1.1 新增 `RagQuickDocumentProperties`（`@ConfigurationProperties(prefix = "rag.quick-document")`，字段
      `enabled`（默认 `true`）、`redisDatabase`（默认 `2`）、`ttlHours`（默认 `2`）、
      `maxTotalCharacters`（默认 `15000`））
- [x] 1.2 `application.yml` 新增 `rag.quick-document.*` 配置块，注释说明用途、默认值来源（对齐
      `RagMemoryProperties.sessionIdleHours`）
- [x] 1.3 新增独立 Redis 连接工厂/`StringRedisTemplate` bean（`quickDocumentRedisConnectionFactory`/
      `quickDocumentRedisTemplate`，仿照 `RagMemoryConfiguration` 的 `memoryRedisConnectionFactory`
      写法，指向 DB 2），`@ConditionalOnProperty(prefix = "rag.quick-document", name = "enabled",
      havingValue = "true")`，不耦合 `rag.memory.enabled`

## 2. 领域模型与存取层

- [x] 2.1 新增 `QuickDocument`（Java record：`docId`/`sessionId`/`filename`/`content`/
      `characterCount`/`createdAt`），JSON 序列化用现有 `ObjectMapper`
- [x] 2.2 新增 `QuickDocumentStore`：`save(sessionId, doc)`/`findAllBySession(sessionId)`/
      `delete(sessionId, docId)`/`touch(sessionId, docIds)`（续期）——内部实现 Redis key 结构
      （`quickdoc:content:{docId}` + `quickdoc:session-index:{sessionId}` Set），读取时对 Set
      成员做 MGET 自愈清理已过期的 docId 引用
- [x] 2.3 `findAllBySession`/额度检查逻辑：累加会话内全部未过期文档的 `characterCount`，供上传接口
      判断是否超过 `maxTotalCharacters`

## 3. 解析与额度校验服务

- [x] 3.1 新增 `QuickDocumentService.upload(sessionId, orgId, kbId, memberId, multipartFile)`：
      包装成 `DocumentInput` 调用 `DocumentParserFactory.parse()`（复用现成方法，不新写解析逻辑），
      `ParsedDocument.sections()` 拼接成纯文本
- [x] 3.2 额度校验：拼接后字符数 + 该会话已用字符数 > `maxTotalCharacters` 时抛出明确异常
      （映射为 HTTP 400），不写入 Redis
- [x] 3.3 不支持的格式（`DocumentParserFactory` 抛出解析失败）映射为 HTTP 400 明确错误信息
- [x] 3.4 `QuickDocumentService.list(sessionId)`/`delete(sessionId, docId)` 直接委托 `QuickDocumentStore`

## 4. Controller 端点

- [x] 4.1 新增 `QuickDocumentController`：`POST/GET/DELETE
      /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}/quick-documents[/{docId}]`
- [x] 4.2 每个端点先校验 `sessionId` 归属当前认证成员的组织与 `kbId`（复用
      `ChatSessionService.touchSession` 或等价校验逻辑，越权/不存在 → 404）
- [x] 4.3 上传接口返回 `{docId, filename, characterCount}`；超额度/格式不支持返回结构化错误

## 5. 接入检索/生成链路

- [x] 5.1 `QueryService` 新增 `QuickDocumentService`（或其 Store 接口）依赖，`prepare()` 里
      `retriever.retrieveWithDecision(...)` 之后取该 session 的临时文档，包装成合成
      `RetrievedChunk`（`finalScore` 固定高值排在检索结果前面，`bm25Rank`/`vectorRank`/
      `rrfScore`/`rerankScore` 均为 null，`metadata` 打 `quickDocument=true`）
- [x] 5.2 拒答分支改造：`result.refused() && quickDocChunks.isEmpty()` 时才真正拒答；否则用
      `quickDocChunks +（result.refused() ? 空 : result.chunks()）` 继续走生成流程
- [x] 5.3 `documentNames` Map 拼接：把临时文档的 `docId → filename` 一并塞进传给
      `CitationBuilder.build()` 的 Map（`CitationBuilder` 本身不改）
- [x] 5.4 命中的临时文档触发 `QuickDocumentStore.touch()` 续期 TTL（只续期本轮实际用到的文档）

## 6. 前端

- [x] 6.1 `ChatPanel.vue` 新增"临时文档"入口（新组件 `QuickDocumentPanel.vue`）：已挂文档小
      列表（文件名+字符数）、上传按钮、删除按钮，展示"已用 X/15000 字符"
- [x] 6.2 上传交互：文件选择（未做拖拽，本次只做点击选择，够用且改动更小），上传中按钮转圈
      禁用，同步等待接口返回，失败由 `http.ts` 拦截器统一弹出后端返回的错误信息（超额度/
      格式不支持）
- [x] 6.3（范围调整）实现时发现给引用加"临时文档"视觉标签需要给 `Citation` record 加新字段，
      贯穿 `CitationBuilder`/4 个测试文件/MongoDB 历史消息持久化/前端类型，改动面明显大于
      这个纯 UI 细节本身的价值，决定不做——引用抽屉照常显示上传时的文件名，用户能自行分辨，
      记入 TODOS.md「引用来源的临时文档视觉标签未实现」

## 7. 测试

- [x] 7.1 `QuickDocumentServiceTest`：正常上传、超额度拒绝、格式不支持、多文档共享额度池
- [x] 7.2 `QuickDocumentStoreTest`：TTL 过期后不出现在 `findAllBySession`、`touch()` 续期生效、
      Set 自愈清理已过期 docId 引用
- [x] 7.3 `QueryServiceTest` 扩展：会话挂临时文档时检索拒答被绕过、无临时文档时行为不变
      （回归）、临时文档 chunk 正确拼进 `contexts`/citations
- [x] 7.4 安全测试：跨会话/跨组织访问临时文档 CRUD 端点返回 404，不泄露内容
- [x] 7.5 回归：现有 `QueryServiceTest`/`QueryControllerTest`/`ChatSessionServiceTest` 全部通过

## 8. 收尾

- [x] 8.1 更新 `docs/检索与审计验收.md` 或新增小节说明这个能力的验收步骤
- [x] 8.2 更新 `TODOS.md`/`CHANGELOG.md`
- [x] 8.3 `/review` 代码评审，修复所有 CRITICAL/HIGH 发现
- [x] 8.4 提交 PR，合并后用 `openspec-archive-change` 归档本 change 并同步 delta specs
