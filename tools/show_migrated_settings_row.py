"""看迁移后项目信息表一行的真实内容（含 extra_json 是否还夹着图片、库里文本字段有多大）。"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

target = Path(sys.argv[1])
db = sqlite3.connect(f"file:{target / 'machining_dfm.sqlite3'}?mode=ro", uri=True)
db.row_factory = sqlite3.Row

print("=== project_settings 一行 ===")
row = db.execute("SELECT * FROM project_settings").fetchone()
for key in row.keys():
    value = row[key]
    if key == "extra_json":
        print(f"  {key:22s} = {value}")
    elif key.endswith("_id"):
        print(f"  {key:22s} = {value}")
    else:
        print(f"  {key:22s} = {value!r}")

extra = json.loads(row["extra_json"] or "{}")
print("\n  extra_json 键:", list(extra), "| 是否夹带图片:",
      [k for k, v in extra.items() if isinstance(v, str) and v.startswith("data:")] or "没有")

print("\n=== 库里文本字段体量（迁移前 vs 迁移后）===")
before = db.execute("SELECT length(state_json) AS n FROM projects_legacy_v1").fetchone()["n"]
after = db.execute("SELECT length(state_json) AS n FROM projects").fetchone()["n"]
settings = db.execute("SELECT length(extra_json) AS n FROM project_settings").fetchone()["n"]
revisions = db.execute("SELECT SUM(length(state_json)) AS n FROM revisions").fetchone()["n"]
print(f"  迁移前 projects.state_json : {before/1024:9.1f} KB")
print(f"  迁移后 projects.state_json : {after/1024:9.1f} KB")
print(f"  迁移后 settings.extra_json : {settings/1024:9.1f} KB")
print(f"  历史版本快照合计（未动）    : {revisions/1024/1024:9.2f} MB")
print(f"  库文件大小                 : {db.execute('PRAGMA page_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0] / 1024 / 1024:.2f} MB")
print("\n=== 附件目录 ===")
for path in sorted((target / "assets").rglob("*")):
    if path.is_file():
        print(f"  {path.relative_to(target)}  {path.stat().st_size/1024:.1f} KB")
