# frontend-chat Specification

## Purpose
TBD - created by archiving change frontend-ui. Update Purpose after archive.
## Requirements
### Requirement: 流式问答

用户 SHALL 在问答 Tab 输入问题并提交，系统 MUST 通过 SSE（原生 fetch + ReadableStream）调用 POST /api/v1/knowledge-bases/{kbId}/query 实时流式渲染答案。queryApi.stream() MUST 手动注入 Authorization 和 X-Org-Id 请求头（原生 fetch 不经过 Axios 拦截器）。

SSE 事件格式（Spring SseEmitter 多行）：
```
event: chunk
data: {"content": "..."}

event: source
data: {"documentName": "...", "content": "...", "score": 0.95}

event: done
data: {}

event: error
data: {"message": "..."}
```

#### Scenario: 流式回答渲染

- **WHEN** 用户提交问题
- **THEN** 用户消息追加到对话历史，助手气泡实时渲染 chunk 内容，streaming 状态为 true

#### Scenario: 问答完成

- **WHEN** 收到 done 事件
- **THEN** streaming 变为 false，完整消息（含 sources）归档到 histories[kbId]

#### Scenario: SSE 错误

- **WHEN** 收到 error 事件或 fetch 抛异常
- **THEN** 聊天区插入红色错误气泡，streaming 变为 false

### Requirement: 会话创建与 sessionId 传递

用户切换到某知识库或发起新对话时，前端 SHALL 调用 `POST /api/v1/knowledge-bases/{kbId}/sessions` 创建会话并持有返回的 `sessionId`；后续该对话内的每次 `POST .../query` 请求 SHALL 携带该 `sessionId`。切换知识库 SHALL 视为新对话，重新创建会话。

#### Scenario: 首次提问前创建会话

- **WHEN** 用户在某知识库首次发起提问，当前无已持有的 `sessionId`
- **THEN** 前端先调用创建会话接口获取 `sessionId`，再携带该值发起问答请求

#### Scenario: 同一对话内复用 sessionId

- **WHEN** 用户在同一知识库连续提问多轮
- **THEN** 每轮请求携带同一个 `sessionId`，不重复创建会话

#### Scenario: 切换知识库重新建会话

- **WHEN** 用户从知识库 A 切换到知识库 B
- **THEN** 前端为知识库 B 创建新的 `sessionId`，不复用知识库 A 的会话

### Requirement: 多轮对话历史

`ChatPanel.vue` SHALL 为当前知识库维护一个活跃会话（`sessionId`，创建前允许为空），对话历史 SHALL 通过 localStorage（按 `kbId` 记录最后活跃的 `sessionId`）与后端 `GET .../sessions/{sessionId}/messages` 恢复，而非仅存于组件内存、刷新即重置。切换知识库或页面刷新时，系统 SHALL 优先尝试恢复 localStorage 记录的会话；恢复失败（如该会话已被删除）或没有记录时 SHALL 回到"尚未创建会话"的空白状态，而不得立即调用创建会话接口——真正的会话记录 SHALL 推迟到用户实际发送第一条消息时才创建（懒创建），避免每次挂载/切知识库都在服务端留下从未使用过的空会话。KB 无历史时 SHALL 显示"向知识库提问，开始对话"引导。

#### Scenario: 刷新页面恢复上一次会话

- **WHEN** 用户在某知识库对话后刷新页面（F5）
- **THEN** 系统读取该知识库对应的 localStorage 记录，调用消息查询接口恢复历史消息，用户看到刷新前的完整对话，而非空白的新对话

#### Scenario: 记录的会话已失效时回到空白状态，不提前创建会话

- **WHEN** localStorage 记录的 `sessionId` 对应的会话已被删除或不再属于当前成员（消息查询接口返回 404）
- **THEN** 系统捕获该错误，回到没有 `sessionId` 的空白对话状态并清空历史，但不得在此时调用创建会话接口；用户可以继续提问

#### Scenario: 首次真正发送消息时才创建会话

- **WHEN** 当前没有 `sessionId`（挂载时未恢复到历史会话，或已切到空白新对话状态），用户输入并发送第一条消息
- **THEN** 系统在发送问答请求前先调用创建会话接口取得 `sessionId`，再携带该 `sessionId` 发起问答请求，并写入 localStorage

#### Scenario: 切换知识库时取消进行中请求并重新解析会话

- **WHEN** 用户在 SSE 流式输出进行中时切换知识库
- **THEN** 系统先中止当前请求（`AbortController.abort()`），再按新知识库的 localStorage 记录尝试恢复会话或回到空白状态（不提前创建）

#### Scenario: 无历史时的引导文案

- **WHEN** 当前会话没有任何消息（尚未创建会话的空白状态，或恢复的会话本身为空）
- **THEN** 界面显示"向知识库提问，开始对话"引导文案

### Requirement: 历史会话侧边栏

`ChatPanel.vue` SHALL 内嵌一个默认折叠、可展开的历史会话侧边栏，展开时调用会话列表接口展示当前知识库下已有实际问答内容的历史会话（标题、最后活跃时间，按时间倒序）；用户 SHALL 能点击任一历史项切换为当前会话（恢复其消息历史），SHALL 能删除任一历史项，SHALL 能通过"新建对话"按钮回到空白对话状态。

#### Scenario: 点击历史会话项切换

- **WHEN** 用户在侧边栏点击某个历史会话项
- **THEN** 系统调用消息查询接口拉取该会话的历史消息并替换当前展示内容，更新 localStorage 记录的活跃会话为该项

#### Scenario: 删除当前正在使用的会话

- **WHEN** 用户删除的历史会话项恰好是当前正在使用的会话
- **THEN** 系统回到没有 `sessionId` 的空白对话状态并清空展示内容，不立即创建新会话；真正的新会话推迟到用户下次实际发送消息时才创建

#### Scenario: 新建对话

- **WHEN** 用户点击"新建对话"按钮
- **THEN** 系统回到没有 `sessionId` 的空白对话状态，清空当前展示内容，不立即调用创建会话接口；真正的会话记录推迟到用户实际发送第一条消息时才创建

### Requirement: 引用来源卡片

答案流式完成后，系统 SHALL 收集所有 source 事件，MUST 在答案下方渲染引用来源卡片（SourceCard.vue），展示文档名称、引用片段（截断 200 字）和相似度分数，按 score 降序排列。

#### Scenario: 展示引用来源

- **WHEN** done 事件触发且 sources 数组非空
- **THEN** 答案消息下方渲染每个来源卡片，按 score 降序排列

#### Scenario: 无引用来源

- **WHEN** done 事件触发且 sources 数组为空
- **THEN** 不显示来源区域

