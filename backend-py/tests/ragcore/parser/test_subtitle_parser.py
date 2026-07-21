"""SubtitleParser 测试。

覆盖：SRT / VTT 两种格式、时间戳 `,` 与 `.` 毫秒分隔符、WEBVTT header 跳过、
多行字幕文本、纯数字编号行被当作索引、空字幕文件抛错、heading_path 始终是
`("字幕",)`。
"""

from __future__ import annotations

import pytest

from app.ragcore.parser.subtitle_parser import SubtitleParser
from tests.ragcore.parser.conftest import FakeDocumentInput


class TestSupports:
    def test_supports_srt(self):
        assert SubtitleParser().supports(None, "a.srt") is True

    def test_supports_vtt(self):
        assert SubtitleParser().supports(None, "a.vtt") is True

    def test_supports_vtt_content_type(self):
        assert SubtitleParser().supports("text/vtt", None) is True
        assert SubtitleParser().supports("application/x-subrip", None) is True

    def test_rejects_unrelated_extension(self):
        assert SubtitleParser().supports(None, "doc.txt") is False
        assert SubtitleParser().supports(None, "doc.md") is False

    def test_rejects_text_plain_without_subtitle_extension(self):
        """text/plain 兼容时,仍要求文件名是字幕扩展名,避免误吃 .txt。"""
        assert SubtitleParser().supports("text/plain", "notes.txt") is False
        assert SubtitleParser().supports("text/plain", "captions.srt") is True


class TestSrtBasic:
    def test_srt_single_cue(self, make_document_input):
        content = b"1\n00:00:01,000 --> 00:00:04,000\nHello world\n"
        doc_input = make_document_input(content, "a.srt")
        result = SubtitleParser().parse(doc_input)

        assert len(result.sections) == 1
        assert result.sections[0].text == "Hello world"
        assert result.sections[0].heading_path == ("字幕",)
        assert result.sections[0].metadata["start"] == "00:00:01.000"
        assert result.sections[0].metadata["end"] == "00:00:04.000"
        assert result.sections[0].metadata["timeRange"] == "00:00:01.000 --> 00:00:04.000"
        # SRT 显式编号被写入 metadata.index
        assert result.sections[0].metadata["index"] == "1"

    def test_srt_multiple_cues_with_index(self, make_document_input):
        content = (
            b"1\n00:00:01,000 --> 00:00:04,000\nFirst\n\n"
            b"2\n00:00:05,000 --> 00:00:08,000\nSecond\n"
        )
        doc_input = make_document_input(content, "a.srt")
        result = SubtitleParser().parse(doc_input)

        assert len(result.sections) == 2
        assert [s.metadata["index"] for s in result.sections] == ["1", "2"]
        assert [s.text for s in result.sections] == ["First", "Second"]


class TestVtt:
    def test_vtt_webvtt_header_skipped(self, make_document_input):
        content = b"WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nVTT cue one\n"
        doc_input = make_document_input(content, "a.vtt")
        result = SubtitleParser().parse(doc_input)

        assert len(result.sections) == 1
        assert result.sections[0].text == "VTT cue one"
        # 没有显式编号,index 按 cue 出现顺序(从 1 开始)
        assert result.sections[0].metadata["index"] == "1"

    def test_vtt_webvtt_with_description(self, make_document_input):
        """`WEBVTT - Chinese captions` 这种带说明的 header 也要跳过。"""
        content = (
            b"WEBVTT - Chinese captions\n\n"
            b"00:00:01.000 --> 00:00:04.000\nVTT cue one\n"
        )
        doc_input = make_document_input(content, "a.vtt")
        result = SubtitleParser().parse(doc_input)

        assert len(result.sections) == 1
        assert result.sections[0].text == "VTT cue one"

    def test_vtt_uses_dot_milliseconds(self, make_document_input):
        """VTT 毫秒分隔符是 `.`,不能被 `,` 解析逻辑误吃。"""
        content = b"00:00:01.500 --> 00:00:04.250\nVTT with dot ms\n"
        doc_input = make_document_input(content, "a.vtt")
        result = SubtitleParser().parse(doc_input)

        assert result.sections[0].metadata["start"] == "00:00:01.500"
        assert result.sections[0].metadata["end"] == "00:00:04.250"


class TestMultilineCue:
    def test_multiline_cue_kept_as_single_section(self, make_document_input):
        content = (
            b"1\n00:00:01,000 --> 00:00:04,000\nLine one\nLine two\nLine three\n\n"
            b"2\n00:00:05,000 --> 00:00:08,000\nNext cue\n"
        )
        doc_input = make_document_input(content, "a.srt")
        result = SubtitleParser().parse(doc_input)

        assert len(result.sections) == 2
        assert result.sections[0].text == "Line one\nLine two\nLine three"
        # line_start / line_end 反映字幕文本在源文件里的真实行号
        assert result.sections[0].line_start == 3
        assert result.sections[0].line_end == 5


class TestErrorHandling:
    def test_no_cues_raises(self, make_document_input):
        doc_input = make_document_input(b"", "empty.srt")
        with pytest.raises(IOError):
            SubtitleParser().parse(doc_input)

    def test_block_without_time_line_dropped(self, make_document_input):
        """只有纯文本、没有时间行的 block 应该被丢弃(不会污染字幕)。"""
        content = (
            b"Just random text\nmore random text\n\n"
            b"1\n00:00:01,000 --> 00:00:04,000\nReal cue\n"
        )
        doc_input = make_document_input(content, "a.srt")
        result = SubtitleParser().parse(doc_input)

        # 第一个 block(无时间行)被丢弃,只剩一个有效 cue
        assert len(result.sections) == 1
        assert result.sections[0].text == "Real cue"
