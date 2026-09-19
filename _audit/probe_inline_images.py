# -*- coding: utf-8 -*-
"""只读排查：内联图片的快照行 + 哪些项目还在"表空、JSON 满"的状态。"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "machining_dfm" / "machining_dfm.sqlite3"

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.row_factory = sqlite3.Row

print("=== 1) 哪些保存版本快照里还带着内联图片 ===")
rows = db.execute(
    "SELECT id,project_id,revision,kind,created,length(state_json) AS n,state_json "
    "FROM project_versions WHERE state_json LIKE '%data:image%' ORDER BY created DESC").fetchall()
print("命中", len(rows), "行")
for row in rows[:8]:
    state = row["state_json"]
    hits = state.count("data:image")
    print(f"  v{row['revision']:<4} {row['created']} kind={row['kind']} "
          f"{row['n']} 字节 data:image × {hits}  project={row['project_id'][:8]}")
    # 找到内联发生在哪个字段
    def walk(value, path, depth=0, found=None):
        found = found if found is not None else []
        if depth > 9:
            return found
        if isinstance(value, str):
            if value.startswith("data:image"):
                found.append((path, len(value)))
            return found
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]", depth + 1, found)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else key, depth + 1, found)
        return found
    for path, size in walk(json.loads(state), "")[:6]:
        print(f"        {path}  {size} 字符")

print()
print("=== 2) 每个项目：表里有多少行 / state_json 多大 ===")
tables = ("project_processes", "project_process_tools", "project_issues",
          "project_fixtures", "project_gauges")
for row in db.execute("SELECT id,name,revision,length(state_json) AS n FROM projects ORDER BY rowid"):
    counts = {}
    for table in tables:
        counts[table] = db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (row["id"],)).fetchone()[0]
    inline = db.execute("SELECT COUNT(*) FROM projects WHERE id=? AND state_json LIKE '%data:image%'",
                        (row["id"],)).fetchone()[0]
    print(f"  {row['id'][:8]} rev={row['revision']:<4} state_json={row['n']:>7} 字节"
          f" 内联图={inline}")
    print(f"        " + "  ".join(f"{name.replace('project_','')}={value}" for name, value in counts.items()))

print()
print("=== 3) 最近的保存版本（最新 8 条）===")
for row in db.execute(
        "SELECT project_id,revision,kind,created,length(state_json) AS n FROM project_versions "
        "ORDER BY created DESC LIMIT 8"):
    print(f"  v{row['revision']:<4} {row['created']} kind={row['kind']:<8} "
          f"{row['n']:>7} 字节 {row['project_id'][:8]}")

print()
print("=== 4) project_settings.extra_json 里有没有内联图 ===")
row = db.execute("SELECT COUNT(*) AS n FROM project_settings WHERE extra_json LIKE '%data:image%'").fetchone()
print("  ", row["n"], "行")
db.close()
