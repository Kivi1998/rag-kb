# quick-document-qa Specification

## Purpose

单文档直接问答（长上下文直接塞入模式）：会话内可上传临时文档，不写入知识库、不切块不索引，
直接把解析出的全文拼进 LLM 上下文，与知识库检索结果一起参与回答。参考同类项目 rag系统2 的
`quick_parse` 实现思路，重新校准了大小限制（deepseek-chat 128K 上下文窗口，而非原本的 4000
字符），详见 `openspec/changes/archive/2026-07-18-quick-document-qa/design.md`。

## Requirements

### Requirement: 会话内上传临时文档
系统 SHALL 提供 `POST /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}/quick-documents` 接口，同步解析上传文件（复用 `DocumentParserFactory`，含 OCR/ASR 网关自动降级），解析结果计入该会话的字符额度池；若加入后总字符数超过 `rag.quick-document.max-total-characters`（默认 15000），拒绝本次上传且不写入任何数据。

#### Scenario: 正常上传
- **WHEN** 已认证成员对自己有权访问的会话上传一个受支持格式的文件，加入后会话总字符数未超过额度池上限
- **THEN** 系统同步返回 HTTP 200 与 `{docId, filename, characterCount}`，该临时文档立即对后续同会话的问答可见

#### Scenario: 超过额度池拒绝上传
- **WHEN** 解析后的字符数加上会话已用字符数超过 `rag.quick-document.max-total-characters`
- **THEN** 系统返回 HTTP 400 与明确错误信息，不写入 Redis，不影响会话已有的临时文档

#### Scenario: 跨租户/越权会话拒绝上传
- **WHEN** 请求的 `sessionId` 不属于当前认证成员所在组织，或不属于路径中的 `kbId`
- **THEN** 系统返回 HTTP 404，不执行解析，不产生任何 Redis 写入

#### Scenario: 不受支持格式
- **WHEN** 上传文件的格式不被 `DocumentParserFactory` 任何解析器支持
- **THEN** 系统返回 HTTP 400 与明确错误信息，不写入任何数据

### Requirement: 查询与删除会话内临时文档
系统 SHALL 提供 `GET .../quick-documents` 列出当前会话已挂的临时文档（含文件名、字符数），SHALL 提供 `DELETE .../quick-documents/{docId}` 删除指定临时文档并释放其占用的额度池空间；查询/删除操作 SHALL 只做归属校验，不得触发会话活跃状态的续期（避免只读请求悄悄改变会话的 ACTIVE/IDLE/ARCHIVED 状态机）。

#### Scenario: 列出当前会话临时文档
- **WHEN** 已认证成员查询自己有权访问的会话
- **THEN** 系统返回该会话当前未过期的全部临时文档列表及各自字符数，已过期（TTL 到期）的文档不出现在列表中，且该次查询不改变会话的 `lastActiveAt`/状态

#### Scenario: 删除临时文档释放额度
- **WHEN** 已认证成员删除会话内一个已存在的临时文档
- **THEN** 该文档立即从 Redis 移除，后续上传检查额度时不再计入其字符数

#### Scenario: 跨租户/越权会话拒绝查询或删除
- **WHEN** 请求的 `sessionId` 不属于当前认证成员所在组织，或不属于路径中的 `kbId`
- **THEN** 系统返回 HTTP 404，不返回或删除任何临时文档数据

### Requirement: 临时文档参与问答生成
系统 SHALL 在 `QueryService.prepare()` 检索完成后，把当前会话未过期的临时文档内容包装为合成检索结果，与知识库检索结果一并用于生成回答与引用来源；临时文档不写入知识库、不参与切块/向量化/ES 索引。查询审计记录 SHALL 反映实际发生的最终结果（是否真的拒答、实际参与回答的上下文），不得停留在知识库检索本身的中间结果。

#### Scenario: 临时文档内容参与生成
- **WHEN** 会话挂有未过期的临时文档，成员发起问答
- **THEN** 生成的回答可以引用临时文档内容，对应引用来源的文档名为上传时的文件名（不是知识库文档名）

#### Scenario: 会话活跃时临时文档续期
- **WHEN** 某次问答实际引用到了会话内的某个临时文档
- **THEN** 该临时文档在 Redis 中的 TTL 重置为 `rag.quick-document.ttl-hours`（默认 2 小时）

#### Scenario: 临时文档过期后不再参与生成
- **WHEN** 某临时文档的 TTL 已到期
- **THEN** 后续问答不再包含该文档内容，`GET .../quick-documents` 也不再返回它

#### Scenario: 跨会话隔离
- **WHEN** 某会话挂了临时文档，另一个会话（即使属于同一成员、同一知识库）发起问答
- **THEN** 另一个会话的回答不得引用前者挂的临时文档内容

#### Scenario: 拒答豁免场景下审计记录与实际结果一致
- **WHEN** 知识库检索本身触发拒答阈值，但会话挂有临时文档使得本轮问答实际完成（未拒答）
- **THEN** 该轮查询审计记录（`rag_query_audit`）SHALL 标记为未拒答，不得保留知识库检索阶段的原始拒答原因；审计记录的 chunk/文档标识 SHALL 反映实际参与回答的完整上下文（含临时文档），不得只反映知识库检索的（可能为空的）结果
