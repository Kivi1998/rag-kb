## ADDED Requirements

### Requirement: 会话历史列表查询

系统 SHALL 提供 `GET /api/v1/knowledge-bases/{kbId}/sessions`，返回已认证成员在该知识库下最近活跃、且已发生过至少一轮问答（即已有标题）的会话列表（固定最多 50 条，不分页），按 `lastActiveAt` 倒序排列；每项包含 `sessionId`/`title`/`lastActiveAt`；ACTIVE/IDLE/ARCHIVED 状态的会话一视同仁展示，不做区分或过滤。从未发生过问答的空会话（`title` 为空）不出现在列表结果里，避免前端每次挂载/新建对话产生的占位会话淤积历史列表。

#### Scenario: 返回按最后活跃时间倒序的会话列表

- **WHEN** 已认证成员请求某知识库的会话列表，该知识库下存在多条属于自己、已有实际问答内容的会话
- **THEN** 系统返回这些会话，按 `lastActiveAt` 从新到旧排序

#### Scenario: 从未使用过的空会话不出现在列表里

- **WHEN** 某会话已创建（存在 `chat_session` 记录）但从未收到过任何用户消息，`title` 仍为空
- **THEN** 该会话不出现在会话列表查询结果里，即使它的创建时间/最后活跃时间比其他会话更新

#### Scenario: 跨知识库/跨组织/跨成员列表隔离

- **WHEN** 已认证成员请求某知识库的会话列表
- **THEN** 返回结果只包含该成员自己在该知识库下创建的会话，不包含其他成员、其他知识库或其他组织的会话

### Requirement: 会话标题自动生成

系统 SHALL 在会话的第一轮用户消息写入时，若该会话 `title` 当前为空，截取该消息内容前 30 个字符作为标题写入；后续轮次不再覆盖已有标题。

#### Scenario: 首轮消息生成标题

- **WHEN** 某会话收到第一条用户消息
- **THEN** 系统截取该消息前 30 个字符作为会话标题写入，供列表查询展示

#### Scenario: 已有标题不被覆盖

- **WHEN** 某会话已有标题（非首轮），收到新的用户消息
- **THEN** 会话标题保持不变，不被本轮消息内容覆盖

### Requirement: 会话硬删除

系统 SHALL 提供 `DELETE /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}`，对已认证成员归属的会话执行硬删除：级联清除 Elasticsearch 统一记忆索引中该会话的语义历史条目、MongoDB 长期存档消息、Redis 滑动窗口缓存与 Postgres 会话记录；不属于该成员/该知识库/该组织的会话请求 SHALL 返回 HTTP 404，不泄露该会话是否存在。删除操作 SHALL NOT 影响该成员的长期用户画像（`memory_items`）。

#### Scenario: 成功删除自己的会话

- **WHEN** 已认证成员请求删除自己创建、归属本知识库的会话
- **THEN** 系统级联清除该会话在 Elasticsearch、MongoDB、Redis、Postgres 中的全部数据，返回成功

#### Scenario: 删除他人或跨知识库的会话被拒

- **WHEN** 已认证成员请求删除不属于自己、或不属于当前 URL 路径知识库的会话
- **THEN** 系统返回 HTTP 404，不删除任何数据，不泄露该会话是否存在

#### Scenario: 删除会话不影响用户画像

- **WHEN** 某会话被删除，该成员在其他会话中提炼出的长期画像条目（`memory_items`）已存在
- **THEN** 删除操作完成后，该成员的画像条目不受影响，仍可在后续问答中被检索使用

#### Scenario: 记忆子系统关闭时仅删除会话元数据

- **WHEN** `rag.memory.enabled=false`（Redis/MongoDB/Elasticsearch 记忆子系统未启用）
- **THEN** 删除请求仍成功完成，只清除 Postgres 中的会话记录，不尝试访问未启用的存储
