## Context

用户希望在知识库问答之外支持"上传单个文档、立即针对这份文档回答"的模式（长上下文直接塞入，跳过切块/向量化/索引），参考了同类项目 rag系统2 的 `quick_parse` 实现（session 级临时文档、Redis 缓存、硬截断），但重新校准了参数——rag-kb 用的 `deepseek-chat` 上下文窗口是 128K token（官方文档：输入+输出合计不超过 128K，默认最大输出 4000 token），远大于 rag系统2 原本设定的 4000 字符。

brainstorming 阶段已与用户逐项确认的关键决策（design 阶段不重新讨论）：依附现有 `ChatSession`（不新建独立会话模型）；允许同一会话挂多个临时文档，共享一个会话级总额度池，超额直接拒绝新上传（不做静默截断/挤占旧文档）；支持 `DocumentParserFactory` 全部格式，含需要 parser-gateway 的 OCR/ASR；上传接口同步阻塞，不做异步状态机；会话挂了临时文档时，知识库检索触发拒答阈值不再拒答，改用临时文档内容回答。

## Goals / Non-Goals

**Goals:**
- 会话内临时文档的上传/查询/删除、大小限额、Redis 存储与生命周期。
- 复用现有解析（`DocumentParserFactory`）、生成（`AnswerGenerator`）、引用（`CitationBuilder`）、自检（`AnswerSelfChecker`）基础设施，新增代码只聚焦"临时文档的存取与拼接"这一层。
- 多租户隔离：临时文档只在创建它的会话内可见，Redis key 必须绑定 `sessionId`（进而绑定 `orgId`/`kbId`/`memberId`），不给跨会话/跨租户读取留任何路径。

**Non-Goals（同 proposal.md，重申）:**
- 不写入知识库、不参与切块/向量化/索引；不做跨会话共享、下载/导出；不做异步任务状态机；不做按组织可配置的额度/开关粒度；不改动 `HybridRetriever` 拒答阈值本身的校准逻辑。

## Decisions

### 1. 字符预算：会话级共享 15000 字符池，超额拒绝新上传

**决策**：`deepseek-chat` 128K token 窗口，扣掉默认最大输出 4000 token、会话记忆滑窗预算 1000 token（`RagMemoryProperties.tokenBudget`）、知识库检索片段预留约 4800 token（`resultLimit=8` × 目标切块大小上限 600 token）、system prompt 与用户问题预留约 1200 token，剩余仍有极大余量；出于"不需要顶格用满、留足安全边际"的考虑，给临时文档池定一个明显比 rag系统2 慷慨、但仍只占上下文窗口一小部分的额度：**15000 字符**（中文按约 1.5 token/字符估算，约合 22500 token，占 128K 窗口不到 18%）。

同一会话内所有临时文档共享这一个池，新上传会先检查"已用字符数 + 新文档解析后字符数"是否超过 15000，超过则直接拒绝该次上传（HTTP 400 + 明确错误信息"会话临时文档总额已满，请先删除一个再上传"），不做静默截断挤占已有文档、也不做自动淘汰最旧文档——这两种"自动化"行为都会让用户搞不清楚当前上下文里实际还剩什么内容，拒绝更可预测。

**备选方案**：直接照搬 rag系统2 的 4000 字符/PDF 4 页。放弃原因：没有利用 `deepseek-chat` 实际可用的窗口空间，用户已在 brainstorming 阶段明确要求重新校准。

### 2. 解析后统一按字符数截断，不做 PDF 专门的页数预检查

**决策**：rag系统2 对 PDF 是"页数"限制、对 DOCX/TXT 是"字符数"限制，两套规则。本设计统一：所有格式先经 `DocumentParserFactory.parse()` 解析成结构化文本，再对解析结果（拼接后的纯文本）应用同一个字符数上限——因为解析器已经把格式差异抹平了，没必要在截断规则上再按格式分叉。超出总额度池剩余空间的部分直接拒绝整次上传（而不是"允许上传但截断内容"），因为已经决定"超额拒绝"而非"截断"（见决策 1）。

### 3. 存储层：新独立 Redis 逻辑 DB，不耦合 `rag.memory.enabled`

**决策**：新增 `RagQuickDocumentProperties`（`@ConfigurationProperties(prefix = "rag.quick-document")`，字段 `enabled`（默认 `true`）、`redisDatabase`（默认 `2`）、`ttlHours`（默认 `2`，对齐 `RagMemoryProperties.sessionIdleHours` 和 `chat_session` 的 ARCHIVED 阈值）、`maxTotalCharacters`（默认 `15000`，做成可调配置项，不是硬编码常量——这个数字本身就是"重新校准"出来的估算值，不像 `MIN_RERANK_SCORE` 那样是拿评估集校准过的，留活口更合适）。

Redis 现状：JWT 黑名单用默认 DB 0；`rag.memory` 会话记忆子系统用独立逻辑 DB 1（`rag.memory.enabled` 门控，且要求 `mongo-uri`）。本功能**不能耦合 `rag.memory.enabled`**——`ChatSession`/`QueryController` 的核心问答链路本来就不依赖可选的记忆子系统，临时文档功能是核心问答能力的一部分，不应该因为用户没开会话记忆就跟着不可用。装配方式仿照 `RagMemoryConfiguration` 里 `memoryRedisConnectionFactory`/`memoryRedisTemplate` 的写法，但用独立的 `@Bean` 名字（如 `quickDocumentRedisTemplate`）和独立的连接工厂，指向 DB 2，`@ConditionalOnProperty(prefix = "rag.quick-document", name = "enabled", havingValue = "true")` 门控，默认开启。

**备选方案**：复用 DB 0（JWT 黑名单）加前缀区分。放弃原因：DB 0 的注释明确写着"专供 JWT 黑名单"，混入其他键类型破坏这个既有约定，而且黑名单和临时文档的 TTL/清理策略完全不同，混在一个 DB 里增加运维排查成本。

### 4. Redis 数据结构

```
quickdoc:content:{docId}      → JSON（filename, question 无关内容不适用，contentText, characterCount, createdAt），TTL=ttlHours
quickdoc:session-index:{sessionId} → Set<docId>，成员随内容 key 过期自然失效需要自愈：
                                      每次读取时对 Set 成员做 MGET，丢弃已过期（MGET 返回 null）的 docId
                                      并异步 SREM，不依赖 Set 本身的精确 TTL 同步
```

选择"内容 key 独立 TTL + 索引 Set 自愈清理"而不是给整个 Set 也设精确 TTL，是因为 Redis 原生不支持 Set 单个成员的 TTL，硬同步 Set 的整体 TTL 需要每次写入都重置，容易因为漏更新导致 Set 过期时间和内容 key 不一致；读时自愈更简单可靠，成本是多一次 MGET，量级很小（一个会话最多几个临时文档）。

**会话活跃续期**：每次该会话发起一次问答（无论是否用到临时文档），命中的临时文档 key 的 TTL 重置为 `ttlHours`（对齐 `chat_session` 因新消息从 IDLE/ARCHIVED 续期回 ACTIVE 的既有行为）；未被本轮问答引用到的临时文档不续期（正常过期）。

### 5. 与检索/生成链路的集成点

`QueryService.prepare()` 里，在 `retriever.retrieveWithDecision(...)` 之后：

```java
List<RetrievedChunk> quickDocChunks = quickDocumentService.buildRetrievedChunks(sessionId, organizationId, knowledgeBaseId);
if (result.refused() && quickDocChunks.isEmpty()) {
    return PreparedQuery.refused(question, resolvedQuestion, result.refusalReason(), audit);
}
List<RetrievedChunk> combinedChunks = new ArrayList<>(quickDocChunks);
if (!result.refused()) {
    combinedChunks.addAll(result.chunks());
}
```

临时文档包装成合成 `RetrievedChunk`：`Chunk.documentId` 用临时文档自己的 `docId`（`UUID`），`content` 是解析+截断后的全文，`bm25Rank`/`vectorRank`/`rrfScore`/`rerankScore` 均为 `null`（未经过检索排序，不适用），`finalScore` 设一个固定高值（如 `1.0`）让排序时排在检索结果前面（临时文档通常是用户当次最关心的内容）。`metadata` 里打一个 `quickDocument=true` 标记，便于后续如果要做"排除临时文档只看知识库命中"之类的诊断。

`CitationBuilder.build(chunks, documentNames)` 不需要改动——调用方在拼接 `documentNames` 这个 `Map<UUID,String>` 时，把临时文档的 `docId → 上传时的文件名` 也塞进去即可，`CitationBuilder` 内部本来就是从这个 Map 按 `documentId` 查名字，查不到才兜底成"已删除或不可访问的文档"。

### 6. API 与前端交互

- `POST /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}/quick-documents`（multipart 文件上传，同步阻塞，返回 `{docId, filename, characterCount, truncated:false}`；超额度返回 400）
- `GET .../quick-documents`（列出当前会话已挂的临时文档，供前端展示"已用 X/15000 字符"）
- `DELETE .../quick-documents/{docId}`（删除一个，释放额度池空间）

前端：`ChatPanel.vue` 新增一个"临时文档"入口（按钮+已挂文档小列表，复用 `DocumentPanel.vue` 的文件选择/拖拽交互，不需要它的状态轮询逻辑），上传时按钮转圈禁用，同步等待接口返回。

## Risks / Trade-offs

- **[风险] 同步阻塞上传遇到大文件走 OCR/ASR 可能耗时较长（前端长时间转圈）** → **缓解**：用户已在 brainstorming 阶段明确选择同步而非异步轮询，接受这个权衡；后端 HTTP 客户端/网关调用需要设置足够长的超时（复用 `DocumentParserFactory`/`HttpMultimodalDocumentParser` 现有超时配置，不额外收紧）。
- **[风险] 临时文档绕过知识库拒答阈值，理论上任何人传一份不相关文档也能让本该拒答的问题得到"回答"** → **缓解**：这是功能本身的设计目的（用户主动上传就是想问这份文档），不是缺陷；引用来源会明确标注来自"上传的文件名"而非知识库文档，前端应能区分这两类来源（复用现有引用抽屉 UI，citation 的 `documentName` 已经能区分）。
- **[权衡] 15000 字符是估算值，不是像 `MIN_RERANK_SCORE` 那样经过评估集校准的数字** → 做成可调配置项（`rag.quick-document.max-total-characters`），上线后如果发现常见文档大小与这个额度不匹配，运维可以直接改配置，不需要代码变更。

## Migration Plan

1. 新增 `RagQuickDocumentProperties`/Redis 装配（默认开启，DB 2）——纯新增，不影响现有功能。
2. 新增 `QuickDocumentService`/Controller 端点——纯新增。
3. `QueryService.prepare()` 的改动是纯新增分支（`quickDocChunks` 为空时行为与现状完全一致），不影响没有使用这个功能的现有会话。
4. 回滚：直接回退代码版本即可，Redis 里的临时文档数据本身会随 TTL 自然过期，不需要额外清理步骤。

## Open Questions

无——关键参数（额度、TTL、格式范围、拒答例外）均已在 brainstorming 阶段确认；剩余的都是本文档已给出方案的实现细节。
