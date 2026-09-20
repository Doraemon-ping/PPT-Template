"""打印刀具库（及附件表）的真实建表 SQL、索引与字段登记表，便于对照文档。

用法：python tools/show_tool_schema.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "machining_dfm" / "machining_dfm.sqlite3"

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
for name in ("tool_groups", "tool_categories", "tools", "assets"):
    print(db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0] + ";")
print()
print("tools 外键:", [
    f"{row[3]} → {row[2]}.{row[4]}" for row in db.execute("PRAGMA foreign_key_list(tools)")
])
for row in db.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name IN ('tools','tool_categories')"):
    if row["sql"]:
        print(row["sql"] + ";")
print()
print("工具函数插入列顺序:", ", ".join(
    row[1] for row in db.execute("PRAGMA table_info(tools)")
))
print()

from app.domains.tools import TOOL_DERIVED, tool_field_headers  # noqa: E402

print("字段登记表（tools 表）:")
for item in tool_field_headers():
    print(json.dumps(item, ensure_ascii=False))
print()
print("自动列（不入库）:")
for item in TOOL_DERIVED:
    print(json.dumps(item, ensure_ascii=False))
