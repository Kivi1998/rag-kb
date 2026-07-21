"""针对 app/deepdoc/pipeline.py 的编排逻辑测试。

覆盖两个真实场景，对应文档解析的"多栏排版""无边框表格"两个坑：
1. 多栏文档不应该按行交叉拼接（用真实模型 + 合成双栏图片验证）。
2. 无边框表格的文字不应该跨行/跨列错配（用 mock 的表格结构 + 手工构造的
   OCR 文字框验证行列打标签逻辑，不依赖版面模型是否把合成图片正确分类为
   "table"——这一点已知对高度简化的合成图片不可靠，真实场景请用真实 PDF
   样本另行验收）。
"""
from __future__ import annotations

import numpy as np
import pytest

from app.ragcore.parser.deepdoc import pipeline
from app.ragcore.parser.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer


def _ocr_box(text: str, x0: float, x1: float, top: float, bottom: float,
             layout_type: str = "table") -> dict:
    return {
        "text": text, "score": 0.99,
        "x0": x0, "x1": x1, "top": top, "bottom": bottom,
        "layout_type": layout_type,
    }


class TestReconstructTable:
    """无边框表格：文字必须落进正确的行列格子，不能跨行/跨列错配。"""

    @staticmethod
    def _borderless_rate_table_boxes():
        # 4 行（年龄段）x 3 列（年龄段 / 男费率 / 女费率），靠坐标对齐，无边框线。
        rows_data = [
            ("Age 30", "120.00", "110.00"),
            ("Age 40", "150.00", "140.00"),
            ("Age 50", "190.00", "175.00"),
            ("Age 60", "260.00", "230.00"),
        ]
        col_x = [(60, 180), (320, 420), (580, 680)]
        boxes = []
        y = 60
        for row in rows_data:
            for (x0, x1), text in zip(col_x, row):
                boxes.append(_ocr_box(text, x0, x1, y, y + 30))
            y += 70
        return boxes, col_x, rows_data

    def test_construct_table_no_cross_row_misalignment(self):
        """直接验证 construct_table：给定已知正确的 R/C 标签，输出不能串行。"""
        boxes = [
            {**_ocr_box("Age 30", 60, 180, 60, 90), "page_number": 0,
             "R": 0, "R_top": 60, "R_bott": 90, "C": 0, "C_left": 60, "C_right": 180},
            {**_ocr_box("120.00", 320, 420, 60, 90), "page_number": 0,
             "R": 0, "R_top": 60, "R_bott": 90, "C": 1, "C_left": 320, "C_right": 420},
            {**_ocr_box("Age 60", 60, 180, 270, 300), "page_number": 0,
             "R": 3, "R_top": 270, "R_bott": 300, "C": 0, "C_left": 60, "C_right": 180},
            {**_ocr_box("260.00", 320, 420, 270, 300), "page_number": 0,
             "R": 3, "R_top": 270, "R_bott": 300, "C": 1, "C_left": 320, "C_right": 420},
        ]
        html = TableStructureRecognizer.construct_table(boxes, html=True)
        rows = [r for r in html.split("\n") if r.startswith("<tr>")]
        assert len(rows) == 2
        assert "Age 30" in rows[0] and "120.00" in rows[0]
        assert "260.00" not in rows[0]  # 60 岁的费率不能混进 30 岁那行
        assert "Age 60" in rows[1] and "260.00" in rows[1]
        assert "120.00" not in rows[1]

    def test_reconstruct_table_tags_rows_and_columns_correctly(self):
        """端到端：_reconstruct_table 用 mock 的表格结构框 + 真实 OCR 框，
        验证行列打标签这段胶水逻辑（曾经把裁剪偏移量算错，导致所有框都打不上
        行标签，这里回归防止再犯）。"""
        boxes, col_x, rows_data = self._borderless_rate_table_boxes()
        crop_x0, crop_top = 50, 50  # 与 _reconstruct_table 内 margin=10 的计算一致

        def make_components():
            comps = []
            for x0, x1 in col_x:
                comps.append({"label": "table column", "score": 0.9,
                              "x0": x0 - crop_x0, "x1": x1 - crop_x0,
                              "top": 55 - crop_top, "bottom": 300 - crop_top})
            r_top = 60
            for _ in rows_data:
                comps.append({"label": "table row", "score": 0.9,
                              "x0": 50 - crop_x0, "x1": 700 - crop_x0,
                              "top": r_top - crop_top, "bottom": r_top + 30 - crop_top})
                r_top += 70
            return comps

        class FakeTableRecognizer:
            def __call__(self, images):
                return [make_components()]

        original_table = pipeline._table
        pipeline._table = FakeTableRecognizer()
        try:
            result = pipeline._reconstruct_table(
                np.zeros((500, 900, 3), dtype=np.uint8), boxes)
        finally:
            pipeline._table = original_table

        rows_html = [r for r in result.split("\n") if r.startswith("<tr>")]
        assert len(rows_html) == 4
        for row_html, (age, male, female) in zip(rows_html, rows_data):
            assert age in row_html and male in row_html and female in row_html
        # 交叉校验：60 岁那行的两个费率不能出现在其余任何一行里
        for row_html in rows_html[:-1]:
            assert "260.00" not in row_html
            assert "230.00" not in row_html

    def test_reconstruct_table_falls_back_when_structure_not_detected(self):
        """表格结构模型没检出任何行列（比如低质量扫描件），退化为按阅读
        顺序拼文本，而不是抛异常或返回空。"""
        boxes, *_ = self._borderless_rate_table_boxes()

        class EmptyTableRecognizer:
            def __call__(self, images):
                return [[]]

        original_table = pipeline._table
        pipeline._table = EmptyTableRecognizer()
        try:
            result = pipeline._reconstruct_table(
                np.zeros((500, 900, 3), dtype=np.uint8), boxes)
        finally:
            pipeline._table = original_table

        assert "Age 30" in result
        assert "230.00" in result


@pytest.mark.skipif(
    True,
    reason="需要真实下载 OCR/LayoutRecognizer 模型（约 90MB），CI 环境默认跳过；"
           "本地手动验证命令见本文件顶部注释。",
)
class TestParsePageEndToEnd:
    """需要真实模型权重才能跑，默认跳过。手动验证方法：
    去掉本类的 skipif 装饰器，在能访问 HuggingFace（或配置好 HF_ENDPOINT 镜像）
    的环境下运行 `pytest tests/test_deepdoc_pipeline.py -v`。
    """

    def test_two_column_document_is_not_interleaved(self):
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (1200, 1600), "white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
        except Exception:
            font = ImageFont.load_default()
        y = 60
        for i in range(1, 21):
            draw.text((40, y), f"Claim process line {i}", fill="black", font=font)
            y += 55
        y = 60
        for i in range(1, 21):
            draw.text((650, y), f"Required document {i}", fill="black", font=font)
            y += 55

        sections = pipeline.parse_page(img)
        assert len(sections) >= 2
        left_section = next(s for s in sections if "Claim process" in s["text"])
        right_section = next(s for s in sections if "Required document" in s["text"])
        # 左栏 section 里不应该混入右栏的文字，反之亦然——这正是修复的坑。
        assert "Required document" not in left_section["text"]
        assert "Claim process" not in right_section["text"]
