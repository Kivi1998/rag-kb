## 1. `nli-gateway` Python 服务

- [ ] 1.1 新建 `nli-gateway/` 目录，结构参照 `parser-gateway/`（`app/__init__.py`、`app/main.py`、`requirements.txt`、`.env.example`、`tests/`），但完全独立、不共享代码
- [ ] 1.2 `app/main.py`：FastAPI 应用，启动时加载 `IDEA-CCNL/Erlangshen-Roberta-110M-NLI`（transformers），提供 `GET /health`
- [ ] 1.3 实现 `POST /nli`：请求体 `{"premise": "...", "hypothesis": "..."}`，响应 `{"label": "entailment"|"neutral"|"contradiction", "entailment_prob": float, "neutral_prob": float, "contradiction_prob": float}`
- [ ] 1.4 编写 Python 测试（`tests/test_nli.py`）：正常推理、premise/hypothesis 缺失时返回 4xx、health 端点

## 2. 后端 `NliClient`

- [ ] 2.1 新增 `NliClient` 接口（`backend/src/main/java/com/diit/ragkb/ragcore/nli/NliClient.java`），方法签名如 `NliVerdict check(String premise, String hypothesis)`
- [ ] 2.2 新增 `NliVerdict` record（label + 三个概率字段）
- [ ] 2.3 新增 `HttpNliClient` 实现，HTTP 调用 `RAG_NLI_ENDPOINT`；新增 `RagModelProperties`（或独立配置类）里的 `rag.nli.enabled`/`endpoint`/`timeout-ms` 配置项
- [ ] 2.4 Spring 配置：`rag.nli.enabled=true` 时注册 `NliClient` bean，`false`/未配置时不注册（`ObjectProvider<NliClient>` 取不到实例，走 fail-open）
- [ ] 2.5 编写 `HttpNliClientTest`：正常调用解析、HTTP 异常抛 `ModelClientException`（参照 `OpenAiCompatibleRerankerClient` 的异常处理约定）

## 3. 阈值校准（必须先完成，产出真实数字后才能进入第 4 组）

- [ ] 3.1 扩大此前 6 条真实语料构造的测试样本到 20-30 条，覆盖准确复述/完全无关编造/部分相关编造/张冠李戴四类，继续从 `rag_chunks_eval_v3` 对应语料摘取资料原文
- [ ] 3.2 新增 `eval/scripts/analyze_nli_threshold.py`（或 Java 版本，仿照 `analyze_refusal_threshold.py`），跑真实 `nli-gateway` 记录每条样本的 `entailment_prob`，扫描候选阈值选 F1 最优点
- [ ] 3.3 产出校准报告 `eval/reports/nli-threshold-calibration-<日期>.md`（格式仿照 `refusal-threshold-calibration-20260714.md`），如实记录 F1/精确率/召回率与样本规模局限
- [ ] 3.4 用此前的 6 条样本作回归对照，记录新阈值下这 6 条的命中情况变化（不预设一定变好）

## 4. `AnswerSelfChecker` 重构（使用第 3 组产出的真实阈值）

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
