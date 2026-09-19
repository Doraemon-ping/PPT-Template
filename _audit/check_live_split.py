# -*- coding: utf-8 -*-
"""重启后看线上库现状（只读）：新表在不在、外键干不干净、最近几个版本是什么。"""
import hashlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "machining_dfm" / "machining_dfm.sqlite3"

digest = hashlib.sha256(DB.read_bytes()).hexdigest()
print("库文件        =", DB)
print("sha256        =", digest[:24], "·", DB.stat().st_size, "字节")

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
tables = [row["name"] for row in db.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("表数          =", len(tables))
for name in ("project_fixtures", "project_gauges", "project_selections", "project_changes"):
    if name not in tables:
        print(f"  {name:20s} 不在")
        continue
    total = db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    print(f"  {name:20s} {total} 行")

print()
print("project_changes 的列里有选型那几列吗 =",
      [row[1] for row in db.execute("PRAGMA table_info(project_changes)")
       if "row_id" in row[1]])
print("project_fixtures 外键 =",
      [(row["from"], row["table"], row["on_delete"])
       for row in db.execute("PRAGMA foreign_key_list(project_fixtures)")])
print("project_gauges   外键 =",
      [(row["from"], row["table"], row["on_delete"])
       for row in db.execute("PRAGMA foreign_key_list(project_gauges)")])

print()
for row in db.execute("SELECT id,name,revision,archived FROM projects ORDER BY rowid"):
    print(f"项目 {row['id'][:8]} rev={row['revision']:3d} archived={row['archived']} {row['name'][:40]}")
print()
print("最近 5 个保存版本：")
for row in db.execute(
        "SELECT project_id,revision,created FROM project_versions "
        "ORDER BY created DESC LIMIT 5"):
    print(f"  {row['project_id'][:8]} v{row['revision']:<4} {row['created']}")
print()
print("最近 5 条变更流水：")
for row in db.execute(
        "SELECT project_id,entity,action,label,created FROM project_changes "
        "ORDER BY created DESC LIMIT 5"):
    print(f"  {row['created']} {row['project_id'][:8]} {row['entity']:10s} {row['action']:8s} "
          f"{row['label'][:60]}")

print()
print("foreign_key_check =", db.execute("PRAGMA foreign_key_check").fetchall() or "干净")
print("integrity_check   =", db.execute("PRAGMA integrity_check").fetchone()[0])
db.close()
