"""把刀具行的唯一写入口 sS()、渲染器 bToolTable()、工序级 setter 全部打印出来（只读）。"""

from __future__ import annotations

import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src = io.open("static/machining_dfm/legacy_app.js", encoding="utf-8").read()


def body(name: str) -> str:
    match = re.search(rf"function {name}\(", src)
    if not match:
        return ""
    depth, index = 0, src.index("{", match.start())
    while index < len(src):
        if src[index] == "{":
            depth += 1
        elif src[index] == "}":
            depth -= 1
            if depth == 0:
                return src[match.start():index + 1]
        index += 1
    return ""


for name in ("sS", "setProcMachine", "updNC", "refEqPrice", "procToolCost", "getNCperTool"):
    text = body(name)
    print(f"=== {name} ===")
    print("  " + re.sub(r"\s+", " ", text)[:700] if text else "  (没有这个函数)")
    print()

table = body("bToolTable")
print("=== bToolTable 里的 sS 调用（字段清单）===")
for match in re.finditer(r"sS\('?\s*\+?\s*(?:pi)?\s*\+?\s*'?,?\s*\d*\s*,?\s*'([a-zA-Z_]+)'", table):
    print("  ", match.group(1))
print("\n=== bToolTable 里所有 onchange/onclick 处理名 ===")
names = set()
for match in re.finditer(r'on(?:change|input|click)="([a-zA-Z_]\w*)\(', table):
    names.add(match.group(1))
print("  ", sorted(names))
print("\n=== bToolTable 表头 ===")
head = re.search(r"<thead>(.*?)</thead>", table, re.S)
if head:
    for cell in re.findall(r"<th[^>]*>([^<]{0,30})", head.group(1)):
        print("  ·", cell)
print("\n=== 工序页签里改工序字段的入口 ===")
proc = body("bProcess")
for match in re.finditer(r'on(?:change|input|click)="([a-zA-Z_]\w*)\(([^"]{0,80})', proc):
    print("  ", match.group(1) + "(" + match.group(2)[:70])
