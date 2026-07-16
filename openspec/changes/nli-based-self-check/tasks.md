## 1. `nli-gateway` Python 服务

- [x] 1.1 新建 `nli-gateway/` 目录，结构参照 `parser-gateway/`（`app/__init__.py`、`app/main.py`、`app/model.py`、`requirements.txt`、`.env.example`、`tests/`），但完全独立、不共享代码
- [x] 1.2 `app/main.py` + `app/model.py`：FastAPI 应用，启动时（lifespan）加载 `IDEA-CCNL/Erlangshen-Roberta-110M-NLI`（`BertForSequenceClassification`/`BertTokenizer`），提供 `GET /health`；`requirements.txt` 里 torch/transformers 版本按实际可安装解析结果锁定（torch==2.13.0/transformers==5.14.1，本机环境 torch==2.5.1 已不可用）
- [x] 1.3 实现 `POST /nli`：请求体 `{"premise": "...", "hypothesis": "..."}`，响应 `{"label": "entailment"|"neutral"|"contradiction", "entailment_prob": float, "neutral_prob": float, "contradiction_prob": float}`；真实模型冒烟测试确认输出顺序 [entailment, neutral, contradiction] 与模型卡片一致
- [x] 1.4 编写 Python 测试（`tests/test_nli.py`，6 个用例）：正常推理、premise/hypothesis 缺失时返回 422、health 端点两种状态；全部通过

## 2. 后端 `NliClient`

- [x] 2.1 新增 `NliClient` 接口（`backend/src/main/java/com/diit/ragkb/ragcore/nli/NliClient.java`），方法签名 `NliVerdict check(String premise, String hypothesis)`
- [x] 2.2 新增 `NliVerdict` record（label + 三个概率字段）
- [x] 2.3 新增 `HttpNliClient` 实现，HTTP 调用 `RAG_NLI_ENDPOINT`；新增独立的 `RagNliProperties`（`rag.nli` 前缀，不嵌套进 `RagModelProperties`，因为不是 OpenAI 兼容端点、不需要 apiKey/model 字段），`application.yml` 新增 `rag.nli.*` 映射
- [x] 2.4 Spring 配置：`RagModelConfiguration` 新增 `nliClient` bean，`@ConditionalOnProperty(prefix = "rag.nli", name = "enabled")`，`false`/未配置时不注册（`ObjectProvider<NliClient>` 取不到实例，走 fail-open）
- [x] 2.5 编写 `HttpNliClientTest`（3 个用例，用 `com.sun.net.httpserver.HttpServer` 起本地测试服务器，仿照 `OpenAiCompatibleChatCompletionClientTest` 的写法）：正常调用解析、HTTP 非 2xx 抛 `ModelClientException`、响应缺字段抛 `ModelClientException`；完整后端测试套件通过，无回归

## 3. 阈值校准（必须先完成，产出真实数字后才能进入第 4 组）

- [x] 3.1 扩大此前 6 条真实语料构造的测试样本到 26 条（`eval/datasets/nli-self-check-calibration-set.jsonl`），覆盖准确复述(8)/完全无关编造(6)/部分相关编造(7)/张冠李戴(5)四类，从 `rag_chunks_eval_v3` 对应语料摘取 8 段真实资料原文
- [x] 3.2 新增 `eval/scripts/analyze_nli_threshold.py`（仿照 `analyze_refusal_threshold.py`），跑真实 `nli-gateway` 记录每条样本的 `entailment_prob`，扫描候选阈值选 F1 最优点
- [x] 3.3 产出校准报告 `eval/reports/nli-threshold-calibration-20260716.md`——**负面结果**：形式上最优阈值 t=0.195（F1=0.837），但"应支撑"的 8 条样本 entailment_prob 全部很低（0.0006–0.2418，多数被判成 contradiction 而非 entailment），与"不该支撑"组高度重叠，F1 由 2 个孤立偏高点撑起，不是真实判别信号；排查确认不是截断问题（134 token，远低于上限），是 110M 模型对长篇技术中文的分布外问题
- [x] 3.4 用此前 6 条样本回归对照：F1 从 0.837 掉到 0.667（比上次 Reranker 的 4/6 命中率更差），证实上面的负面结论不是偶然

**⚠️ 用户决策（2026-07-16）：暂缓第 4-5 组，保留第 1-3 组的基础设施先提交。** `nli-gateway`/`NliClient` 默认 `rag.nli.enabled=false`，不影响现有 Reranker 版本的 `AnswerSelfChecker`（未被这次改动触碰），因此不需要"注释掉"任何东西。后续待办已记入 `TODOS.md`："自检机制仍待解决"条目——换一个更大的 NLI 模型（如 325M 的 `Erlangshen-MacBERT-325M-NLI-Chinese`）重新跑 `analyze_nli_threshold.py` 校准，通过后再回来完成第 4-5 组。

## 4. `AnswerSelfChecker` 重构（暂缓，等换更大模型重新校准通过后再做；使用第 3 组产出的真实阈值）

- [ ] 4.1 `AnswerSelfChecker` 构造参数从 `RerankerClient` 改为 `NliClient`
- [ ] 4.2 "有引用句子"核查逻辑改为：对每个引用资料调用 `NliClient.check(premise=资料原文, hypothesis=句子)`，取多次调用里 `entailment_prob` 最高的一次
- [ ] 4.3 用第 3 组校准报告产出的真实阈值判定"是否支撑"（写入常量并注明来源报告文件名与日期，不写占位数字）
- [ ] 4.4 "无引用长句直接判定未标注"规则保持不变
- [ ] 4.5 `QueryService`/`RagQueryConfiguration` 装配点从注入 `RerankerClient` 改为注入 `ObjectProvider<NliClient>`；`NliClient` 不可用时自检整体 fail-open（跳过，不影响主流程）
- [ ] 4.6 更新 `AnswerSelfCheckerTest`：原来针对 `RerankerClient` 的 stub 改为 `NliClient` stub，覆盖 entailment_prob 高/低两种判定、`NliClient` 调用异常 fail-open
- [ ] 4.7 更新 `QueryServiceTest` 中依赖 `RerankerClient` 触发自检的测试用例，改为用 `NliClient` stub

## 5. 验证与收尾

- [ ] 5.1 运行完整后端测试套件（`mvn test`），确认无回归
- [ ] 5.2 本地启动 `nli-gateway` + 后端 + 前端，真实浏览器验证：正常问答（自检无问题）、以及尽力构造一次能观察到 `self_check_warning` 的场景
- [ ] 5.3 `openspec validate --strict` 通过
