"""把前端里"按名字找库、按库算价"的地方全找出来（只读）。

1b 阶段要把这些改成 id 引用 + 价格快照，先列清单，避免漏掉某处导致报价静默算错。
"""

from __future__ import annotations

import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
src = io.open("static/machining_dfm/legacy_app.js", encoding="utf-8").read()

PATTERNS = {
    "刀具按名字匹配": r"TDB\[[^\]]*\]\.tp\s*===\s*[^;]{0,40}",
    "刀具按名字查找": r"tp\s*===\s*t\.tp|\.tp\s*===\s*tp\b",
    "夹具 fixByKey": r"fixByKey\([^)]{0,60}\)",
    "夹具按中心+名字": r"\(fix\.center\|\|''\)\|\|\|\"|center\s*\+\s*'\|'",
    "检具 inspByKey": r"inspByKey\([^)]{0,60}\)",
    "设备按 id 取": r"mid\b[^;\n]{0,60}",
    "夹具费用 fixP": r"fixP[^;\n]{0,50}",
    "设备费用 eqP": r"eqP[^;\n]{0,50}",
    "派生 _ct": r"_ct\b[^;\n]{0,60}",
    "派生 _vc": r"_vc\b[^;\n]{0,60}",
    "派生 _fz": r"_fz\b[^;\n]{0,60}",
    "工序引用 is.pr": r"\bpr\s*[:=]\s*[^;,\n]{0,40}(?:nm|name)",
    "nc 计数": r"\bnc\.[a-z_]+",
    "toolCost 定义": r"function toolCost\([^)]*\)\{[\s\S]{0,400}?\n\}",
    "fixQuoteTable": r"function fixQuoteTable\([^)]*\)\{[\s\S]{0,300}?\n\}",
}

for label, pattern in PATTERNS.items():
    hits = list(dict.fromkeys(m.group(0) for m in re.finditer(pattern, src)))
    print(f"\n=== {label}：{len(hits)} 处 ===")
    for hit in hits[:8]:
        text = re.sub(r"\s+", " ", hit).strip()
        print("  ", text[:150])
