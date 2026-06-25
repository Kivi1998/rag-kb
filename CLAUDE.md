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
3. **合并回 main**:验证通过后切回 `main`,`git merge --ff-only <分支>`(优先 fast-forward)
4. **清理**:删除已合并分支 `git branch -d <分支>`
5. **提交规范**:
   - 仅在用户明确要求时 commit / push
   - commit message 用中文,遵循 `<type>: <简述>` + 必要正文
   - 结尾附 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
6. **推送**:远程为 GitHub HTTPS(`gh` 已配为凭证助手),`git push origin main` 即可

## AI 增强开发三件套

| 工具 | 阶段 | 用途 |
|------|------|------|
| **OpenSpec** | 规划 | 需求 → proposal / specs / design / tasks;`/opsx:propose` 发起,`/opsx:apply` 实现,`openspec validate` 校验 |
| **Superpowers** | 开发 | 先澄清(brainstorming)、TDD、子 Agent 执行、code-review、完成前 verification |
| **gstack** | 交付 | 应用跑起来后的 Browser QA / dogfooding(规格阶段不适用,实现出可运行后端后启用) |

## 编码约定(与 openspec/config.yaml 对齐)

- 注释 / 文档 / commit message 用中文,代码标识符用英文
- 密钥放 `.env` / `application-secret`,禁止硬编码与提交
- 多租户隔离必须在每个查询路径强制校验,安全测试覆盖跨租户访问(toB 红线)
- 后端只用 REST/Feign 调 RAGFlow,不自写 RAG 内核
