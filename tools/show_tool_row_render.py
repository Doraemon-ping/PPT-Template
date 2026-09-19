"""刀具行表格到底怎么渲染、写入口在哪（只读）。"""

from __future__ import annotations

import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src = io.open("static/machining_dfm/legacy_app.js", encoding="utf-8").read()

print("=== 含 .tl 且像编辑入口的片段 ===")
seen = set()
for match in re.finditer(r"tl\s*\[", src):
    snippet = re.sub(r"\s+", " ", src[max(0, match.start() - 170):match.start() + 190])
    key = snippet[:90]
    if key in seen:
        continue
    seen.add(key)
    if "value=" in snippet or "onchange" in snippet or "oninput" in snippet or "setT" in snippet:
        print("  …", snippet, "…\n")

print("\n=== 名字里带 toolT/tRow/tRowHtml/setTF/setTT 的函数 ===")
for match in re.finditer(r"function (\w*(?:[Tt]ool|tRow|setT\w*)\w*)\(", src):
    print("  ", match.group(1))

print("\n=== 含 'tl[' 的 onchange/oninput（真实写入口）===")
handlers = set()
for match in re.finditer(r'on(?:change|input|click)="([^"]{0,240})"', src):
    handler = match.group(1)
    if ".tl[" in handler or "tl[" in handler:
        handlers.add(re.sub(r"\s+", " ", handler)[:200])
for handler in sorted(handlers):
    print("  ", handler)

print("\n=== 刀具行渲染函数（返回 <tr> 的那个）===")
for match in re.finditer(r"function (\w+)\(([^)]{0,60})\)\{(.{0,900}?)<tr>", src, re.S):
    name = match.group(1)
    print(f"  {name}({match.group(2)}) → 生成 tr")
