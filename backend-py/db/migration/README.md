# DDL 迁移脚本(从已退役的 Java 版 backend/ 恢复)

这 15 个 `V001__*.sql` ~ `V015__*.sql` 文件是 Java 版 `backend/src/main/resources/db/migration/`
的原始内容,在 commit `a3b9d3f`(退役 Java 后端)时随整个 `backend/` 目录一起被删除。

`backend-py/app/core/db.py` 的模块 docstring 写明:"Schema 由现有 Flyway 迁移
(`backend/.../db/migration`)管理,Python 侧不新建迁移工具,只做只读/读写访问层迁移,
DDL 权威来源不变"——也就是说 backend-py 从设计上就**从未实现自己的建表机制**,
一直依赖 Java 侧的 Flyway 迁移脚本作为唯一 DDL 权威来源。Java 删除之后,这个假设
的前提(Java 进程首次启动时 Flyway 自动执行迁移)不再成立,但 DDL 本身没有失效——
11 张表(`organization`/`team`/`member`/`knowledge_base`/`app_user`/`document`/
`ingestion_job`/`rag_query_audit`/`document_upload_session`/`chat_session`/
`intent_training_sample`)的表名已逐一核对,与 `backend-py/app/models/*.py` 里
`__tablename__` 完全一致。

## 为什么恢复到这里而不是 acceptance/

这是 backend-py 运行所需的通用 DDL,不是 acceptance 专属产物——任何真实部署
backend-py 连接一个全新 Postgres 实例都需要先跑这些迁移,不只是验收测试。放在
`backend-py/db/migration/` 而不是 `acceptance/` 下面,是为了让这份依赖关系对读代码
的人可见:acceptance 的 Postgres 初始化容器只是这份 DDL 的一个消费者。

## 已知技术债

backend-py 目前仍然**没有自己的迁移工具**(没有 Alembic,没有等价的 Python 迁移框架)。
这些 SQL 文件目前只是被动挂载给 `acceptance/compose.yml` 里的一次性 `flyway/flyway`
CLI 容器执行(见该文件的 `migrate` 服务),继续借用 Flyway 只是因为它是现成、无需额外
开发的执行器,不代表 backend-py 打算长期依赖 Java 生态的工具链。生产环境部署 backend-py
时如何建表(继续用 Flyway CLI,还是迁移到 Alembic 重新表达这些迁移)是一个未决问题,
不在本次"验收测试套件改造"任务范围内,记录在此留待后续处理。
