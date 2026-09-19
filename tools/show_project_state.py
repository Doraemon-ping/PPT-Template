"""看当前线上项目业务数据的形状与体量（只读）。"""

from __future__ import annotations

import io
import json
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB = "data/machining_dfm/machining_dfm.sqlite3"
db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.row_factory = sqlite3.Row

print("=== 项目表 ===")
for row in db.execute("SELECT id,name,revision,archived,length(state_json) AS bytes,created,updated FROM projects"):
    print(f"  {row['name'][:34]:36s} rev={row['revision']:3d} archived={row['archived']} state={row['bytes']/1024:8.1f} KB 更新={row['updated'][:19]}")

print("\n=== 版本历史 ===")
for row in db.execute("SELECT project_id,count(*) AS n,sum(length(state_json)) AS bytes,max(revision) AS top FROM revisions GROUP BY project_id"):
    print(f"  项目 {row['project_id'][:12]}… 共 {row['n']} 个版本，合计 {row['bytes']/1024/1024:.1f} MB，最新 rev={row['top']}")

print("\n=== 最新项目 state 结构 ===")
row = db.execute("SELECT name,state_json FROM projects ORDER BY updated DESC LIMIT 1").fetchone()
state = json.loads(row["state_json"])
print("  项目:", row["name"])
for key, value in state.items():
    if isinstance(value, list):
        print(f"  {key:6s} list  {len(value):5d} 项  {len(json.dumps(value, ensure_ascii=False))/1024:8.1f} KB")
    elif isinstance(value, dict):
        print(f"  {key:6s} dict  {len(value):5d} 键  {len(json.dumps(value, ensure_ascii=False))/1024:8.1f} KB")
    else:
        print(f"  {key:6s} {type(value).__name__}")

globals_ = state.get("G", {})
print("\n=== G 逐键体量（前 25 大）===")
sizes = sorted(((len(json.dumps(v, ensure_ascii=False)), k, type(v).__name__) for k, v in globals_.items()), reverse=True)
for size, key, kind in sizes[:25]:
    print(f"  {key:14s} {kind:5s} {size/1024:8.1f} KB")

print("\n=== 工序样本（第一条）===")
if state.get("pr"):
    process = state["pr"][0]
    print("  字段:", list(process))
    print("  tl 行数:", len(process.get("tl", [])))
    if process.get("tl"):
        print("  刀具行字段:", list(process["tl"][0]))

print("\n=== 问题清单样本 ===")
if state.get("is"):
    issue = state["is"][0]
    print("  字段:", {k: (f"<{len(v)/1024:.1f}KB 图片>" if isinstance(v, str) and len(v) > 5000 else v) for k, v in issue.items()})

print("\n=== 版本履历样本 ===")
if state.get("vh"):
    print("  字段:", list(state["vh"][0]))
    print("  内容:", json.dumps(state["vh"][0], ensure_ascii=False)[:300])
