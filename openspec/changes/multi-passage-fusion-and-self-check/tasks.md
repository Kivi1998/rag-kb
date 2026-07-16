## 1. 多段融合：低可信片段过滤 + 取舍指令

- [x] 1.1 `HybridRetriever.retrieveWithDecision()`：把原本只检查排名第一片段的阈值判断，重构为对 `selected` 全体元素做同一次过滤（`reranked` 模式下移除 `finalScore() < MIN_RERANK_SCORE` 的每一项，含首位）；过滤后为空则复用原有拒答文案（实现时发现原设计里"先检查首位再单独过滤"会产生一段永远不可达的死代码——首位一旦通过检查，过滤后必然非空——已合并为一次过滤，逻辑等价且更简洁）
- [x] 1.2 `PromptAssembler.systemPrompt()` 追加一句取舍指令：参考资料已按相关性排序，矛盾时优先采信排序更靠前、相关性更高的资料
- [x] 1.3 `HybridRetrieverTest` 补充用例：排名非首位但分数不达标的片段被过滤，只保留达标的片段
- [x] 1.4 `PromptAssemblerTest` 补充用例：system prompt 包含取舍指令关键词

## 2. `AnswerSelfChecker` 核心组件

- [x] 2.1 新增 `backend/src/main/java/com/diit/ragkb/ragcore/generation/AnswerSelfChecker.java`：依赖 `RerankerClient`，输入完整正文 + `List<Citation>`，输出核查结果（`SelfCheckResult`，新增于同包）
- [x] 2.2 实现句子切分：按中文/英文句末标点（。！？\n）切分正文
- [x] 2.3 实现引用提取：正则匹配 `[资料N]`，映射到 `citations.get(N-1)`；一句话可能引用多个编号
- [x] 2.4 实现有引用句子的核查：句子文本为 query，引用的 `Citation.snippet()` 构造成 `RetrievedChunk` 候选，调用 `RerankerClient.rerank()`，`finalScore() < MIN_RERANK_SCORE` 判定为"引用但相关性偏低"
- [x] 2.5 实现无引用句子的核查：句子长度（去除标点）≥ 6 字且不含任何 `[资料N]` 标记，判定为"疑似未标注断言"
- [x] 2.6 Reranker 调用异常时 fail-open：整体核查视为"无问题"，记日志，不抛出
- [x] 2.7 编写 `AnswerSelfCheckerTest`：引用提取+高分不标记、引用+低分标记、无引用长句标记、短过渡句不误判、Reranker 异常 fail-open、全文无问题时返回空结果（含跨 。！？\n 混合标点的综合用例）

## 3. SSE 协议扩展与 `QueryService` 接入

- [x] 3.1 `QueryEventType` 新增 `SELF_CHECK_WARNING`（wireName `self_check_warning`）
- [x] 3.2 `QueryEvent` 新增工厂方法 `selfCheckWarning(String message)`
- [x] 3.3 `QueryController.payload()` 的 switch 补充 `SELF_CHECK_WARNING` 分支（复用 `message` 字段）
- [x] 3.4 `QueryService.stream()`：`gate.flush()` 之后、仅当未被事实核验拒答时，调用 `AnswerSelfChecker` 核查 `answerBuilder` 全文；发现问题拼一条提醒消息并 `eventConsumer.accept(QueryEvent.selfCheckWarning(...))`；不影响 `recordTurn()` 写入的 answer 文本；`QueryService` 新增 `ObjectProvider<RerankerClient>` 构造参数，`RagQueryConfiguration` 与全部既有测试同步更新构造调用
- [x] 3.5 确认 `QueryController` 的审计状态判断（`resolveStatus()`）不需要改动——`self_check_warning` 不是新的审计状态（未改动该方法，仅新增 payload 分支）
- [x] 3.6 `QueryServiceTest` 补充：自检发现问题时推送 `self_check_warning` 事件（无引用长句场景）；自检无问题时不推送该事件（有高分引用支撑场景）

## 4. 前端事件类型与展示

- [x] 4.1 `frontend/src/types/query.ts`：`QueryEventType` 联合类型新增 `'self_check_warning'`，新增 `SelfCheckWarningEventPayload`（`message: string`），`QueryEvent` 联合类型补充对应分支，`Message` 新增 `selfCheckWarning?: string` 字段；更新文件头部注释（改为六类事件）
- [x] 4.2 `frontend/src/api/queryApi.ts`：`toQueryEvent()` 的 switch 补充 `self_check_warning` 分支解析；更新头部与 `openStream` 注释里"五类事件"的表述
- [x] 4.3 `ChatPanel.vue`：`applyEvent()` 补充 `self_check_warning` 分支写入 `message.selfCheckWarning`，模板在参考来源卡片下方渲染 `.self-check-warning` 警示样式提醒块
- [x] 4.4 前端单测：`query.test.ts` 补充 `toQueryEvent` 对 `self_check_warning` 的解析（正常 + 缺字段降级为 error）用例；`ChatPanel.test.ts` 补充收到该事件时渲染提醒块、未收到时不渲染的两个用例；`vue-tsc --build` 类型检查通过

## 5. 真实回归验证与收尾

- [ ] 5.1 运行完整后端测试套件（`mvn test`）与前端测试套件（`pnpm test`），确认无回归
- [x] 5.2 人工构造一批"编造但标了引用"和"正常引用"的对照样本（本次没有先例数据集，改用从真实语料摘取的 3 段真实资料原文 + 人工构造的 6 条测试句子），跑真实 Reranker + `AnswerSelfChecker`，产出报告 `eval/reports/multi-passage-fusion-and-self-check-validation-20260716.md`。**真实结果：4/6 命中预期**——3 条准确复述都正确不标记（分数 0.997-0.999），但 3 条"标了引用但内容对不上"的编造句子只命中 1 条（分数 0.00003 的完全文不对题案例），另外 2 条"部分相关的编造"（分数 0.53/0.15）未被拦住，说明复用 0.06 阈值对这类更隐蔽的编造无效，如实记录、不美化，明确不建议现在就用这 6 个样本去定新阈值
- [ ] 5.3 本地启动后端 + 前端，用真实浏览器测试：至少一次触发低可信片段过滤的检索场景（确认参考来源数量减少）、至少一次能观察自检提醒的场景、至少一次自检无问题的正常场景
- [ ] 5.4 检查后端日志/审计表，确认自检提醒不改变审计状态判断
- [ ] 5.5 `openspec validate --strict` 通过
