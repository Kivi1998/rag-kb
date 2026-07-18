# 设计文档：LLM Prompt 查询意图识别 + 影响检索策略

日期：2026-07-17

## 背景与动机

`TODOS.md` 早先记录过"查询意图识别"待办，目的是给 RRF 融合做动态权重，但其方法论是保守的
"先归因、有证据、再动手"（先积累错误分析证据，再决定要不要改检索）。

本次用户明确要求跳过归因步骤，采用行业里常见的冷启动路径：**先用 LLM Prompt 粗分类上线**，
线上积累真实 query 之后再训练 BERT 分类器替换（更快、更省成本），并且**这次分类结果要立即影响
检索策略**，不只是被动记录——这是用户对上述保守方法论的一次主动、知情的偏离，在 brainstorming
过程中已向用户显式确认。

## 分类体系

不采用 `eval-set-v2.jsonl` 现成的 6 个类别（api/config/troubleshoot/module/data-structure/
out-of-scope）——那是针对"本科毕设"这一个知识库的**主题类别**，rag-kb 是多租户、知识库内容任意
的系统，主题类别不通用。改用**领域无关、基于查询结构**的四类分类，直接服务于检索策略路由这个
下游目的：

| 分类 | 定义 | 检索侧倾向 |
|---|---|---|
| `precise-lookup`（精确检索型） | 含具体错误码/型号/参数名/专有名词/编号等精确定位信息 | BM25 精确匹配更可靠 |
| `semantic`（语义理解型） | 概念性、宽泛的"是什么/为什么/怎么样" | 向量语义检索更可靠 |
| `comparative`（对比推理型） | 涉及比较多个实体/方法/方案 | 暂不调整（见下） |
| `out-of-scope`（闲聊/超纲型） | 与知识库内容无关，或含糊到无法归类 | 暂不调整（见下） |

## 架构总览

在 `QueryService.prepare()`（`QueryService.java:74-90`）里，指代消解（`orchestrator.prepareContext`，
第79行）之后、检索调用（`retriever.retrieveWithDecision`，第89行）之前，插入一次分类调用：

```
resolvedQuestion（指代消解后）
  → queryIntentClassifier.classify(resolvedQuestion)   [同步 LLM 调用，复用 ChatCompletionClient]
      ├─ PRECISE_LOOKUP → bm25Weight=1.3, vectorWeight=0.7
      ├─ SEMANTIC       → bm25Weight=0.7, vectorWeight=1.3
      ├─ COMPARATIVE    → bm25Weight=1.0, vectorWeight=1.0（仅记录标签，不调权重）
      ├─ OUT_OF_SCOPE   → bm25Weight=1.0, vectorWeight=1.0（仅记录标签，不短路检索）
      └─ UNKNOWN（分类失败/超时/未启用）→ bm25Weight=1.0, vectorWeight=1.0（即现状）
  → retrievalOptions.withWeights(bm25Weight, vectorWeight)
  → retriever.retrieveWithDecision(..., retrievalOptions)
```

**为什么 comparative / out-of-scope 阶段不调整检索行为**：
- comparative 的最佳策略（如拓宽候选池）还没想清楚，本阶段只记录标签，不引入新行为（用户已确认）。
- out-of-scope 如果直接短路跳过检索，会绕开已经用 150 题评估集验证过、拒答 F1=0.564 的
  `MIN_RERANK_SCORE` 阈值机制（`HybridRetriever.java:36`），把拒答决策权完全交给一个尚未经过任何
  验证的新分类器，用户已确认改为仅记录标签，检索和现有拒答阈值照常运行（用户已确认）。

**为什么权重幅度选 1.3x/0.7x 而不是更激进的值**：分类器本身没有经过任何真实准确率验证，用一个温和
的倾斜（而不是硬覆盖）可以让分类器判断错误时的代价可控——这不是拍脑袋定的最优值，只是一个保守的
起点，具体数值放配置项，方便后续用评估集验证后调整（见"验证方案"）。

## 组件设计

### 1. `QueryIntentClassifier` 接口 + `QueryIntent` 枚举

新增包 `backend/.../ragcore/intent/`：

```java
public enum QueryIntent { PRECISE_LOOKUP, SEMANTIC, COMPARATIVE, OUT_OF_SCOPE, UNKNOWN }

public interface QueryIntentClassifier {
    QueryIntent classify(String question);
}
```

`UNKNOWN` 是分类失败的哨兵值（超时/异常/输出不匹配四个合法标签之一），只在内部流转，从不写入
`rag_query_audit`（写入时映射为 `null`）。

### 2. `LlmQueryIntentClassifier`（实现类）

风格参照 `DeepSeekCoreferenceResolver.java`：静态 `SYSTEM_PROMPT` 常量、拼接 `userPrompt`、调用
`chatCompletionClient.complete(system, user)`、内部 try/catch 做 fail-open，从不向调用方抛异常。

**System Prompt**（brainstorming 阶段已与用户确认过文案）：

```
你是一个检索意图分类器。给定用户的一个检索问题，判断它属于以下四类中的哪一类：

- precise-lookup：问题包含具体的错误码、型号、参数名、专有名词、编号等精确定位信息，
  用户在找一个具体、明确存在的东西
- semantic：问题是概念性的、宽泛的"是什么/为什么/怎么样"式提问，没有具体定位信息
- comparative：问题涉及比较两个或以上的实体、方法、方案的异同或优劣
- out-of-scope：问题与文档内容无关（闲聊、问候、与知识库主题无关的话题），
  或者问题含糊到无法归入前三类

只输出上面四个标签中的一个（precise-lookup / semantic / comparative / out-of-scope），
不要输出任何解释、标点、引号或其他文字。

示例：
问题：NullPointerException 怎么排查？
输出：precise-lookup

问题：为什么要用 L1 范数代替 L0 范数？
输出：semantic

问题：RPCA 和 PCA 的区别是什么？
输出：comparative

问题：今天天气怎么样？
输出：out-of-scope
```

**User Prompt**：`"问题：" + resolvedQuestion + "\n输出："`

**解析规则**：`complete()` 返回值 `trim()` 后与四个标签字面量做大小写不敏感的精确匹配；不匹配（空
字符串、带解释文字、幻觉出别的词）一律返回 `UNKNOWN`，并 `log.warn` 记录原始输出（不含问题原文，
避免日志里出现业务内容）方便排查 prompt 是否需要调整。异常（超时/网络错误）同样返回 `UNKNOWN`，
不重试（增加端到端延迟不划算，且这只是辅助优化，参照本次 brainstorming 已确认的 fail-open 决策）。

### 3. `RetrievalOptions` 新增字段

`RetrievalOptions.java` 是 record，现有字段：`candidateLimit, resultLimit, rerank, documentIds,
precomputedQueryVector`。新增两个字段放在**末尾**（保持已有位置的调用点兼容）：

```java
public record RetrievalOptions(int candidateLimit, int resultLimit, boolean rerank, List<UUID> documentIds,
                               List<Float> precomputedQueryVector, double bm25Weight, double vectorWeight) {

    public RetrievalOptions {
        // ...原有校验...
        if (bm25Weight < 0 || vectorWeight < 0) {
            throw new IllegalArgumentException("检索权重不能为负数");
        }
    }

    // 已有的 4 参数 / 3 参数重载构造，追加 this(..., 1.0, 1.0) 委托，保持默认等权重
    // defaults() 同样追加 1.0, 1.0

    public RetrievalOptions withWeights(double bm25Weight, double vectorWeight) {
        return new RetrievalOptions(candidateLimit, resultLimit, rerank, documentIds, precomputedQueryVector,
                bm25Weight, vectorWeight);
    }
}
```

### 4. `RrfFusion` 支持加权

`RrfFusion.fuse(bm25, vector)` → `RrfFusion.fuse(bm25, vector, bm25Weight, vectorWeight)`；
`rankScore` 不变，融合公式从 `rankScore(bm25Rank) + rankScore(vectorRank)` 改为
`bm25Weight * rankScore(bm25Rank) + vectorWeight * rankScore(vectorRank)`。默认值 1.0/1.0
时数学上与现状完全一致（回归安全）。

`HybridRetriever.retrieveWithDecision`（第76行）调用处改为
`RrfFusion.fuse(bm25, vector, options.bm25Weight(), options.vectorWeight())`。

### 5. `QueryService.prepare()` 接入

```java
ObjectProvider<QueryIntentClassifier> intentClassifierProvider; // 新增构造参数，风格同 rerankerProvider

// prepare() 内，resolvedQuestion 确定之后、retrieveWithDecision 调用之前：
QueryIntentClassifier intentClassifier = intentClassifierProvider.getIfAvailable();
QueryIntent intent = intentClassifier != null ? intentClassifier.classify(resolvedQuestion) : QueryIntent.UNKNOWN;
retrievalOptions = applyIntentWeights(retrievalOptions, intent);
```

`applyIntentWeights` 是私有静态映射（switch 表达式），对应"架构总览"表格里的权重值。

### 6. 审计字段（仅标签，不留问题原文）

- `QueryAuditSnapshot`（`ragcore/audit/QueryAuditSnapshot.java`）新增 `String predictedIntent`
  字段（record 末尾追加，nullable）；`from()`/`beforeRetrieval()` 静态工厂追加对应参数。
- `QueryAuditLog`（JPA 实体）新增 `@Column(name = "predicted_intent", length = 32) private String
  predictedIntent;`（无 `nullable=false`，跟 `refusalReason`/`errorCode` 一样天然可空）。
- Flyway 迁移 `V014__add_query_predicted_intent.sql`：
  ```sql
  ALTER TABLE rag_query_audit ADD COLUMN predicted_intent VARCHAR(32);
  ```
- `QueryAuditService.record()` 追加 `entity.setPredictedIntent(snapshot.predictedIntent());`。
- 值域：`precise-lookup`/`semantic`/`comparative`/`out-of-scope`（与 LLM 输出的字面量一致，
  即 `QueryIntent` 枚举到字符串的映射）或 `null`（`UNKNOWN`/未启用）。

**明确不做的事**（brainstorming 阶段已与用户确认，记入 TODOS.md 而非本次范围）：不新建"问题原文 +
标签"的训练数据留存表——`rag_query_audit` 按现有安全约定不能存问题原文，真正积累 BERT 训练集需要
专门设计新表/保留期/脱敏策略，是独立的合规决策。本次上线后只能拿到 `predicted_intent` 的**标签
分布**，拿不到可训练的文本-标签数据集。

### 7. 功能开关

新增 `RagIntentClassificationProperties`（`@ConfigurationProperties(prefix = "rag.intent-
classification")`，字段 `enabled`，默认 `false`，风格参照 `RagNliProperties`）。

新增 `RagIntentClassificationConfiguration`（`@Configuration` + `@ConditionalOnProperty(prefix =
"rag.intent-classification", name = "enabled", havingValue = "true")`），**独立于**
`RagMemoryConfiguration`（现有 `chatCompletionClient` bean 挂在 `rag.memory.enabled` 开关下，
而意图分类在概念上与会话记忆无关，不应该被迫要求先开会话记忆）：

```java
@Bean
public ChatCompletionClient intentClassificationChatCompletionClient(RagModelProperties modelProperties,
                                                                     ObjectMapper objectMapper) {
    return new OpenAiCompatibleChatCompletionClient(modelProperties.getGeneration(), objectMapper);
}

@Bean
public QueryIntentClassifier queryIntentClassifier(
        @Qualifier("intentClassificationChatCompletionClient") ChatCompletionClient client) {
    return new LlmQueryIntentClassifier(client);
}
```

`application.yml` 新增：

```yaml
rag:
  intent-classification:
    enabled: ${RAG_INTENT_CLASSIFICATION_ENABLED:false}
```

**默认关闭**（跟 `rag.nli.enabled` 一致的保守默认）：先合并代码、通过评估集回归验证，确认没有明显
副作用后再决定是否默认打开，这是可以随时关闭的安全阀。

## 代码评审发现与实现调整（2026-07-17）

`/review` 跑完后发现一个真实缺陷、两处设计与实现的偏差，处理方式记录如下：

1. **【已修复】加权 RRF 会误收紧 `MIN_RRF_SCORE` 早退拒答阈值**：`HybridRetriever.MIN_RRF_SCORE
   =0.01` 是按等权重（1.0/1.0）校准的早退检查——两个独立评审 angle 各自算出了同一个缺陷：
   查询意图分类调低某一路权重（如语义型问题 `bm25Weight=0.7`）后，单路命中的候选分数按加权
   分数判断会被提前拒答（精确算出临界点：未加权时 rank≤40 都能通过，加权 0.7 后临界点收紧到
   rank≤10，rank 11 起原本能通过阈值的候选会被误判为"未检索到足够依据"）。修复：早退检查
   固定用未加权分数判断（`unweightedTopScore()`，始终按 1.0/1.0 计算），加权分数只用于候选
   排序/选择，两者解耦。已加回归测试
   `HybridRetrieverTest.intentWeightingDoesNotTightenTheMinRrfScoreRefusalGate`。
2. **【实现方式调整】1.3/0.7 权重值改为命名常量，不做成 application.yml 配置项**：本文档早先
   写"具体数值放配置项"，但读了 `HybridRetriever.MIN_RERANK_SCORE`/`MIN_RRF_SCORE`
   （同类"待验证的检索调优常量"）才发现项目里这类值的既有约定是**命名 Java 常量 + 校准方法
   注释**，不是 yaml 配置项——调整这类数字本身就该走代码评审，不是运维随手改配置。为与既有
   约定一致，改为 `QueryService.PRECISE_LOOKUP_BM25_WEIGHT` 等命名常量（保留详细注释说明未
   验证、如何校准），不新增 `rag.intent-classification.*.weight` 配置项。
3. **【实现方式调整】bean 装配放进 `RagModelConfiguration` 而非本文档原先设想的独立
   `RagIntentClassificationConfiguration`**：`RagModelConfiguration` 本身就是"模型客户端装配"
   的既有归宿，已经承载 embedding/rerank/generation/nli 四个独立开关的 bean，intent
   classification 的两个 bean（`intentClassificationChatCompletionClient`/
   `queryIntentClassifier`）放进去更符合这个文件的既有职责，没有必要为两个 bean 新开一个文件。
4. **【核实为既有模式，不修复】`intentClassificationChatCompletionClient` 只受
   `rag.intent-classification.enabled` 门控，未同时要求 `rag.model.generation.enabled`**：
   若只开意图分类、不配置生成模型端点，启动时会抛 `IllegalArgumentException` 导致应用起不来。
   核实后确认 `RagMemoryConfiguration.chatCompletionClient`（服务会话记忆）早就是同样写法，
   是项目里"配置不全就 fail-fast"的既定模式（`application.yml` 里 `rag.retrieval`/`rag.query`
   的注释也这么写），不是本次改动引入的新问题，不单独修复。
5. **【记入 TODOS.md，不在本次范围】意图分类是同步阻塞 LLM 调用，叠加在指代消解之后**：
   `QueryService.prepare()` 里指代消解（`orchestrator.prepareContext`）和意图分类
   都是同步阻塞的 LLM 调用，且意图分类依赖指代消解后的 `resolvedQuestion`，两者存在真实的
   先后依赖（无法简单并行）。若要优化，需要重构 `ConversationMemoryOrchestrator` 把
   "拿到 resolvedQuestion" 和"算 embedding/画像"两步拆开，让意图分类与 embedding 计算
   重叠——这是比本次功能大得多的改动，记入 TODOS.md，不在本次范围内处理。

## 验证方案

1. 单元测试覆盖分类解析（4个合法标签、非法输出、异常均正确 fail-open）、加权 RRF（默认权重与现状
   数学等价、非默认权重生效）、`QueryService.prepare()` 集成（mock 分类器返回各类值，验证
   `RetrievalOptions` 权重正确传给 retriever）。
2. 真实回归：在 `eval-set-v2.jsonl`（150题）用 `EvalRetrievalRunner` 分别跑"开关关闭"（现状基线，
   已有 Recall@1=0.816/Recall@5=0.904/MRR=0.849/拒答F1=0.564）和"开关打开"两次，对比四项指标，
   确认没有回归（预期改动很小，因为只是温和倾斜）；产出报告
   `eval/reports/intent-classification-retrieval-impact-2026-07-17.md`，如实记录，不夸大效果。
3. 抽查若干条 `predicted_intent` 分类结果做人工 sanity check（没有真实标注的意图 ground truth，
   无法算准确率，只能肉眼看是否离谱）。

## 遗留待办（记入 TODOS.md，不在本次范围）

- **意图分类训练数据留存**：`rag_query_audit` 不能存问题原文，真正积累 BERT 训练集需要专门的新表/
  保留期/脱敏策略，是独立的合规决策。
- **意图分类准确率的系统性评估**：目前没有标注了真实意图类别的评估集，`predicted_intent` 字段本身
  的分类准确率无法量化。
- **comparative 类的检索策略**：本次只记录标签、不调整行为，具体策略（如拓宽候选池）留待后续设计。

## 测试计划

| 测试 | 覆盖点 |
|---|---|
| `LlmQueryIntentClassifierTest` | mock `ChatCompletionClient`：4个合法标签解析正确、大小写不敏感、非法输出→UNKNOWN、异常→UNKNOWN且不抛出 |
| `RrfFusionTest`（扩展现有） | 默认权重 1.0/1.0 与现状数学等价；非默认权重按公式生效 |
| `QueryServiceTest`（扩展现有） | mock `QueryIntentClassifier` 返回各 `QueryIntent` 值，`ArgumentCaptor` 验证传给 `retriever` 的 `RetrievalOptions` 权重字段正确；`QueryIntentClassifier` bean 不可用时行为不变（现状） |
| `QueryAuditServiceTest`（扩展现有） | `predictedIntent` 为 null/非 null 均正确落库 |
| 真实回归（非自动化） | `EvalRetrievalRunner` 开关前后对比报告 |
