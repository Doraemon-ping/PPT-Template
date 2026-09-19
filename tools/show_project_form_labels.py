"""提取项目信息相关表单的标签与输入 id（用于字段登记表的 label）。"""

from __future__ import annotations

import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src = io.open("static/machining_dfm/legacy_app.js", encoding="utf-8").read()

ROW = re.compile(r"'<div class=\"r\"><span class=\"l\">([^<]+)<br><span class=\"u\">([^<]*)</span></span>(.{0,320}?)</div>'")

for name in ("bSetup", "bSettings"):
    m = re.search(rf"function {name}\(", src)
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
    print("=====", name, "=====")
    for label, english, tail in ROW.findall(body):
        ids = re.findall(r'id="([^"]+)"', tail) or re.findall(r'id=([A-Za-z_][\w]*)', tail)
        print(f"  {label:16s} | {english:24s} | {ids}")
    print()
