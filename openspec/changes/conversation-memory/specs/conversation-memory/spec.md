## ADDED Requirements

### Requirement: 会话创建与生命周期管理

系统 SHALL 提供 `POST /api/v1/knowledge-bases/{kbId}/sessions` 创建会话，返回 `sessionId`；会话记录归属 `org_id`/`kb_id`/`member_id`，状态在 ACTIVE（30 分钟无新消息前）/IDLE（超过 30 分钟、2 小时内无新消息）/ARCHIVED（超过 2 小时无新消息）之间流转，有新消息时从 IDLE/ARCHIVED 自动续期回 ACTIVE。系统 SHALL 提供 `GET /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}/messages` 查询该会话历史消息。

#### Scenario: 创建新会话

- **WHEN** 已认证成员对某知识库发起创建会话请求
- **THEN** 系统在 Postgres `chat_session` 表新建记录（状态 ACTIVE），返回新生成的 `sessionId`

#### Scenario: 会话因无新消息进入 IDLE

- **WHEN** 某会话最后一条消息时间距今超过 30 分钟且未超过 2 小时
- **THEN** 该会话状态标记为 IDLE，Redis 侧滑动窗口 key 允许自然过期，历史消息仍可从 MongoDB 完整查得

#### Scenario: IDLE 会话收到新消息后续期

- **WHEN** 状态为 IDLE 或 ARCHIVED 的会话收到新的问答请求
- **THEN** 系统将该会话状态续期为 ACTIVE，历史消息正常参与短期记忆检索

#### Scenario: 跨租户访问会话被拒

- **WHEN** 已认证成员请求不属于本组织或非本人创建的 `sessionId`
- **THEN** 系统返回 HTTP 404，不返回任何该会话的消息内容

### Requirement: 短期记忆滑动窗口

系统 SHALL 在检索前从 Redis 按 token 预算（默认 1000 token）取该会话最近的原始消息作为滑动窗口上下文；超出预算时，系统 SHALL 触发摘要压缩（调用 LLM 生成摘要替换最旧的消息），而非直接丢弃；标记为关键事实的消息 SHALL 始终保留原文，不参与摘要压缩。

#### Scenario: 窗口内消息未超预算

- **WHEN** 会话滑动窗口内消息总 token 数未超过预算
- **THEN** 系统直接使用全部窗口内消息作为短期记忆上下文，不触发摘要

#### Scenario: 窗口超出预算触发摘要压缩

- **WHEN** 会话滑动窗口内消息总 token 数超过预算
- **THEN** 系统调用 LLM 将超出部分中最旧的消息压缩成摘要，保留摘要与最近若干轮原文，压缩后的上下文总 token 数不超过预算

#### Scenario: 关键事实消息不被压缩

- **WHEN** 待压缩的消息范围内存在被标记为关键事实的消息
- **THEN** 该消息以原文形式保留，不计入被摘要替换的部分

### Requirement: 短期记忆语义相关历史检索

系统 SHALL 在滑动窗口之外，用当前问题的向量在 Elasticsearch 统一记忆索引中按 `session_id` 过滤检索语义相关的历史消息（不受滑动窗口的时间范围限制）。

#### Scenario: 命中窗口外的语义相关历史

- **WHEN** 当前问题与本会话早于滑动窗口范围的某条历史消息语义高度相关
- **THEN** 该历史消息被检索出来并加入指代消解与生成阶段的上下文，即使它已不在滑动窗口内

#### Scenario: 无语义相关历史

- **WHEN** 本会话没有语义相关的窗口外历史
- **THEN** 语义检索历史部分为空，不影响滑动窗口原文正常参与后续流程

### Requirement: 指代消解

系统 SHALL 在检索知识库之前，若当前会话存在历史消息，调用 LLM 对当前问题做指代消解，将代词/省略补全为独立完整的问题；该调用 MUST 仅解决指代/省略问题，不得改写技术术语、错误码、配置项等专有名词；调用失败或超时时，系统 SHALL 直接使用原始问题继续检索，不得中断问答流程。

#### Scenario: 成功补全指代性问题

- **WHEN** 用户提问"那它过了还能退吗"，历史消息中提及过"重疾险"
- **THEN** 系统将问题补全为"重疾险过了还能退吗"这类独立完整问题用于检索

#### Scenario: 指代消解调用失败降级

- **WHEN** 指代消解的 LLM 调用抛出异常或超时
- **THEN** 系统记录 warning 日志，直接使用用户原始问题继续检索流程，问答正常完成

#### Scenario: 问题不含指代不应被改写

- **WHEN** 用户提问不包含任何代词或省略指代（如直接问"NullPointerException 怎么排查"）
- **THEN** 系统输出的问题在语义上与原始问题一致，技术术语（类名/错误码）不被更改

### Requirement: 长期记忆用户画像提炼

系统 SHALL 在每轮问答生成完成后异步调用 LLM，从本轮问答中提炼候选画像条目（类型为 PREFERENCE 偏好、FACT 事实或 GOAL 长期目标之一）；每条候选条目 SHALL 先与该用户（`member_id` 维度）已有画像条目做语义相似度检索，相似度超过阈值时合并/跳过，否则新增；该异步流程失败 SHALL 不影响已返回给用户的回答。

#### Scenario: 提炼新画像条目

- **WHEN** 某轮问答内容包含可提炼的偏好/事实/长期目标信息，且与该用户已有画像均不相似
- **THEN** 系统新增一条画像条目，写入 MongoDB `memory_items` 与 Elasticsearch 统一记忆索引

#### Scenario: 语义去重跳过重复画像

- **WHEN** 提炼出的候选画像条目与该用户已有某条目语义高度相似
- **THEN** 系统不新增重复条目，跳过或合并

#### Scenario: 画像提炼失败不影响已完成的问答

- **WHEN** 画像提炼的异步 LLM 调用失败
- **THEN** 用户已收到的本轮回答不受影响，系统仅记录日志，不重试整个问答流程

### Requirement: 长期记忆遗忘机制

系统 SHALL 为每条画像条目维护 `importance`（初始重要度）、`accessCount`、`lastAccessedAt`；检索画像条目时 SHALL 按读时计算的 `effective_importance = importance × decay(now - lastAccessedAt)` 排序取 top-K；条目被检索命中并实际用于生成时，SHALL 更新其 `accessCount` 与 `lastAccessedAt`。

#### Scenario: 久未使用的画像条目权重衰减

- **WHEN** 某画像条目自上次被访问已超过较长时间
- **THEN** 该条目的 `effective_importance` 低于近期活跃的同类条目，在 top-K 排序中排名靠后

#### Scenario: 命中画像条目被巩固

- **WHEN** 某画像条目被检索命中并实际注入本轮生成的 System 上下文
- **THEN** 系统更新该条目的 `accessCount+1` 与 `lastAccessedAt` 为当前时间

#### Scenario: 低权重条目不进入结果但不被物理删除

- **WHEN** 某画像条目的 `effective_importance` 低于其他候选条目
- **THEN** 该条目不出现在本次 top-K 结果中，但仍保留在存储中，可在未来重新被访问巩固

### Requirement: 用户画像注入生成阶段

系统 SHALL 将检索到的画像条目组装成一段 System 上下文，与知识库检索结果一并提供给生成模型；画像内容 SHALL 仅影响生成阶段的回答风格与关注点，不得用于调整知识库检索的参数（如候选池大小、过滤条件、RRF 权重）。

#### Scenario: 画像影响回答风格

- **WHEN** 检索到该用户的相关画像条目（如长期在跟进的项目）
- **THEN** 生成阶段的 System 上下文包含该画像信息，但知识库检索的候选集与排序不因此改变

#### Scenario: 无画像条目时正常生成

- **WHEN** 该用户尚无任何画像条目或本轮检索未命中任何画像
- **THEN** 系统不注入画像相关的 System 上下文，问答流程正常完成

### Requirement: 记忆数据的多租户隔离

系统 SHALL 对会话、消息、画像条目的所有读写路径强制校验 `org_id`/`member_id`边界，禁止跨组织或跨成员访问。

#### Scenario: 跨成员画像隔离

- **WHEN** 系统为成员 A 检索画像条目
- **THEN** 检索结果只包含成员 A 自己的画像条目，不包含同组织内其他成员的画像

#### Scenario: 跨组织会话消息隔离

- **WHEN** 已认证成员尝试查询不属于本组织的会话消息
- **THEN** 系统返回 HTTP 404，不泄露该会话是否存在
