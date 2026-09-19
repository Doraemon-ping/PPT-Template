"""临时排查用：打印夹具库/检具库页面里"一行的单元格"是怎么渲染的（输入控件与操作列）。"""

from __future__ import annotations

import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
source = io.open(ROOT / "static" / "machining_dfm" / "legacy_app.js", encoding="utf-8").read()

for name in ("bFixDB", "bInspDB"):
    start = source.index(f"function {name}(")
    body = source[start:start + 12000]
    marker = "'</thead><tbody>'"
    offset = body.index(marker) + len(marker)
    print(f"===== {name} 行渲染（表体开始后 3200 字）=====")
    print(body[offset:offset + 3200].replace("\\'", "'").replace("\\'", "'"))
    print()
