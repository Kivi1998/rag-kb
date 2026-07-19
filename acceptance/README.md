# 文档上传与解析生产同构验收

本目录验证真实的 PostgreSQL、Redis、MinIO、Elasticsearch、双摄取 Worker、OCR 与 ASR 网关。Embedding 使用可注入 429/5xx 的确定性协议替身，因此这里签收的是上传、解析、切块、模型协议容错和索引写入可靠性，不签收向量模型的检索质量。

验收数据固定为 5000 份，覆盖 Markdown、代码、JSON、DOCX、文本/图片型 PPTX、文本/扫描 PDF、PNG/JPG/TIFF、SRT/VTT、WAV/MP3 与 MP4/MOV/MKV。每份文件均通过 `initiate -> MinIO presigned PUT -> complete` 的真实 HTTP 链路进入系统。

首次修改解析链路时先运行每种格式 1 份的快速兼容性测试：

```bash
ACCEPTANCE_MODE=smoke docker compose -f compose.yml --profile acceptance up --abort-on-container-exit --exit-code-from runner runner
```

```bash
cd acceptance
docker volume create rag-parser-model-cache
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
export PATH="$JAVA_HOME/bin:$PATH"
mvn -f ../backend/pom.xml test package
docker compose -f compose.yml config -q
docker compose -f compose.yml --profile acceptance build
docker compose -f compose.yml --profile acceptance up --abort-on-container-exit --exit-code-from runner runner
docker compose -f compose.yml cp runner:/reports/acceptance-report.json ./reports/acceptance-report.json
```

每次完整验收必须使用空数据卷：

```bash
docker compose -f compose.yml --profile acceptance down -v --remove-orphans
```

通过条件：5000/5000 上传成功、5000/5000 最终 `READY`、内容哈希和解析产物路径均唯一且非空、全部写入解析时间、代表格式可从 MinIO 解析产物恢复出预期文本、OCR 格式有 OCR 证据、音视频有时间戳、Elasticsearch chunk 数量不少于 5000。默认模型替身的前两次 Embedding 请求返回 503，最终仍必须 0 失败。

## Worker 故障转移验收

全量摄取期间先查询 `PARSING` 且属于 `acceptance-worker-a` 的任务，记录任务 ID、`attempt` 和租约到期时间，然后执行：

```bash
docker stop -t 1 rag-kb-acceptance-worker-a-1
```

租约到期后，`worker-b` 日志必须出现过期租约恢复记录；受影响任务的 `attempt` 必须增加且最终为 `READY`。确认接管后恢复容量：

```bash
docker start rag-kb-acceptance-worker-a-1
```

本次通过证据见 `reports/failover-evidence.json`，5000 份原始结果见 `reports/full-5000-report.json`。故障注入必须发生在真实处理中任务上，不能仅用单元测试替代。

`model-stub` 只能用于链路和协议验收，禁止将其结果描述为真实向量模型的检索质量结果。

本地验收后端使用 `Dockerfile.acceptance`，以规避部分 Docker Desktop 环境的基础镜像清单缓存故障；正式发布镜像必须使用 `backend/Dockerfile` 的精简 JRE 多阶段构建。

## Milvus 验收边界

`compose.yml` 提供 `milvus` profile，用于启动隔离的 Milvus、etcd 和对象存储依赖：

```bash
export RAG_MILVUS_MINIO_ACCESS_KEY=<本地验收账号>
export RAG_MILVUS_MINIO_SECRET_KEY=<本地验收强密码>
docker compose -f compose.yml --profile milvus up -d milvus
```

该 profile 当前只签收基础设施可启动，不会自动把 5000 份验收 Worker 切到 Milvus，也不能替代
ES+Milvus 双写、检索、删除、跨租户隔离和 150 题质量对比。完整配置与待完成门槛见
[`docs/Milvus向量检索迁移设计.md`](../docs/Milvus向量检索迁移设计.md)。默认 5000 份验收仍以
Elasticsearch 投影为准。
