"""打印前端里"工具价格/寿命、_vf、夹具费用"这几段真实代码（只读）。"""

from __future__ import annotations

import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src = io.open("static/machining_dfm/legacy_app.js", encoding="utf-8").read()

print("=== 按刀具名取 price/life 的上下文 ===")
for match in re.finditer(r"\.tp===t\.tp", src):
    start = max(0, match.start() - 420)
    print("  …", re.sub(r"\s+", " ", src[start:match.end() + 260]), "…\n")

print("\n=== _vf 的定义 ===")
for match in re.finditer(r"_vf\s*=", src):
    start = max(0, match.start() - 260)
    print("  …", re.sub(r"\s+", " ", src[start:match.end() + 160]), "…\n")

print("\n=== 夹具选型 k 的形状（fixByKey 用哪个键）===")
for match in re.finditer(r"function fixByKey", src):
    print("  …", re.sub(r"\s+", " ", src[match.start():match.start() + 420]), "…\n")

print("\n=== cI（工序的夹具引用）怎么用 ===")
for match in re.finditer(r"\bcI\b", src):
    start = max(0, match.start() - 160)
    print("  …", re.sub(r"\s+", " ", src[start:match.end() + 200]), "…\n")
