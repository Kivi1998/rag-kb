# TODOS

延后但已记录的工作项。每项注明动机、现状与起点,避免日后丢失上下文。

## Milvus 向量检索迁移——观察期验收项未做(2026-07-18)

- **What:** `openspec/changes/archive/2026-07-18-migrate-vector-retrieval-to-milvus/tasks.md` 第 7、8 节未完成：①历史回填检查点表/Flyway 迁移、ES 向量分页读取与模型/维度/切块版本兼容性判断、Milvus 批量回填断点续跑、总数/租户分布/孤儿 ID/抽样向量一致性校验报告；②真实 ES+Milvus 环境全链路集成测试、跨组织/跨知识库/伪造 ID/删除残留安全验收、150 题 ES/Milvus 对比评测（确认 Recall@1/5、MRR、拒答指标不低于已签字基线）、目标并发压测（P50/P95/P99、吞吐、内存、磁盘、单位查询成本）。
- **Why:** 这两节都依赖真实部署的 Milvus/ES 实例和真实负载，本机开发环境跑不出有意义的数字；`design.md` 的 Migration Plan 本身就是分阶段推进（先双写校验、再影子比较、达标后才灰度切流），第 7-8 节是"影子验证通过后"才需要做的观察期工作，不是合并 PR #29 的前置条件。
- **现状:** 当前默认配置 `rag.vector.provider=elasticsearch`（纯 ES 模式），Milvus 双写基础设施已合并但未在生产启用；`mvn test` 288/288（含新修复的可见性翻页回归测试）通过，属单测/集成假数据覆盖，不含真实 Milvus 实例。
- **Pros:** 分阶段推进降低了单次变更的风险面，先把端口拆分、双写协议、租户过滤这些结构性工作合入主干，验收项可以独立排期不阻塞其他开发。
- **Cons:** 在真正跑通第 7-8 节之前，`shadow`/`milvus` 模式的实际召回质量和性能表现都是未知数，不能凭这次合并就认为"Milvus 已经可以在生产用"。
- **Depends on / blocked by:** 需要目标环境的 Milvus 部署（Standalone 还是集群待压测后定）和真实负载/125 题评测集跑通，之后再开独立 change 推进。

## P95/P99/QPS 监控与压测缺口(2026-07-17 讨论记录)

- **What:** `rag_query_audit` 表（`QueryAuditLog`）已经在记录每次查询的 `retrieval_latency_ms`/`generation_latency_ms`/`total_latency_ms`/`status`/`created_at`，但目前是"只写不读"——没有任何代码/接口把这些数据算成 P95/P99 延迟或 QPS 展示出来；Prometheus/Actuator 只暴露了 Spring 默认的 `http.server.requests`（笼统的 HTTP 层耗时，不区分检索/生成阶段）和摄取相关指标（`IngestionMetrics`），没有查询侧的自定义指标。
- **Why:** `docs/自研RAG核心重构架构设计.md` §2.3 定了试点验收线（检索阶段 P95 ≤ 2 秒、端到端 P95 ≤ 10 秒），但从未系统验证过是否达标。
- **已做的临时测量（不是压测，仅一次性观测）**：直接对 `rag_query_audit` 表跑 SQL（Postgres 原生 `percentile_cont`）算出来的：
  ```sql
  SELECT count(*) AS sample_count,
         percentile_cont(0.50) WITHIN GROUP (ORDER BY total_latency_ms) AS p50_ms,
         percentile_cont(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_ms,
         percentile_cont(0.99) WITHIN GROUP (ORDER BY total_latency_ms) AS p99_ms
  FROM rag_query_audit WHERE status = 'COMPLETED';
  -- 按分钟统计请求数，粗略估算观测到的峰值 QPS（不是压测出的容量上限）
  SELECT date_trunc('minute', created_at) AS minute_bucket, count(*)
  FROM rag_query_audit GROUP BY minute_bucket ORDER BY minute_bucket DESC;
  ```
  2026-07-17 跑出的结果（46 条 `COMPLETED` 样本，2026-07-13～07-17 本机手动测试流量）：
  端到端 P50=7354ms/**P95=10809ms**（略超 10 秒目标）/P99=11723ms；检索阶段
  P95=6211ms（明显超 2 秒目标）；观测峰值 2 请求/分钟。**样本量小、流量非真实生产
  分布，不能当作"检索阶段不达标"的结论**，只是记录了可复现的测量方法，详见
  `docs/自研RAG核心重构架构设计.md` §2.3 后的观测记录。
  - **踩坑记录**：本机 `psql` 命令行工具在当前环境里对这个数据库会直接挂起（无论
    `-h localhost`、`127.0.0.1` 还是走 Unix socket 默认连接都一样，`pg_hba.conf`
    确认是 `trust` 认证、不需要密码，`nc` 测试 TCP 连接本身正常），原因未查明；
    绕过方法是用 `~/.m2/repository/org/postgresql/postgresql/<version>/postgresql-<version>.jar`
    直接写一个几行的 JDBC 小程序连接查询，不依赖 psql 命令行。
- **Pros:** 补齐后能持续监控是否达标，而不是只在需要时手动查一次库。
- **Cons:** 真正的产品级方案（自定义 Micrometer 指标 + Prometheus + Grafana 仪表盘）需要新写一个类似 `IngestionMetrics.java` 的 `QueryMetrics` 类，有设计和实现成本；且"系统最大承载 QPS"这个数字必须靠专门压测（不断加压直到延迟劣化/报错率上升）才能测出来，现在项目里没有任何压测配置（无 JMeter/k6/gatling/wrk），真实生产流量到来前也没有意义。
- **Context:** 用户问"怎么拿到 P95/P99/QPS"，探索确认现状后跑的这次一次性观测。
- **Depends on / blocked by:** 无硬阻塞。分两步走都可以：①先在 `QueryAuditLogRepository` 加几个原生 SQL 统计方法 + 一个只读的管理端点，把上面这段 SQL 变成随时可查的接口（成本低）；②如果需要真正的容量规划，再补 Micrometer 指标 + 压测（成本高，且必须等真实流量或专门排期压测）。

## 知识库右键菜单的可访问性缺口(deferred from /review，2026-07-17)

- **What:** 知识库列表的重命名/删除/查看技术文档操作目前完全依赖右键单击（`el-dropdown trigger="contextmenu"`），没有任何持久可见的按钮/图标提示这些操作存在。
- **Why:** 触屏设备（平板/触屏笔记本）通常没有可靠的 `contextmenu` 事件触发方式（多数移动浏览器只在长按后触发、行为不一致，还可能被系统级文本选择菜单抢先）；纯键盘用户也没有 Tab 聚焦 + 键盘触发菜单的路径。这是用户明确要求的设计（"重命名删除等操作集成到右键单击中"），当时权衡后接受，但代价值得记录。
- **Pros:** 修复后触屏/键盘用户也能使用这些操作，覆盖面更完整。
- **Cons:** 需要额外的可见入口（如常驻的"⋯"按钮，左键点击也能打开同一个下拉菜单）和/或键盘事件处理，与当前"完全靠右键"的简洁设计有取舍。
- **Context:** `code-review` 在 2026-07-17 对 `KbSidebar.vue` 的评审里独立从多个角度（removed-behavior、altitude）反复命中同一个发现，判定为真实、非误报。
- **Depends on / blocked by:** 无，随时可做；建议给 `.kb-item` 加一个 hover 时才显示的"⋯"图标按钮，左键点击复用同一个 `el-dropdown` 的 `#dropdown` 插槽（不新增右键以外的第二套菜单逻辑）。

## MongoDB 引用持久化缺自动化回归测试(deferred from /review，2026-07-17)

- **What:** `ChatMessageDocument` 新增的 `citations: List<Citation>` 字段（`Citation` 是带 `UUID`/`List<String>`/`Integer`/`Double` 字段的 Java record）是这个代码库第一次让 Spring Data MongoDB 把 record 作为嵌套文档字段持久化，目前没有任何自动化测试验证 write→read 往返是否正确。
- **Why:** 已用真实浏览器 + 真实运行中的后端 + 真实 MongoDB 手工验证过（新会话生成带引用的回答→刷新页面恢复历史→`citCount` 与生成时一致→点击 `[N]` 正确弹出抽屉），当前确认可用；但没有 CI 会跑到的自动化测试守护这条路径，如果未来升级 Spring Data MongoDB 版本或改动 `Citation` record 结构，可能悄悄破坏且不会被发现。
- **Pros:** 补一个针对 `ChatMessageDocument` 的持久化回归测试，能在 CI 里长期守护这条路径。
- **Cons:** 这个代码库目前没有任何 MongoDB 集成测试基础设施（现有 `RedisMongoConversationStoreTest` 全部走 Mockito mock，不连真实 MongoDB），补齐需要引入 Testcontainers 或类似方案，工作量不小。
- **Context:** `code-review` 在 2026-07-17 对历史引用持久化改动的评审中命中，判定为 CONFIRMED（真实存在的测试缺口，不是误报）。
- **Depends on / blocked by:** 无硬阻塞；可以先补一个不需要真实 MongoDB 的轻量单测（直接用 Spring 的 `MappingMongoConverter` 在内存里转换 `ChatMessageDocument` 到 `org.bson.Document` 再转回来，断言 `citations` 往返一致），作为比 Testcontainers 更低成本的中间方案。

## 引用文档被删除后历史记录不会提示(deferred from /review，2026-07-17)

- **What:** `Citation.documentName` 是生成时的一次性快照，持久化进 `ChatMessageDocument` 后永远不会重新校验。如果某个被引用的文档后续从知识库里删除，历史会话恢复后引用抽屉仍然显示这个文档名，就像它还存在一样，没有"该文档已被删除"的提示。
- **Why:** `CitationBuilder` 目前只在生成当时处理"文档已不存在"的情况（用兜底字符串替换），这个安全网不会追溯应用到已经持久化的历史 citation 上。
- **Pros:** 修复后用户能清楚知道某条历史引用指向的文档是否还能访问，避免误以为陈旧/已撤回的信息仍然有效。
- **Cons:** 需要在渲染历史引用抽屉时按 `documentId` 实时查一次知识库当前文档列表（额外查询成本），或者在文档删除时反向扫描/标记所有引用过它的历史消息（写放大）。
- **Context:** `code-review` 在 2026-07-17 对历史引用持久化改动的评审中命中（altitude 角度），判定为真实的产品边界问题，非误报。
- **Depends on / blocked by:** 无硬阻塞；优先级不高，仅在合规/审计场景（需要明确知道"这条引用来源现在还在不在"）下才比较关键。

## RRF 融合动态权重（2026-07-17 已实现，见下方"查询意图识别"条目）

~~原"RRF 融合动态权重"待办~~：`RrfFusion.fuse()`/`RetrievalOptions` 已支持 `bm25Weight`/
`vectorWeight` 参数（默认各 1.0，即原始等权行为不变），由查询意图分类结果驱动，见下一条
"查询意图识别"的实现记录。**用户明确决定跳过本条目原先建议的"先分类误差分析拿证据再动手"
步骤**，权重值（1.3x/0.7x）目前是未经评估集验证的保守起点，见设计文档
`docs/superpowers/specs/2026-07-17-llm-intent-classification-retrieval-design.md`。

## Query 扩写与重写(deferred，2026-07-15 讨论记录)

- **What:** 检索前对用户 query 做处理：**扩写**=给问题加同义词/相关词后多路一起检索（求"全"，提召回）；**重写**=把口语化问题改写成贴近知识库表达的规范问法（求"准"，提精度）。当前两者都没有：多轮场景只做窄范围指代消解，随后直接用 `resolvedQuestion` 跑 BM25+embedding；意图分类只调整融合权重，不改写问题文本。`QueryRequest.rewrite` 字段是预留空壳且注释明确"首期固定关闭"。
- **Why:** 扩写解决"文档写'索赔'、用户问'理赔'搜不到"的词汇错配；但我们是混合检索，bge-m3 向量腿天然覆盖大部分同义词漂移，剩余收益主要在向量模型没学过的领域黑话/内部术语。重写在技术文档场景风险大于收益：高价值查询恰是 `NullPointerException`、配置 key 这类必须逐字精确的 token（BM25 已给 `symbol_names`/`config_keys`/`error_codes` 加 7-8 倍权重），LLM"润色"可能把精确匹配改没。
- **Pros:** 扩写若命中领域黑话场景可直接提升召回，且纯词典方案零 LLM 调用、零延迟成本。
- **Cons:** 需要自建技术领域同义词表（数据工作）；无证据前属预防性堆功能。
- **Context:** 2026-07-15 结合外部学习材料与 rag系统1/rag系统2 对比讨论。两个旧项目都有扩写但均来自 RAGFlow（rag系统2 直接复制了 `FulltextQueryer`：同义词词典降权拼进查询 + 正则清洗疑问虚词；rag系统1 调 RAGFlow API 且 `keyword=true`）。**结论：现在不加**——基线 Recall@5=0.904，应先对 eval-set-v2 上约 12 道 Recall@5 失败题做错误归因，确认失败原因确实是同义词错配再动手。实现方式必须自研（CLAUDE.md 禁止复制 RAGFlow 代码）：自建小型同义词表，在 `ElasticsearchLexicalCandidateSource.search()` 的 should 子句里增加降权同义词匹配。重写维持关闭，理由已写在 `QueryController.QueryRequest` 注释里。
- **Depends on / blocked by:** 前置步骤是失败题错误归因（评估集与脚本已就绪，随时可跑）。

## 查询意图识别（2026-07-17 已实现 LLM Prompt 粗分类 + 影响检索策略）

- **已实现**：`ragcore/intent/` 新增 `QueryIntentClassifier`/`LlmQueryIntentClassifier`（复用
  `ChatCompletionClient` 做一次同步 LLM 分类调用），分类体系改用**领域无关、基于查询结构**的
  四类（精确检索型/语义理解型/对比推理型/闲聊超纲型），而非本条目原先设想的技术文档主题类别
  （API/故障排查/配置说明）——原因：`eval-set-v2` 的 6 个主题类别是针对单一知识库内容定制的，
  rag-kb 是多租户、知识库内容任意的系统，主题类别不通用，改按查询结构分类才能跨知识库复用。
  精确检索型/语义理解型分类结果实时调整 `RrfFusion` 的 BM25/向量权重（`QueryService`
  `PRECISE_LOOKUP_BM25_WEIGHT` 等命名常量，1.3x/0.7x）；对比推理型/闲聊超纲型本阶段只记录
  标签，不改变检索行为。默认关闭（`rag.intent-classification.enabled=false`）。设计文档：
  `docs/superpowers/specs/2026-07-17-llm-intent-classification-retrieval-design.md`。
- **用户明确决定跳过"先分类误差分析拿证据再动手"**：本条目原先建议的保守路径（先等分类误差
  分析证据）被用户显式跳过，直接让分类结果影响检索——权重值尚未经真实评估集验证。
- **仍未做（记入以下子项）**：见下方三条子待办。
- **意图规模化（若未来意图数达数百，仍未做）:** 两种成熟方案——①检索式意图识别（推荐）：把每个
  意图描述当"文档"建向量库，先召回 top-10 候选意图再让 LLM 从中选，prompt 里永远只出现 10 个
  （复用现有检索能力）；②两级分类：先粗分大类（10 个以内）再在命中大类里细分，代价是维护两层
  意图树。核心思想相同：别让模型一次面对几百个选项，先用检索/分层把候选缩到个位数。当前只有
  4 类，远未到需要这套方案的规模。

### 意图分类训练数据留存（2026-07-17 已实现，见 `openspec/changes/intent-classification-training-data-retention/`）

~~原"本次不做"待办~~：用户随后明确要求把这个决策落地，已新增独立表 `intent_training_sample`
（`V015__add_intent_training_sample.sql`）存「问题原文 + 预测意图标签」，`QueryController` 在
`prepare()` 成功后立即记录（与生成阶段结果无关），复用已有分类结果不新增 LLM 调用。关键参数
均为用户 brainstorming 阶段逐项确认：**不自动清理**（人工删除）、**不脱敏**（原样存问题原文）、
**全局开关**（非按组织可选）、**默认开启**（`rag.intent-training-data.enabled=true`，与
`rag.nli.enabled` 等默认关闭的既有惯例不同，是本次特意的例外）。表结构对齐既有 `tenantFilter`
租户隔离约定。设计文档：`openspec/changes/intent-classification-training-data-retention/design.md`。
- **Depends on / blocked by:** 无硬阻塞，随时可作为独立 change 立项。

### 意图分类准确率的系统性评估（2026-07-17）

- **What:** 目前没有标注了真实意图类别（精确检索型/语义理解型/对比推理型/闲聊超纲型）的评估集，
  `predicted_intent` 字段本身的分类准确率无法量化，只能人工抽查 sanity check。
- **Depends on / blocked by:** 需要专门标注一批 query 的真实意图类别，工作量与当年 `eval-set-v2`
  的人工标注相当。

### comparative 类的检索策略（2026-07-17）

- **What:** 对比推理型问题本次只记录标签、不调整检索行为，具体应该怎么优化（如拓宽候选池、
  多路检索融合）留待后续设计，需要先想清楚再动手。

### 意图分类调用与指代消解无法并行，叠加同步阻塞延迟（2026-07-17，`/review` 发现）

- **What:** `QueryService.prepare()` 里指代消解（`orchestrator.prepareContext`）和意图分类
  都是同步阻塞的 LLM 调用；意图分类依赖指代消解后的 `resolvedQuestion`，两者有真实先后依赖，
  无法简单并行。
- **Why:** 每次查询（`rag.intent-classification.enabled=true` 时）多付出一次完整的 LLM 往返
  延迟，在 `orchestrator.prepareContext()` 内部的 embedding/画像检索阶段其实与意图分类彼此独立，
  理论上可以重叠执行以减少端到端延迟。
- **Cons:** 需要重构 `ConversationMemoryOrchestrator` 把"拿到 resolvedQuestion"和"算
  embedding/画像"两步拆开，是比本次功能大得多的改动。
- **Depends on / blocked by:** 无硬阻塞，随时可做，但优先级低于先用 eval 集验证权重调整本身是否
  有效。

## HYDE 假设文档检索(deferred，2026-07-15 讨论记录)

- **What:** Hypothetical Document Embeddings：检索前先让 LLM 根据问题生成一段"可能的答案"（假设文档，允许事实错误），向量化这段假答案去检索真实文档，替代直接向量化短 query。最终回答仍基于检索回的真实 chunk，假答案只是检索跳板。
- **Why:** 短查询（如"等待期"）关键词少、向量"不丰满"，检索容易飘；LLM 编的整段答案自带相关术语和上下文，其向量更接近真正答案文档的向量。
- **Pros:** 对短查询/黑话查询的向量召回有针对性提升，学界工程界验证充分。
- **Cons:** 每次查询多一次 LLM 调用（延迟+token 成本）；对本就写得具体的技术问题收益有限。
- **Context:** 2026-07-15 结合外部学习材料讨论。当前 `HybridRetriever.java:60` 直接 `embed(List.of(query))`，无任何 LLM 预处理。**加之前先用评估集分"短查询/长查询"两组看 Recall 差异**，有证据证明短查询召回确实偏差再做；实现位置在 `HybridRetriever` 的 embedding 调用前插一步可选的生成调用（复用现有 DeepSeek `AnswerGenerator` 客户端），需带超时降级（LLM 不可用时退回直接 embed query）。
- **Depends on / blocked by:** 无硬阻塞；建议与 Query 扩写条目共用同一轮失败题错误归因，一次分析定两个方向的取舍。

## 多轮对话指代消解(deferred，2026-07-15 讨论记录)

- **What:** 多轮场景用户爱用指代（"那它过了还能退吗？"），直接拿这句检索知识库不知道"它"是啥。需结合对话历史先把问题补全成能独立理解的一句（指代消解/query 补全），再去检索。
- **Why:** 当前系统是完全无状态的单轮问答：前端 `ChatPanel.vue` 只发 `{question: text}`，本地 `messages` 数组仅用于渲染气泡不回传；后端 `QueryRequest.history` 字段是预留空壳（无任何代码消费）。指代性追问现在会原样进检索器，大概率检索不准。
- **Pros:** 解锁真正的多轮对话体验，是用户感知最直接的能力升级之一。
- **Cons:** 需要 LLM 做指代消解（多一次调用）；引入对话历史带来上下文扩张与旧轮次信息泄露的边界问题（`QueryRequest` 注释里写明的当初不做的原因）；前后端都要改（前端回传 history、后端消费并补全）。
- **Context:** 2026-07-15 结合外部学习材料讨论确认现状。这是"首期不做"的产品范围决定而非遗漏，接口字段已预留。实现起点：后端在 `QueryService.prepare()` 里、检索之前加一步"若 history 非空则调 LLM 把 question 补全为独立问题"（prompt 只做指代消解不做润色，避开技术 token 被改写的坑，与 rewrite 关闭的理由不冲突）；前端把 `messages` 近几轮回传即可。
- **Depends on / blocked by:** 无硬阻塞；属产品决策项——单轮问答够用就不急，等真实用户出现多轮追问的使用模式再做。

## 文档列表分页(deferred from kb-document-ingest 评审)

- **What:** 给 `GET /api/v1/knowledge-bases/{kbId}/documents` 加分页(Spring Data `Pageable`)。
- **Why:** 当前 `DocumentService.listByKb` 一次返回知识库下全部文档;文档数极大时响应体过大、内存与传输开销高。
- **Pros:** 限制单次返回规模,支撑大知识库;前端可滚动加载。
- **Cons:** 改 Controller/Service 签名与 spec,略扩范围;需定分页参数与默认页大小。
- **Context:** kb-document-ingest 评审(Issue 9)确认本 change 不做,以专注上传摄取闭环。实现时:`DocumentRepository.findByKbIdAndOrgId` 加 `Pageable` 重载,Controller 接 `page/size`,spec 文档列表 requirement 补分页 scenario。
- **Depends on / blocked by:** 无（kb-document-ingest 早已落地，随时可做；2026-07-14 复核 `DocumentController` 仍无 `Pageable`，此项仍未实现）。

## 角色感知删除按钮隐藏(deferred from frontend-ui 评审)

- **What:** 删除 KB / 文档操作需 admin/owner 权限（DocumentService/KnowledgeBaseService 均有校验），但前端目前无角色控制，普通 member 可见删除按钮并点击，收到 403。
- **Why:** MVP 单组织假设下普通 member 数量少，403 有 el-message 提示可接受。
- **Pros:** 消除无效操作，改善普通 member 体验。
- **Cons:** 需给 `KbSidebar.vue`/`DocumentPanel.vue` 的删除按钮加 `v-if` 判断。
- **Context:** frontend-ui 评审（Issue 13）确认 MVP 不做。**2026-07-14 更新**：原先的阻塞条件（login 响应需返回 role）已解决——`authStore.ts` 现已有 `role` 字段（供 `AppHeader`/`AdminMembersView` 使用），实现成本已降为纯前端改动：`KbSidebar.vue`/`DocumentPanel.vue` 的删除按钮加 `v-if="authStore.role === 'OWNER' || authStore.role === 'ADMIN'"` 即可，不再需要后端改动。
- **Depends on / blocked by:** 无（已解除阻塞，可随时实现）。

## ~~mustChangePassword 流程~~（已完成，2026-06-28 落地）

已在 0.2.0 版本实现：`LoginResponse` 返回 `mustChangePassword`，`ChangePasswordView.vue` + 路由守卫已上线（见 CHANGELOG [0.2.0]）。

## 后端安全加固（deferred from /cso 审计 2026-06-28）

以下 5 项安全发现在 /cso 审计中识别。2026-07-14 复核代码：3 项已在后续 RAG Core 重构（PR #4 冻结安全基线）中修复，2 项仍未处理，正式上线前必须完成。

### 已修复（2026-07-14 复核确认）

- ~~S1 — JWT_SECRET 空默认值~~：`JwtService` 已在密钥缺失或短于 32 字节时抛 `IllegalStateException`，启动即失败。
- ~~A01-1 — isBootstrapEndpoint() 路径混淆~~：`JwtAuthFilter.isBootstrapEndpoint()` 已改为 `request.getRequestURI().equals("/api/v1/organizations")` 精确匹配。
- ~~A05-2 — Actuator health 泄露基础设施信息~~：`application.yml` 已设置 `management.endpoint.health.show-details: never`。

### A07-1/A07-2 — login/register 无速率限制 [HIGH/MEDIUM]（仍开放）

- **What:** `POST /auth/login` 和 `POST /auth/register` 完全公开且无请求频率限制，可暴力破解密码、批量注册垃圾账户。
- **Fix:** 引入 Bucket4j + Redis 速率限制（同 IP 5 次/分钟 for login；同邮箱 3 次/小时 for register）。
- **Context:** 实现时参考 `spring-bucket4j` 自动配置或手写 `RateLimitFilter`。

### A09-1 — 认证失败无安全审计日志 [MEDIUM]（仍开放）

- **What:** `JwtAuthFilter.sendError()` 只返回 HTTP 401，无 `log.warn` 记录 IP/路径/原因。攻击者暴力破解/token 重放攻击不留痕迹。
- **Fix:** 在 `sendError()` 前追加 `log.warn("AUTH_FAILURE ip={} path={} reason={}", request.getRemoteAddr(), request.getRequestURI(), message);`
- **File:** `backend/src/main/java/com/diit/ragkb/security/JwtAuthFilter.java`（sendError 方法）

## RAG 检索质量（deferred from 2026-07-13 真实模型联调）

- **What:** 查询侧调用 `embeddingClient.embed()` 时直接传入用户问题原文，未加 BGE 系列模型官方建议的检索指令前缀（如 `为这个句子生成表示以用于检索相关文章：`）。
- **Why:** BGE 是非对称检索模型，只对 query 侧加指令、passage/chunk 侧不加；不加指令召回率会明显下降（不影响跑通，只影响效果）。
- **Fix:** 在 `HybridRetriever.java`（约第 44 行 `embeddingClient.embed(List.of(query))`）调用前，按配置的 embedding 模型族决定是否拼接指令前缀。
- **Context:** 2026-07-13 用真实 Xinference `bge-large-zh-v1.5` + DeepSeek 生成模型联调时发现，当时优先级是先跑通链路，此项留到下一轮检索质量优化。

## 切分/检索质量评测（2026-07-14 已完成 v2 权威基线 + 拒答阈值首轮校准，后续项如下）

**权威基线已测得**（v2 人工标注集 × 完整混合检索 × 拒答阈值已校准，工具
`eval/scripts/EvalRetrievalRunner.java`）：
**Recall@1 = 0.816 / Recall@5 = 0.904 / Recall@10 = 0.912 / MRR = 0.849 / 拒答 F1 = 0.564**。
报告：`eval/reports/eval-v2-calibrated-20260714.md`（含校准前后对比）、
`eval/reports/refusal-threshold-calibration-20260714.md`（校准全过程）。
评估集 `eval/datasets/eval-set-v2.jsonl`（150 题，构建脚本 `eval/scripts/build_eval_set_v2.py`）。
历史基线（骨架集时代 0.094/0.264；v2 校准阈值前 0.912/拒答F1=0）仅供追溯。
模型服务：硅基流动在线 API（embedding=BAAI/bge-m3；rerank=BAAI/bge-reranker-v2-m3；
bge-large-zh-v1.5 在硅基流动对 >512 token 报错 code 20015 不可用于 chunk 侧）。

**拒答阈值校准已完成首轮**（`HybridRetriever.MIN_RERANK_SCORE=0.06`，rerank 成功后
top1 分数低于阈值即拒答；139/139 后端测试通过，新增 3 个单测）：拒答 F1 从 0 → 0.564，
代价是 3/125 应答题被误伤（Recall@5/MRR 各降 0.008，属可接受权衡）。

**已发现的机制性局限（下一步真正的优先级）**——按拒答类型命中率：LOW_CONFIDENCE
3/4、OUT_OF_SCOPE 6/10、SAFETY 2/3、**NO_RETRIEVAL 0/8**。rerank 分数衡量的是
"主题相关性"，管不了"具体事实是否存在"（NO_RETRIEVAL）或"内容是否该外发"
（SAFETY）——这两类检索到的 chunk 确实主题相关甚至真包含相关信息，问题出在
别的判断维度，不是检索排序能解决的。

按预期收益排序的后续项：

- ~~**NO_RETRIEVAL 类拒答方案**~~ **已完成（2026-07-16，PR #17）**：生成模型自判 `{"found": true/false}` + `FactVerificationGate` 拦截解析，8/8 命中标注题，详见 `docs/architecture.md` 决策 8、`eval/reports/no-retrieval-fact-verification-validation-20260716.md`。
- **自检机制仍待解决（2026-07-16，最高优先，已尝试 NLI 路线但未成功）**：`multi-passage-fusion-and-self-check`（PR #19）的 `AnswerSelfChecker` 复用 `MIN_RERANK_SCORE=0.06` 判断句子有没有资料支撑，真实验证（`eval/reports/multi-passage-fusion-and-self-check-validation-20260716.md`）显示只能拦住"完全文不对题"的编造，对"部分相关的编造"基本拦不住（6 个样本命中 4 个）。之后尝试换成真正的 NLI 模型（`nli-based-self-check` 分支，本机部署 `nli-gateway` + `IDEA-CCNL/Erlangshen-Roberta-110M-NLI`），真实校准（`eval/reports/nli-threshold-calibration-20260716.md`）结果更差：这个 110M 小模型对长篇技术性中文段落（矩阵符号、专业术语）判别力不足，"应支撑"样本的 entailment_prob 普遍很低、多数被判成 contradiction，6 条回归样本 F1 只有 0.667，比 Reranker 还差。`nli-gateway`/`NliClient` 基础设施已保留（默认 `rag.nli.enabled=false`，不影响现有 Reranker 版本 `AnswerSelfChecker`），**下一步待办：换一个更大的 NLI 模型（如 325M 的 `Erlangshen-MacBERT-325M-NLI-Chinese`，或多语言的 `mDeBERTa-v3-base-mnli-xnli`）重新跑 `eval/scripts/analyze_nli_threshold.py` 校准**，如果依然不理想，需要重新评估 NLI 路线本身是否可行，或考虑扩大校准样本规模到 150 题级别再下结论。
- **SAFETY 类拒答方案**：需要独立的内容安全/合规分类器（如是否涉及个人信息聚合外发），与检索相关性正交，rerank 分数天生管不了。
- **业务专家盲标复核**：v2 为 AI 单标注人构建（锚点定位+人工复核），按标注指南 §6 第③步抽 30% 双人独立标注，Jaccard ≥ 0.8 后补齐验收门 6。
- **ES 中文分析器**：`content_search` 仍是 standard analyzer 字级切分，加 IK/smartcn 并让 `heading_path` 参与召回，观察 module/config 短板类（Recall@5 0.77-0.83）能否抬升。
- **V0 切分基线对比**：检出 `1fc29ab` 在同一 v2 集组合下重跑（V0 chunk 边界不同，GT 需按锚点重定位——重跑 `build_eval_set_v2.py --report` 即可）。此前一版"模拟对比数据"是随机数生成的，已删除，不可引用。
- **拒答阈值中期复核**：0.06 校准自单次 v2 评估（25 道拒答题），样本量有限；q-126（OUT_OF_SCOPE，深度学习方法）rerank 分数异常达 0.916 需要单独排查是否是 reranker 对"同文档不同方法"判别力的系统性问题；语料/评估集扩充后应重新校准。
- **BGE query 指令前缀**：bge-m3 密集检索模式对指令前缀不敏感，优先级低；换回 bge 非对称模型时必须做。

## deepdoc 版面/表格识别集成的后续项（2026-07-14，`feat/deepdoc-parsing-foundation` 分支）

移植了 RAGFlow deepdoc 的版面分析、OCR、表格结构识别（Apache 2.0，见
`parser-gateway/app/deepdoc/LICENSE_THIRD_PARTY`），替代原来的 RapidOCR，
解决了"多栏文档被按行交叉拼接"和"无边框表格行列错配"两个解析坑。已用真实
`parse_document()` 产线代码路径验证：合成双栏文档、mock 表格结构的费率表
场景均通过。以下几点还没做，记录下来避免误以为已经完工：

- **文本型 PDF 的多栏问题仍未修复**：`parsers.py::_parse_pdf()` 里可提取文本的
  页面（`len(text) >= 100`）走的是 PyMuPDF 原生 `get_text("text")`，没有走
  版面分析，多栏的文本型 PDF（不需要 OCR 的那种）仍可能按行交叉拼接。要修的话，
  思路是改用 `page.get_text("words")` 拿带位置信息的文字框，复用
  `app/deepdoc/pipeline.py` 里现成的 `LayoutRecognizer` 分组逻辑，不需要跑 OCR
  模型。
- **版面/表格识别（多栏 PDF、无边框表格）仍只用合成样本验证**：`parser-gateway/tests/test_deepdoc_pipeline.py` 里的双栏测试用的是程序画出来的合成图片，表格测试用的是 mock 的表格结构（绕开了版面模型是否真能把表格识别成"table"类型这一环）。真实扫描件/真实费率表 PDF 上的效果需要单独找样本验收。
- ~~DOCX/PPTX 内嵌图片 OCR 未用真实样本验证~~（**2026-07-14 已验证**）：本机首次真正启用 parser-gateway 后，用真实文档（贾昊-文献翻译.docx）跑通端到端 `/v1/parse`，过程中发现并修复了一个真实 bug——单张内嵌图片解码/OCR 失败（如老式 WMF 格式）会导致整份文档解析 500，现已改为该图片降级返回空文本、不影响文档其余内容（见 `parsers.py::_ocr_bytes`，新增 3 个单测 `test_parsers_ocr_resilience.py`）。验证结果：71 段落全部提取，3 张内嵌图片中可识别的均被识别。
- **印章压字（坑 3）仍未解决**：deepdoc 本身也没有针对性的印章检测/图层分离方案，这个坑目前四个参考项目（rag-kb、rag系统1/2/3）都没真正解决，见此前的调研结论。
- **`_ocr_bytes()`（DOCX/PPTX 内嵌图片）不做版面分析**：这是有意的简化，这类图片通常是单张截图/Logo，不是多栏页面。
- **Docker 镜像还没验证过完整跑通**：`Dockerfile` 已加 nltk 语料预下载，但没有实际 build 镜像跑过摄取全链路；本地验证用的是手工建的 venv（2026-07-14：本机 venv 首次真正跑通，Python 3.13 + `httpx[socks]`——本机走 SOCKS5 代理下载 HuggingFace 模型需要装这个 extra，`requirements.txt` 未声明，见下条）。
- **`requirements.txt` 缺 `httpx[socks]`**：本机环境经 SOCKS5 代理（`all_proxy`）访问 HuggingFace 下载 deepdoc 模型时，`huggingface_hub` 底层用 httpx 走 SOCKS 代理需要 `socksio` 包，而 `requirements.txt` 只声明了 `huggingface_hub`，未显式声明 `httpx[socks]`。当前只是本机手动 `pip install "httpx[socks]"` 补的，未写回 `requirements.txt`——是否要固化取决于生产环境是否也走代理拉模型，暂不改动生产依赖清单。

## 结构感知切分 V3 五招式（2026-07-14 实现，见 backend/.../ragcore/chunk/impl/TechnicalChunker.java + HeadingStyle.java）

`TechnicalChunker` 按计划实现了 5 项结构感知切分技巧，Task 1-5 均已通过最终评审（Task 1-4 各经过
1-2 轮修复，Task 5 首次评审即通过），全量后端测试通过（135 个测试，0 失败，`TechnicalChunkerTest`
从约 16 个扩到 30 个，另新增 `HeadingStyleTest` 6 个）。已实现：

- **多风格文档层级自动识别**（`HeadingStyle`，非移植代码）：支持多种编号体系（含中文"第 N 章/条"层级），
  命中数低于阈值时退化到既有 Markdown 标题 + 空行分段逻辑，不强行误判。
- **结构→段落→句子三级递归降级**（`recursiveSplit`/`splitByLevel`/`splitByBlankLine`/`splitBySentenceWithOverlap`）：
  超长结构单元按层级逐级降级切分。
- **大表格分组分块并重复表头**（`chunkTableSection`）：大表格按行分组分块，每组重复表头，避免表格
  被截断后丢失列语义。
- **overlap 比例区间验证**：确认 overlap 大小落在预期比例区间内，且切分点对齐句子边界。
- **chunk 元数据增强**（`enrichMetadata`）：新增 `sectionPath`/`contentType`/`isKeyClause`/
  `prevChunkId`/`nextChunkId`，均落在既有 `metadata` Map 里，`Chunk` record 签名未变，ES mapping
  无需改动。

实现过程中发现并修复的问题（记录以避免误认为"一次到位"）：

- Task 1：计划自带的测试有 bug（`CN_FORMAL` 的"章"层级期望下标写错），已修正测试本身，未改真实的
  （本来正确的）层级顺序。
- Task 2：发现真实 bug——`recursiveSplit` 退化到按句子切分且 overlap 非空时，`lineStart`/`lineEnd`
  行号被错误推进，没有把 overlap 重复的内容算进去；同时计划自带的两个测试用例本身不能区分新旧行为，
  已替换为更有判别力的测试数据。
- Task 3：两轮修复。第一轮发现静默丢数据 bug——只有超长表头、没有数据行的表格段落本身超过
  `maxCharacters` 时会产出 0 个 chunk，整张表被静默丢弃。第二轮发现"表格空行跳过"回归测试没有真正
  覆盖到目标代码路径（`.strip()` 提前去掉了尾部空行，循环根本没机会看到它们），已替换为使用表格
  内部（非尾部）空行的测试。
- Task 4：验证 overlap 对齐句子边界的测试用了完全周期性的测试夹具，恰好 overlap 大小与夹具的重复
  周期数值重合，导致一个故意写错的实现依然能通过测试；已换成非周期性夹具并加了正向结构断言。
- Task 5：首次评审即通过，无需修复轮次。

以下几点本轮明确没做，也没打算做（记录避免误以为遗漏）：

- **ML 分类器兜底未实现**：`HeadingStyle.detectDominant()` 命中数低于阈值时直接退化，不接入
  轻量分类器辅助判断层级。训练/维护分类器的成本远超收益，现有阈值退化策略已能覆盖"文档没有清晰
  编号体系"的场景，本身就不在计划范围内。
- **prevChunkId/nextChunkId 检索侧自动补全未实现**：目前只在 chunk 生成时写入这两个字段，检索侧
  （`HybridRetriever`）还没有用它们自动补全语义不完整的相邻块——这是原文提到的用法，但属于检索
  模块的改动，不在本次切块计划范围内，需要单独排期。

以下 2 项是最终评审中记录、评估为低风险但未修复的 Minor 发现，留作后续项：

- **跨表格/非表格类型的 prev/next 链接缺测试覆盖**（Task 5 评审 Minor）：目前没有测试覆盖"文档
  同时混有表格 section 和非表格 section"时 prev/next chunk 链接是否正确跨类型串联。代码里链接逻辑
  本身没有按类型分支，评审判断这是低风险缺口而非已知 bug，但尚未验证。
- **表格空行跳过导致行号少算**（Task 3 评审 Minor）：`chunkTableSection` 循环中通过 `isBlank()`
  跳过的空白行不会推进 `currentLine`，导致当表格里数据行与空行交错时，产出 chunk 的
  `lineStart`/`lineEnd` 会比真实原始行号偏小。目前没有测试断言这一点，问题是潜在的、按计划范围
  判断为 out of scope，但记录在此供后续处理。

## rag_query_audit 的外键缺 ON DELETE CASCADE，有查询记录后无法删除知识库/组织（2026-07-17，`/review` 发现）

- **What:** `rag_query_audit`（`V006__add_rag_query_audit.sql`）的 `org_id`/`kb_id`/`member_id`
  外键都没有 `ON DELETE CASCADE`（默认 `NO ACTION`），而 `document` 表（`V003`）对
  `knowledge_base` 的外键是有 CASCADE 的——这是既有的不一致。一旦某个知识库被查询过一次
  （几乎总是），后续删除该知识库会因外键冲突失败。
- **Why:** `intent_training_sample`（`V015`，本次新增）复用了同样的 org/kb/member 外键形状，
  评审时发现并确认 `rag_query_audit` 早就有这个问题——`intent_training_sample` 本身已经加上了
  `ON DELETE CASCADE`（新表零成本做对），但没有回头修 `rag_query_audit`（改现有表的外键约束是
  更大的迁移改动，且与本次功能无关）。
- **验证结果**：全仓搜索确认知识库删除（`KnowledgeBaseService.delete()`）目前没有任何测试覆盖
  （不论是否存在审计记录），Member 删除功能本身也还不存在（`MemberService` 没有 delete 方法）。
- **Depends on / blocked by:** 需要一个新 Flyway 迁移改 `rag_query_audit` 的外键约束（Postgres
  改外键需要先 DROP CONSTRAINT 再 ADD CONSTRAINT ... ON DELETE CASCADE），加一个删除知识库时
  验证审计记录被级联清理的测试。

## 单文档直接问答（长上下文直接塞入模式，2026-07-18 已实现，见 `openspec/changes/quick-document-qa/`）

- **What:** 会话内可上传临时文档（不写入知识库、不切块不索引），复用 `DocumentParserFactory`
  同步解析全文，会话级共享 15000 字符总额度池（超额拒绝新上传），存 Redis（独立逻辑 DB 2，
  TTL 2 小时随会话活跃续期）。提问时临时文档内容包装成合成 `RetrievedChunk`，与知识库检索
  结果一起送入现有 `AnswerGenerator`/引用抽屉/自检；会话挂临时文档时知识库检索触发的拒答
  阈值不再让整轮问答拒答。参考同类项目 rag系统2 的 `quick_parse` 思路，重新校准了大小限制
  （deepseek-chat 128K 上下文窗口，rag系统2 原本是 4000 字符）。
- **未做（记入以下子项）：**

### 引用来源的临时文档视觉标签未实现

- **What:** 设计阶段计划给临时文档来源的引用加一个"临时文档"标签，与知识库文档来源区分；
  实现时发现这需要给 `Citation` record 加新字段（贯穿 `CitationBuilder`/4 个测试文件/
  MongoDB 历史消息持久化/前端类型），改动面明显大于这个纯 UI 细节本身的价值，决定不做——
  现状引用抽屉会照常显示上传时的文件名（如"临时笔记.md"），用户能自行分辨来源，不影响
  功能正确性。
- **Depends on / blocked by:** 无硬阻塞，如果以后确实需要严格区分（如审计/合规场景），
  再给 `Citation` 加 `quickDocument: boolean` 字段。

### 单文档问答的真实端到端验证未做

- **What:** 后端单测/集成测试（含跨租户安全测试）已覆盖，但没有用真实浏览器跑过一遍完整
  上传-提问-回答流程。~~需要 parser-gateway 的扫描版 PDF/音视频格式~~（**2026-07-21 已解决
  架构前提**：`parser-gateway` 独立服务已下线删除，OCR/ASR 合并进 backend-py 进程内模块
  `LocalMultimodalDocumentParser`，真实图片 OCR、真实历史失败 DOCX 内嵌图片 OCR 重试均已
  用真实 HTTP 上传流程验证通过；仍未做的是真实浏览器端到端，不是 OCR/ASR 链路本身）。
- **Depends on / blocked by:** 无硬阻塞，需要真实浏览器环境验证。

### 临时文档额度校验存在窄幅并发竞态（`/review` 发现，评估后决定不修）

- **What:** `QuickDocumentService.upload()` 的额度校验是"查询已用字符数→判断→写入"三步非原子
  操作；同一会话并发发起两次接近额度上限的上传，理论上都能通过校验都能写入，合计超出
  `max-total-characters` 硬上限。
- **Why 不修：** 评估过用 Redis `INCRBY`/`DECRBY` 做原子计数器的方案，但发现单个文档 TTL
  自然到期（用户从不手动删除、只是不再用这个会话）不会触发任何代码去递减计数器，会导致
  额度长期只增不减、最终整个会话再也传不了新文档——这个新缺陷比现有的窄幅并发竞态更严重
  （现有问题只有真的同时发起并发请求才触发，且只影响发起请求的用户自己这一个会话，不涉及
  跨租户/安全边界）。
- **Depends on / blocked by:** 无硬阻塞；如果要修，需要一个不依赖显式计数器、能感知 TTL 自然
  过期的方案（比如 Redis Lua 脚本原子地读取当前有效文档总和再判断再写入，避免应用层三步
  非原子操作），比简单加个计数器复杂，值得单独评估。
