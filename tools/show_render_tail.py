"""看 render() 结尾有没有调用 save()（决定前端动作会不会触发整份回存）。"""

from __future__ import annotations

import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src = io.open("static/machining_dfm/legacy_app.js", encoding="utf-8").read()

m = re.search(r"function render\(", src)
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
body = src[m.start():j + 1]
print("render() 长度:", len(body))
print("\n=== 结尾 700 字符 ===")
print(body[-700:])

print("\n=== render() 里出现的 save/sve 调用 ===")
for hit in re.finditer(r"\b(save|sve|scheduleSave)\(\)", body):
    print("  …", body[max(0, hit.start() - 80):hit.start() + 30].replace("\n", " "), "…")
