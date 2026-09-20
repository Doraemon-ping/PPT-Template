# -*- coding: utf-8 -*-
"""扫一遍 app/ 下所有 .py 是不是合法 UTF-8，把被外部工具写坏的文件揪出来。"""
import pathlib

bad = []
for path in sorted(pathlib.Path("app").rglob("*.py")):
    if "__pycache__" in path.parts:
        continue
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        bad.append((str(path), str(exc)))
    else:
        if raw.startswith(b"\xef\xbb\xbf"):
            bad.append((str(path), "带 UTF-8 BOM"))

if bad:
    print("× 这些文件不是干净的 UTF-8：")
    for name, why in bad:
        print("  -", name, "|", why)
else:
    print("√ app/ 下所有 .py 都是干净的 UTF-8（无 BOM）")
