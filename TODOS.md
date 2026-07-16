# TODOS

延后但已记录的工作项。每项注明动机、现状与起点,避免日后丢失上下文。

## RRF 融合动态权重(deferred，2026-07-15 讨论记录)

- **What:** `RrfFusion.merge()` 目前 BM25 与向量两路固定等权（各自 `1/(60+rank)` 直接相加）。可以引入查询意图分类，对"精确型"查询（命中编号、术语、错误码等）调高 BM25 权重，对"语义型"查询调高向量权重。
- **Why:** 固定等权对"孩子摔伤能赔吗"这类语义型问题和"等待期是多久"这类关键词型问题一视同仁，理论上有提升空间——精确型查询字面命中最稳，语义检索反而可能引入噪声；反之亦然。
- **Pros:** 检索相关性理论上限更高，尤其对关键词/语义两类查询占比都不低的知识库。
- **Cons:** 需要先做查询意图分类（引入新模块或复用现有 LLM 做轻量分类，增加一次调用延迟或训练成本）；具体权重取值必须用评估集实测校准，不能拍脑袋定，否则可能比固定等权更差。
- **Context:** 2026-07-15 用户结合外部学习材料讨论检索链路时提出。材料本身的建议是"别一上来就追求动态权重，先用固定权重+RRF 跑通，再拿评估集看哪类查询拉胯，才有依据去调"——现状正好停在这个推荐的第一阶段：固定等权 RRF 已跑通，`eval-set-v2`（150题评估集）也已就绪，具备了做"分类误差分析"的条件，只是还没有人力去跑这一步分析。实现起点：先用 `eval/datasets/eval-set-v2.jsonl` 跑一遍现有固定等权效果，按 query 分成"关键词主导/语义主导"两类看 Recall 差异，若差异明显再决定是否值得引入分类器调权重；分类器可以先用现有 LLM（DeepSeek）做零样本分类原型，不必训练专门模型。
- **Depends on / blocked by:** 无，随时可做；建议在 `RrfFusion.fuse()`/`merge()` 里加一个可选的 `bm25Weight`/`vectorWeight` 参数（默认各 1.0，即现状），分类逻辑放在 `HybridRetriever` 层决定权重再传入。

## Query 扩写与重写(deferred，2026-07-15 讨论记录)

- **What:** 检索前对用户 query 做处理：**扩写**=给问题加同义词/相关词后多路一起检索（求"全"，提召回）；**重写**=把口语化问题改写成贴近知识库表达的规范问法（求"准"，提精度）。当前两者都没有：`HybridRetriever` 拿原始 query 直接跑 BM25+embedding，`QueryRequest.rewrite` 字段是预留空壳且注释明确"首期固定关闭"。
- **Why:** 扩写解决"文档写'索赔'、用户问'理赔'搜不到"的词汇错配；但我们是混合检索，bge-m3 向量腿天然覆盖大部分同义词漂移，剩余收益主要在向量模型没学过的领域黑话/内部术语。重写在技术文档场景风险大于收益：高价值查询恰是 `NullPointerException`、配置 key 这类必须逐字精确的 token（BM25 已给 `symbol_names`/`config_keys`/`error_codes` 加 7-8 倍权重），LLM"润色"可能把精确匹配改没。
- **Pros:** 扩写若命中领域黑话场景可直接提升召回，且纯词典方案零 LLM 调用、零延迟成本。
- **Cons:** 需要自建技术领域同义词表（数据工作）；无证据前属预防性堆功能。
- **Context:** 2026-07-15 结合外部学习材料与 rag系统1/rag系统2 对比讨论。两个旧项目都有扩写但均来自 RAGFlow（rag系统2 直接复制了 `FulltextQueryer`：同义词词典降权拼进查询 + 正则清洗疑问虚词；rag系统1 调 RAGFlow API 且 `keyword=true`）。**结论：现在不加**——基线 Recall@5=0.904，应先对 eval-set-v2 上约 12 道 Recall@5 失败题做错误归因，确认失败原因确实是同义词错配再动手。实现方式必须自研（CLAUDE.md 禁止复制 RAGFlow 代码）：自建小型同义词表 + 在 `ElasticsearchHybridCandidateSource.searchBm25()` 的 should 子句里加降权同义词匹配，几十行即可。重写维持关闭，理由已写在 `QueryController.QueryRequest` 注释里。
- **Depends on / blocked by:** 前置步骤是失败题错误归因（评估集与脚本已就绪，随时可跑）。

## 查询意图识别(deferred，2026-07-15 讨论记录，含数百意图规模化方案)

- **What:** 检索前先判断用户"想干啥"（如 API 用法类/故障排查类/配置说明类），据此调整检索策略。三条路线按成本递增：①规则/关键词（意图少、词表稳定时够用）；②BERT 类分类器（需标注数据）；③LLM Prompt 直判（零样本可用，有延迟成本）。实务常组合：先 LLM 粗分类冷启动，攒够数据后训 BERT 分类器。当前完全没有：`kbId` 是用户手动选的，`HybridRetriever` 对所有问题走同一套固定流程和参数。
- **Why:** 意图不同该走的检索/回答策略不同；它也是"RRF 融合动态权重"（见上一条）的必要前置——动态权重需要先知道 query 是精确型还是语义型。
- **Pros:** 打开动态权重、按意图路由检索范围/参数等一系列优化的前提。
- **Cons:** 每次查询多一层判断（LLM 路线加延迟和成本）；意图体系需要产品层面先定义清楚，rag-kb 目前单一技术问答场景下意图类别可能不足以支撑收益。
- **意图规模化（若未来意图数达数百）:** 两种成熟方案——①检索式意图识别（推荐）：把每个意图描述当"文档"建向量库，先召回 top-10 候选意图再让 LLM 从中选，prompt 里永远只出现 10 个（复用现有检索能力）；②两级分类：先粗分大类（10 个以内）再在命中大类里细分，代价是维护两层意图树。核心思想相同：别让模型一次面对几百个选项，先用检索/分层把候选缩到个位数。
- **Context:** 2026-07-15 结合外部学习材料讨论。若启动，建议从最简单的规则/关键词路线起步（识别 query 是否含类名/错误码/配置 key 特征，正则即可），不要一上来就上分类器。
- **Depends on / blocked by:** 无硬阻塞；但建议先等"动态权重"条目的分类误差分析给出证据（意图区分确实带来 Recall 差异）再投入。

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
