# Changelog

## [Unreleased]

在 `fix/model-client-force-http11` 分支，尚未合并进 main：

- **前端视觉改版** — 全局改为 Anthropic 风格设计语言（暖白背景、陶土色主色调、标题衬线字体），新增 `frontend/src/assets/theme.css` 覆盖 Element Plus 主题变量
- **模型客户端强制 HTTP/1.1** — `OpenAiCompatibleEmbeddingClient`/`OpenAiCompatibleRerankerClient`/`OpenAiCompatibleAnswerGenerator` 显式指定 `HttpClient.Version.HTTP_1_1`，规避部分本地模型网关不支持明文 h2c 升级协商的问题（该改动未能解决当次遇到的 502，真实根因见下方"已知问题"，但作为通用健壮性改进保留）

在 `feat/structure-aware-chunking-v3` 分支，尚未合并进 main：

### 新增

- **结构感知切分 V3 五招式** —— `TechnicalChunker` 新增多风格文档层级自动识别（`HeadingStyle`，
  支持含中文"第 N 章/条"在内的多种编号体系，识别不清时退化到既有 Markdown/空行分段逻辑）、
  结构→段落→句子三级递归降级、大表格分组分块并重复表头、overlap 比例区间与句子边界校验、chunk
  元数据增强（`sectionPath`/`contentType`/`isKeyClause`/`prevChunkId`/`nextChunkId`，均落在既有
  `metadata` Map，`Chunk` record 签名与 ES mapping 均无需改动）。`TechnicalChunkerTest` 从约 16 个
  测试扩到 30 个，新增 `HeadingStyleTest` 6 个，全量后端测试 135 个全部通过。ML 分类器兜底与
  prevChunkId/nextChunkId 检索侧自动补全明确不在本轮范围内，详见 [TODOS.md](TODOS.md)。

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

- 部分内网模型网关（如某些 Xinference 部署）对"请求头与请求体分两次 TCP 写入"处理有 bug，会向标准 HTTP 客户端（Java/Python）返回 502，curl 因单次写入不受影响；详见 [部署验收手册](docs/自研RAG摄取部署与验收手册.md) §6.6
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
