"""针对 app/main.py::decode_filename_header 的回归测试。

背景：2026-07-15 真实上传文档（含中文文件名）走多模态解析网关时，Java 端
HttpMultimodalDocumentParser 直接把原始文件名塞进 HTTP header 值，触发
Java HttpRequest 的 ASCII-only 校验（IllegalArgumentException: invalid
header value）。修复为 Java 侧 application/x-www-form-urlencoded 编码后
再发送，网关侧对称解码——本文件覆盖解码这一半。
"""
from __future__ import annotations

from app.main import decode_filename_header


class TestDecodeFilenameHeader:
    def test_decodes_java_url_encoder_output_for_chinese_filename(self):
        """真实触发过该 bug 的文件名，用 Java URLEncoder.encode 的实际输出结果验证。"""
        encoded = (
            "2020%E5%B9%B4%E4%B8%AD%E5%9B%BD%E5%9C%B0%E7%90%83%E7%89%A9%E7%90%86"
            "%E8%81%94%E5%90%88%E5%B9%B4%E4%BC%9A%E6%8A%95%E7%A8%BF-%E8%B4%BE"
            "%E6%98%8A-%E9%AB%98%E5%BB%BA%E5%86%9B.docx"
        )
        assert decode_filename_header(encoded) == "2020年中国地球物理联合年会投稿-贾昊-高建军.docx"

    def test_decodes_filename_with_parentheses_and_punctuation(self):
        encoded = (
            "%E4%B8%8A%E4%BC%A0%E6%B5%8B%E9%87%8F%E6%A0%87%E5%BF%97%E7%82%B9zip"
            "%E5%8C%85%E3%80%81%E6%9F%A5%E8%AF%A2%E6%B5%8B%E9%87%8F%E6%A0%87"
            "%E5%BF%97%E7%82%B9%E4%BF%A1%E6%81%AF%E6%8E%A5%E5%8F%A3%283%29.pdf"
        )
        assert decode_filename_header(encoded) == "上传测量标志点zip包、查询测量标志点信息接口(3).pdf"

    def test_ascii_filename_unaffected(self):
        """纯 ASCII 文件名（无 %/+ 字符）解码应原样返回，不受影响。"""
        assert decode_filename_header("deployment-guide.pdf") == "deployment-guide.pdf"

    def test_space_encoded_as_plus_is_restored(self):
        """application/x-www-form-urlencoded 把空格编码为 +，须用 unquote_plus
        而不是 unquote，否则空格会被误当作字面 + 保留。"""
        assert decode_filename_header("annual+report+2024.pdf") == "annual report 2024.pdf"
