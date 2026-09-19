"""从 *_legacy_v1 归档表重放夹具库/检具库迁移（PUT /libraries 的整表覆盖曾误删数据）。

只碰 fixtures / gauges 两张类型化表与两个版本键，不动项目快照、设备、刀具、图片。
做法就是让既有迁移再跑一次：清空类型化表、删掉版本键，由 MachiningDFMStore 启动时
按归档 payload 重新入库（字典已存在，只会补录不会重排）。
用法：python tools/restore_fixture_gauge.py [--apply]（不加 --apply 只打印将要做什么）
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "machining_dfm"
DB = DATA / "machining_dfm.sqlite3"
APPLY = "--apply" in sys.argv

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

print("=== 现状 ===")
for table in ("fixtures", "fixtures_legacy_v1", "gauges", "gauges_legacy_v1"):
    if table in tables:
        print(f"  {table}: {db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]} 行")
    else:
        print(f"  {table}: (无此表)")

plan: dict[str, int] = {}
for table in ("fixtures", "gauges"):
    archive = f"{table}_legacy_v1"
    if archive not in tables:
        raise SystemExit(f"缺少归档表 {archive}，无法重放；请改用 backups/pre-typed-*.sqlite3")
    rows = [row for row in db.execute(f"SELECT payload_json FROM {archive} ORDER BY sort_order, id")]
    payloads = [json.loads(row[0]) for row in rows]
    if not payloads:
        raise SystemExit(f"归档表 {archive} 是空的")
    plan[table] = len(payloads)
    print(f"  → 将用 {archive} 的 {len(payloads)} 行重建 {table}")

if not APPLY:
    print("\n（预览模式；加 --apply 才会写入）")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_dir = DATA / "backups"
backup_dir.mkdir(exist_ok=True)
backup = backup_dir / f"pre-fixture-gauge-restore-{stamp}.sqlite3"
db.close()
shutil.copy2(DB, backup)
print("\n备份:", backup.name)

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
for table in ("fixtures", "gauges"):
    db.execute(f"DELETE FROM {table}")
for key in ("fixture_library_schema_version", "gauge_library_schema_version"):
    db.execute("DELETE FROM app_settings WHERE key=?", (key,))
db.commit()
db.close()
print("已清空类型化表并移除版本键，交由下一次启动重新迁移")

sys.path.insert(0, str(ROOT))
from app.machining_dfm import MachiningDFMStore  # noqa: E402

store = MachiningDFMStore(ROOT / "data" / "machining_dfm", ROOT / "app" / "resources" / "machining_dfm_seed")
print("\n=== 重放结果 ===")
for table, expected, library in (("fixtures", plan["fixtures"], store.fixtures),
                                 ("gauges", plan["gauges"], store.gauges)):
    count = library.count()
    print(f"  {table}: {count} 行（期望 {expected}）{'✓' if count == expected else '✗'}")
    if count != expected:
        raise SystemExit(f"{table} 行数不符")

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
print("\n=== 版本与字典 ===")
print(" ", {row[0]: json.loads(row[1]) for row in db.execute(
    "SELECT key,value_json FROM app_settings WHERE key LIKE '%schema_version'")})
for table, column, target in (("fixture_centers", "center", "fixtures"),
                              ("gauge_categories", "category", "gauges")):
    names = [row[0] for row in db.execute(f"SELECT name FROM {table} ORDER BY sort_order, name")]
    usage = dict(db.execute(f"SELECT {column}, COUNT(*) FROM {target} GROUP BY {column}"))
    total = sum(usage.values())
    print(f"  {table}: {len(names)} 个类别，引用合计 {total}")
db.close()
print("\n完成")
