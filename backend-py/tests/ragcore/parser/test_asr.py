"""app.ragcore.parser.asr 测试。

覆盖:
- `ensure_asr_ready()` 在 faster-whisper 运行时未安装 / 模型加载失败时的 fail-fast 行为
  (通过 monkeypatch 模拟 import 失败与 WhisperModel 构造失败，不做真实模型推理)。
- `asr_is_loaded()` 状态探测。
- `transcribe_media()` 在没有转写出任何文本片段时抛出 `ParseError`。
- 真实模型加载 + faster-whisper 推理已用合成音频手动验证过一次(见任务报告)，
  单测里 mock 掉真实模型调用以保持测试快速、可重复、不依赖网络下载模型。
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.ragcore.parser.asr as asr_module
from app.ragcore.parser.asr import (
    ParseError,
    ParserUnavailableError,
    asr_is_loaded,
    ensure_asr_ready,
    transcribe_media,
)


@pytest.fixture(autouse=True)
def _reset_model_singleton():
    """每个用例前后重置模块级单例，避免测试间相互污染全局状态。"""
    asr_module._whisper_model = None
    yield
    asr_module._whisper_model = None


class TestEnsureAsrReady:
    def test_raises_parser_unavailable_when_faster_whisper_not_installed(self, monkeypatch):
        """faster_whisper 包未安装(import 失败)时,fail-fast 抛出 ParserUnavailableError。"""
        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "faster_whisper":
                raise ImportError("No module named 'faster_whisper'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        with pytest.raises(ParserUnavailableError, match="ASR 运行时未安装"):
            ensure_asr_ready()
        assert asr_is_loaded() is False

    def test_raises_parser_unavailable_when_model_load_fails(self, monkeypatch):
        """faster_whisper 已安装，但 WhisperModel 构造失败(如模型文件损坏/下载失败)时，
        同样 fail-fast 收敛为 ParserUnavailableError，而不是让底层原始异常裸露出去。
        """

        class _BoomWhisperModel:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("model file corrupted")

        fake_module = SimpleNamespace(WhisperModel=_BoomWhisperModel)
        monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

        with pytest.raises(ParserUnavailableError, match="ASR 模型不可用"):
            ensure_asr_ready()
        assert asr_is_loaded() is False

    def test_loads_model_once_and_returns_model_name(self, monkeypatch):
        """模型只加载一次:第二次调用不应该再触发 WhisperModel 构造。"""
        call_count = {"n": 0}

        class _FakeWhisperModel:
            def __init__(self, *args, **kwargs):
                call_count["n"] += 1

        fake_module = SimpleNamespace(WhisperModel=_FakeWhisperModel)
        monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
        monkeypatch.setattr(asr_module.settings, "rag_whisper_model", "tiny")

        name1 = ensure_asr_ready()
        name2 = ensure_asr_ready()

        assert name1 == "tiny"
        assert name2 == "tiny"
        assert call_count["n"] == 1
        assert asr_is_loaded() is True


class TestTranscribeMedia:
    def test_raises_parse_error_when_no_segments_produced(self, monkeypatch, tmp_path):
        """转写没有产出任何非空文本片段时，fail-fast 抛出 ParseError。"""

        class _EmptySegment:
            text = "   "
            start = 0.0
            end = 1.0

        class _FakeWhisperModel:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, path, vad_filter=True):
                info = SimpleNamespace(language="zh")
                return [_EmptySegment()], info

        fake_module = SimpleNamespace(WhisperModel=_FakeWhisperModel)
        monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

        media_path = tmp_path / "silence.wav"
        media_path.write_bytes(b"")

        with pytest.raises(ParseError, match="ASR 未产生任何转写文本"):
            transcribe_media(media_path)

    def test_returns_sections_for_non_empty_segments(self, monkeypatch, tmp_path):
        """有实际文本内容的片段能正确映射为 DocumentSection，并带上时间戳元数据。"""

        class _Segment:
            def __init__(self, text: str, start: float, end: float):
                self.text = text
                self.start = start
                self.end = end

        class _FakeWhisperModel:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, path, vad_filter=True):
                info = SimpleNamespace(language="en")
                segments = [_Segment("hello world", 0.0, 1.5), _Segment("  ", 1.5, 2.0)]
                return segments, info

        fake_module = SimpleNamespace(WhisperModel=_FakeWhisperModel)
        monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

        media_path = tmp_path / "clip.wav"
        media_path.write_bytes(b"")

        result = transcribe_media(media_path)

        assert len(result.sections) == 1
        assert result.sections[0].text == "hello world"
        assert result.sections[0].metadata["type"] == "subtitle"
        assert result.sections[0].metadata["timeRange"] == "00:00:00.000 --> 00:00:01.500"
        assert result.metadata["format"] == "wav"
        assert result.metadata["language"] == "en"
        assert result.metadata["segmentCount"] == "1"
