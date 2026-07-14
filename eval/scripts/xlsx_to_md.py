#!/usr/bin/env python3
"""
XLSX → Markdown 预处理脚本（V3 dump 工具前置步骤）。

为什么需要：
- V3 DocumentParserFactory 不支持 .xlsx
- MarkdownParser 支持 .md
- 把 XLSX 的每个 sheet 渲染成 Markdown 表格 → 用 .md 喂给 MarkdownParser

用法：
    python3 xlsx_to_md.py <input.xlsx> <output.md>
"""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import load_workbook


def sheet_to_markdown(ws) -> str:
    """把一个 sheet 渲染成 Markdown 表格。"""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return ""

    # 第一行作为表头；过滤全 None 的列
    headers = [str(c).strip() if c is not None else "" for c in rows[0]]
    if not any(headers):
        return ""

    # 数据行
    body = []
    for row in rows[1:]:
        cells = [str(c).strip() if c is not None else "" for c in row]
        if any(cells):
            body.append(cells)

    md = [f"## {ws.title}", ""]
    md.append("| " + " | ".join(headers) + " |")
    md.append("| " + " | ".join("---" for _ in headers) + " |")
    for r in body:
        # 转义管道符，避免破坏表格
        cells = [c.replace("|", "\\|").replace("\n", " ") for c in r]
        md.append("| " + " | ".join(cells) + " |")
    md.append("")
    return "\n".join(md)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    if not src.exists():
        print(f"❌ 源文件不存在: {src}")
        sys.exit(1)

    wb = load_workbook(src, read_only=True, data_only=True)
    sections = [f"# {src.stem}", ""]
    for ws in wb.worksheets:
        sections.append(sheet_to_markdown(ws))
    wb.close()

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(sections), encoding="utf-8")
    print(f"✅ {src.name} → {dst.name} ({len(wb.worksheets)} sheets)")


if __name__ == "__main__":
    main()
