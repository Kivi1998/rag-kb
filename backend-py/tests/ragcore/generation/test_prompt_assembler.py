"""PromptAssembler 测试。

对照 Java 版 `PromptAssembler.java`：system prompt 拼接顺序与 additional_context 追加逻辑、
user prompt 里资料编号/定位信息/字符预算截断逻辑。文案本身不做校验（保留原样，翻译/改写
不在移植范围内），只测试组装逻辑。
"""

from __future__ import annotations

from uuid import uuid4

from app.ragcore.generation.prompt_assembler import (
    MAX_CHUNK_CHARS,
    MAX_TOTAL_CONTEXT_CHARS,
    PromptAssembler,
)
from app.ragcore.model import Chunk, RetrievedChunk


def _chunk(**overrides) -> Chunk:
    defaults = dict(
        id="c1",
        organization_id=None,
        knowledge_base_id=None,
        document_id=uuid4(),
        ordinal=0,
        content="示例正文",
    )
    defaults.update(overrides)
    return Chunk(**defaults)


class TestSystemPrompt:
    def test_no_additional_context_returns_base_sections(self):
        prompt = PromptAssembler().system_prompt()
        assert "你是企业技术文档助手" in prompt
        assert "长度与语气" in prompt
        assert "参考资料已按相关性从高到低排序" in prompt
        assert "以下两个示例仅用于演示输出格式" in prompt

    def test_blank_additional_context_treated_as_none(self):
        base = PromptAssembler().system_prompt()
        assert PromptAssembler().system_prompt("   ") == base

    def test_additional_context_appended_after_base(self):
        prompt = PromptAssembler().system_prompt("用户是财务部门同事。")
        assert prompt.endswith("用户是财务部门同事。")
        assert prompt.startswith("你是企业技术文档助手")


class TestUserPromptBasic:
    def test_question_is_trimmed_and_included(self):
        prompt = PromptAssembler().user_prompt("  这是问题吗？  ", [])
        assert prompt.startswith("问题：\n这是问题吗？\n\n参考资料：\n")

    def test_no_contexts_produces_only_header(self):
        prompt = PromptAssembler().user_prompt("问题", [])
        assert prompt == "问题：\n问题\n\n参考资料：\n"

    def test_contexts_numbered_from_one_in_order(self):
        chunks = [
            RetrievedChunk(chunk=_chunk(content="资料一内容")),
            RetrievedChunk(chunk=_chunk(content="资料二内容")),
        ]
        prompt = PromptAssembler().user_prompt("问题", chunks)
        assert "[资料1] " in prompt
        assert "[资料2] " in prompt
        assert prompt.index("[资料1]") < prompt.index("[资料2]")
        assert "资料一内容" in prompt
        assert "资料二内容" in prompt


class TestUserPromptLocationMetadata:
    def test_heading_path_and_page_and_line_all_present(self):
        chunk = _chunk(
            content="正文",
            heading_path=("第一章", "概述"),
            page_no=3,
            line_start=10,
            line_end=20,
        )
        prompt = PromptAssembler().user_prompt("q", [RetrievedChunk(chunk=chunk)])
        assert "标题=第一章 / 概述" in prompt
        assert "页码=3" in prompt
        assert "行=10-20" in prompt

    def test_line_start_without_line_end_omits_range(self):
        chunk = _chunk(content="正文", line_start=5, line_end=None)
        prompt = PromptAssembler().user_prompt("q", [RetrievedChunk(chunk=chunk)])
        assert "行=5\n" in prompt or "行=5）" in prompt
        assert "行=5-" not in prompt

    def test_no_location_metadata_omits_parenthetical(self):
        chunk = _chunk(content="正文")
        prompt = PromptAssembler().user_prompt("q", [RetrievedChunk(chunk=chunk)])
        assert "[资料1] \n正文" in prompt
        assert "（" not in prompt


class TestUserPromptCharBudget:
    def test_chunk_content_truncated_to_max_chunk_chars(self):
        long_content = "字" * (MAX_CHUNK_CHARS + 500)
        chunk = _chunk(content=long_content)
        prompt = PromptAssembler().user_prompt("q", [RetrievedChunk(chunk=chunk)])
        # 截断后应恰好包含 MAX_CHUNK_CHARS 个"字"，不多不少。
        assert ("字" * MAX_CHUNK_CHARS) in prompt
        assert ("字" * (MAX_CHUNK_CHARS + 1)) not in prompt

    def test_total_context_budget_stops_including_further_chunks(self):
        # 单块上限 MAX_CHUNK_CHARS=4000，总预算 MAX_TOTAL_CONTEXT_CHARS=24000，
        # 6 个满字符块正好耗尽总预算（6*4000=24000），第 7 个块应完全不出现在输出里。
        assert MAX_TOTAL_CONTEXT_CHARS == MAX_CHUNK_CHARS * 6
        full_chunks = [_chunk(content="A" * MAX_CHUNK_CHARS) for _ in range(6)]
        overflow = _chunk(content="B" * 100)
        contexts = [RetrievedChunk(chunk=c) for c in full_chunks] + [RetrievedChunk(chunk=overflow)]

        prompt = PromptAssembler().user_prompt("q", contexts)

        assert "[资料6]" in prompt
        assert "[资料7]" not in prompt
        assert "B" not in prompt

    def test_remaining_budget_below_max_chunk_chars_caps_at_remaining(self):
        # 5 块吃满 5*4000=20000，第 6 块只给 3950（allowed=min(4000,4000,3950)=3950），
        # 剩余预算 = 24000-20000-3950=50；第 7 块内容 200 字符，
        # allowed=min(MAX_CHUNK_CHARS, remaining=50, len=200)=50——验证三者取 min 的截断逻辑，
        # 而不是只看单块上限 MAX_CHUNK_CHARS。
        first_five = [_chunk(content="A" * MAX_CHUNK_CHARS) for _ in range(5)]
        sixth = _chunk(content="B" * 3950)
        seventh = _chunk(content="C" * 200)
        contexts = [RetrievedChunk(chunk=c) for c in first_five] + [
            RetrievedChunk(chunk=sixth),
            RetrievedChunk(chunk=seventh),
        ]

        prompt = PromptAssembler().user_prompt("q", contexts)

        assert "[资料7]" in prompt
        assert ("C" * 50) in prompt
        assert ("C" * 51) not in prompt
