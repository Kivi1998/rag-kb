你要接手一个 Java→Python 迁移任务,以下信息完全自包含。

## 项目背景

`/Users/kivi/Documents/rag系统/rag-kb/` 是 toB 企业级文档知识库,正把 Java 后端(`backend/`)重写成 Python FastAPI(`backend-py/`),分支 `feat/py-fastapi-migration`。速度优先但安全/正确性关键代码必须写对,不允许明知有洞还交付。

## 你的任务

`app/ragcore/generation/` 目前只完成了 `citation_builder.py`/`client.py`/`metrics.py`/`prompt_assembler.py`,`client.py` 里已经定义了 `AnswerGenerator`/`ChatCompletionClient` 两个 Protocol,但**具体实现和自检/事实核验这块完全没写**。

**源代码(只读)**:
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/generation/OpenAiCompatibleChatCompletionClient.java`(80 行)
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/generation/OpenAiCompatibleAnswerGenerator.java`(145 行)
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/generation/FactVerificationGate.java`(146 行)
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/generation/AnswerSelfChecker.java`(106 行)
- `/Users/kivi/Documents/rag系统/rag-kb/backend/src/main/java/com/diit/ragkb/ragcore/generation/SelfCheckResult.java`(28 行)

**必读背景文档**:
- `/Users/kivi/Documents/rag系统/rag-kb/docs/评估指南.md`(NO_RETRIEVAL 事实核验 8/8、自检 4/6 已知局限的说明)
- `/Users/kivi/Documents/rag系统/rag-kb/eval/reports/no-retrieval-fact-verification-validation-20260716.md`
- `/Users/kivi/Documents/rag系统/rag-kb/eval/reports/multi-passage-fusion-and-self-check-validation-20260716.md`

**已有共享基础设施,直接 import,不要重新定义**:
- `app.ragcore.generation.client.AnswerGenerator`/`ChatCompletionClient`:Protocol,你的实现类要满足这两个接口
- `app.ragcore.generation.citation_builder`、`app.ragcore.generation.prompt_assembler`、`app.ragcore.generation.metrics.GenerationMetrics`:已完成,直接复用,不要重写
- `app.ragcore.rerank.thresholds.MIN_RERANK_SCORE`:拒答门槛,如果 `FactVerificationGate`/`AnswerSelfChecker` 逻辑里需要引用这个阈值,从这里 import,不要重新定义字面量
- `app.ragcore.model`(单数,不是 `models` 复数):`Chunk`/`RetrievedChunk`/`Citation`/`QueryEvent`/`QueryEventType`/`ModelClientException` 等共享类型,新代码统一从这里 import
- `app.ragcore.nli.gate`:NLI 自检网关已经实现,fail-open 降级模式(未启用/超时直接跳过)可以参考它的写法风格,`AnswerSelfChecker`大概率要调用这个模块

**目标目录**:`/Users/kivi/Documents/rag系统/rag-kb/backend-py/app/ragcore/generation/`,新增:
- `openai_compatible_chat_completion_client.py`
- `openai_compatible_answer_generator.py`(SSE 流式生成,产出 `QueryEvent` 序列)
- `fact_verification_gate.py`
- `answer_self_checker.py`
- `self_check_result.py`

## 技术要求

- HTTP 调用用 `httpx`(已在 `pyproject.toml` 声明)
- SSE 流式输出用 async generator,产出 `app.ragcore.model.QueryEvent`(CHUNK/SOURCE/REFUSAL/SELF_CHECK_WARNING/DONE/ERROR 六种事件类型已经定义好)
- 所有降级路径必须保留,不能因为"先出功能"删掉:Embedding 不可用→BM25-only(这个不归你管,是 retrieval 层的事)、Rerank 不可用→直接用 RRF 排序、**NLI/自检不可用→直接跳过检查,不阻塞主流程返回**(fail-open,这个必须做对)

## 测试

在 `/Users/kivi/Documents/rag系统/rag-kb/backend-py/tests/ragcore/generation/` 下补测试(已有 `test_citation_builder.py`/`test_client.py`/`test_metrics.py`/`test_prompt_assembler.py`,你新增的这几个类也要有对应测试文件),参考已有测试的风格(pytest class 分组 + 中文 docstring)。重点测试 fail-open 降级路径,这是最容易漏测又最容易在生产环境出问题的地方。

## 验证

虚拟环境在 `/Users/kivi/Documents/rag系统/rag-kb/backend-py/.venv/`:
```
.venv/bin/python -c "from app.ragcore.generation import openai_compatible_answer_generator, fact_verification_gate, answer_self_checker"
.venv/bin/python -m pytest -q
```
确认 import 正常、198 个已有测试不能变红(加上你新增的测试应该全部通过)。

## 不要做的事

不要跑 `git add`/`git commit`;不要动 Java 源码;不要动 `app/ragcore/generation/` 目录下已有的 4 个文件(citation_builder.py/client.py/metrics.py/prompt_assembler.py,已完成不需要改);不要动 `app/ragcore/retrieval/`、`app/ragcore/ingestion/`、`app/services/`、`app/routers/`(其他任务在处理或已完成,避免冲突)。

完成后给我简短总结:创建了哪些文件、fail-open 降级路径是否有测试覆盖、有没有需要人工确认的地方。
