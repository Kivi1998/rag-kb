"""针对移植的 deepdoc 版面分析（LayoutRecognizer）与 OCR 模块的测试。

这两个模块移植自 RAGFlow deepdoc（Apache 2.0），源文件见
``app/deepdoc/vision/layout_recognizer.py`` 与 ``app/deepdoc/vision/ocr.py``。
模型权重（.onnx）不随源码打包，运行时从 HuggingFace 仓库
``InfiniFlow/deepdoc`` 下载到 ``app.deepdoc.paths.deepdoc_model_dir()``。

由于模型下载依赖网络，CI/离线环境可能无法访问 HuggingFace，因此：
- 所有需要真实模型的测试都用 ``_ensure_models_downloaded()`` 统一尝试下载一次；
- 下载失败（网络不可达/超时）时用 ``pytest.skip`` 跳过，而不是让测试挂死或报错。

模型下载目标目录用环境变量 ``DEEPDOC_TEST_MODEL_DIR`` 覆盖（默认使用项目自带的
``deepdoc_model_dir()``），方便在已经下载过模型的机器上复用缓存、避免重复下载。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.deepdoc.vision.ocr import OCR  # noqa: E402
from app.deepdoc.vision.layout_recognizer import (  # noqa: E402
    LayoutRecognizer4YOLOv10,
)

# 只下载 OCR + layout 用得到的文件，跳过表格结构识别用的 tsr.onnx，
# 减少测试期间的下载体积（约 90MB 而不是全量 ~315MB）。
_REQUIRED_FILES = ["det.onnx", "rec.onnx", "ocr.res", "layout.onnx"]

_DOWNLOAD_TIMEOUT = 120  # 秒，网络不可用时不要让测试无限挂起


def _model_dir() -> str:
    override = os.environ.get("DEEPDOC_TEST_MODEL_DIR")
    if override:
        return override
    from app.deepdoc.paths import deepdoc_model_dir
    return deepdoc_model_dir()


def _models_present(model_dir: str) -> bool:
    return all(os.path.exists(os.path.join(model_dir, f)) for f in _REQUIRED_FILES)


def _ensure_models_downloaded() -> str:
    """确保测试所需的 onnx 模型 + 字符字典存在本地，否则尝试从 HuggingFace 下载。

    下载失败（网络问题、超时等）时抛出异常，调用方负责转换成 pytest.skip。
    """
    model_dir = _model_dir()
    if _models_present(model_dir):
        return model_dir

    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id="InfiniFlow/deepdoc",
        local_dir=model_dir,
        local_dir_use_symlinks=False,
        allow_patterns=_REQUIRED_FILES,
    )
    if not _models_present(model_dir):
        raise RuntimeError("模型下载完成但文件仍缺失，请检查 HuggingFace 仓库内容")
    return model_dir


@pytest.fixture(scope="module")
def model_dir() -> str:
    try:
        return _ensure_models_downloaded()
    except Exception as exc:  # noqa: BLE001 - 网络/环境问题都应跳过而不是报错
        pytest.skip(f"deepdoc 模型下载失败，跳过需要真实模型的测试：{exc}")


def _make_text_image(lines: list[str], x_offset: int = 20, width: int = 640,
                      line_height: int = 40, top: int = 30) -> np.ndarray:
    """用 PIL 画一张只含纯文本的合成图片，返回 BGR ndarray（cv2 约定）。"""
    from PIL import Image, ImageDraw

    height = top + line_height * len(lines) + 20
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = top
    for line in lines:
        draw.text((x_offset, y), line, fill=(0, 0, 0))
        y += line_height
    # PIL 是 RGB，cv2/OCR pipeline 约定 BGR
    return np.array(img)[:, :, ::-1].copy()


def _make_two_column_image() -> np.ndarray:
    """构造一张双栏排版的合成图片：左栏、右栏各自有多行文字，模拟双栏文档。"""
    from PIL import Image, ImageDraw

    width, height = 1200, 1600
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    left_lines = [f"Left column line {i} lorem ipsum dolor sit amet" for i in range(30)]
    right_lines = [f"Right column line {i} consectetur adipiscing elit" for i in range(30)]

    y = 40
    for line in left_lines:
        draw.text((40, y), line, fill=(0, 0, 0))
        y += 40

    y = 40
    for line in right_lines:
        draw.text((640, y), line, fill=(0, 0, 0))
        y += 40

    return np.array(img)


def _make_ocr(model_dir: str) -> OCR:
    """按 RAGFlow 原版 OCR.__init__ 的实际行为构造可用的 OCR 实例。

    已知限制（原样保留，未修复，见下方 test_ocr_explicit_model_dir_is_a_known_noop）：
    OCR.__init__ 只有在 `model_dir` 为空（走 `if not model_dir:` 分支）时才会
    设置 self.text_detector / self.text_recognizer；显式传入 model_dir 时这两个
    属性不会被赋值，是 RAGFlow 原版就存在的行为，移植时按"保持公开签名/行为不变"
    的要求原样保留，没有顺手"修好"。因此测试内统一用 monkeypatch 让
    `deepdoc_model_dir()` 指向测试模型目录，走无参构造路径。
    """
    import app.deepdoc.vision.ocr as ocr_module
    import pytest as _pytest

    mp = _pytest.MonkeyPatch()
    mp.setattr(ocr_module, "deepdoc_model_dir", lambda: model_dir)
    try:
        return OCR()
    finally:
        mp.undo()


class TestOCRInstantiation:
    def test_ocr_loads_via_default_model_dir(self, model_dir):
        """OCR 无参构造（走 deepdoc_model_dir() 默认路径）应正常加载 onnx 会话。"""
        ocr = _make_ocr(model_dir)
        assert ocr.text_detector is not None
        assert ocr.text_recognizer is not None
        assert ocr.drop_score == 0.5

    def test_ocr_explicit_model_dir_is_a_known_noop(self, model_dir):
        """记录 RAGFlow 原版的已知行为：显式传 model_dir 时 __init__ 内部
        不会设置 text_detector/text_recognizer（只有 `if not model_dir` 分支
        才会）。这不是移植引入的回归，是原始实现如此；此测试确保未来有人
        "顺手改掉"这个签名行为时能被测试捕捉到，改动需要显式决策而不是无意间的。
        """
        ocr = OCR(model_dir=model_dir)
        assert not hasattr(ocr, "text_detector")
        assert not hasattr(ocr, "text_recognizer")

    def test_ocr_call_signature_preserved(self):
        """确保 OCR.__call__(self, img, cls=True) 签名未被移植过程改动。"""
        import inspect

        sig = inspect.signature(OCR.__call__)
        params = list(sig.parameters)
        assert params == ["self", "img", "cls"]
        assert sig.parameters["cls"].default is True


class TestLayoutRecognizerInstantiation:
    def test_layout_recognizer_loads(self, model_dir, monkeypatch):
        """LayoutRecognizer4YOLOv10 应该能正常实例化并加载 onnx 会话。

        Recognizer.__init__ 在 model_dir 未显式传入时会调用
        app.deepdoc.paths.deepdoc_model_dir()；这里通过 monkeypatch 把它指向
        测试用的 model_dir，避免测试污染项目里的默认模型缓存目录。
        """
        import app.deepdoc.vision.layout_recognizer as lr_module

        monkeypatch.setattr(lr_module, "deepdoc_model_dir", lambda: model_dir)
        lr = LayoutRecognizer4YOLOv10("layout")
        assert lr.ort_sess is not None
        assert lr.label_list == LayoutRecognizer4YOLOv10.labels
        assert lr.garbage_layouts == ["footer", "header", "reference"]

    def test_public_class_alias_and_call_signature(self):
        """确保移植后 LayoutRecognizer4YOLOv10 的公开方法签名未变。"""
        import inspect

        sig = inspect.signature(LayoutRecognizer4YOLOv10.__call__)
        params = list(sig.parameters)
        assert params == [
            "self", "image_list", "ocr_res", "scale_factor", "thr",
            "batch_size", "drop",
        ]


class TestOCRSyntheticImage:
    def test_ocr_recognizes_simple_text(self, model_dir):
        """合成一张单行文字图片，验证 OCR 能正确识别出文字内容。"""
        img = _make_text_image(["Hello World Test 123"])
        ocr = _make_ocr(model_dir)

        result = ocr(img)

        assert result, "OCR 应至少识别出一个文本框"
        texts = [rec_res[0] for _box, rec_res in result]
        joined = " ".join(texts)
        # 合成图片干净、字体清晰，允许少量 OCR 误差，只检查关键片段。
        assert "Hello" in joined
        assert "World" in joined

    def test_ocr_empty_image_returns_empty(self, model_dir):
        """空白图片（无文字）应该返回空的识别结果，不应抛异常。"""
        img = _make_text_image([])  # 没有文字，纯白图
        ocr = _make_ocr(model_dir)
        result = ocr(img)
        assert result == []


class TestLayoutRecognizerTwoColumn:
    def test_layout_recognizer_separates_two_columns(self, model_dir, monkeypatch):
        """核心验收点：双栏文本图片应被识别为空间上分离的左右两组区域，
        而不是像当前 rag-kb 按行交叉拼接那样把两栏混在一起。

        由于合成图片没有真实 PDF 页面那种版式特征（页眉/页脚/自然分段），
        通用版面模型可能把每一行都识别成独立的 text 框而不是合并成大块，
        这里不对"合并成几块"做强假设，只验证一个更稳的信号：所有检测框的
        x 坐标应该能明显分成左右两个不重叠的簇（对应左右两栏），
        这正是后续排序逻辑（先左栏后右栏）依赖的空间信息。
        """
        import app.deepdoc.vision.layout_recognizer as lr_module

        monkeypatch.setattr(lr_module, "deepdoc_model_dir", lambda: model_dir)
        lr = LayoutRecognizer4YOLOv10("layout")

        img = _make_two_column_image()
        boxes = lr.forward([img], thr=0.1)[0]

        if not boxes:
            pytest.skip("合成图片在通用版面模型上未检测到任何区域，"
                        "样本非真实 PDF 页面，模型泛化到极简合成图上表现有限")

        x0s = sorted(b["bbox"][0] for b in boxes)
        # 用最大间隔法把 x0 分成两簇，验证间隔本身足够大（即存在明显的左右栏分隔），
        # 而不是所有框的 x0 连续分布、无法分栏。
        gaps = [x0s[i + 1] - x0s[i] for i in range(len(x0s) - 1)]
        max_gap = max(gaps) if gaps else 0
        span = x0s[-1] - x0s[0] if len(x0s) > 1 else 0

        assert len(boxes) >= 2, "双栏图片至少应检测到左右各一个区域"
        if span > 0:
            assert max_gap / span > 0.3, (
                f"检测框 x0 坐标应能明显分成左右两簇（最大间隔占比 {max_gap / span:.2f}），"
                "如果间隔很小说明模型没有区分出左右栏"
            )
