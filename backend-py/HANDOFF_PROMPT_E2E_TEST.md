你要做一次 rag-kb Python 后端(backend-py/)的真实端到端联调测试,以下信息完全自包含。

## 背景

这是 Java→Python 迁移项目,代码层面已经全量迁移完成(model/service/repository/router/ragcore 全部子包,逐文件核对过)。但**从没有真正打开过 Embedding/Rerank/生成模型这几个开关跑过一次完整链路**——之前的测试都是关着这几个开关做的(只测了注册/登录/多租户/知识库管理这些不需要模型 API 的部分)。这次要做的就是把开关打开,上传一个真实文档,验证它能不能真的变成可检索、可问答的内容。

**这次会产生真实的小额 API 调用费用**(硅基流动 Embedding/Rerank + DeepSeek 生成,几分钱量级),这个已经跟人类确认过可以做。

## 环境现状

- 虚拟环境:`/Users/kivi/Documents/rag系统/rag-kb/backend-py/.venv/`
- 依赖服务(Postgres/Redis/MongoDB/MinIO/Elasticsearch)已经用 Docker Compose 起在仓库根目录 `compose.dev.yml` 里,容器名前缀 `rag-kb-`,确认都在跑:`docker ps --format "{{.Names}}\t{{.Status}}" | grep rag-kb`,应该有 6 个都是 healthy/up。如果没起,`cd /Users/kivi/Documents/rag系统/rag-kb && docker compose -f compose.dev.yml up -d`。
- `backend-py/.env` 当前把 `RAG_EMBEDDING_ENABLED`/`RAG_RERANK_ENABLED`/`RAG_GENERATION_ENABLED`/`RAG_INGESTION_WORKER_ENABLED` 都设成了 `false`。
- 仓库根目录 `/Users/kivi/Documents/rag系统/rag-kb/.env`(Java 后端在用的)里已经配好了真实的模型 API:硅基流动(`RAG_EMBEDDING_ENDPOINT`/`RAG_EMBEDDING_API_KEY`/`RAG_EMBEDDING_MODEL=BAAI/bge-m3`,`RAG_RERANK_*` 同理)和 DeepSeek(`RAG_GENERATION_*`)。**把这几个值原样抄到 `backend-py/.env`,不要自己编 key。**

## 你的任务

### 1. 改 `backend-py/.env`

把这几行从 `false` 改成 `true`,并把根目录 `.env` 里对应的真实 endpoint/api-key/model 三元组抄过来(`RAG_EMBEDDING_ENDPOINT`/`RAG_EMBEDDING_API_KEY`/`RAG_EMBEDDING_MODEL`、`RAG_RERANK_*`、`RAG_GENERATION_*` 六个变量原样照抄):

```
RAG_EMBEDDING_ENABLED=true
RAG_RERANK_ENABLED=true
RAG_GENERATION_ENABLED=true
RAG_INGESTION_WORKER_ENABLED=true
```

### 2. 重启后端

```bash
pkill -f "uvicorn app.main:app"
cd /Users/kivi/Documents/rag系统/rag-kb/backend-py
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8090 --reload > /tmp/rag-kb-py-uvicorn.log 2>&1 &
sleep 4
tail -30 /tmp/rag-kb-py-uvicorn.log
```

确认日志里出现"摄取 Worker 已启动"字样(对应 `app/main.py` lifespan 里的日志),没有报错、没有 `Application startup failed`。

### 3. 登录 + 建一个全新的知识库(不要用已有的两个真实 KB,避免污染已有数据)

```bash
curl -s --noproxy "*" -X POST http://127.0.0.1:8090/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@rag-kb.local","password":"Test12345678"}'
```

拿到 `token` 和 `orgId`(应该是 `5fb86aec-356e-473e-a6f5-e8ada23c4437`)。用这个 token 建一个新知识库(名字带上时间戳或"e2e-test"字样,方便识别):

```bash
curl -s --noproxy "*" -X POST http://127.0.0.1:8090/api/v1/knowledge-bases \
  -H "Authorization: Bearer <token>" -H "X-Org-Id: <org_id>" \
  -H "Content-Type: application/json" \
  -d '{"name":"e2e-test-kb"}'
```

拿到新 kb_id。

### 4. 上传一个真实文档

随便找一个小的 markdown 或 txt 文件(比如可以直接用 `/Users/kivi/Documents/rag系统/rag-kb/README.md` 或 `docs/` 下任意一篇文档,内容要有实质文字,不要空文件),用 `POST /api/v1/documents/upload` 上传到刚建的知识库。**这个接口是 `multipart/form-data`,`kb_id` 是 Form 字段(不是 URL 路径的一部分),`file` 是文件字段**,精确用法:

```bash
curl -s --noproxy "*" -X POST http://127.0.0.1:8090/api/v1/documents/upload \
  -H "Authorization: Bearer <token>" -H "X-Org-Id: <org_id>" \
  -F "kb_id=<新kb_id>" \
  -F "file=@/Users/kivi/Documents/rag系统/rag-kb/README.md;type=text/markdown"
```

响应里 `data.id` 是 document_id,轮询任务状态需要的 job_id 从上传响应或后续 `GET /api/v1/documents` 列表接口里的对应文档拿(具体看 `app/routers/documents.py` 的 `DocumentView`/`JobView` 返回结构,如果响应里没有直接给 job_id,查一下 `list_documents`/`get_job` 两个接口的关联方式)。

### 5. 轮询任务状态,验证真的处理完成

用返回的 job_id 或 document_id 轮询 `GET /api/v1/documents/jobs/{job_id}`(或者查文档状态的接口,看 `app/routers/documents.py`),每隔几秒查一次,**最多等 2 分钟**。关键验证点:

- 状态应该从 `QUEUED` 依次变成 `PARSING`→`CHUNKING`→`EMBEDDING`→`INDEXING`→`READY`(具体状态名以 `app/ragcore/ingestion/status.py` 为准),**不能卡在 QUEUED 不动**(这正是之前那个 bug 的症状,已经修过,这次是验证修复是否真的生效)。
- 如果卡住或变成 `FAILED`,去看 `/tmp/rag-kb-py-uvicorn.log` 里 Worker 相关的日志和报错堆栈,把完整报错贴出来。

### 6. 验证 ES 里真的有新 chunk

```bash
curl -s --noproxy "*" "http://127.0.0.1:9200/rag_chunks_v1/_count?q=knowledge_base_id:<新kb_id>"
```

数字应该大于 0。

### 7. 真实问答测试

**问答接口要求先创建一个会话(`session_id` 是必填字段,不能直接问)**,分两步:

**7a. 先建会话**:`POST /api/v1/knowledge-bases/{kb_id}/sessions`(看 `app/routers/chat_sessions.py`,应该不需要请求体或请求体很简单),拿到返回里的 `sessionId`。

**7b. 再问答**:`POST /api/v1/knowledge-bases/{kb_id}/query`,请求体是 JSON:

```json
{"question": "<和你上传文档内容相关的问题>", "sessionId": "<上一步拿到的 session_id>"}
```

这是 SSE 流式接口(`Content-Type: text/event-stream`),用 `curl -N`(不缓冲)或者写个 Python 脚本用 `httpx.stream()` 读取比较方便。**必须验证**:

- 能收到 SSE `chunk` 事件(回答内容分段推送)
- 能收到 SSE `source` 事件(带引用,citation 里的 `document_id` 应该等于你刚上传的那个文档)
- 最终有 `done` 事件正常结束,不是卡死或 `error` 事件

### 8. 清理

测试完成后,**把 `backend-py/.env` 的四个开关改回 `false`**(避免以后每次起服务都调用真实付费 API),恢复成测试前的状态。uvicorn 进程可以留着跑,或者你觉得需要的话重启一次让配置生效。

## 报告要求

请给出结构化报告,明确回答:

1. Worker 启动日志是否正常(贴关键行)
2. 文档状态是否真的从 QUEUED 走到了 READY(贴每次轮询看到的状态和耗时)
3. ES 里的 chunk 数量
4. 问答测试:问了什么问题、SSE 事件序列大概是什么样、回答内容摘要、citation 是否指向正确的文档
5. **如果任何一步失败或卡住,把完整报错堆栈贴出来,不要只说"失败了"**——这次的目的就是找出全链路里还有没有没暴露过的真实 bug
6. `.env` 是否已经改回 `false`

不需要写代码改动(这次是测试任务,不是开发任务),但如果测试过程中发现了明确的 bug(不是环境问题),照实报告,不要自己动手改代码,交给我们决定怎么处理。
