"""只读核对：真实库里的刀具迁移结果（不启动服务、不写库）。

用法：python tools/check_live_tool_db.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "machining_dfm" / "machining_dfm.sqlite3"

COLUMN_OF = {
    "tp": "name", "d": "diameter", "n": "spindle_rpm", "vf": "feed_rate",
    "cat": "category", "life": "life_minutes", "price": "price",
    "grp": "tool_group", "ln": "length",
}
KEYS = ("tp", "d", "n", "vf", "cat", "tI", "life", "price", "grp", "ln")

if not DB.is_file():
    sys.exit(f"找不到数据库：{DB}")

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
if "tools_legacy_v1" not in tables:
    sys.exit("还没有 tools_legacy_v1：刀具迁移尚未运行")

old = [json.loads(row["payload_json"]) for row in
       db.execute("SELECT payload_json FROM tools_legacy_v1 ORDER BY sort_order,id")]
new = db.execute("SELECT * FROM tools ORDER BY sort_order,id").fetchall()
print("旧归档行数:", len(old), "新类型化行数:", len(new))
print("版本:", json.loads(db.execute(
    "SELECT value_json FROM app_settings WHERE key='tool_library_schema_version'").fetchone()[0]))

differences = 0
for index, (before, after) in enumerate(zip(old, new)):
    for key in KEYS:
        if key == "tI":
            continue
        left, right = before.get(key), after[COLUMN_OF[key]]
        if key in ("tp", "cat", "grp"):
            if str(left or "") != str(right or ""):
                differences += 1
                print("差异", index, key, repr(left), repr(right))
        elif float(left or 0) != float(right):
            differences += 1
            print("差异", index, key, left, right)
print("逐行字段差异:", differences)
print("首行:", json.dumps(dict(new[0]), ensure_ascii=False) if new else "空")
print("带图片行数:", db.execute("SELECT COUNT(*) FROM tools WHERE photo_id IS NOT NULL").fetchone()[0])
print("资产类别分布:", [tuple(row) for row in db.execute("SELECT kind, COUNT(*) FROM assets GROUP BY kind")])
print("备份:", sorted(path.name for path in (ROOT / "data" / "machining_dfm" / "backups").glob("*.sqlite3")))
print("设备行数:", db.execute("SELECT COUNT(*) FROM machines").fetchone()[0],
      "| 夹具:", db.execute("SELECT COUNT(*) FROM fixtures").fetchone()[0],
      "| 检具:", db.execute("SELECT COUNT(*) FROM gauges").fetchone()[0])
