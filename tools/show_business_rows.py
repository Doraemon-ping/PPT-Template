"""看四个基础库的列结构，以及项目里对刀具库的引用方式（只读）。"""

from __future__ import annotations

import io
import json
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

db = sqlite3.connect("file:data/machining_dfm/machining_dfm.sqlite3?mode=ro", uri=True)
db.row_factory = sqlite3.Row

tables = [r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("=== 全部表 ===")
for name in tables:
    count = db.execute(f'SELECT count(*) AS n FROM "{name}"').fetchone()["n"]
    print(f"  {name:34s} {count:6d} 行")

for name in ("tools", "machines", "fixtures", "gauges"):
    if name not in tables:
        continue
    columns = [r["name"] for r in db.execute(f'PRAGMA table_info("{name}")')]
    print(f"\n=== {name} 列 ===")
    print("  ", ", ".join(columns))

state = json.loads(db.execute("SELECT state_json FROM projects ORDER BY updated DESC LIMIT 1").fetchone()["state_json"])
print("\n=== 工序刀具行 tp 与刀具库 name 的匹配 ===")
names = {}
for row in db.execute("SELECT id,name FROM tools"):
    names.setdefault(row["name"], []).append(row["id"])
for row in state["pr"][0]["tl"][:8]:
    tp = row.get("tp")
    print(f"  tl.id={row.get('id')!r:8s} tp={tp!r:26s} 刀具库同名 {len(names.get(tp, []))} 条")

print("\n=== 选型（名称引用）===")
for key in ("fixQ", "fixQC", "insp", "inspQ", "icnX", "fcnX", "_vSnap"):
    value = state["G"].get(key)
    print(f"  {key:8s} = {json.dumps(value, ensure_ascii=False)[:260]}")

print("\n=== 基础库的“逻辑删除”相关列 ===")
for name in ("machines", "tools", "fixtures", "gauges", "tool_groups", "tool_categories", "fixture_centers", "gauge_categories"):
    if name not in tables:
        continue
    columns = [r["name"] for r in db.execute(f'PRAGMA table_info("{name}")')]
    soft = [c for c in columns if any(word in c.lower() for word in ("delete", "archiv", "active", "enabled"))]
    print(f"  {name:22s} 软删除列: {soft or '（无）'}")
