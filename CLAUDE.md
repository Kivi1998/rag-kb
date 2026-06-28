# CLAUDE.md — rag-kb 项目级开发规范

本文件为 rag-kb(toB 企业级文档知识库 / RAG)的项目级指令,Claude Code 在本仓库工作时 **必须** 遵守。

## 项目定位

- toB 企业级文档知识库,目标支持百人级团队协作
- 三层架构:Spring Boot 编排后端 → RAGFlow(RAG 引擎)→ Xinference(模型服务,LLM 优先小米 MiMo)
- 详见 [`README.md`](README.md)、[`docs/architecture.md`](docs/architecture.md)
- 规格驱动开发,规格在 [`openspec/`](openspec/);项目背景固化在 `openspec/config.yaml`

## Git 工作流(强制)

**所有功能开发走"分支 → 实现 → 合并 → 提交"流程,禁止直接在 `main` 上提交功能性改动。**

1. **建分支**:从最新 `main` 切出,命名 `<type>/<简述>`,type ∈ `feat` / `fix` / `docs` / `chore` / `refactor`
   - 一个 OpenSpec change 对应一个分支,如 `feat/tenant-kb-foundation`
2. **在分支上实现**:完成功能并跑通测试(多租户/权限改动必须含安全测试)
3. **评审门**:通过 `/review` + `/codex` + `/cso` 三轮评审,修复所有 CRITICAL/HIGH 发现
4. **提交 + 推送分支**:commit message 用中文 `<type>: <简述>`,结尾附 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`,`git push -u origin <分支>`
5. **创建 PR**:用 `gh pr create` 创建 Pull Request,PR body 包含 What/Why/Security/Tests/Review 摘要
6. **合并 PR**:评审通过后 `gh pr merge --merge`,切回 `main` 并 `git pull`
7. **清理**:删除已合并分支 `git branch -d <分支>`

## AI 增强开发三件套:按阶段路由 + 交接契约

三个工具在"规划"阶段能力三重重叠(OpenSpec propose / Superpowers brainstorming / gstack plan-eng-review 都能做),
在"代码评审"双重重叠。为避免互相打架,**每个阶段只认一个"权威所有者",重叠技能降级为辅助或弃用**。

各工具不可替代的内核:**OpenSpec = 把规格/变更持久化落盘(可评审、可归档进 `specs/`);
Superpowers = TDD 内循环纪律 + 自动触发;gstack = 接触真实外部世界(评审 / 安全 / 交付 / 反思)**。

| 阶段 | 权威所有者 | 辅助 | 交接产物 |
|------|-----------|------|---------|
| 规划·探索 | **Superpowers `brainstorming`**(自动触发,苏格拉底式追问) | OpenSpec `/opsx:explore` | 澄清后的想法 |
| 规划·定规格 | **OpenSpec `/opsx:propose`** | — | proposal / specs / design / tasks(落盘进 git) |
| 规划·评审(强制 ≥1 轮) | **gstack `/plan-eng-review`**;安全相关加 `/cso` | — | 评审决议回填进 design / tasks,`openspec validate --strict` 通过 |
| 实现 | **Superpowers TDD + 子 Agent**,按 `tasks.md` 逐项红绿重构 | OpenSpec `/opsx:apply` 当任务追踪 | 代码 + 测试 |
| 代码评审(强制,不可跳) | **gstack `/review`(Opus 4.8)+ `/codex`(跨模型第二意见)+ `/cso`**(OWASP/STRIDE 打多租户红线) | Superpowers `requesting-code-review`(实现期每任务内循环) | 评审结论 + 修复 |
| 交付 | **gstack `/ship`** + `/document-release` | — | PR + 文档更新 |
| 归档 | **OpenSpec `/opsx:archive`** | — | specs 提升到 `openspec/specs/` |
| 反思 | gstack `/retro` | — | learnings |

**模型与跨模型评审说明:**

- **强制评审门 = gstack `/review` + `/codex` 交叉模型 + `/cso`**:
  - `/review`、`/cso`、Superpowers `requesting-code-review` 跑在当前 Claude 会话模型;
  - `/codex` 是跨模型第二意见工具,具体使用哪个模型由用户配置决定,经 **cc-switch 本地代理**
    (`http://127.0.0.1:15721/v1`,request rectifier 矫正工具协议)接入。
  - 二者构成**跨模型交叉评审**:`/review` 与 `/codex` 都跑过同一分支后,gstack 给出交叉分析(哪些 bug 两边都报、哪些各自独有)。
- **`/codex` 的前置依赖**:依赖 **cc-switch 本地代理常驻**(端口 `15721`)。cc-switch / 代理未运行时
  codex 连不上 → `/codex` 失效。用前确认代理在跑;若 `/codex` 报连接错误,先查 cc-switch 是否启用了对应 provider。

**注意事项:**

- gstack **半数技能是前端 / 可视化**(`/design-*`、`/qa` 浏览器、`/canary`),纯后端阶段 N/A;
  后端实际可用的是 `/plan-eng-review`、`/review`、`/codex`、`/cso`、`/ship`、`/document-release`、`/investigate`、`/retro`。
  待前端就绪后再启用浏览器 QA / 视觉评审一类技能。
- "规格阶段强制评审"与"代码评审"两道门**都不可跳过**(见 Git 工作流);一个 OpenSpec change 对应一个分支。

## 编码约定(与 openspec/config.yaml 对齐)

- 注释 / 文档 / commit message 用中文,代码标识符用英文
- 密钥放 `.env` / `application-secret`,禁止硬编码与提交
- 多租户隔离必须在每个查询路径强制校验,安全测试覆盖跨租户访问(toB 红线)
- 后端只用 REST/Feign 调 RAGFlow,不自写 RAG 内核
