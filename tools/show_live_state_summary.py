"""迁移后的线上库现状一页纸（给汇报用的数字）。"""

from __future__ import annotations

import io
import json
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
db = sqlite3.connect("file:data/machining_dfm/machining_dfm.sqlite3?mode=ro", uri=True)
db.row_factory = sqlite3.Row

page_count = db.execute("PRAGMA page_count").fetchone()[0]
page_size = db.execute("PRAGMA page_size").fetchone()[0]
print("项目版本            = v" + str(db.execute("SELECT revision FROM projects").fetchone()[0]))
print("revisions 条数      =", db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0])
print("库文件大小          = %.2f MB" % (page_count * page_size / 1024 / 1024))

raw = db.execute("SELECT state_json FROM projects").fetchone()[0]
print("projects.state_json = %.1f KB，顶层键 %s" % (len(raw.encode("utf-8")) / 1024, sorted(json.loads(raw))))
archive = db.execute("SELECT state_json FROM projects_legacy_v1").fetchone()[0]
print("迁移前归档          = %.1f KB（projects_legacy_v1）" % (len(archive.encode("utf-8")) / 1024))

row = db.execute("SELECT * FROM project_settings").fetchone()
extra = json.loads(row["extra_json"])
print("project_settings    = 1 行 %d 列；extra_json %.1f KB，额外键 %s"
      % (len(row.keys()), len(row["extra_json"].encode("utf-8")) / 1024, list(extra)))
print("图片槽 product      =", row["product_photo_id"])
print("附件行数            =", db.execute("SELECT COUNT(*) FROM assets").fetchone()[0])
tables = sorted(x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%legacy%'"))
print("归档表              =", tables)
backups = sorted(p.rsplit("\\", 1)[-1] for p in
                 [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE 0")] )
print("备份目录文件        =", sorted(x.name for x in (__import__("pathlib").Path("data/machining_dfm/backups")).iterdir()))
