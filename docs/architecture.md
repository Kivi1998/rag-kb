# rag-kb 架构设计

> 当前状态：旧 RAGFlow 摄取与问答实现已下线，自研 RAG Core 主链路已经落地并持续迭代；
> Milvus 当前为可选投影，默认仍使用 Elasticsearch 向量检索。
>
> 详细实施设计见：[自研 RAG 核心重构架构设计](自研RAG核心重构架构设计.md)。

## 一、定位与边界

- 面向内部技术团队的企业级技术文档知识库；
- 解决文档、配置、接口说明和代码片段分散在群聊中、难以检索的问题；
- 保留组织、团队、成员、RBAC、知识库等企业应用能力；
- 自研解析、切块、索引、混合检索、重排、引用与问答主链路；
- 不使用 RAGFlow、LangChain、LlamaIndex、Dify 等高层 RAG 编排框架。

## 二、目标架构

```text
Vue 前端
  └─ Spring Boot 应用层
       ├─ JWT / 组织团队 / RBAC / 审计
       ├─ 知识库与文档任务管理
       └─ ragcore（自研）
            ├─ 文档解析与技术切块
            ├─ Embedding / Rerank / LLM Client
            ├─ Elasticsearch：BM25 + 默认 kNN 候选（向量可切流 Milvus，见决策 12）
            ├─ HybridRetriever：RRF 融合 / Rerank / 拒答
            ├─ Conversation Memory：滑动窗口 / 指代消解 / 用户画像 / 会话历史列表（2026-07-15 新增）
            ├─ 引用构造、拒答与 SSE 输出
            └─ 评测、重试与可观测性

基础设施：PostgreSQL（业务、任务与会话元数据）/ MinIO（原文件）/
Elasticsearch（chunk、全文、向量默认投影；统一记忆索引）/
Milvus（可选向量投影，`rag.vector.provider` 切流，默认关闭，见决策 12）/
Redis（JWT 黑名单 + 会话记忆滑动窗口 + 临时文档，逻辑 DB 隔离）/
MongoDB（会话消息长期存档 + 用户画像，只服务记忆子系统）/
OpenAI 兼容模型服务（已验证基线：硅基流动 Embedding/Rerank + DeepSeek 生成）
```

> 注：限流尚未实现（此前版本图里的"限流"是规划态描述，代码中未落地）。

## 三、关键技术决策

### 决策 1：保持 Spring Boot 单体模块化

- 现有认证、租户与权限代码保留；
- RAG Core 放在 `com.diit.ragkb.ragcore`，以接口隔离 Parser、Chunker、Index、Retriever、Reranker 与 Generator；
- 在真正出现独立扩缩容需求前，不拆微服务、不引入消息队列全家桶。

### 决策 2：直接使用基础设施，不使用高层 RAG 框架

- Elasticsearch 提供 BM25、过滤和向量 kNN；
- OpenAI 兼容客户端对接 Embedding、Rerank 和 LLM；
- MinIO 保存原始文件，PostgreSQL 保存元数据和摄取任务；
- 技术策略、Prompt、引用、拒答和评测全部在本项目代码中实现。

### 决策 3：技术文档优先

- Markdown、代码、YAML/JSON/XML、DOCX 和文本型 PDF 为第一阶段范围；
- 切块保留标题层级、代码块、类/方法、配置路径、页码和行号；
- 错误码、类名、方法名、接口路径与配置 key 优先走关键词精确召回，避免过早 Query Rewrite 损坏技术标识。

### 决策 4：应用层强制多租户隔离

- 所有检索请求先完成组织、知识库和角色校验；
- Elasticsearch 查询由服务端强制注入 `org_id` 与 `kb_id` 过滤；
- 跨组织访问按资源不存在处理，并作为自动化测试发布门禁；
- 会话生命周期（`chat_session`）额外强制 `kb_id` 归属校验（2026-07-15 review 修复：此前 `GET .../messages` 只校验 org/member，未核对 URL 里的 kbId 与会话真实归属 kb 是否一致，同组织同成员可跨 kb 读取对话历史）；
- MongoDB 层（`ChatMessageRepository`/`MemoryItemStoreImpl`）不完全信任上游 Elasticsearch 过滤结果，读回文档后二次比对 `org_id`/`member_id`，作为纵深防御，防止未来 ES 过滤逻辑出 bug 时直接跨租户泄露数据。

### 决策 5：多轮对话记忆是学习性质的能力储备，非当前刚需

- 短期记忆（滑动窗口+语义历史检索+摘要压缩）与长期记忆（用户画像+读时衰减遗忘机制）已实现，详见 [brainstorming 设计文档](superpowers/specs/2026-07-15-conversation-memory-design.md)；
- 存储引入 Redis 专属实例（与 JWT 黑名单逻辑隔离）+ MongoDB（只服务本子系统），当前规模（单节点、日均 5000 次查询）本不需要这套复杂度，是为学习生产级架构、给未来用户规模增长预先建设；
- 画像内容只影响生成阶段的 System 上下文，不影响 `HybridRetriever` 的检索排序/过滤参数；但指代消解后的 `resolvedQuestion` 向量本身，在画像检索阶段算好后会通过 `MemoryContext`/`RetrievalOptions` 带给检索阶段直接复用（纯粹是避免同一句话被调用两次 Embedding 的效率优化，不构成"画像影响检索"）；
- 会话生命周期管理（`ChatSessionService`）不受 `rag.memory.enabled` 开关门控、常驻注册——因为 `sessionId` 在 `QueryRequest` 上始终必填，即使记忆子系统（Redis 滑动窗口/MongoDB 长期存档/ES 语义检索）关闭，会话归属校验也必须生效，不能变成摆设；
- 同样不引入 LangChain/LlamaIndex 等编排框架，指代消解/摘要压缩/画像提炼均为自研 prompt + 现有模型客户端。

### 决策 6：历史会话列表——标题写时算好存库，硬删除而非软删除

- 前端此前每次刷新/重新进入知识库都无条件新建会话，未消费已有的会话生命周期与长期存档能力；新增 `GET .../sessions` 列表接口与前端历史侧边栏补齐这一消费侧，详见 [brainstorming 设计文档](superpowers/specs/2026-07-15-conversation-history-list-design.md)；
- 会话标题（首条用户消息前 30 字）在写入时算好存 `chat_session.title`，而非列表查询时对每个会话现查 MongoDB——避免列表接口产生 N+1 跨存储查询；
- 删除会话选择硬删除（级联清理 Elasticsearch→MongoDB/Redis→Postgres），而非软删除标记：用户对"删除"的直觉预期就是清除，且没有强需求要保留已删除会话用于审计/恢复；删除不影响 `memory_items` 用户画像（画像是 member 维度长期记忆，与会话生命周期无关）；
- 前端用 `localStorage` 记录每个知识库最后活跃的会话 ID 实现"刷新回到刚才那个对话"，而非引入路由级 `sessionId` 参数——因为当前 `kbId` 本身就不是路由参数（由 `kbStore.selectedKbId` 驱动），引入 URL 级会话参数需要同时改造 kbId 的路由方式，改动面明显更大。

### 决策 7：拒答阈值（`MIN_RERANK_SCORE=0.06`）是真实实验校准出来的，不是拍脑袋定的

- **原始问题**：`HybridRetriever` 最早只有 `MIN_RRF_SCORE=0.01` 一道拒答门槛，三轮实测拒答 F1 均为 0——RRF 分数分母含 `rank_constant=60`，任何 top-1 候选几乎必然超过该阈值，从未真正拦截过任何一道拒答题；
- **实验方法**（完整记录见 [拒答阈值校准报告](../eval/reports/refusal-threshold-calibration-20260714.md)，复现脚本见 [`eval/scripts/analyze_refusal_threshold.py`](../eval/scripts/analyze_refusal_threshold.py)）：
  1. 扩展 `EvalRetrievalRunner`，在 150 题人工标注评估集（`eval-set-v2.jsonl`）上跑一次真实检索（硅基流动 `bge-m3` + `bge-reranker-v2-m3`），把每题 top-1 候选的 rerank 分数作为诊断字段（`_top_rerank_score`）一起吐出，不影响正式评测 schema；
  2. 按人工标注的 `expect_refusal` 把 150 题分成"应拒答"（25 道）与"应回答"（125 道）两组，观察两组 rerank 分数的分布差异；
  3. 用 `analyze_refusal_threshold.py` 对候选阈值 t（0 到 1，步长 0.005）逐个计算"rerank 分数 < t 就拒答"规则下的精确率/召回率/F1，选 F1 最优点；
- **结果**：t=0.06 时 F1=0.564 全局最优，命中 11/25 道拒答题，代价是误伤 3/125 道应答题（均为语料信息密度低、细节湮没在长文档里的冷门题，如"作者单位邮编""开发机显卡型号"）；
- **已知机制性局限（不是调参能解决的）**：按拒答子类型（`refusal_reason`）细分后发现，t=0.06 只对 **LOW_CONFIDENCE**（4/4 全中）和 **OUT_OF_SCOPE**（10 中 9）有效；**NO_RETRIEVAL**（如"随机数种子设的多少"——检索到的 chunk 主题对了，具体数值恰好没写）与 **SAFETY**（检索到的内容本身没问题，但组织后外发涉及合规）两类的 rerank 分数普遍很高（NO_RETRIEVAL 8 道题 0.178–0.921，SAFETY 甚至有 0.972），reranker 衡量的是"主题相关性"而非"该问题的具体答案是否存在于此内容"，天花板明确。这两类需要生成阶段的事实核验/独立内容安全分类器，单一检索分数阈值解决不了——**NO_RETRIEVAL 的事实核验机制见决策 8**，SAFETY 仍不在范围内。

### 决策 8：NO_RETRIEVAL 拒答靠生成模型自判，不是独立核验调用

- **方案**（详见 [brainstorming 设计文档](superpowers/specs/2026-07-16-no-retrieval-fact-verification-design.md)）：`PromptAssembler` 要求生成模型在正文之前先输出一行 `{"found": true|false}`，判断参考资料是否包含问题的具体答案；新增 `FactVerificationGate`（`ragcore/generation/`）拦截解析这一行，`found:false` 时丢弃已缓冲内容、转为固定话术拒答（"未在当前知识库中检索到该问题的具体答案"），不新增一次独立的核验 LLM 调用（成本/延迟更低，复用同一次生成请求的结构化输出）；
- **关键架构联动**：`SOURCE` 引用事件的发送时机从"生成开始前"推迟到"`FactVerificationGate` 确认 `found:true` 之后"，避免"已经展示引用来源却又拒答"的自相矛盾；
- **审计正确性**：`GenerationMetrics` 新增 `factVerificationRefusalReason` 字段，`QueryController` 的审计状态判断同时检查检索阶段与生成阶段两种拒答来源——生成阶段拒答此前会被误记为 `COMPLETED`（因为审计快照在 `prepare()` 阶段就已固化），这是实现过程中发现并修复的问题；
- **真实回归验证**（`eval/reports/no-retrieval-fact-verification-validation-20260716.md`）：8 道 NO_RETRIEVAL 标注题命中拒答 8/8；25 道抽样应答题里 2 道被误判拒答，排查后确认根因是检索召回本身没找到该找的 chunk（与本机制无关）。

### 决策 9：多段融合与生成后自检——复用 Reranker，而非新增 LLM 调用或依赖生成模型自查

- **多段融合**（详见 [brainstorming 设计文档](superpowers/specs/2026-07-16-multi-passage-fusion-and-self-check-design.md)）：`HybridRetriever` 的 `MIN_RERANK_SCORE` 阈值检查从只看排名第一的片段，扩展到全部候选片段——排名靠后但分数不达标的片段直接过滤，不进生成 prompt 也不出现在参考来源里；`PromptAssembler` 追加一句取舍指令，片段矛盾时优先采信排序更靠前的资料；
- **生成后自检（防幻觉"两道闸"的第二道）**：新增 `AnswerSelfChecker`，复用现有 Reranker 对生成正文逐句核查——带 `[资料N]` 标记的句子核查该句与其引用资料的语义相关性，没有任何引用标记的实质性句子直接判定为疑似未标注断言；核查方判定权衡上明确选择"独立于生成模型之外"（而非同一模型自查自己），因为让编造内容的同一个模型去检查自己有没有编造，说服力有限；
- **已知局限（真实验证发现，未解决）**：`eval/reports/multi-passage-fusion-and-self-check-validation-20260716.md` 用真实语料构造的 6 条测试句子里，Reranker 复用的 `MIN_RERANK_SCORE=0.06` 阈值只能拦住"完全文不对题"的编造（分数低至 0.00003），对"部分相关的编造"（如张冠李戴到相邻主题，分数 0.15–0.53）基本拦不住，4/6 命中预期。机制方向正确但阈值不是为这个场景校准的，需要类似决策 7 那样规模的标注集才能负责任地重新定阈值，本次未做，留作后续。

### 决策 10：引用展示改为点击弹出，知识库管理改为右键菜单（2026-07-16～17）

- **引用展示从"始终全展示"改为"点击弹出"**：此前每条 assistant 回答下方始终展示全部引用来源卡片；改为只在正文里点击 `[资料N]` 时才在右侧 `el-drawer` 弹出该条来源，减少默认状态下的信息噪音。副作用是模型没有在正文里内联引用到的资料（生产环境 `RetrievalOptions.defaults()` 检索保留最多 8 条候选，但模型通常只挑相关的引用其中几条）现在没有任何 UI 入口能看到——这是权衡后接受的设计，不是遗漏；
- **历史消息引用持久化**：引用来源此前只在当次流式生成时通过 SSE `source` 事件推给前端，历史会话恢复（`getSessionMessages`）不带 citations，点击历史回答的 `[N]` 静默无反应。现在 `ChatMessageDocument`（MongoDB）/`ChatMessage`（内存态 record）新增 `citations` 字段，`ConversationMemoryOrchestrator.recordTurn()` 持久化时一并写入 `query.citations()`（`prepare()` 阶段已算好，与 SSE 推送给前端的是同一份数据，不会不一致）；Redis 短期滑动窗口不需要 citations（该路径消费方只提取 role/content 拼文本），序列化前显式剔除，避免每条消息把最多 8 条、每条最长 500 字的片段白白写进 Redis；明确不做历史数据回填（已与用户确认接受），旧消息读出来 citations 为空，效果上跟没有引用一样；
- **知识库管理从 hover 按钮改为右键菜单**：知识库列表项的重命名/删除操作从"hover 才出现的图标按钮"改为右键单击弹出菜单（`el-dropdown trigger="contextmenu"`），新增"技术文档"菜单项跳转到独立路由 `/kb/:kbId/documents`；工作区不再内嵌技术文档面板，问答区占满主区域。这是用户明确要求的设计（"重命名删除等操作集成到右键单击中"），代价是触屏和纯键盘用户目前完全无法触达这些操作，已如实告知、未做额外的可见入口兜底；
- **实现过程中定位并修复的一个 Vue 响应式坑**：流式回答的逐字显现动画（打字机效果）此前完全不生效——`assistantMessage` 是 push 进 `messages` 响应式数组之前创建的普通对象，reveal 定时器一直用这个本地变量原样引用去改 `content` 属性，这些修改绕开了 Vue 响应式 Proxy 的 set 陷阱，Vue 从未被通知需要重新渲染；屏幕上真实卡在"正在生成…"，只有 `sending` 这个真正响应式的变量在生成结束那一刻变化时才触发一次整体重渲染，看起来就是整段答案一次性冒出来。用真实浏览器同时采样"数据层 `content.length`"和"DOM 实际渲染出的文字长度"确认了这个不一致（数据层平稳增长、DOM 全程冻结）。修复：`createAssistantMessage()` 返回 `reactive()` 包装的对象。

### 决策 11：单文档直接问答用长上下文直接塞入，不走切块检索（2026-07-18）

- **为什么不复用现有切块/索引/检索链路**：临时文档是会话内的一次性上下文，用户上传后马上就要问答，不值得为它跑一遍写 Elasticsearch 索引再检索召回的完整流程；参考 rag系统2 的 `quick_parse` 思路，直接复用 `DocumentParserFactory.parse()` 拿到解析后的纯文本，包装成一个合成 `RetrievedChunk`（`finalScore` 固定给高分，确保排在真实检索结果前面）直接送进现有生成/引用/自检链路，不新增解析逻辑、不新增生成逻辑；
- **为什么是会话级而不是知识库级或独立会话模型**：`ChatSession` 在 Postgres 和路由两层都已强制绑定 `kbId`，临时文档挂在现有会话上不需要新的会话模型；生命周期天然跟随会话活跃度（TTL 随活跃续期），比另建一套独立的临时文档会话更省心；
- **为什么额度从 rag系统2 原始的 4000 字符重新校准到 15000**：调研 DeepSeek 的上下文窗口（`deepseek-chat` 128K token，约 22500 token 也只占不到 18% 窗口）后判断 4000 字符过于保守，浪费了长上下文模型的能力；
- **为什么超额直接拒绝新上传，而不是静默截断挤占**：多文档共享一个总额度池，如果超额还允许上传但静默丢弃/截断旧文档内容，用户会在不知情的情况下发现之前上传的文档"消失了"；直接拒绝新上传、把决定权交给用户（先删旧的再传新的）更符合"不静默丢数据"的原则；
- **为什么检索触发拒答阈值时可以被临时文档豁免**：临时文档是用户主动提供、明确要求基于其内容回答的上下文，与知识库检索召回不到内容时的"防止瞎编"拒答语义不同——用户上传了文档就是要问它，因此拒答判断改为"知识库检索该拒答 **且** 当前会话没有挂临时文档"才真正拒答；这也要求 `QueryAuditSnapshot` 必须按最终决策结果（是否真的拒答、最终用了哪些 context）重建，不能用检索阶段的中间结果，否则审计记录会跟用户实际看到的回答矛盾；
- **为什么上传接口同步阻塞**：临时文档不进异步摄取任务表（`ingestion_job`），没有 `QUEUED→PARSING→READY` 状态机的必要，前端转圈等待即可，避免为一次性小文档解析引入不必要的异步复杂度；
- **为什么用独立 Redis 逻辑 DB（DB 2）**：现有 Redis 里 DB 0 是 JWT 黑名单、DB 1 是会话记忆子系统（受 `rag.memory.enabled` 开关门控），临时文档存取必须独立于 `rag.memory.enabled`（`ChatSession` 本身不依赖记忆子系统开关），所以另开一个不受该开关影响的逻辑 DB；
- **已知取舍**：详见 [第 8 章文档](../README.md)"已知取舍"条目——引用来源暂不区分临时文档/知识库文档的视觉标签、额度校验存在窄幅并发竞态（评估过 Redis 原子计数器修复方案，因 TTL 过期不触发计数器递减、会导致更严重的永久额度漂移而放弃）。

### 决策 12：向量检索迁移 Milvus——ES/Milvus/影子三模式切流，ES 仍是正文权威源（2026-07-18）

- **为什么不整体替换 ES、只迁移向量**：ES 同时承担 BM25、技术字段加权和正文/引用回查，把这些也搬去 Milvus 会扩大双写一致性面且丢失已验证的 ES 词法基线；Milvus 只保存向量与最小过滤字段（`chunk_id`/`embedding`/`org_id`/`kb_id`/`document_id`/`retrieval_ready` 等），命中后必须回 ES 补齐正文——ES 依旧是唯一的正文与引用定位权威源；
- **为什么按端口拆分而不是直接改 `ElasticsearchHybridCandidateSource`**：新增 `LexicalCandidateSource`/`VectorCandidateSource`/`ChunkHydrator` 三个端口，`HybridRetriever` 只编排两路结果、不直接依赖任何数据库 SDK，ES 和 Milvus 各自实现对应端口；迁移期原 `HybridCandidateSource`/`ChunkIndex` 由适配器兼容保留（供评测脚本/存量测试使用），保证每个提交都可构建、可回滚；
- **为什么摄取要"双端暂存、ES 最后激活"**：分布式写入没有跨库事务，用确定性 Chunk ID + `retrieval_ready` 可见性闸门代替——顺序是 ES 暂存（`retrieval_ready=false`）→ Milvus 暂存 → Milvus 激活 → ES 最后激活，只有第 4 步成功文档才进 `READY`；所有查询路径都强制过滤 `retrieval_ready=true`，因此任一步失败时暂存数据都不可能被检索到，Worker 复用现有幂等重试收敛，不需要新增消息队列；
- **为什么删除是"先关 ES 可见性、再物理清理"**：ES 是最后一道正文回查边界，删除请求先把 ES 对应 Chunk 的 `retrieval_ready` 置 false，再依次删 Milvus 向量、ES Chunk、对象与元数据；中途失败保留 `DELETING` 由既有补偿任务重试，确保"已删除"文档不会因为清理顺序问题继续出现在检索结果里；
- **为什么要三种 Provider 模式而不是直接切换**：`elasticsearch`（默认回滚模式）、`shadow`（线上仍用 ES 结果，同时采样查询 Milvus 记录 TopK 差异与延迟，不影响用户）、`milvus`（Milvus 主查询，超时/故障自动退回 ES kNN，再失败退化纯 BM25）——切流必须经过影子验证质量、达标后再灰度，不能靠"上线就直接换"；模式由服务端配置决定，外部 API 不暴露也不接受请求覆盖；
- **为什么租户过滤要做三次**：Milvus 查询表达式由服务端按类型化的 `orgId+kbId+documentIds` 构造（参数化模板，禁止透传任意表达式/字符串拼接）→ 命中后 ES 批量回查再次带相同边界 → 转换为 `RetrievedChunk` 前再比对返回记录的组织与知识库，任何不一致直接丢弃并计入安全指标；Collection 用共享 Collection + 标量过滤而非每租户一个 Collection，当前百人级团队规模下运维更简单，未来超大租户需要物理隔离再独立演进；
- **评审中发现并修复的问题**：`code-review` 8 角度里 4 个独立角度交叉确认了同一个 HIGH 级缺陷——`MilvusVectorIndex.setVisibility()` 用单次 `QueryReq(limit=16384)` 拉取文档全部 chunk_id 再翻转可见性，超过该上限的文档会静默漏掉尾部 chunk（删除场景下超限内容在文档"删除"后仍可被检索到），已修复为按 offset 翻页查询直到取完，并补了跨页回归测试；
- **已知限制（观察期内不阻塞合并，见 TODOS）**：历史 ES 向量批量回填 Milvus、真实 ES+Milvus 环境集成验收、150 题 ES/Milvus 对比评测、目标并发压测均未做；当前默认配置仍是纯 ES 模式，Milvus 未默认启用。当前状态与配置见 [Milvus 向量检索迁移设计](Milvus向量检索迁移设计.md)，D1-D7 原始决策见 OpenSpec 归档 `openspec/changes/archive/2026-07-18-migrate-vector-retrieval-to-milvus/design.md`。

## 四、当前重构边界

- 已删除：RAGFlow Client、RAGFlow dataset/chat/session 管理、旧文档摄取、旧 SSE 问答、相关前后端页面与测试；
- 保留：认证、组织、团队、成员、知识库 CRUD 和应用外壳；
- 历史 Flyway 迁移保留，确保已部署环境可以演进；新逻辑不得继续使用其中的 RAGFlow 字段；
- 新实现遵循“任务表 + Worker”异步摄取，完成压测后再决定是否引入消息队列。

## 五、企业级必备能力

- 多租户与 RBAC；
- 文档摄取状态、失败重试、幂等和删除补偿；
- 引用溯源、拒答、评测集与回归指标；
- 查询审计、延迟、Token 与模型版本可观测；
- 登录限流、密钥 fail-fast、健康检查脱敏与认证失败审计。
