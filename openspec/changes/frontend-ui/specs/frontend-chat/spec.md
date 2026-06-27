## ADDED Requirements

### Requirement: 流式问答

用户在问答 Tab 输入问题并提交，系统通过 SSE（原生 fetch + ReadableStream）调用 POST /api/v1/knowledge-bases/{kbId}/query，实时流式渲染答案。

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

### Requirement: 多轮对话历史

chatStore 按 kbId 隔离存储对话历史（Record<kbId, Message[]>），切换 KB 时保留各自历史（内存存储，刷新重置）。KB 无历史时显示"向知识库提问，开始对话"引导。

#### Scenario: 切换 KB 历史隔离

- **WHEN** 用户在 KB-A 对话后切换到 KB-B
- **THEN** KB-B 展示自己的历史，KB-A 历史保留在内存

#### Scenario: 切换 KB 时取消进行中请求

- **WHEN** 用户在 SSE 流式输出进行中时切换 KB
- **THEN** AbortController.abort() → 清空 currentAnswer → 更新 selectedKbId，按此顺序执行

### Requirement: 引用来源卡片

答案流式完成后，收集所有 source 事件，在答案下方渲染引用来源卡片（SourceCard.vue），展示文档名称、引用片段和相似度分数。

#### Scenario: 展示引用来源

- **WHEN** done 事件触发且 sources 数组非空
- **THEN** 答案消息下方渲染每个来源卡片，按 score 降序排列

#### Scenario: 无引用来源

- **WHEN** done 事件触发且 sources 数组为空
- **THEN** 不显示来源区域
