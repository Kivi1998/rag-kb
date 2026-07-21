"""把 OCR / 版面分析 / 表格结构识别三个模块串成单页解析流程。

对应 RAGFlow deepdoc 原版 `parser/pdf_parser.py` 里的编排逻辑（该文件本身
未整体移植，见 ../LICENSE_THIRD_PARTY 和相关 commit 说明：它还挂了
pdfplumber、xgboost 等本项目不需要的依赖，而且和我们自己用 PyMuPDF 渲染页面
的方式不是一回事）。这里只保留并改写了两段真正需要复用的编排算法：

1. 用 LayoutRecognizer 给 OCR 文字框打版面区域标签、按阅读顺序分组排序
   （解决多栏文档被按行交叉拼接的问题）。
2. 表格内文字框的行列标签算法，移植自原版 `_table_transformer_job()`
   （只搬了这一个方法涉及的逻辑，不是整个 pdf_parser.py），用于喂给
   `TableStructureRecognizer.construct_table()`。

单页、单表格假设：不处理跨页表格（原版 `_table_transformer_job` 里的
`page_cum_height` 跨页累计逻辑在这里省略了），足够覆盖当前摄取流程按页处理
文档的场景；后续如果需要跨页合并表格，再单独扩展。
"""
from __future__ import annotations

import re
import threading
from collections import Counter

import numpy as np
from PIL import Image

from .vision import OCR, LayoutRecognizer, TableStructureRecognizer
from .vision.recognizer import Recognizer

_lock = threading.Lock()
_ocr: OCR | None = None
_layout: LayoutRecognizer | None = None
_table: TableStructureRecognizer | None = None


def ensure_models_ready() -> None:
    """预热三个模型（首次调用触发下载），供 /ready 健康检查探测用。"""
    global _ocr, _layout, _table
    with _lock:
        if _ocr is None:
            _ocr = OCR()
        if _layout is None:
            _layout = LayoutRecognizer(domain="layout")
        if _table is None:
            _table = TableStructureRecognizer()


def models_loaded() -> bool:
    return _ocr is not None and _layout is not None and _table is not None


def _polygon_to_box(points, text: str, score: float) -> dict:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {
        "text": text,
        "score": float(score),
        "x0": float(min(xs)), "x1": float(max(xs)),
        "top": float(min(ys)), "bottom": float(max(ys)),
    }


def parse_page(image: Image.Image) -> list[dict]:
    """对单页渲染图跑 OCR + 版面分析 + 表格结构识别。

    返回按阅读顺序排列的 section 列表：
        [{"text": "...", "layout_type": "text"|"title"|"table"|...}]
    表格区域的 text 是 construct_table() 生成的 HTML 表格文本；其余区域是
    按版面分组、组内按阅读顺序拼接的原始文字。
    """
    ensure_models_ready()
    np_image = np.array(image.convert("RGB"))

    raw_boxes = _ocr(np_image)
    ocr_boxes = [
        _polygon_to_box(pts, text, score)
        for pts, (text, score) in raw_boxes
        if text and text.strip()
    ]
    if not ocr_boxes:
        return []

    # scale_factor=1：OCR 和版面分析在这里用的是同一张图、同一套坐标系，
    # 不像 RAGFlow 原版那样对 OCR 和版面用不同的渲染分辨率，所以不需要换算。
    tagged_boxes, _ = _layout([np_image], [ocr_boxes], scale_factor=1)

    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for b in tagged_boxes:
        key = b.get("layoutno") or f"_none-{id(b)}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(b)

    def group_sort_key(key: str):
        first = groups[key][0]
        return (round(first["top"] / 20), first["x0"])

    order.sort(key=group_sort_key)

    sections: list[dict] = []
    for key in order:
        boxes = groups[key]
        layout_type = boxes[0].get("layout_type", "") or "text"
        if layout_type == "table":
            text = _reconstruct_table(np_image, boxes)
        else:
            boxes = sorted(boxes, key=lambda b: (round(b["top"] / 20), b["x0"]))
            text = "\n".join(b["text"] for b in boxes if b["text"].strip())
        if text and text.strip():
            sections.append({"text": text, "layout_type": layout_type})

    return sections


def _reconstruct_table(np_image: np.ndarray, table_ocr_boxes: list[dict]) -> str:
    """把落在表格版面区域内的 OCR 文字框，按行列标签重组成表格文本。

    移植自 RAGFlow deepdoc `parser/pdf_parser.py::_table_transformer_job()`
    里"给表格内文字框打 R/C 行列标签"这一段算法（省略了跨页表格的
    page_cum_height 累计逻辑），其余部分（裁剪表格区域、跑表格结构识别、
    调用 construct_table）是本项目按同样思路新写的编排代码。
    """
    margin = 10
    x0 = max(0, min(b["x0"] for b in table_ocr_boxes) - margin)
    top = max(0, min(b["top"] for b in table_ocr_boxes) - margin)
    x1 = max(b["x1"] for b in table_ocr_boxes) + margin
    bottom = max(b["bottom"] for b in table_ocr_boxes) + margin

    crop = np_image[int(top):int(bottom), int(x0):int(x1)]
    if crop.size == 0:
        boxes = sorted(table_ocr_boxes, key=lambda b: (round(b["top"] / 20), b["x0"]))
        return "\n".join(b["text"] for b in boxes if b["text"].strip())

    structures = _table([crop])
    components = structures[0] if structures else []
    if not components:
        # 表格结构模型没检出行列网格，退化为按阅读顺序拼文本，不假装有结构。
        boxes = sorted(table_ocr_boxes, key=lambda b: (round(b["top"] / 20), b["x0"]))
        return "\n".join(b["text"] for b in boxes if b["text"].strip())

    # 结构框坐标是相对裁剪图的，加回偏移量还原成整页坐标，和 OCR 框对齐。
    # 注意：top/bottom 都是纵轴坐标，都要加裁剪区域的 top 偏移量，不能把
    # bottom（裁剪区域的下边界）错当成偏移量加进来。
    for c in components:
        c["x0"] += x0
        c["x1"] += x0
        c["top"] += top
        c["bottom"] += top

    def gather(pattern: str, fzy: float = 10, ratio: float = 0.6):
        eles = Recognizer.sort_Y_firstly(
            [c for c in components if re.match(pattern, c["label"])], fzy)
        eles = Recognizer.layouts_cleanup(table_ocr_boxes, eles, 5, ratio)
        return Recognizer.sort_Y_firstly(eles, 0)

    headers = gather(r".*header$")
    rows = gather(r".* (row|header)")
    spans = gather(r".*spanning")
    clmns = sorted([c for c in components if re.match(r"table column$", c["label"])],
                   key=lambda x: x["x0"])
    clmns = Recognizer.layouts_cleanup(table_ocr_boxes, clmns, 5, 0.5)

    tagged = []
    for b in table_ocr_boxes:
        b = dict(b)
        b["page_number"] = 0

        ii = Recognizer.find_overlapped_with_threashold(b, rows, thr=0.3)
        if ii is not None:
            b["R"] = ii
            b["R_top"] = rows[ii]["top"]
            b["R_bott"] = rows[ii]["bottom"]

        ii = Recognizer.find_overlapped_with_threashold(b, headers, thr=0.3)
        if ii is not None:
            b["H_top"] = headers[ii]["top"]
            b["H_bott"] = headers[ii]["bottom"]
            b["H_left"] = headers[ii]["x0"]
            b["H_right"] = headers[ii]["x1"]
            b["H"] = ii

        ii = Recognizer.find_horizontally_tightest_fit(b, clmns)
        if ii is not None:
            b["C"] = ii
            b["C_left"] = clmns[ii]["x0"]
            b["C_right"] = clmns[ii]["x1"]

        ii = Recognizer.find_overlapped_with_threashold(b, spans, thr=0.3)
        if ii is not None:
            b["H_top"] = spans[ii]["top"]
            b["H_bott"] = spans[ii]["bottom"]
            b["H_left"] = spans[ii]["x0"]
            b["H_right"] = spans[ii]["x1"]
            b["SP"] = ii

        tagged.append(b)

    if not any("R" in b for b in tagged):
        # 一个文字框都没能对齐到任何行结构上，说明表格检测基本没生效，
        # 同样退化为按阅读顺序拼文本。
        boxes = sorted(table_ocr_boxes, key=lambda b: (round(b["top"] / 20), b["x0"]))
        return "\n".join(b["text"] for b in boxes if b["text"].strip())

    html = TableStructureRecognizer.construct_table(tagged, html=True)
    return html if isinstance(html, str) else "\n".join(html)
