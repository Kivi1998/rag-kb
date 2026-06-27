## ADDED Requirements

### Requirement: 知识库关联 RAGFlow Chat Assistant

系统 SHALL 在 `knowledge_base` 表中存储 `ragflow_chat_id` 字段，记录该知识库对应的 RAGFlow Chat Assistant ID。该字段 SHALL 在首次发起问答时懒建并写入，之后复用。

#### Scenario: 首次问答写入 ragflow_chat_id

- **WHEN** 知识库 `ragflow_chat_id` 为空时发起首次问答
- **THEN** 系统创建 Chat Assistant 后将 chatId 持久化到 `knowledge_base.ragflow_chat_id`，后续问答直接读取该值

#### Scenario: ragflow_chat_id 不影响已有知识库操作

- **WHEN** 对已有知识库执行 CRUD（创建/更新/删除/列举）操作
- **THEN** `ragflow_chat_id` 字段的存在不改变任何已有行为；删除知识库时 SHALL 一并清理对应 Chat Assistant
