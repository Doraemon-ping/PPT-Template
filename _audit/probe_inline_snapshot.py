# -*- coding: utf-8 -*-
"""查 rowid=112 那条快照：哪个项目、哪种 kind、内联图在哪个键上。"""
import json
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "machining_dfm" / "machining_dfm.sqlite3"
db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
rows = db.execute(
    "SELECT rowid AS rid, id, project_id, revision, kind, name, created, length(state_json) AS n, "
    "state_json FROM project_versions ORDER BY rowid DESC LIMIT 12").fetchall()
print(f"{'rowid':>6} {'rev':>5} {'kind':<8} {'字节':>7}  project  created              含 data:image")
for row in rows:
    text = row["state_json"] or ""
    print(f"{row['rid']:>6} {row['revision']:>5} {row['kind']:<8} {row['n']:>7}  "
          f"{row['project_id'][:8]} {row['created'][:19]}  {'有' if 'data:image' in text else '无'}")

print()
allinline = db.execute(
    "SELECT rowid AS rid, project_id, revision, kind, created, state_json FROM project_versions "
    "WHERE state_json LIKE '%data:image%'").fetchall()
print("全库含内联图的快照 =", len(allinline))
for row in allinline:
    snapshot = json.loads(row["state_json"])
    paths = []

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str) and node.startswith("data:image"):
            paths.append((path, len(node)))

    walk(snapshot)
    print(f"  rowid={row['rid']} 第 {row['revision']} 版 kind={row['kind']} "
          f"（{row['project_id'][:8]}，{row['created'][:19]}）")
    for path, size in paths:
        print(f"      {path} → {size} 字符")

print()
print("项目清单：")
for row in db.execute("SELECT id, name, revision, length(state_json) AS n FROM projects"):
    print(f"  {row['id'][:8]}  rev={row['revision']:<4} state_json={row['n']} 字节  {row['name'][:40]}")
