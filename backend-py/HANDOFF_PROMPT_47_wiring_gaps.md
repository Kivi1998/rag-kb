你要接手一个 Java→Python 迁移项目里三个零散的装配缺口,以下信息完全自包含。这三个问题彼此独立,不分先后,都是小范围改动。

## 项目背景

`/Users/kivi/Documents/rag系统/rag-kb/` 是 toB 企业级文档知识库,正把 Java 后端重写成 Python FastAPI(`backend-py/`),分支 `feat/py-fastapi-migration`。虚拟环境在 `/Users/kivi/Documents/rag系统/rag-kb/backend-py/.venv/`。

## 缺口 1:MemoryIndex(ES 实现)没有共享客户端工厂

**现状**:`/Users/kivi/Documents/rag系统/rag-kb/backend-py/app/routers/chat_sessions.py` 第 47-53 行:

```python
def _memory_index() -> MemoryIndex | None:
    """MemoryIndex(Elasticsearch 实现)依赖的 AsyncElasticsearch 客户端目前尚未有统一的
    应用级工厂(检索/索引层的 DI 组装由其他并行任务负责),暂时始终降级为 None——
    等 ES 客户端工厂就绪后,在这里按 `ElasticsearchMemoryIndex(es_client)` 装配即可,
    `ChatSessionService` 已经按"None = 不可用"做了优雅降级,不需要改调用方。
    """
    return None
```

`app/ragcore/memory/elasticsearch_memory_index.py` 里的 `ElasticsearchMemoryIndex` 类已经实现好了,缺的只是一个能拿到 `AsyncElasticsearch` 客户端实例的地方。

**任务**:
1. 在 `app/core/` 下新建 `es_client.py`,参考 `app/core/redis_client.py` 的写法风格,基于 `app.core.config.settings` 里的 `rag_es_endpoint`/`rag_es_api_key`/`rag_es_connect_timeout_ms`/`rag_es_socket_timeout_ms` 建一个模块级单例 `AsyncElasticsearch` 客户端(参考 `app/ragcore/index/es_chunk_index.py` 或 `app/ragcore/retrieval/` 下 ES 相关文件是怎么建 `AsyncElasticsearch` 实例的,保持配置方式一致)。
2. 改 `app/routers/chat_sessions.py` 的 `_memory_index()`,当 `settings.rag_es_enabled` 为真时,用这个共享客户端装配 `ElasticsearchMemoryIndex(es_client)` 并返回;否则仍然返回 `None`。
3. 验证:`.venv/bin/python -c "import app.main"` 正常。

## 缺口 2:会话记忆清理任务没有接入 FastAPI lifespan

**现状**:`app/ragcore/memory/memory_cleanup_task.py` 里的 `run_cleanup_loop()` 函数已经写好了(第 25 行开始),docstring 里写着"启动方式:在 FastAPI lifespan 里 `asyncio.create_task(run_cleanup_loop(...))`",但没有人真的在 `app/main.py` 里这样做。

**任务**:
1. 读 `run_cleanup_loop()` 的完整签名,确认它需要哪些参数(大概率需要某个 store/repository 实例和一个间隔时间配置)。
2. 改 `/Users/kivi/Documents/rag系统/rag-kb/backend-py/app/main.py`,把当前的 `FastAPI(title=...)` 构造改成用 `lifespan` 参数(FastAPI 的 `@asynccontextmanager` 风格,参考 `parser-gateway/app/main.py` 里 `lifespan` 的写法作为 Python 侧同风格项目的参考),在应用启动时 `asyncio.create_task(run_cleanup_loop(...))`,应用关闭时妥善取消这个 task(`task.cancel()` + `await` 等它真正结束,不要留孤儿任务)。
3. 只在 `settings.rag_memory_enabled` 为真时才启动这个清理任务,关闭时不需要启动(对应 Java 版"记忆子系统关闭时不应尝试连接任何 Mongo/Redis"的原则)。
4. 验证:`.venv/bin/python -c "import app.main"` 正常;如果你能在测试里验证 lifespan 正确启动/关闭 task 也可以顺手加一个(用 FastAPI `TestClient` 的 context manager 形式会触发 lifespan)。

## 缺口 3:Milvus 三模式切流的 shadow_executor 只是占位参数

**现状**:`/Users/kivi/Documents/rag系统/rag-kb/backend-py/app/ragcore/retrieval/provider_vector_candidate_source.py` 第 55 行左右:

```python
shadow_executor: Any | None = None,
# shadow_executor 暂未启用——影子读 fire-and-forget 在事件循环上调度,
```

`pymilvus` 的客户端调用是同步阻塞的,如果影子模式(`rag.vector.provider=shadow`)下直接在事件循环里调用同步 Milvus 查询,会阻塞其他并发请求。

**任务**:
1. 读 `provider_vector_candidate_source.py` 完整文件,理解影子读(shadow read)目前是怎么调度的("fire-and-forget 在事件循环上调度"具体是什么写法)。
2. 改成用 `asyncio.to_thread(...)` 包裹同步的 Milvus 调用,不要让阻塞的 pymilvus 调用直接占用事件循环线程。参考 `app/ragcore/index/milvus_vector_index.py` 或 `app/ragcore/retrieval/milvus_vector_candidate_source.py` 里其他地方是怎么用 `asyncio.to_thread` 包 pymilvus 调用的,保持写法一致。
3. `shadow_executor` 这个参数——如果改完之后不再需要外部传入线程池执行器(`asyncio.to_thread` 用的是默认线程池,不需要调用方传),可以把这个参数删掉;如果你觉得保留一个可选的自定义 executor 参数更合理(比如未来想控制线程池大小),也可以保留但要真正接入 `loop.run_in_executor(shadow_executor, ...)`。两种做法都行,自己判断,但不能像现在这样留一个完全没用到的占位参数。
4. 验证:`.venv/bin/python -c "from app.ragcore.retrieval import provider_vector_candidate_source"` 正常。

## 通用要求

- 虚拟环境:`.venv/bin/python`,改完三处后统一跑一遍 `.venv/bin/python -m pytest -q`,确认 198 个已有测试不能变红。
- 不要跑 `git add`/`git commit`。
- 不要动 Java 源码。
- 这三个缺口互相独立,可以按任意顺序做,但**改动范围要收紧**——只改这三处提到的具体文件,不要顺手"优化"其他不相关的代码。

完成后给我简短总结:三个缺口分别怎么修的、验证结果如何、有没有需要人工确认的地方(比如缺口 1 里 ES 客户端的具体连接参数是否要和已有的其他 ES 客户端建立方式对齐,建议你花点时间核实清楚)。
