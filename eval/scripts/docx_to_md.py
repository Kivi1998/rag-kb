#!/usr/bin/env python3
"""
DOCX → Markdown 预处理（绕过 V3 DocxParser 对内嵌图片的拒答）。

为什么需要：
- V3 DocxParser 碰到含图片的 DOCX 会抛 NeedsMultimodalParsingException
- 标 100+ 题的 QA 集，图片里信息往往不是关键，文本才是
- 抽纯文本 → .md → MarkdownParser 接收

用法：python3 docx_to_md.py <input.docx> <output.md>
"""
import sys
import zipfile
import re
from pathlib import Path


def extract_text(docx_path: Path) -> str:
    """从 DOCX 的 document.xml 抽可见文本（保留段落结构）。"""
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    # 删 <w:p>...</w:p> 之外的标签干扰
    # 段落以 </w:p> 分隔
    text = xml
    # 把段落结束符变成换行
    text = re.sub(r"</w:p>", "\n", text)
    # 表格行结束也加换行
    text = re.sub(r"</w:tr>", "\n", text)
    # 单元格用 | 分隔
    text = re.sub(r"</w:tc>", " | ", text)
    # 删所有其他 XML 标签
    text = re.sub(r"<[^>]+>", "", text)
    # XML 实体
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'")
    # 压缩连续空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    if not src.exists():
        print(f"❌ {src}")
        sys.exit(1)
    body = extract_text(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(f"# {src.stem}\n\n{body}\n", encoding="utf-8")
    print(f"✅ {src.name} -> {dst.name} ({len(body)} chars)")


if __name__ == "__main__":
    main()
