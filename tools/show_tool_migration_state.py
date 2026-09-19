"""运维小工具：打印刀具库迁移状态（版本、字典表、外键、行数）——只读。"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "machining_dfm" / "machining_dfm.sqlite3"

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
tables = sorted(row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
print("全部表:", tables)
print("迁移版本:", {
    row[0]: row[1] for row in db.execute(
        "SELECT key,value_json FROM app_settings WHERE key LIKE '%schema_version'"
    )
})
for name in ("tools", "tools_legacy_v1", "tool_groups", "tool_categories"):
    if name in tables:
        count = db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"{name}: {count} 行")
print("tools 外键:", [(row[2], row[3], row[4]) for row in db.execute("PRAGMA foreign_key_list(tools)")])
print("库分类:", [tuple(row) for row in db.execute("SELECT code,label FROM tool_groups ORDER BY sort_order")])
print("类型数:", db.execute("SELECT COUNT(*) FROM tool_categories").fetchone()[0],
      "| 非内置:", [tuple(row) for row in db.execute(
          "SELECT code,label,source FROM tool_categories WHERE builtin=0")])
print("备份:", sorted(path.name for path in (ROOT / "data" / "machining_dfm" / "backups").glob("*.sqlite3")))
