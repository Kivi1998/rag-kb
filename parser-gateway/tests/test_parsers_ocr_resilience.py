"""app/parsers.py::_ocr_bytes 的容错测试 —— 单张图片解码/识别失败不该拖垮整份文档。

背景：2026-07-15 真实文档（贾昊-文献翻译.docx，2021 年老 Word 文档）内嵌一张
WMF（Windows 图元文件）格式图片，Pillow 无法解码，导致整份文档的 /v1/parse
请求直接 500，即使文档里其余段落文字和图片都能正常提取。
"""
from __future__ import annotations

import io

import pytest

from app import parsers


class TestOcrBytesResilience:
    def test_undecodable_image_returns_empty_instead_of_raising(self, monkeypatch):
        """老式 WMF/EMF 等 Pillow 不支持的图片格式：Image.open().convert('RGB')
        会抛 OSError，修复前会直接冒泡导致整份文档解析失败。"""
        monkeypatch.setattr(parsers, "ensure_ocr_ready", lambda: "ok")
        result = parsers._ocr_bytes(b"this is not a valid image payload")
        assert result == ""

    def test_ocr_model_recognition_failure_also_returns_empty(self, monkeypatch):
        """图片本身能被 Pillow 解码，但 OCR 模型调用本身抛异常时同样降级为空文本，
        而不是让整份文档失败。"""
        from PIL import Image

        from app.deepdoc import pipeline as deepdoc_pipeline

        monkeypatch.setattr(parsers, "ensure_ocr_ready", lambda: "ok")
        monkeypatch.setattr(deepdoc_pipeline, "_ocr",
                             lambda np_image: (_ for _ in ()).throw(RuntimeError("boom")))

        buf = io.BytesIO()
        Image.new("RGB", (10, 10), color="white").save(buf, format="PNG")
        result = parsers._ocr_bytes(buf.getvalue())
        assert result == ""

    def test_ocr_service_unavailable_is_not_swallowed(self, monkeypatch):
        """OCR 模型本身未加载/不可用是服务级故障（应映射为 503），必须让
        ParserUnavailableError 冒泡，不能被"单图片容错" try/except 误吞成空文本。"""
        def _raise_unavailable():
            raise parsers.ParserUnavailableError("OCR model is unavailable")

        monkeypatch.setattr(parsers, "ensure_ocr_ready", _raise_unavailable)

        with pytest.raises(parsers.ParserUnavailableError):
            parsers._ocr_bytes(b"irrelevant bytes, ensure_ocr_ready raises before decoding")
