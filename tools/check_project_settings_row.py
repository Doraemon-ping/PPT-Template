"""只为核对还原结果：项目信息行、图片附件、版本号。"""

from __future__ import annotations

import io
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
db = sqlite3.connect("file:data/machining_dfm/machining_dfm.sqlite3?mode=ro", uri=True)
db.row_factory = sqlite3.Row

row = dict(db.execute("SELECT * FROM project_settings").fetchone())
for key in ("customer", "part", "project_type", "hours_per_day", "shifts", "days_per_month",
            "availability", "final_insp_type", "product_photo_id", "product2_photo_id", "updated"):
    print(f"  {key:20s} = {row[key]!r}")
print("  projects.revision   =", db.execute("SELECT revision FROM projects").fetchone()[0])
print("  revisions 条数      =", db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0])
for item in db.execute("SELECT id,path,size FROM assets WHERE path LIKE 'project_photo/%'"):
    print("  project_photo 附件  =", dict(item))
print("  assets 总数         =", db.execute("SELECT COUNT(*) FROM assets").fetchone()[0])
