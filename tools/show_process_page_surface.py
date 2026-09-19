"""把工序页签（bProcess）的前端写面全列出来（只读）。

1b 阶段要用 process_page.js 接管这个页签，接手前必须知道：
哪些函数在改 PR / 刀具行、哪些 DOM id 带 onchange/onclick、哪些是"做完动作没重绘"的坑。
"""

from __future__ import annotations

import io
import re
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src = io.open("static/machining_dfm/legacy_app.js", encoding="utf-8").read()


def body(name: str) -> str:
    match = re.search(rf"function {name}\(", src)
    if not match:
        return ""
    depth, index = 0, src.index("{", match.start())
    position = index
    while position < len(src):
        if src[index] == "{":
            depth += 1
        elif src[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
        position = index
    return src[match.start():index + 1]


print("=== bProcess 结构（页面分区标题）===")
for title in re.findall(r"<h2>([^<]{1,40})</h2>", body("bProcess")):
    print("  ·", title)

print("\n=== 直接改 PR / 刀具行的函数 ===")
names = [m.group(1) for m in re.finditer(r"function (\w+)\(", src)]
touched = []
for name in names:
    text = body(name)
    if not text:
        continue
    writes = len(re.findall(r"\bPR\[[^\]]*\]\s*(?:\.\w+\s*)?=", text)) + len(re.findall(r"\.tl\.(?:push|splice)", text))
    if writes:
        touched.append((name, writes))
for name, writes in sorted(touched, key=lambda item: -item[1])[:22]:
    print(f"  {name:16s} 写 {writes} 处")

print("\n=== 刀具行表格里的 onchange / onclick（写面的精确入口）===")
handler_ids = Counter()
for match in re.finditer(r"on(?:change|click)=\"([^\"]{0,220})\"", body("bProcess")):
    handler = re.sub(r"'\s*\+\s*[pi]+\s*\+\s*'", "{i}", match.group(1))
    handler = re.sub(r"\"\s*\+\s*[pi]+\s*\+\s*\"", "{i}", handler)
    if "PR[" in handler or "tl" in handler or "Proc" in handler:
        handler_ids[handler[:150]] += 1
for handler, count in handler_ids.most_common(28):
    print(f"  ×{count}  {handler}")

print("\n=== 输入框 id（工序页签） ===")
ids = re.findall(r"id=\"([a-zA-Z0-9_]+)\"", body("bProcess"))
print("  ", sorted(set(ids)))

print("\n=== 加/删/排序 相关函数签名 ===")
for name in ("addProc", "delProc", "moveProc", "addT", "delT", "addTool", "delTool", "setIns", "setProc", "calcT", "st", "gm"):
    text = body(name)
    if text:
        head = re.sub(r"\s+", " ", text[:190])
        print(f"  {name}: {head}…")

print("\n=== 动作后有没有重绘（render() 调用计数）===")
for name in ("addProc", "delProc"):
    text = body(name)
    print(f"  {name}: render() × {text.count('render()')}, save() × {text.count('save()')}")
