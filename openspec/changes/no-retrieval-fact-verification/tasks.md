## 1. Prompt 与生成阶段格式约束

- [x] 1.1 `PromptAssembler.systemPrompt()` 追加格式硬约束：要求先输出一行 `{"found": true|false}` 判断，换行后再输出正文；`found:false` 时不得输出其他内容
- [x] 1.2 补充/更新 `PromptAssemblerTest`，验证新 system prompt 文本包含格式约束说明

## 2. `FactVerificationGate` 核心组件

- [x] 2.1 新增 `backend/src/main/java/com/diit/ragkb/ragcore/generation/FactVerificationGate.java`：包装 `Consumer<QueryEvent>`，内部缓冲首行直到换行符或 200 字符上限
- [x] 2.2 实现 `found:true` 分支：发送延迟的 `SOURCE` 事件（`Citation` 列表），再把换行后剩余内容作为 `CHUNK` 事件转发，之后转入直通模式
- [x] 2.3 实现 `found:false` 分支：丢弃缓冲内容，只发送一条固定文案 `REFUSAL` 事件（"未在当前知识库中检索到该问题的具体答案"），标记 `refusedByFactVerification()` 为 `true`
- [x] 2.4 实现 200 字符 fail-open 分支：无法解析出合法 JSON 时，把已缓冲内容全部当正文透传，正常发送 `SOURCE` + `CHUNK`
- [x] 2.5 编写 `FactVerificationGateTest`：JSON 跨多个 chunk 事件被切开、`found:true` 正常路径、`found:false` 拒答路径、200 字符 fail-open、非法/缺失 JSON fail-open 五个用例

## 3. 审计状态修正

- [x] 3.1 `GenerationMetrics` 新增可空字段 `factVerificationRefusalReason`（默认 `null`），更新构造校验逻辑
- [x] 3.2 `QueryService.stream()` 改造：用 `FactVerificationGate` 包装传给 `answerGenerator.streamWithMetrics()` 的 consumer；判定 `found:false` 时把拒答原因写入返回的 `GenerationMetrics`
- [x] 3.3 `QueryController.query()` 的审计状态判断从 `prepared.refusalReason() == null ? COMPLETED : REFUSED` 改为同时检查 `metrics.factVerificationRefusalReason()`
- [x] 3.4 编写/更新 `QueryServiceTest`：生成阶段拒答场景下 `GenerationMetrics.factVerificationRefusalReason()` 非空；编写/更新 `QueryControllerTest`：该场景下最终记录的审计状态为 `REFUSED`（`QueryController.resolveStatus()` 抽成 package-private 静态方法以便单测，仿照现有 `payload()` 的可测性写法）

## 4. 真实回归验证工具

- [x] 4.1 仿照 `eval/scripts/EvalRetrievalRunner.java` 风格，新增独立 Java 评测工具，直接复用 `HybridRetriever`/`AnswerGenerator` 生产代码（不经 HTTP）
- [x] 4.2 工具跑通 150 题评估集中 8 道 NO_RETRIEVAL 标注题，统计命中拒答的比例（结果：8/8 命中）
- [x] 4.3 从应答题中抽样 20-30 道（覆盖不同难度），统计被误判为拒答的比例（结果：2/25 误伤，根因排查为检索召回缺口而非核验机制过严）
- [x] 4.4 产出实验报告（格式仿照 `eval/reports/refusal-threshold-calibration-20260714.md`），如实记录命中率/误伤率，不确定或效果不佳之处直接写明（`eval/reports/no-retrieval-fact-verification-validation-20260716.md`）

## 5. 验证与收尾

- [x] 5.1 运行完整后端测试套件（`mvn test`），确认无回归
- [x] 5.2 本地启动后端 + 前端，用真实浏览器测试至少一道已知 NO_RETRIEVAL 问题（触发拒答）与一道正常应答问题（确认引用与正文仍正常展示、顺序符合新时序）——真实验证：NO_RETRIEVAL 问题（"异常值噪声生成程序的随机数种子设的多少？"）展示固定拒答文案，正常问题（RPCA 范数约束）展示带 [资料N] 引用标记的正文 + 完整参考来源卡片
- [x] 5.3 检查后端日志/审计表，确认生成阶段拒答的查询审计记录状态为 `REFUSED`——真实日志确认：NO_RETRIEVAL 问题 status=REFUSED（completionTokens=5，只有判断行本身），正常问题 status=COMPLETED
- [x] 5.4 `openspec validate --strict` 通过
