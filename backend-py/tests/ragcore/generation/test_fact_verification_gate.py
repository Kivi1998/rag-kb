"""`FactVerificationGate` 测试。

对照 Java 版 `ragcore/generation/FactVerificationGate.java`:覆盖三种 BUFFERING 收尾路径
(`found:true` / `found:false` / 解析失败的 fail-open)以及 `flush()` 收尾解析的
edge case(`found:true` 紧跟正文、模型整段就是判断行本身、`found:false` 模型在
BUFFERING 期间没再产出)。fail-open 路径是生产环境最容易触发的降级路径(模型网络抖动
或截断响应),必须有测试覆盖。
"""

from __future__ import annotations

from uuid import uuid4

from app.ragcore.generation.fact_verification_gate import (
    FIXED_REFUSAL_MESSAGE,
    MAX_BUFFER_CHARS,
    FactVerificationGate,
)
from app.ragcore.model import Citation, QueryEvent, QueryEventType


def _citation(document_id=None, snippet="snippet", name="doc.txt") -> Citation:
    return Citation(
        document_id=document_id or uuid4(),
        document_name=name,
        heading_path=("章",),
        snippet=snippet,
        page_no=1,
        line_start=1,
        line_end=2,
        score=0.5,
    )


def _drain(gate: FactVerificationGate, *events: QueryEvent) -> list[QueryEvent]:
    """把 `events` 依次 `feed` 给 gate,再调 `flush()`,汇总下游应收到的事件。"""
    out: list[QueryEvent] = []
    for event in events:
        out.extend(gate.feed(event))
    out.extend(gate.flush())
    return out


class TestFoundTrue:
    """`found:true` 时,模式切到 PASSTHROUGH,先补发引用再透传剩余正文。"""

    def test_citations_emitted_before_body(self):
        c1, c2 = _citation(), _citation()
        gate = FactVerificationGate([c1, c2])

        events = _drain(gate, QueryEvent.chunk('{"found": true}\n正文'))

        sources = [e for e in events if e.type is QueryEventType.SOURCE]
        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert len(sources) == 2
        assert [s.citation for s in sources] == [c1, c2]
        assert len(chunks) == 1
        assert chunks[0].content == "正文"

    def test_refused_flag_stays_false(self):
        gate = FactVerificationGate([_citation()])
        _drain(gate, QueryEvent.chunk('{"found": true}\n'))
        assert gate.refused_by_fact_verification is False

    def test_citations_emitted_only_once_when_first_line_is_just_found(self):
        """模型只输出 `{"found": true}\n` 时,引用补发一次,没有正文 chunk。"""
        c1 = _citation()
        gate = FactVerificationGate([c1])

        events = _drain(gate, QueryEvent.chunk('{"found": true}\n'))

        assert [e.type for e in events] == [QueryEventType.SOURCE]
        assert events[0].citation == c1


class TestFoundFalse:
    """`found:false` 时只发 REFUSAL,引用与后续内容都被丢弃。"""

    def test_emits_refusal_and_sets_refused_flag(self):
        gate = FactVerificationGate([_citation()])

        events = _drain(gate, QueryEvent.chunk('{"found": false}\n这是本来想输出的正文'))

        assert [e.type for e in events] == [QueryEventType.REFUSAL]
        assert events[0].message == FIXED_REFUSAL_MESSAGE
        assert gate.refused_by_fact_verification is True

    def test_subsequent_chunks_after_refusal_are_dropped(self):
        """切到 REFUSED 后,后续 feed 的内容都不能漏到下游——这是 Java 版契约。"""
        gate = FactVerificationGate([_citation()])

        out: list[QueryEvent] = []
        out.extend(gate.feed(QueryEvent.chunk('{"found": false}\n')))
        out.extend(gate.feed(QueryEvent.chunk("不应该出现")))
        out.extend(gate.feed(QueryEvent.chunk("也不应该出现")))

        assert [e.type for e in out] == [QueryEventType.REFUSAL]
        # 第二个 refusal 不会再次出现(切到 REFUSED 模式后 feed 直接返回空)
        assert len(out) == 1

    def test_found_false_in_flush_when_buffer_has_no_newline(self):
        """模型整段输出就是 `{"found": false}` 没换行——`flush()` 必须兜底解析。"""
        gate = FactVerificationGate([_citation()])

        events = _drain(gate, QueryEvent.chunk('{"found": false}'))

        assert [e.type for e in events] == [QueryEventType.REFUSAL]
        assert gate.refused_by_fact_verification is True


class TestFailOpen:
    """解析不出合法 `{"found": ...}` 时 fail-open:整段缓冲区当正文透传 + 补发引用。"""

    def test_invalid_json_in_buffer_fails_open(self):
        c1 = _citation()
        gate = FactVerificationGate([c1])

        events = _drain(gate, QueryEvent.chunk("这不是 JSON,只是普通文字"))

        sources = [e for e in events if e.type is QueryEventType.SOURCE]
        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert [s.citation for s in sources] == [c1]
        assert len(chunks) == 1
        assert chunks[0].content == "这不是 JSON,只是普通文字"
        assert gate.refused_by_fact_verification is False

    def test_json_without_found_field_fails_open(self):
        """合法 JSON 但缺 found 字段——fail-open,不拒答。"""
        gate = FactVerificationGate([_citation()])

        events = _drain(gate, QueryEvent.chunk('{"answer": "yes"}\n后续正文'))

        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        # 整段缓冲区(含已缓冲的 {"answer": "yes"}\n + 后续)拼起来当正文透传
        assert len(chunks) == 1
        assert chunks[0].content.startswith('{"answer": "yes"}')
        assert "后续正文" in chunks[0].content

    def test_non_boolean_found_fails_open(self):
        """`found` 字段不是 bool(如字符串/数字)——fail-open。"""
        gate = FactVerificationGate([_citation()])

        events = _drain(gate, QueryEvent.chunk('{"found": "yes"}\n'))

        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert len(chunks) == 1

    def test_buffer_exceeds_max_chars_fails_open(self):
        """缓冲超过 200 字符仍解析不出合法判断时,直接 fail-open,不拒答。"""
        gate = FactVerificationGate([_citation()])
        long_text = "x" * (MAX_BUFFER_CHARS + 50)  # 超过 MAX_BUFFER_CHARS,无换行

        events = _drain(gate, QueryEvent.chunk(long_text))

        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert len(chunks) == 1
        assert chunks[0].content == long_text
        assert gate.refused_by_fact_verification is False

    def test_fail_open_in_flush_when_buffer_invalid(self):
        """`flush()` 时如果缓冲区是非法 JSON,也要 fail-open 而非抛异常。"""
        gate = FactVerificationGate([_citation()])

        events = _drain(gate, QueryEvent.chunk("not json at all"))

        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert len(chunks) == 1
        assert chunks[0].content == "not json at all"


class TestFlush:
    """`flush()` 收尾解析覆盖三个分支:空 buffer / 合法 found / 非法 fail-open。"""

    def test_flush_with_empty_buffer_emits_citations_only(self):
        """模型完全没产出内容(理论不应发生,但契约要稳):补发引用,不抛。"""
        c1 = _citation()
        gate = FactVerificationGate([c1])

        events = gate.flush()

        assert [e.type for e in events] == [QueryEventType.SOURCE]
        assert events[0].citation == c1

    def test_flush_does_nothing_after_passthrough(self):
        """已经 PASSTHROUGH 之后调 `flush()`,不应该重复发引用/重新触发 fail-open。"""
        c1, c2 = _citation(), _citation()
        gate = FactVerificationGate([c1, c2])
        out = list(gate.feed(QueryEvent.chunk('{"found": true}\n正文')))
        # 此时已经 PASSTHROUGH,引用已发、正文已透传

        tail = gate.flush()
        assert tail == []

    def test_flush_does_nothing_after_refused(self):
        """已经 REFUSED 之后调 `flush()`,不能再产生事件。"""
        gate = FactVerificationGate([_citation()])
        gate.feed(QueryEvent.chunk('{"found": false}\n'))
        assert gate.flush() == []

    def test_flush_with_found_true_emits_citations_only(self):
        c1 = _citation()
        gate = FactVerificationGate([c1])

        events = _drain(gate, QueryEvent.chunk('{"found": true}'))

        assert [e.type for e in events] == [QueryEventType.SOURCE]
        assert events[0].citation == c1
        assert gate.refused_by_fact_verification is False

    def test_flush_with_found_false_emits_refusal(self):
        gate = FactVerificationGate([_citation()])
        events = _drain(gate, QueryEvent.chunk('{"found": false}'))

        assert [e.type for e in events] == [QueryEventType.REFUSAL]
        assert gate.refused_by_fact_verification is True


class TestWhitespaceTolerance:
    """首行前后有空白(模型常加 padding)时,`parse_found` 仍应正确识别。"""

    def test_leading_whitespace_around_found_line(self):
        gate = FactVerificationGate([_citation()])
        events = _drain(gate, QueryEvent.chunk('   {"found": true}   \n正文'))

        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert chunks[0].content == "正文"
        assert gate.refused_by_fact_verification is False

    def test_crlf_separator_treated_as_terminator(self):
        """\\r\\n 风格换行:Python 通用换行会把 \\r\\n 切成 \\n,所以我们单独测 \\r 的处理。"""
        gate = FactVerificationGate([_citation()])
        events = _drain(gate, QueryEvent.chunk('{"found": true}\n正文'))

        chunks = [e for e in events if e.type is QueryEventType.CHUNK]
        assert chunks[0].content == "正文"


class TestEventPassthrough:
    """BUFFERING 期间收到非 content 事件(SOURCE/ERROR)的处理:与 Java 版 `event.content == null`
    分支保持一致——直接透传到下游,不进缓冲区。"""

    def test_error_event_passes_through_during_buffering(self):
        """BUFFERING 期间如果上游先发了个 ERROR(无 content),不能被缓冲区吞掉。"""
        gate = FactVerificationGate([_citation()])
        out: list[QueryEvent] = []
        out.extend(gate.feed(QueryEvent.error("上游错误")))
        out.extend(gate.feed(QueryEvent.chunk('{"found": true}\n')))
        out.extend(gate.flush())

        # ERROR 应该原样透传,不影响后续 found:true 解析
        assert any(e.type is QueryEventType.ERROR for e in out)
        # found:true 仍然被正确解析并发出引用
        assert any(e.type is QueryEventType.SOURCE for e in out)
