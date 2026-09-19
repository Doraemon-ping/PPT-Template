"""拿真实数据的**副本**试跑基础库迁移，逐字段比对，绝不动线上库。

用法：python tools/verify_library_migration.py

比对内容：
* 夹具库（fdb → fixtures + fixture_centers）、检具库（idb → gauges + gauge_categories）、
  刀具库（tdb → tools + tool_groups/tool_categories）的归档行 vs 新类型化行，逐字段差异；
* 字典表条目与引用计数、迁移版本号、备份文件、二次打开的幂等性。
"""

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

SOURCE = ROOT / "data" / "machining_dfm"
SEED = ROOT / "app" / "resources" / "machining_dfm_seed"

LIBRARIES = (
    ("夹具", "fdb", "fixtures", "fixtures_legacy_v1"),
    ("检具", "idb", "gauges", "gauges_legacy_v1"),
    ("刀具", "tdb", "tools", "tools_legacy_v1"),
)

workdir = Path(tempfile.mkdtemp(prefix="libcheck-"))
target = workdir / "machining_dfm"
shutil.copytree(SOURCE, target)
print("副本:", target)

# 迁移前：从归档表（或旧 payload 表）取原始行
before = sqlite3.connect(target / "machining_dfm.sqlite3")
before.row_factory = sqlite3.Row
tables = {row[0] for row in before.execute("SELECT name FROM sqlite_master WHERE type='table'")}
baseline: dict[str, list[dict]] = {}
for label, key, table, archive in LIBRARIES:
    source_table = ""
    if archive in tables:
        source_table = archive
    elif table in tables:
        columns = {row[1] for row in before.execute(f"PRAGMA table_info({table})")}
        source_table = table if "payload_json" in columns else ""
    rows: list[dict] = []
    if source_table:
        for row in before.execute(f"SELECT payload_json FROM {source_table} ORDER BY sort_order,id"):
            rows.append(json.loads(row["payload_json"]))
    baseline[key] = rows
    print(f"迁移前 {label}（{key}）: {len(rows)} 行，来源 {source_table or '（已在类型化表里）'}")
before.close()

store = MachiningDFMStore(target, SEED)

print()
print("=== 迁移后逐字段比对 ===")
total_diff = 0
for label, key, table, archive in LIBRARIES:
    original = baseline[key]
    view = store.libraries()[key]
    if not original:
        print(f"{label}: 归档为空，跳过（新类型化行 {len(view)}）")
        continue
    diffs: list[str] = []
    if len(original) != len(view):
        diffs.append(f"行数不一致 {len(original)} → {len(view)}")
    for index, (old, new) in enumerate(zip(original, view)):
        for field, value in old.items():
            if field in {"img", "tI"}:
                # 图片：旧数据是 data URL，新读模型也是 data URL/URL，单独看是否为空即可
                if bool(value) != bool(new.get(field)):
                    diffs.append(f"第{index}行 {field} 有无不一致")
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if abs(float(value) - float(new.get(field) or 0)) > 1e-9:
                    diffs.append(f"第{index}行 {field}: {value} → {new.get(field)}")
            elif str(value or "") != str(new.get(field) or ""):
                diffs.append(f"第{index}行 {field}: {value!r} → {new.get(field)!r}")
    total_diff += len(diffs)
    print(f"{label}（{key}）: {len(original)} 行，差异 {len(diffs)} 处" + (f" → {diffs[:5]}" if diffs else " ✓"))

print()
print("=== 字典表 ===")
print("模具中心:", [(item["name"], item["builtin"], item["source"]) for item in store.fixture_centers.names()])
print("检具类别:", [(item["name"], item["builtin"], item["source"]) for item in store.gauge_categories.names()])
print("库分类:", [(item["code"], item["label"]) for item in store.tool_dict.groups()])
print("刀具类型数:", len(store.tool_dict.categories()))
print("引用计数: 夹具", store.fixture_centers.usage(), "| 检具", store.gauge_categories.usage())

print()
print("=== 版本与备份 ===")
with store.connect() as db:
    print({row[0]: row[1] for row in db.execute(
        "SELECT key,value_json FROM app_settings WHERE key LIKE '%schema_version'"
    )})
    for label, key, table, archive in LIBRARIES:
        count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        archive_count = (
            db.execute(f"SELECT COUNT(*) FROM {archive}").fetchone()[0] if archive in tables else "-"
        )
        fks = [(row[2], row[3], row[4]) for row in db.execute(f"PRAGMA foreign_key_list({table})")]
        print(f"{label}: {table} {count} 行 | 归档 {archive_count} | 外键 {fks}")
print("备份:", sorted(path.name for path in (target / "backups").glob("*.sqlite3")))
print("设备/夹具/检具:", store.machines.count(), store.fixtures.count(), store.gauges.count(),
      "| 刀具:", store.tools.count())

again = MachiningDFMStore(target, SEED)
print("二次打开幂等:", again.fixtures.count() == store.fixtures.count(),
      again.gauges.count() == store.gauges.count(), again.tools.count() == store.tools.count(),
      "| 字典:", len(again.fixture_centers.names()), len(again.gauge_categories.names()))

print()
print("逐字段差异合计:", total_diff)
print("副本目录:", workdir)
