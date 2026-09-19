"""一次性校验脚本：在真实数据副本上跑刀具库迁移，逐行比对迁移前后。"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.machining_dfm import MachiningDFMStore  # noqa: E402

REAL = ROOT / "data" / "machining_dfm"
SEED = ROOT / "app" / "resources" / "machining_dfm_seed"

work = Path(tempfile.mkdtemp(prefix="toolcheck-"))
target = work / "machining_dfm"
shutil.copytree(REAL, target)
print("副本:", target)

# 迁移前：旧刀具行（已是 v2 的库从归档表读，未迁移的库从 payload_json 读）
before_db = sqlite3.connect(target / "machining_dfm.sqlite3")
before_db.row_factory = sqlite3.Row
tables = {row[0] for row in before_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
if "tools_legacy_v1" in tables:
    source_table, column = "tools_legacy_v1", "payload_json"
    print("迁移前形态: v2（类型化 tools + 归档表 tools_legacy_v1）")
elif "tools" in tables:
    columns = {row[1] for row in before_db.execute("PRAGMA table_info(tools)")}
    source_table = "tools" if "payload_json" in columns else ""
    column = "payload_json"
    if not source_table:
        source_table = ""  # 已经是类型化表但还没有归档：直接按列比对
    print("迁移前形态:", "v1 payload 表" if source_table else "类型化表（无归档）")
else:
    source_table, column = "", ""
    print("迁移前形态: 无 tools 表")

legacy_rows: list[dict] = []
if source_table:
    legacy_rows = [json.loads(row[column]) for row in before_db.execute(
        f"SELECT {column} FROM {source_table} ORDER BY sort_order, id"
    )]
else:
    for row in before_db.execute("SELECT * FROM tools ORDER BY sort_order, id"):
        legacy_rows.append({
            "tp": row["name"], "d": row["diameter"], "n": row["spindle_rpm"],
            "vf": row["feed_rate"], "cat": row["category"], "tI": "",
            "life": row["life_minutes"], "price": row["price"],
            "grp": row["tool_group"], "ln": row["length"],
        })
print("迁移前 tools 行数:", len(legacy_rows), "键:", sorted(legacy_rows[0]) if legacy_rows else None)
before_db.close()

store = MachiningDFMStore(target, SEED)

with store.connect() as db:
    tables = sorted(r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'tool%'"
    ))
    version = db.execute(
        "SELECT value_json FROM app_settings WHERE key='tool_library_schema_version'"
    ).fetchone()
    columns = [r[1] for r in db.execute("PRAGMA table_info(tools)")]
    foreign_keys = {f"{r[2]}.{r[3]} -> {r[4]}" for r in db.execute("PRAGMA foreign_key_list(tools)")}
    groups = db.execute("SELECT COUNT(*) FROM tool_groups").fetchone()[0]
    categories = db.execute("SELECT COUNT(*) FROM tool_categories").fetchone()[0]
    legacy_codes = [r[0] for r in db.execute(
        "SELECT code FROM tool_categories WHERE source='legacy' ORDER BY code"
    )]
print("表:", tables, "版本:", version["value_json"] if version else None)
print("tools 列:", columns)
print("外键:", sorted(foreign_keys))
print("字典: 库分类", groups, "项 / 类型", categories, "项；旧数据补录:", legacy_codes)

typed = store.tools.list_typed()
legacy = store.tools.list_legacy()
print("类型化行数:", len(typed), "旧视图行数:", len(legacy))

keys = ("tp", "d", "n", "vf", "cat", "tI", "life", "price", "grp", "ln")
mismatch = 0
for index, (old, new) in enumerate(zip(legacy_rows, legacy)):
    for key in keys:
        old_value = old.get(key, "")
        new_value = new.get(key, "")
        if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
            if float(old_value) != float(new_value):
                mismatch += 1
                print("差异", index, key, repr(old_value), repr(new_value))
        elif str(old_value) != str(new_value or ""):
            mismatch += 1
            print("差异", index, key, repr(old_value), repr(new_value))
print("逐行比对差异:", mismatch)
print("样例:", json.dumps(legacy[0], ensure_ascii=False))
print("图片附件行:", sum(1 for row in typed if row["photo_id"]))

# 幂等：再打开一次不应重复迁移
again = MachiningDFMStore(target, SEED)
print("二次打开 tools 行数:", again.tools.count(), "legacy 归档行数:", len(legacy_rows))
with again.connect() as db:
    archived = db.execute("SELECT COUNT(*) FROM tools_legacy_v1").fetchone()[0]
print("归档表行数:", archived)
print("副本目录:", work)
