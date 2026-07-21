你要接手一个 Java→Python 迁移项目的补测试任务,以下信息完全自包含。

## 项目背景

`/Users/kivi/Documents/rag系统/rag-kb/` 是 toB 企业级文档知识库,正把 Java 后端重写成 Python FastAPI(`backend-py/`),分支 `feat/py-fastapi-migration`。核心代码已经写完,但因为是多个 agent 并行开发,很多模块的"验证"只是各自会话里临时跑了一次就没留下,仓库里实际上是 0 测试。

## 你的任务

给以下几层补齐**持久化、可在 CI 里复现**的 pytest 测试,写在 `/Users/kivi/Documents/rag系统/rag-kb/backend-py/tests/` 对应子目录下(仿照已有的 `tests/ragcore/chunk/test_technical_chunker.py`、`tests/ragcore/embedding/test_openai_compatible.py` 的风格:pytest class 分组 + 中文 docstring 说明测试意图)。

虚拟环境:`/Users/kivi/Documents/rag系统/rag-kb/backend-py/.venv/`,已装好依赖,可以直接 `.venv/bin/python -m pytest` 跑。

**范围 1:`app/ragcore/retrieval/`**(21 个文件,HybridRetriever/RRF融合/ES与Milvus候选源/意图权重)
- 对照 Java 源码:`/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/retrieval/`
- **重点必须覆盖多租户过滤**:构造跨组织/跨知识库的"越权" chunk,断言不会被返回(这是本项目 toB 红线,之前的 agent 报告说做过 mock 测试验证,但没留下文件,你需要重建这些测试)
- RRF 融合分数计算、MIN_RRF_SCORE/MIN_RERANK_SCORE 门槛判断、三模式切流(elasticsearch/shadow/milvus)路由逻辑

**范围 2:`app/ragcore/intent/`**(4 个文件)
- 对照:`/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/intent/`
- 重点:LLM 意图分类失败/超时时 fail-open 降级到 UNKNOWN,不能抛异常

**范围 3:`app/ragcore/index/`**(7 个文件,ES 索引 + Milvus 索引 + 可见性回填)
- 对照:`/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/index/`
- **重点必须覆盖**:`milvus_vector_index.py` 里的 `setVisibility` 分页逻辑——构造超过一页(16384)的数据量场景,断言全部被翻转可见性,不能只处理第一页就退出(这是本项目历史上真实出现过的 HIGH 级别 bug,必须有回归测试防止再犯)

**范围 4:`app/ragcore/memory/`**(30 个文件)+ `app/ragcore/audit/`(2 个文件)
- 对照:`/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/conversation/`、`.../audit/`
- **重点必须覆盖**:kbId 跨知识库读取防护——构造同组织同成员但 kb_id 不同的会话消息,断言查询结果不包含越权数据(2026-07-15 这里出过真实漏洞,必须有回归测试);各组件的 fail-open 降级(摘要失败、指代消解异常、Redis 不可达等)

**范围 5:`app/services/`**(11 个文件)+ `app/routers/`(8 个文件,除了 documents.py/query.py/quick_documents.py 这 3 个还没接进 main.py 的,其余都已经在跑)
- 对照:`/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/service/`、`.../controller/`
- 用 FastAPI 的 `TestClient` 写端到端的路由测试(不需要真实数据库,用 `unittest.mock` mock 掉 repository 层,或者如果你判断值得的话可以引入 `pytest-asyncio` + 内存 SQLite 做真实的 DB 层集成测试——自己判断哪种性价比更高,两种都可以接受)
- **重点必须覆盖**:密码 hash round-trip(注册时 hash、登录时验证)、JWT 鉴权依赖在缺 token/token 过期/token 在黑名单时正确返回 401、`require_tenant_factory` 在缺 `X-Org-Id` 头或该主体不属于该组织时正确拒绝

## 已知的、测试里应该体现的行为

- `app.ragcore.retrieval.hybrid_retriever.MIN_RERANK_SCORE` 是从 `app.ragcore.rerank.thresholds` import 的(不是本地定义),值是 0.06,不要在测试里断言错误的数值
- `app.ragcore.index.milvus_collection_manager.MilvusCollectionManager.EMBEDDING` 是 Milvus 向量字段名的唯一权威来源(`"embedding"`),`app.ragcore.retrieval.milvus_vector_candidate_source.py` 现在也是从这里 import,不是本地硬编码
- 多租户共享类型统一从 `app.ragcore.model`(单数)import,不要用 `app.ragcore.models`(复数,是历史遗留的重导出兼容层)

## 验证

写完后跑:
```
.venv/bin/python -m pytest -q
```
确认新增测试全部通过,已有的 198 个测试不能变红。

## 不要做的事

不要跑 `git add`/`git commit`;不要动 Java 源码;**只写测试文件,不要修改 `app/` 目录下任何已有的实现代码**——如果测试过程中发现真的有逻辑 bug(不是"风格不同"，是"结果真的错了"),不要自己改,在报告里明确指出文件、行号和期望行为 vs 实际行为，交给我们决定怎么处理。

完成后给我简短总结:每层写了多少测试、全部跑通了吗、有没有发现疑似的真实 bug(哪怕没有修)、有没有需要人工确认的地方。
