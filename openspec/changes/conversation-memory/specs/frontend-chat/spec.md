## ADDED Requirements

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
