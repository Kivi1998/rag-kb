# Query 理解与改写：当前实现与暂缓项

本文记录 rag-kb 在「Query 理解与改写」环节的当前状态。现已实现多轮对话指代消解、
可选的 LLM 查询意图粗分类，以及由意图驱动的 RRF 权重调整；Query 扩写、重写和 HYDE
仍保持关闭。意图分类默认也关闭，启用前必须完成准确率与收益评估。

## 已实现：指代消解

- **代码**：`DeepSeekCoreferenceResolver`（`backend-py/app/ragcore/memory/deepseek_coreference_resolver.py`），
  由 `ConversationMemoryOrchestrator.prepareContext()` 在检索前调用；
- **行为**：仅当会话存在历史消息时，调 LLM 把当前问题的代词/省略补全为独立完整问题
  （如“那它过了还能退吗”→“重疾险过了还能退吗”）；prompt 明确只做指代消解，不改写
  技术术语、错误码或配置项；调用失败或超时 fail-open，直接用原始问题继续检索；
- 详见[总体架构](architecture.md)决策 5 与多轮对话记忆的设计文档。

## 已实现但默认关闭：查询意图分类与动态 RRF 权重

- **代码**：`QueryIntentClassifier`、`LlmQueryIntentClassifier`、`QueryIntent`（`backend-py/app/ragcore/intent/`），
  由 `QueryService.prepare()` 在指代消解后调用；
- **分类**：`precise-lookup`、`semantic`、`comparative`、`out-of-scope` 四类；模型调用失败或输出
  不可解析时返回 `UNKNOWN`，继续使用默认等权检索，不阻断问答；
- **检索影响**：精确检索型使用 BM25/向量权重 `1.3/0.7`，语义型使用 `0.7/1.3`；对比型、
  超纲型和 `UNKNOWN` 暂时保持 `1.0/1.0`；
- **开关**：`RAG_INTENT_CLASSIFICATION_ENABLED=false`（默认）。当前权重属于未经评估集验证的
  保守起点，不能宣称已提升 Recall 或 MRR；
- **审计与训练数据**：合法分类标签写入 `rag_query_audit.predicted_intent`；训练样本留存由
  `RAG_INTENT_TRAINING_DATA_ENABLED` 独立控制，默认开启，具体数据治理风险见 `TODOS.md`。

## 保持关闭：Query 重写

`QueryRequest.rewrite` 字段是预留空壳，首期固定关闭。本项目高价值查询经常包含
`NullPointerException`、配置 key 等必须逐字精确的 token，LLM 润色可能破坏精确匹配；
BM25 已对 `symbol_names`、`config_keys`、`error_codes` 等字段提高权重。

## 仍保持关闭

| 方向 | 当前结论 | 启动条件 |
|---|---|---|
| Query 扩写（同义词多路检索） | bge-m3 向量腿已覆盖大量同义表达，剩余收益主要集中在领域黑话 | 对 v2 评估集 Recall@5 失败题做错误归因，确认存在同义词错配 |
| HYDE（假设文档检索） | 可能改善短查询或黑话查询，但每次查询增加一次 LLM 调用 | 先按短查询/长查询分析 Recall 差异，再评估收益与延迟 |

这些暂缓项继续遵循：先归因、有证据、再动手。意图分类虽然已经实现，但因为增加一次同步
LLM 调用且权重未经真实评估，仍应保持默认关闭，不能把“代码存在”写成“生产效果已验证”。

## 相关文档

| 文档 | 内容 |
|---|---|
| `TODOS.md` | 扩写/HYDE 暂缓理由、意图分类实现状态、训练数据治理与待评估项 |
| [总体架构](architecture.md) 决策 3/5 | 技术标识优先精确召回、指代消解所在的记忆子系统 |
| [混合检索指南](混合检索指南.md) | 下游混合检索、动态权重与 Milvus Provider |
