# -*- coding: utf-8 -*-
"""给文档用的库结构快照（只读）：表 → 行数 / 外键 / JSON 体积。"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "machining_dfm" / "machining_dfm.sqlite3"

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.row_factory = sqlite3.Row

tables = [row["name"] for row in db.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
print("库文件 =", DB)
print("大小   = %.2f MB（%d 字节）" % (DB.stat().st_size / 1024 / 1024, DB.stat().st_size))
print("sha256 =", hashlib.sha256(DB.read_bytes()).hexdigest()[:16])
print("表数   =", len(tables))
print()

total_fk = 0
for table in tables:
    rows = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    fks = db.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    total_fk += len(fks)
    detail = "、".join(f"{row['from']}→{row['table']}" for row in fks) or "（无）"
    print(f"{table:26s} {rows:5d} 行  外键 {len(fks):2d}  {detail}")
print()
print("外键列合计 =", total_fk)

print()
print("JSON 体积：")
for table, columns in (
        ("projects", ("state_json",)),
        ("project_versions", ("state_json",)),
        ("project_changes", ("extra_json",)),
        ("project_settings", ("extra_json",)),
        ("project_processes", ("count_json",)),
        ("project_fixtures", ("extra_json",)),
        ("project_gauges", ("extra_json",)),
):
    names = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    for column in columns:
        if column not in names:
            print(f"  {table}.{column}: 列不存在")
            continue
        size = db.execute(
            f"SELECT COALESCE(SUM(LENGTH({column})),0) FROM {table}").fetchone()[0]
        print(f"  {table}.{column}: {size} 字节")

print()
print("项目业务数据各表快照类列体积：")
for table in ("project_processes", "project_process_tools", "project_fixtures", "project_gauges"):
    names = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
    for column in names:
        if not column.endswith("_snapshot"):
            continue
        size = db.execute(
            f"SELECT COALESCE(SUM(LENGTH({column})),0) FROM {table}").fetchone()[0]
        print(f"  {table}.{column}: {size} 字节")

print()
print("老表还剩：", db.execute("SELECT COUNT(*) FROM project_selections").fetchone()[0], "行")
print("foreign_key_check =", db.execute("PRAGMA foreign_key_check").fetchall() or "干净")
print("integrity_check   =", db.execute("PRAGMA integrity_check").fetchone()[0])
