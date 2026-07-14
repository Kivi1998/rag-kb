"""对移植自 RAGFlow deepdoc 的表格结构识别与中文分词器的测试。

覆盖：
  - app.deepdoc.nlp.rag_tokenizer：词典加载 + 中英文分词
  - app.deepdoc.vision.table_structure_recognizer.TableStructureRecognizer：
    实例化（mock 掉真实 ONNX 模型下载/加载，避免测试依赖网络）
  - construct_table()：用手工构造的、无边框（靠坐标对齐）的表格 boxes 数据，
    验证按行列重组文本的核心逻辑
"""
from __future__ import annotations

from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# rag_tokenizer
# ---------------------------------------------------------------------------

class TestRagTokenizer:
    def test_module_loads_dictionary_and_builds_trie(self):
        """能正常 import 并加载 huqie 词典（内部会建 datrie 索引/缓存）。"""
        from app.deepdoc.nlp import rag_tokenizer

        assert rag_tokenizer.tokenizer is not None
        assert rag_tokenizer.tokenizer.trie_ is not None
        # trie 不应为空，至少能查到一个常见词的词频
        assert rag_tokenizer.freq("中国") > 0

    def test_tokenize_chinese_text(self):
        from app.deepdoc.nlp import rag_tokenizer

        tokens = rag_tokenizer.tokenize("这周日你去吗？这周日你有空吗？").split()
        assert len(tokens) > 0
        # 分词结果应保留原文包含的关键字符（不应整句原样未切分）
        assert "".join(tokens).replace(" ", "") != ""
        assert any("周日" in t or "周" in t for t in tokens)

    def test_tokenize_english_text(self):
        from app.deepdoc.nlp import rag_tokenizer

        result = rag_tokenizer.tokenize("Hello world, this is a table test.")
        assert "hello" in result
        assert "world" in result

    def test_tag_person_name_heuristic(self):
        """tag() 返回词性标注，用于 blockType() 判断是否人名（'nr'）。"""
        from app.deepdoc.nlp import rag_tokenizer

        # 不对具体词条做强断言（词典内容不受我们控制），只验证接口可调用且类型正确
        result = rag_tokenizer.tag("测试")
        assert isinstance(result, str)

    def test_fine_grained_tokenize(self):
        from app.deepdoc.nlp import rag_tokenizer

        tks = rag_tokenizer.tokenize("数据分析项目经理搜索数据分析")
        fine = rag_tokenizer.fine_grained_tokenize(tks)
        assert isinstance(fine, str)
        assert len(fine) > 0


# ---------------------------------------------------------------------------
# TableStructureRecognizer 实例化（mock 掉真实模型加载）
# ---------------------------------------------------------------------------

class TestTableStructureRecognizerInstantiation:
    def test_instantiate_with_mocked_onnx_session(self, tmp_path):
        """不依赖网络/真实 ONNX 模型文件：mock InferenceSession + snapshot_download，
        验证 TableStructureRecognizer() 能正常构造，且保留公开接口的类名/方法签名。
        """
        from app.deepdoc.vision import table_structure_recognizer as tsr_mod

        fake_model_file = tmp_path / "tsr.onnx"
        fake_model_file.write_bytes(b"not-a-real-onnx-model")

        fake_input_node = mock.Mock()
        fake_input_node.name = "image"
        # shape 需要真正可切片（真实 onnxruntime 返回的是元组/列表），不能留作 Mock，
        # 否则 recognizer.py 里的 self.ort_sess.get_inputs()[0].shape[2:4] 会抛
        # TypeError，被 __init__ 的 except 吞掉后错误地触发真实 snapshot_download。
        fake_input_node.shape = [1, 3, 800, 608]
        fake_output_node = mock.Mock()
        fake_output_node.name = "output"

        fake_session = mock.Mock()
        fake_session.get_inputs.return_value = [fake_input_node]
        fake_session.get_outputs.return_value = [fake_output_node]

        with mock.patch.object(tsr_mod, "deepdoc_model_dir", return_value=str(tmp_path)), \
             mock.patch("app.deepdoc.vision.recognizer.ort.InferenceSession", return_value=fake_session), \
             mock.patch("app.deepdoc.vision.recognizer.ort.RunOptions"):
            recognizer = tsr_mod.TableStructureRecognizer()

        assert isinstance(recognizer, tsr_mod.TableStructureRecognizer)
        assert recognizer.label_list == tsr_mod.TableStructureRecognizer.labels

    def test_instantiate_falls_back_to_snapshot_download_on_missing_model(self, tmp_path):
        """模型文件不存在时应尝试 snapshot_download（这里同样 mock 掉，不发真实网络请求）。"""
        from app.deepdoc.vision import table_structure_recognizer as tsr_mod

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        downloaded_dir = tmp_path / "downloaded"
        downloaded_dir.mkdir()
        (downloaded_dir / "tsr.onnx").write_bytes(b"not-a-real-onnx-model")

        fake_input_node = mock.Mock()
        fake_input_node.name = "image"
        fake_input_node.shape = [1, 3, 800, 608]
        fake_output_node = mock.Mock()
        fake_output_node.name = "output"
        fake_session = mock.Mock()
        fake_session.get_inputs.return_value = [fake_input_node]
        fake_session.get_outputs.return_value = [fake_output_node]

        with mock.patch.object(tsr_mod, "deepdoc_model_dir", return_value=str(empty_dir)), \
             mock.patch.object(tsr_mod, "snapshot_download", return_value=str(downloaded_dir)) as mock_dl, \
             mock.patch("app.deepdoc.vision.recognizer.ort.InferenceSession", return_value=fake_session), \
             mock.patch("app.deepdoc.vision.recognizer.ort.RunOptions"):
            recognizer = tsr_mod.TableStructureRecognizer()

        mock_dl.assert_called_once()
        assert isinstance(recognizer, tsr_mod.TableStructureRecognizer)


# ---------------------------------------------------------------------------
# construct_table(): 无边框、靠坐标对齐的表格重组
# ---------------------------------------------------------------------------

def _box(text, top, bottom, x0, x1, layout_type="table", page_number=1):
    """构造一个最简化的 OCR box，字段对齐 construct_table() 所需的键。"""
    return {
        "text": text,
        "top": top,
        "bottom": bottom,
        "x0": x0,
        "x1": x1,
        "layout_type": layout_type,
        "page_number": page_number,
    }


class TestConstructTable:
    def test_borderless_table_reconstructs_rows_and_columns(self):
        """模拟费率表场景：无边框，仅靠空格/坐标对齐。
        3 行 x 3 列："" | 30岁男性 | 30岁女性
                    费率A | 100     | 90
                    费率B | 200     | 180
        验证 construct_table 能把同一行的文本正确聚合在一起，
        不会把不同行的数字错配（如把 30 岁的费率错配给别的行）。
        """
        from app.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

        row_h = 20
        col_xs = [(0, 80), (80, 160), (160, 240)]

        rows_data = [
            ["性别", "30岁男性", "30岁女性"],
            ["费率A", "100", "90"],
            ["费率B", "200", "180"],
        ]

        boxes = []
        for r, row_texts in enumerate(rows_data):
            top = r * row_h
            bottom = top + row_h
            for (x0, x1), text in zip(col_xs, row_texts):
                boxes.append(_box(text, top, bottom, x0, x1))

        html = TableStructureRecognizer.construct_table(list(boxes), is_english=False, html=True)

        assert "<table>" in html
        # 表头行的两个年龄列都应出现
        assert "30岁男性" in html
        assert "30岁女性" in html
        # 费率数字应各自出现，且不应该出现错配（不会出现例如 100 和 90 被拼接到同一格）
        assert "100" in html
        assert "90" in html
        assert "200" in html
        assert "180" in html

        # 关键校验：每一行的费率数字应该和它自己那一行的行首标签绑在一起，
        # 不应该出现跨行错配（例如 "30岁男性" 的费率被错配成 "费率B" 那一行的数字）。
        rows_html = html.split("<tr>")[1:]
        row_with_100 = next(r for r in rows_html if "100" in r)
        assert "费率A" in row_with_100
        assert "费率B" not in row_with_100  # 100 属于费率A行，不应窜到费率B行
        row_with_200 = next(r for r in rows_html if "200" in r)
        assert "费率B" in row_with_200
        assert "费率A" not in row_with_200  # 200 属于费率B行，不应窜到费率A行
        # 同一行内的两个费率数字（男/女）应该同框出现
        assert "90" in row_with_100
        assert "180" in row_with_200

    def test_construct_table_desc_mode_no_crash(self):
        """html=False 分支（生成描述性文本列表）也应能正常跑通，不抛异常。"""
        from app.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

        row_h = 20
        col_xs = [(0, 80), (80, 160)]
        rows_data = [
            ["姓名", "年龄"],
            ["张三", "30"],
            ["李四", "40"],
        ]
        boxes = []
        for r, row_texts in enumerate(rows_data):
            top = r * row_h
            bottom = top + row_h
            for (x0, x1), text in zip(col_xs, row_texts):
                boxes.append(_box(text, top, bottom, x0, x1))

        row_txt = TableStructureRecognizer.construct_table(list(boxes), is_english=False, html=False)
        assert isinstance(row_txt, list)

    def test_empty_boxes_returns_empty(self):
        from app.deepdoc.vision.table_structure_recognizer import TableStructureRecognizer

        assert TableStructureRecognizer.construct_table([], html=True) == []


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
