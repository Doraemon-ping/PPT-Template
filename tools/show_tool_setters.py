"""补齐 sB/sN/atT 与设备价格字段（只读）。"""

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


for name in ("sB", "sN", "atT", "gR", "gTC", "midIndex"):
    text = body(name)
    print(f"=== {name} ===\n  {re.sub(r'  +', ' ', re.sub(chr(10), ' ', text))[:420] if text else '(无)'}\n")

print("=== 设备库的价格字段（setProcMachine/refEqPrice 用的是 gm(p).price）===")
machines = re.search(r"function gm\(pi\)\{[\s\S]{0,300}?\n\}", src)
print("  gm:", re.sub(r"\s+", " ", machines.group(0))[:300] if machines else "(无)")
print("\n=== sS/sB/sN 在 bToolTable 里的字段名（按出现顺序）===")
table = body("bToolTable")
for match in re.finditer(r"\b(sS|sB|sN)\(", table):
    start = match.end()
    snippet = re.sub(r"\s+", " ", table[start:start + 60])
    print(f"  {match.group(1)} → {snippet[:58]}")
