"""打印 bSettings 与 render() 的页签栏，确定项目信息页要接管哪些字段。"""

from __future__ import annotations

import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src = io.open("static/machining_dfm/legacy_app.js", encoding="utf-8").read()


def body(name: str) -> str:
    m = re.search(rf"function {name}\(", src)
    if not m:
        return ""
    depth = 0
    i = src.index("{", m.start())
    j = i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return src[m.start():j + 1]


print("===== render() 里的页签栏 =====")
render = body("render")
for line in render.split(";"):
    if "curTab" in line or "tab(" in line or "labels" in line:
        print("  ", line.strip()[:400])
        print()

print("===== bSettings 全文 =====")
print(body("bSettings")[:3200])
