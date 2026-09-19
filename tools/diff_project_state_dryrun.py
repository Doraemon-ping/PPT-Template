"""对比干跑副本里"归档的迁移前 state"与"迁移后还原的 state"到底差在哪。"""

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

archived = json.loads(db.execute("SELECT state_json FROM projects_legacy_v1 LIMIT 1").fetchone()["state_json"])
now = json.loads(db.execute("SELECT state_json FROM projects LIMIT 1").fetchone()["state_json"])

print("=== 归档（迁移前）state 顶层键:", list(archived))
print("=== 现在（迁移后）projects.state_json 顶层键:", list(now))

print("\n=== pr 逐工序逐键对比 ===")
for index, (old, new) in enumerate(zip(archived["pr"], now["pr"])):
    keys = sorted(set(old) | set(new))
    for key in keys:
        if old.get(key) != new.get(key):
            print(f"  pr[{index}].{key}: {str(old.get(key))[:80]!r} → {str(new.get(key))[:80]!r}")
print("  （以上为差异，无输出即一致）")

print("\n=== 归档表里的 pr[0] 键 ===", list(archived["pr"][0]))
print("=== 现在 pr[0] 键 ===", list(now["pr"][0]))
print("\n=== tl 行数对比 ===", [len(p.get("tl", [])) for p in archived["pr"]], "→", [len(p.get("tl", [])) for p in now["pr"]])
print("=== is ===", "一致" if archived["is"] == now["is"] else "不一致")
print("=== vh ===", "一致" if archived.get("vh") == now.get("vh") else "不一致")

row = db.execute("SELECT COUNT(*) AS n, MAX(length(state_json)) AS mx FROM projects").fetchone()
print("\nprojects.state_json 现在最大体积:", f"{row['mx'] / 1024:.1f} KB")
legacy = db.execute("SELECT MAX(length(state_json)) AS mx FROM projects_legacy_v1").fetchone()
print("归档的迁移前 state 体积:", f"{legacy['mx'] / 1024:.1f} KB")
