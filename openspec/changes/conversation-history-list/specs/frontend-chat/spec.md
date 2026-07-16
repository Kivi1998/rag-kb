## MODIFIED Requirements

### Requirement: 多轮对话历史

`ChatPanel.vue` SHALL 为当前知识库维护一个活跃会话（`sessionId`），对话历史 SHALL 通过 localStorage（按 `kbId` 记录最后活跃的 `sessionId`）与后端 `GET .../sessions/{sessionId}/messages` 恢复，而非仅存于组件内存、刷新即重置。切换知识库或页面刷新时，系统 SHALL 优先尝试恢复 localStorage 记录的会话；恢复失败（如该会话已被删除）SHALL 退回创建新会话。KB 无历史时 SHALL 显示"向知识库提问，开始对话"引导。

#### Scenario: 刷新页面恢复上一次会话

- **WHEN** 用户在某知识库对话后刷新页面（F5）
- **THEN** 系统读取该知识库对应的 localStorage 记录，调用消息查询接口恢复历史消息，用户看到刷新前的完整对话，而非空白的新对话

#### Scenario: 记录的会话已失效时退回新建

- **WHEN** localStorage 记录的 `sessionId` 对应的会话已被删除或不再属于当前成员（消息查询接口返回 404）
- **THEN** 系统捕获该错误，创建一个新会话并清空对话历史，不阻断用户继续提问

#### Scenario: 切换知识库时取消进行中请求并重新解析会话

- **WHEN** 用户在 SSE 流式输出进行中时切换知识库
- **THEN** 系统先中止当前请求（`AbortController.abort()`），再按新知识库的 localStorage 记录尝试恢复或新建会话

#### Scenario: 无历史时的引导文案

- **WHEN** 当前会话没有任何消息（新建会话，或恢复的会话本身为空）
- **THEN** 界面显示"向知识库提问，开始对话"引导文案

## ADDED Requirements

### Requirement: 历史会话侧边栏

`ChatPanel.vue` SHALL 内嵌一个默认折叠、可展开的历史会话侧边栏，展开时调用会话列表接口展示当前知识库下的历史会话（标题、最后活跃时间，按时间倒序）；用户 SHALL 能点击任一历史项切换为当前会话（恢复其消息历史），SHALL 能删除任一历史项，SHALL 能通过"新建对话"按钮开始一个全新会话。

#### Scenario: 点击历史会话项切换

- **WHEN** 用户在侧边栏点击某个历史会话项
- **THEN** 系统调用消息查询接口拉取该会话的历史消息并替换当前展示内容，更新 localStorage 记录的活跃会话为该项

#### Scenario: 删除当前正在使用的会话

- **WHEN** 用户删除的历史会话项恰好是当前正在使用的会话
- **THEN** 系统删除成功后自动创建一个新会话并清空展示内容，不留在已删除的会话状态里

#### Scenario: 新建对话

- **WHEN** 用户点击"新建对话"按钮
- **THEN** 系统创建新会话、清空当前展示内容，并更新 localStorage 记录
