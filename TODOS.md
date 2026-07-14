# TODOS

延后但已记录的工作项。每项注明动机、现状与起点,避免日后丢失上下文。

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

## 切分质量真实评测（2026-07-14 已测得 BM25-only 基线，后续项如下）

**已完成**：`eval/scripts/EvalRetrievalRunner.java` 用产品真实检索代码
（`ElasticsearchChunkIndex` + `HybridRetriever`，embedding 不可达走产品 BM25-only
降级）对 61 题跑出首个真实基线：**Recall@5 = 0.094，MRR = 0.073，拒答 F1 = 0**。
报告与根因诊断：`eval/reports/eval-v3-bm25-real-20260714.md`。
低分是"模板题与 BM25 错配 + ES 无中文分词 + 向量召回缺位"三因素叠加，
不是 V3 切分质量的结论——解读务必看报告尾部诊断。

按预期收益排序的后续项：

- **评估集质量（最高优先）**：业务专家按 `eval/datasets/README.md` 复核清单精修 61 题——46/53 道是"这一节讲什么"模板题（BM25 词面零重叠），实体题存在 ground truth 漏标相邻 chunk 的假阴性（q-001 实锤）；拒答题多样化；扩到 200-300 题。
- **ES 中文分析器**：`content_search` 目前是 standard analyzer 字级切分，需加 IK/smartcn 并重建索引；`heading_path` 应参与 BM25 召回（题目自带"[文档/章节]"提示目前完全没用上）。
- **完整混合检索**：内网 Xinference 可达后（先起 `scripts/xinference-forward-proxy.py`），真实 embedding 重建向量、补跑 BM25+kNN+Rerank，与 BM25-only 基线对比。
- **V0 基线对比**：检出 `1fc29ab` 用同一工具重跑（注意 V0 切块产物 chunk_id 与现 ground truth 不同源，需按 content_hash 映射或重标）。此前一版"模拟对比数据"是随机数生成的，已删除，不可引用。
- **拒答阈值**：`MIN_RRF_SCORE=0.01` 对中文字级 BM25 无区分度（8 道拒答题全给了结果），需结合中文分词修复后重新校准。
- （已解决）~~后端 JWT_SECRET 阻塞~~：`.env` 与 `application-secret.yml` 本就存在，之前启动失败是没带环境变量；且本轮评测经 EvalRetrievalRunner 直连 ES，不需要起后端。

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
- **只用合成图片验证过，没有跑过真实 PDF 样本**：`parser-gateway/tests/test_deepdoc_pipeline.py` 里的双栏测试用的是程序画出来的合成图片，表格测试用的是 mock 的表格结构（绕开了版面模型是否真能把表格识别成"table"类型这一环）。真实扫描件/真实费率表 PDF 上的效果需要单独找样本验收。
- **印章压字（坑 3）仍未解决**：deepdoc 本身也没有针对性的印章检测/图层分离方案，这个坑目前四个参考项目（rag-kb、rag系统1/2/3）都没真正解决，见此前的调研结论。
- **`_ocr_bytes()`（DOCX/PPTX 内嵌图片）不做版面分析**：这是有意的简化，这类图片通常是单张截图/Logo，不是多栏页面。
- **Docker 镜像还没验证过完整跑通**：`Dockerfile` 已加 nltk 语料预下载，但没有实际 build 镜像跑过摄取全链路；本地验证用的是手工建的 venv。

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
