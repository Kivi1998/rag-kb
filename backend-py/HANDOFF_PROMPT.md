你要接手一个 Java→Python 的后端迁移任务,以下信息完全自包含,不需要额外上下文。

## 项目背景

`/Users/kivi/Documents/rag系统/rag-kb/` 是一个 toB 企业级文档知识库项目(原 Spring Boot + Vue3),正在把整个 Java 后端(`backend/`)重写成 Python FastAPI(`backend-py/`)。当前在分支 `feat/py-fastapi-migration` 上。速度优先、成本不计,先出功能后补测试,**但多租户隔离相关代码必须写对,不允许明知有洞还交付**——这是 toB 红线,一旦漏了一处过滤逻辑,后果是 A 公司能检索到 B 公司的私有文档。

## 已经建好、你可以直接 import 的共享基础设施

- `app.core.config.settings`:Pydantic Settings,`application.yml` 里所有 `rag.*`/`server.*` 配置项都已映射(如 `settings.rag_vector_provider`、`settings.rag_milvus_*`、`settings.rag_es_*`、`settings.rag_memory_*`、`settings.rag_upload_*` 等),不要自己重新读环境变量。
- `app.core.db`:`Base`(SQLAlchemy declarative base)、`get_db()`(FastAPI 依赖,产出 `AsyncSession`)。
- `app.core.tenant_context`:`get_tenant_context()` 返回当前请求的 `TenantContext(org_id, member_id, role)`。
- `app.core.security`:JWT 鉴权依赖(`require_user_factory`/`require_tenant_factory`)。
- `app.ragcore.model`(注意是单数 `model` 不是 `models`):`Chunk`、`RetrievedChunk`、`Citation`、`EmbeddingResult`、`QueryEvent`/`QueryEventType`、`ModelClientException` 这几个共享数据类型定义在这里,新代码需要这些类型就从这里 import,不要重新定义。
- `app.ragcore.index.ports`:`ChunkIndex`/`LexicalChunkIndex`/`VectorChunkIndex` 三个 Protocol 接口已定义。
- `app.ragcore.index.search_request.SearchRequest`:带租户边界的检索请求 dataclass(`organization_id`/`knowledge_base_id`/`query`/`top_k`/`document_ids`),已做非空校验。
- `app.ragcore.index.es_chunk_index.ElasticsearchChunkIndex`:ES 词法投影适配器已实现(`stage`/`activate_document`/`deactivate_document`/`delete_by_document_id`),它的 `search()` 方法故意不实现(和 Java 版一样,防止暴露无租户过滤的泛型查询入口)——真正的检索必须走你要写的 `HybridRetriever`。

**已知遗留问题,不用你处理,但请不要被它误导**:`app/ragcore/models.py`(复数)和 `app/ragcore/model.py`(单数)当前存在重复/冲突的模型定义,是之前并行开发遗留的,后续会统一收敛。你写新代码时一律从 `app.ragcore.model`(单数)import,不要碰 `models.py`(复数)。

## 你的任务:7 个模块,按优先级从高到低

### 优先级 1(最重要,必须先做):ragcore/retrieval + ragcore/intent

这是全项目安全要求最高的模块。

**源代码(只读)**:
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/retrieval/`(全部 19 个文件:`HybridRetriever`/`LexicalCandidateSource`/`VectorCandidateSource`/`ChunkHydrator`/`ElasticsearchLexicalCandidateSource`/`ElasticsearchVectorCandidateSource`/`ElasticsearchHybridCandidateSource`/`MilvusVectorCandidateSource`/`ProviderVectorCandidateSource`/`RrfFusion`/`RetrievalOptions`/`RetrievalResult`/`RetrievalDiagnostics`/`VectorHit`/`VectorSearchRequest`/`VectorRetrievalMetrics` 等)
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/intent/`(`LlmQueryIntentClassifier`/`QueryIntent`/`QueryIntentClassifier`)

**必读背景文档(先读理解设计意图,不要只看代码)**:
- `/Users/kivi/Documents/rag系统/rag-kb/docs/混合检索指南.md`
- `/Users/kivi/Documents/rag系统/rag-kb/docs/architecture.md` 决策 4(多租户隔离)、决策 12(Milvus 迁移)
- `/Users/kivi/Documents/rag系统/rag-kb/docs/Milvus向量检索迁移设计.md`
- `/Users/kivi/Documents/rag系统/rag-kb/docs/Query理解与改写现状.md`(意图分类部分)

**极其重要的历史教训**:Java 版 review 时发现过一个 HIGH 级别真实漏洞——`MilvusVectorIndex.setVisibility()` 原来用单次 `QueryReq(limit=16384)` 查询,超过 16384 个 chunk 的文档做可见性翻转(比如删除文档)时,超出部分会静默不生效,导致本该不可见的内容仍可被检索到。Java 版已修复成 offset 分页遍历。**移植时必须确认 Milvus 相关代码是分页实现,不能移植回有 bug 的旧版本。**

**多租户过滤三重校验(必须全部保留)**:
1. Milvus 侧参数化过滤(查询时按 org_id/kb_id 过滤,不是查完再过滤)
2. Milvus 命中的 chunk_id 回 ES 批量补正文时,ES 侧再做一次 org_id/kb_id 过滤
3. 代码里对拿到的结果再做一次 org_id/kb_id 显式比对(纵深防御)

**目标目录**:
- `/Users/kivi/Documents/rag系统/rag-kb/backend-py/app/ragcore/retrieval/`:`HybridRetriever`、`LexicalCandidateSource`/`VectorCandidateSource`/`ChunkHydrator` 端口(用 Python `Protocol`)+ 各自实现、`RrfFusion`、三模式切流(读 `settings.rag_vector_provider`,取值 `elasticsearch`/`shadow`/`milvus`)
- `/Users/kivi/Documents/rag系统/rag-kb/backend-py/app/ragcore/intent/`:意图分类 + 动态权重调整

ES 客户端用 `elasticsearch`(`AsyncElasticsearch`),Milvus 用 `pymilvus`,已在 `backend-py/pyproject.toml` 声明依赖。

写完后自己过一遍多租户三重过滤清单,在报告里逐条确认。

### 优先级 2:ragcore/memory(会话记忆)+ ragcore/audit(查询审计)

**源代码**:
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/conversation/`(整个目录)
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/audit/`

**必读背景**:`/Users/kivi/Documents/rag系统/rag-kb/docs/architecture.md` 决策 4 和决策 6。**注意**:2026-07-15 修复过一个真实漏洞——`GET .../messages` 只校验 org/member 没核对 URL 里的 kbId 和会话真实归属 kb 是否一致,导致同组织同成员可跨知识库读取对话历史。这个校验逻辑必须完整移植。

MongoDB 层不能完全信任上游 ES 过滤结果,读回文档后要二次比对 org_id/member_id(纵深防御,不要精简掉)。

**目标目录**:`/Users/kivi/Documents/rag系统/rag-kb/backend-py/app/ragcore/memory/`(注意:这个目录已经有 1 个文件了,是被中断的上一个 agent 留下的,先读一下已有内容再继续,不要覆盖式重写)、`/Users/kivi/Documents/rag系统/rag-kb/backend-py/app/ragcore/audit/`

MongoDB 用 `motor`,Redis 用 `redis.asyncio`(这个模块要用独立逻辑 DB,按 `settings.rag_memory_redis_database`,不要复用 JWT 黑名单那个 DB 0 的连接)。

### 优先级 3:ragcore/upload + ragcore/storage + ragcore/ingestion + ragcore/quickdocument

**源代码**:
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/upload/`
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/storage/`
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/ingestion/`
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/quickdocument/`

**必读背景**:`/Users/kivi/Documents/rag系统/rag-kb/docs/architecture.md` 决策 11(单文档直接问答用长上下文直接塞入,不走切块检索)

**目标目录**:对应 `/Users/kivi/Documents/rag系统/rag-kb/backend-py/app/ragcore/upload/`、`storage/`、`ingestion/`、`quickdocument/`

对象存储用 `minio` Python SDK。

## 通用要求

1. **不要跑 `git add`/`git commit`**,只管写文件,commit 由项目负责人统一处理。
2. **不要动 `backend/`(Java 源码)**,只读不改。
3. 不用等外部 code review,但涉及租户过滤/权限校验的代码要自己确认过一遍逻辑正确,不能因为"先出功能"就跳过过滤条件本身。
4. 每个模块写完后跑一下能不能 `import`,基本语法/类型错误自己排除掉。
5. 全部做完后,给我一份总结:每个模块创建了哪些文件、多租户/权限相关校验逐条确认情况、有没有遇到需要人工确认的地方(比如源码里字段语义不清楚、Java 库没有直接对应的 Python 库需要换实现方案等)。
