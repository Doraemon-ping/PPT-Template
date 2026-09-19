# -*- coding: utf-8 -*-
"""59d0a9ab「11」这个项目是谁建的？看它的变更流水与内容。"""
import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "machining_dfm" / "machining_dfm.sqlite3"
db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
PID = "59d0a9ab673444c5b59b131b3e411090"

row = db.execute("SELECT * FROM projects WHERE id=?", (PID,)).fetchone()
print("项目行：", {key: row[key] for key in row.keys() if key != "state_json"})
print()
print("变更流水（前 6 条）：")
for item in db.execute("SELECT action,entity,label,created FROM project_changes "
                       "WHERE project_id=? ORDER BY created LIMIT 6", (PID,)):
    print("  ", dict(item))
print()
print("各域行数：")
for table in ("project_settings", "project_processes", "project_process_tools", "project_issues",
              "project_fixtures", "project_gauges", "project_versions"):
    n = db.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (PID,)).fetchone()[0]
    print(f"   {table:<24} {n}")
print()
first = db.execute("SELECT revision, state_json FROM project_versions WHERE project_id=? "
                   "ORDER BY revision LIMIT 1", (PID,)).fetchone()
state = json.loads(first["state_json"])
print("第 1 版快照的形状：G 键", len(state.get("G", {})), "｜pr", len(state.get("pr", [])),
      "｜is", len(state.get("is", [])), "｜pI 长度", len(state.get("G", {}).get("pI", "")))
print("G 的前几个键：", list(state.get("G", {}))[:12])
