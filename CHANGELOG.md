# Changelog

## [0.7.0] - 2026-07-18

### 新增功能

- **知识库向量检索迁移至 Milvus（ES/Milvus/影子三模式切流）** —— 检索层按端口拆分为
  `LexicalCandidateSource`（ES BM25）/`VectorCandidateSource`（ES kNN 或 Milvus ANN）/
  `ChunkHydrator`（Milvus 命中回查 ES 补齐正文并二次校验租户边界），`HybridRetriever` 只编
  排两路结果、不再直接依赖数据库 SDK。摄取双写遵循"ES 暂存→Milvus 暂存→Milvus 激活→ES 最
  终激活"可见性闸门协议，只有最后一步 ES 激活成功文档才进入 `READY`；删除走"ES 关闭可见
  性→Milvus 删除→ES 删除→对象/元数据清理"补偿顺序。新增 `rag.vector.provider` 三种模式：
  `elasticsearch`（默认，现有 ES kNN 原样保留）、`shadow`（线上仍用 ES 结果，同时采样查询
  Milvus 记录 TopK 差异与延迟，不影响用户可见结果）、`milvus`（Milvus 为主，超时/故障自动
  回退 ES kNN，再失败则退化为纯 BM25）。多租户隔离在 Milvus 查询/写/删三处均使用服务端构
  造的参数化过滤（非字符串拼接），命中后再经 ES 回查二次校验组织与知识库边界，详见
  `docs/architecture.md` 决策 12。**已知限制（如实记录，观察期内不阻塞合并）**：历史 ES
  向量批量回填 Milvus、真实 ES+Milvus 环境集成验收、150 题对比评测、目标并发压测均未做，
  当前默认配置仍是保守的纯 ES 模式，详见 TODOS.md。

## [0.6.0] - 2026-07-18

### 新增功能

- **单文档直接问答（长上下文直接塞入模式）** —— 会话内可上传临时文档（不写入知识库、不
  切块不索引），复用 `DocumentParserFactory` 同步解析全文（含 OCR/ASR 网关自动降级），
  会话级共享 15000 字符总额度池（超额拒绝新上传，不做静默截断），存 Redis（独立逻辑 DB 2，
  TTL 2 小时随会话活跃续期）。提问时临时文档内容与知识库检索结果一起送入现有生成/引用/
  自检链路；会话挂临时文档时，知识库检索触发的拒答阈值不再让整轮问答拒答，改用临时文档
  内容继续回答。参考同类项目 rag系统2 的 `quick_parse` 实现思路，重新校准了大小限制
  （deepseek-chat 128K 上下文窗口，而非原本的 4000 字符）。**未做**：引用来源的临时文档
  视觉标签（详见 TODOS.md），端到端真实浏览器验证。

## [0.5.0] - 2026-07-17

### 新增功能

- **多轮对话记忆管理**（PR #14，已合并）—— 短期记忆（滑动窗口+语义历史检索+摘要压缩）与
  长期记忆（用户画像+读时衰减遗忘机制）、指代消解；Redis 专属实例（逻辑 DB 隔离于 JWT
  黑名单）+ MongoDB 只服务本子系统；学习性质的能力储备，当前规模非刚需驱动（详见
  `docs/architecture.md` 决策 5）。
- **历史会话列表**（PR #15，已合并；PR #16 修复空会话噪音）—— 新增 `GET`/`DELETE
  .../sessions` 接口，前端历史侧边栏支持切换/删除/新建对话；会话标题写入时算好存库避免
  列表 N+1；删除硬删除级联清理 ES→Mongo/Redis→Postgres；`localStorage` 记录最后活跃会话，
  刷新自动恢复。
- **NO_RETRIEVAL 拒答（生成阶段事实核验）**（PR #17，已合并）—— 拒答阈值只对"检索真找不到
  相关内容"有效，对"主题相关但具体事实缺失"无能为力；生成模型自判 `{"found":true/false}`，
  `FactVerificationGate` 拦截解析，`found:false` 转固定话术拒答；8/8 标注题命中，详见
  `docs/architecture.md` 决策 8。
- **多段融合 + 生成后自检**（PR #19，已合并）—— `HybridRetriever` 的相关性阈值扩展到全部
  候选片段（不再只看排名第一）；新增 `AnswerSelfChecker` 复用 Reranker 逐句核查资料支撑，
  防幻觉"两道闸"的第二道；**已知局限（真实验证，未解决）**：对"部分相关的编造"基本拦不住
  （6 个真实样本 4/6 命中），阈值需要专门校准，详见 TODOS.md。
- **NLI 替代 Reranker 做自检的尝试**（PR #20，已合并，未采用）—— 本机部署独立
  `nli-gateway`（Python FastAPI + `IDEA-CCNL/Erlangshen-Roberta-110M-NLI`），真实阈值校准
  结果比 Reranker 更差（110M 小模型对长篇技术性中文段落判别力不足），基础设施保留（默认
  禁用），`AnswerSelfChecker` 仍是 Reranker 版本，详见 TODOS.md。
- **引用点击滚动高亮**（PR #21，已合并，本版本内又被下方"引用抽屉"取代）—— 正文
  `[资料N]` 点击后滚动+高亮下方对应的引用卡片。
- **引用抽屉，取代始终展示的引用卡片列表** —— 回答下方不再始终展示全部引用来源卡片，改为
  点击正文里的 `[资料N]` 才在右侧 `el-drawer` 弹出该条来源的文档名/定位/原文片段/相关度。
- **历史会话消息持久化引用来源** —— `ChatMessageDocument`（MongoDB）/`ChatMessage` 新增
  `citations` 字段随每轮问答一并写入，历史会话恢复后点击 `[N]` 也能弹出抽屉；明确不做旧
  消息回填。
- **知识库右键菜单 + 独立技术文档页面** —— 知识库列表项的重命名/删除操作从 hover 按钮改为
  右键菜单，新增"技术文档"菜单项跳转到独立路由 `/kb/:kbId/documents`；工作区不再内嵌技术
  文档面板，问答区占满主区域；对话历史侧边栏的展开/收起按钮挪到标题栏顶部，图标改为自定义
  SVG。
- **修复流式回答逐字显现动画完全不生效的问题** —— 根因是承载生成中回答的对象在 push 进
  Vue 响应式数组前就被本地变量直接持有并逐字修改，绕开了响应式 Proxy 的 set 陷阱，Vue 从未
  收到重新渲染的通知；用真实浏览器同时采样"数据层长度"与"DOM 渲染长度"确认了这个不一致
  （数据层平稳增长、DOM 全程冻结，直到生成结束才整段跳出来）。修复：改用 `reactive()`
  包装。
- **LLM Prompt 查询意图分类，实时影响检索策略**（PR #25，已合并）—— 领域无关、基于查询结构
  的四类分类（精确检索型/语义理解型/对比推理型/闲聊超纲型），接在指代消解之后、检索之前；
  精确检索型/语义理解型实时调整 `RrfFusion` 的 BM25/向量权重（1.3x/0.7x，未经评估集验证的
  保守起点）；对比推理型/闲聊超纲型只记录标签不改变检索行为。默认关闭
  （`rag.intent-classification.enabled=false`）。代码评审修复：加权 RRF 曾误收紧
  `MIN_RRF_SCORE` 拒答阈值，已改为早退检查固定用未加权分数判断。
- **意图分类训练数据留存** —— 新增独立表 `intent_training_sample`，把「问题原文 + 预测意图
  标签」落库，供未来训练 BERT 分类器替换现在的 LLM Prompt 粗分类。**⚠️ 默认开启**
  （`rag.intent-training-data.enabled=true`，与本文件其它功能开关默认关闭的惯例不同）——
  只要同时打开了意图分类，就会把问题原文明文写入这张新表，不脱敏、不自动清理（需要清理时
  人工执行 SQL 删除）。升级前请确认这一行为符合部署环境的数据合规要求。

### 已知问题

- 知识库列表操作完全依赖右键触发，触屏和纯键盘用户目前无法触达（用户明确要求的设计，见
  TODOS.md）。
- MongoDB 引用持久化（`List<Citation>` 作为嵌套 record 字段）目前没有自动化回归测试守护，
  已用真实浏览器+真实 MongoDB 手工验证正确，详见 TODOS.md。
- 引用的文档若后续被删除，历史消息里的 citation 不会补上"文档已删除"提示，详见 TODOS.md。
- SAFETY 类拒答仍无方案（需要独立内容安全分类器），自检机制的阈值仍需重新校准。

## [0.4.0] - 2026-07-14

### 新增功能

- **结构感知切分 V3 五招式**（PR #13，已合并）—— `TechnicalChunker` 新增多风格文档层级自动识别
  （`HeadingStyle`，支持含中文"第 N 章/条"在内的多种编号体系，识别不清时退化到既有
  Markdown/空行分段逻辑）、结构→段落→句子三级递归降级、大表格分组分块并重复表头、
  overlap 比例区间与句子边界校验、chunk 元数据增强（`sectionPath`/`contentType`/`isKeyClause`/
  `prevChunkId`/`nextChunkId`，均落在既有 `metadata` Map，`Chunk` record 签名与 ES mapping
  均无需改动）。`TechnicalChunkerTest` 扩到 30 个测试，新增 `HeadingStyleTest` 6 个，
  全量后端测试 135 个通过。ML 分类器兜底与检索侧 prev/next 消费不在本轮范围（见 TODOS.md）。
- **v2 人工标注评估集**（`eval/datasets/eval-set-v2.jsonl`）—— 150 题（125 可答 + 25 拒答），
  标注人通读 26 篇本科毕设语料（885 个 V3 切块）逐题手写，锚点短语全库定位 ground truth
  （多格式副本全标，平均 8.1 chunks/题）；构建可复现（`eval/scripts/build_eval_set_v2.py`）。
  机器骨架集 v1 因 GT 大面积错位废弃保留。配套《标注指南》（`eval/datasets/标注指南.md`）。
- **真实检索评测工具**（`eval/scripts/EvalRetrievalRunner.java`）—— 复用产品
  `ElasticsearchChunkIndex` + `HybridRetriever` 直连 ES 独立评测索引，混合/BM25-only 自适应。
- **拒答阈值校准** —— `HybridRetriever` 新增 `MIN_RERANK_SCORE=0.06`：rerank 成功执行
  （非降级）且 top1 相关性分数低于阈值时拒答，修复此前三轮实测拒答 F1 恒为 0 的问题。
  阈值基于 v2 评估集 25 道拒答题的分数分布校准（`eval/scripts/analyze_refusal_threshold.py`），
  过程详见 `eval/reports/refusal-threshold-calibration-20260714.md`。新增 3 个单元测试
  （低分拒答/高分放行/降级场景跳过门槛），全量后端测试 139/139 通过。

### 评测结果（权威基线）

- **Recall@1 = 0.816，Recall@5 = 0.904，Recall@10 = 0.912，MRR = 0.849，拒答 F1 = 0.564**
  （v2 评估集 × BM25 + bge-m3 kNN + RRF + bge-reranker-v2-m3 完整混合检索 + 已校准拒答阈值，
  报告 `eval/reports/eval-v2-calibrated-20260714.md`）
- 拒答阈值校准前后对比：拒答 F1 0 → 0.564（+11/25 命中），代价是 3/125 应答题被误伤，
  Recall@5/MRR 各下降 0.008（0.912→0.904，0.857→0.849），收益/代价权衡记录在报告中
- 分桶：data-structure 类 Recall@5 = 1.000、api = 0.963；短板 module/config ≈ 0.77-0.83
- 关键实证：同一检索系统在机器骨架集上 Recall@5 仅 0.264，人工标注集 0.904——
  评估集质量决定评测有效性，引用指标必须注明评估集版本

### 变更

- **模型服务切换** —— 内网 Xinference → 硅基流动（SiliconFlow）在线 API：
  embedding=`BAAI/bge-m3`（bge-large-zh-v1.5 在硅基流动对 >512 token 输入报错，不可用于
  chunk 侧）、rerank=`BAAI/bge-reranker-v2-m3`；零代码改动（OpenAI 兼容客户端），
  仅 `.env` 配置；本机 TCP 转发代理脚本弃用
- **前端视觉改版** —— 全局改为 Anthropic 风格设计语言（暖白背景、陶土色主色调、标题衬线
  字体），新增 `frontend/src/assets/theme.css` 覆盖 Element Plus 主题变量
- **模型客户端强制 HTTP/1.1** —— 三个 OpenAI 兼容客户端显式指定
  `HttpClient.Version.HTTP_1_1`，规避部分本地模型网关不支持明文 h2c 升级协商的问题

### 已知问题

- 拒答阈值对 NO_RETRIEVAL 类（主题相关但具体事实缺失，如"随机数种子设的多少"）
  和 SAFETY 类（内容确实可检索，但因合规原因应拒答，如汇总个人信息外发）几乎无
  区分力（按类型命中率：LOW_CONFIDENCE 3/4、OUT_OF_SCOPE 6/10、SAFETY 2/3、
  **NO_RETRIEVAL 0/8**）——rerank 分数衡量主题相关性，管不了"事实是否存在"或
  "内容是否该外发"，需要独立机制（事实核验、内容安全分类器），见 TODOS.md（已置顶）
- v2 评估集为 AI 单标注人构建，业务专家 30% 盲标复核待补

## [0.3.0] - 2026-07-14

### 新增功能 — 自研 RAG Core 全链路

替换已下线的 RAGFlow 主链路，新增完全自研的解析、切块、索引、检索、重排、生成与可观测性模块（`backend/.../ragcore/`）：

- **RAG 核心契约与安全基线**（PR #4）— 冻结 `DocumentParser`/`Chunker`/`EmbeddingClient`/`ChunkIndex`/`Retriever`/`RerankerClient`/`AnswerGenerator` 接口；JWT 密钥 fail-fast、Bootstrap 路径精确匹配、health 端点脱敏
- **技术文档解析与结构化切块**（PR #5）— Markdown、代码、JSON/YAML/XML、DOCX、文本 PDF 解析；保留标题层级、代码块、页码/行号的技术切块器
- **摄取与索引闭环**（PR #6）— PostgreSQL `ingestion_job` + 双 Worker 异步摄取、租约心跳、过期任务接管、失败重试、Elasticsearch `rag_chunks_v1` Bulk 写入
- **混合检索与拒答决策**（PR #7）— BM25 + kNN + RRF 融合、可选 Rerank、空召回/低置信拒答、SSE 流式问答与服务端引用构造
- **查询审计与可观测性**（PR #8）— `rag_query_audit` 表、traceId 追踪、Prometheus 指标（`rag_upload_sessions_total` 等）
- **文档工作区与流式问答界面**（PR #9）— Vue 前端知识库工作区、文档上传/状态/重试/删除、聊天面板与引用卡片
- **生产级文档上传与多模态解析**（PR #10）— 独立 Parser Gateway（OCR/ASR/Office 图片提取/字幕时间戳）、扫描 PDF/图片/音频/视频解析；5000 份多模态文档生产同构验收，5000/5000 `READY`、0 失败

### 验证

- 5000 份多模态文档全链路验收通过（详见 [验收报告](docs/文档上传与多模态解析生产验收报告.md)）
- 检索问答全链路（真实 Xinference Embedding/Rerank + DeepSeek 生成模型）人工端到端验证通过，正式 Recall@5 评测与压测尚未执行

### 已知问题

- 部分内网模型网关（如某些 Xinference 部署）对"请求头与请求体分两次 TCP 写入"处理有 bug，会向标准 HTTP 客户端（Java/Python）返回 502，curl 因单次写入不受影响；详见 [检索与审计验收](docs/检索与审计验收.md)第 1 节
- 查询侧未对 BGE 系列 Embedding 模型加检索指令前缀（如 `为这个句子生成表示以用于检索相关文章：`），可能影响召回率
- 登录/注册接口仍无速率限制，认证失败无审计日志（见 [TODOS.md](TODOS.md)）

## [0.2.0] - 2026-06-28

### 新增功能

- **成员管理** — OWNER/ADMIN 可邀请用户入组、修改成员角色、重置成员密码（显示临时密码）
- **团队管理** — OWNER/ADMIN 可创建团队，查看组织内团队列表
- **角色路由守卫** — 路由根据 OWNER/ADMIN/MEMBER 角色分级，MEMBER 无法访问 /admin/*
- **页面刷新守卫** — 刷新后异步 fetchRole 恢复角色状态，OWNER/ADMIN 不再被误重定向
- **强制改密流程** — 登录时后端标记 mustChangePassword，前端引导至 /change-password 完成后退出重登

### 安全修复

- **CRITICAL** — admin 不可重置 owner 的密码（防通过临时密码完成特权提升）；后端 MemberController + 前端按钮双重防护
- **HIGH** — TeamService.create() 在 role 为 null 时改抛 AccessDeniedException，不再产生未处理的 NPE 500 错误
- **HIGH** — /members/me 端点对 memberId 为 null 的情况返回 404，不再 NPE

### Bug 修复

- AppHeader 管理导航链接从普通变量改为 computed()，刷新后正确响应角色变化
- authStore 添加 roleFetched sentinel，fetchRole 失败后不再每次导航重试请求
- AdminMembersView/AdminTeamsView 操作失败时显示错误提示（之前静默失败）
- ChangePasswordView 移除未使用的 useRouter 引用
- MemberController 修正 ResourceNotFoundException 使用 fully-qualified 路径的问题

### 测试

- 新增路由守卫异步 fetchRole 测试用例（页面刷新后 OWNER 放行）
- 路由测试守卫与真实守卫对齐（async + roleFetched sentinel）
- 修正 form-validation 测试中误导性的测试名称
- 前端单元测试共 50 个，全部通过
