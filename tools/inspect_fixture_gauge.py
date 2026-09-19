"""运维小工具：打印夹具库 / 检具库的现状（表结构、行数、payload 键、类别取值）——只读。

用法：python tools/inspect_fixture_gauge.py
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "machining_dfm" / "machining_dfm.sqlite3"

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.row_factory = sqlite3.Row

for name in ("fixtures", "gauges", "equipment", "tools"):
    row = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
    print(f"=== {name} ===")
    print(row[0] if row else "(不存在)")
    print("行数:", db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
    print()

for name in ("fixtures", "gauges"):
    # 迁移后行在归档表里，未迁移时在 payload 表里
    tables = {item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    source = f"{name}_legacy_v1" if f"{name}_legacy_v1" in tables else name
    keys: set[str] = set()
    rows: list[dict] = []
    for item in db.execute(f"SELECT payload_json FROM {source} ORDER BY sort_order, id"):
        try:
            payload = json.loads(item[0])
        except (TypeError, ValueError):
            continue
        rows.append(payload)
        keys |= set(payload)
    print(f"=== {name} payload 分析（来源 {source}，{len(rows)} 行）===")
    print("全部键:", sorted(keys))
    for key in sorted(keys):
        values = [row.get(key) for row in rows]
        filled = [value for value in values if value not in (None, "", 0, 0.0)]
        if key in {"img", "photo"}:
            withdata = [value for value in values if value]
            print(f"  {key}: 有值 {len(withdata)}/{len(rows)}（图片）")
            continue
        if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            print(f"  {key}: 数值，非零 {len(filled)}/{len(rows)}，"
                  f"范围 {min(values) if values else '-'} ~ {max(values) if values else '-'}")
        else:
            counts = Counter(str(value) for value in values)
            print(f"  {key}: 文本，非空 {len(filled)}/{len(rows)}，"
                  f"取值 {len(counts)} 种 → {counts.most_common(12)}")
    print()

print("=== 图片情况 ===")
for name in ("fixtures", "gauges"):
    tables = {item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    source = f"{name}_legacy_v1" if f"{name}_legacy_v1" in tables else name
    rows = [json.loads(item[0]) for item in db.execute(f"SELECT payload_json FROM {source}")]
    withimg = [row for row in rows if row.get("img")]
    total = sum(len(row["img"]) for row in withimg)
    print(f"{name}: 带图 {len(withimg)}/{len(rows)} 行，内联 base64 合计 {total} 字节")
print()

print("=== 类别字典（迁移后）===")
for table, column in (("fixture_centers", "center"), ("gauge_categories", "category")):
    if table not in {item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        continue
    names = [item[0] for item in db.execute(f"SELECT name FROM {table} ORDER BY sort_order, name")]
    usage = dict(db.execute(
        f"SELECT {column}, COUNT(*) FROM {'fixtures' if column == 'center' else 'gauges'} "
        f"GROUP BY {column}"
    ))
    print(f"{table}: {names} | 引用 {usage}")
print()

print("=== app_settings 全部键 ===")
for row in db.execute("SELECT key, value_json FROM app_settings ORDER BY key"):
    value = row["value_json"]
    print(f"  {row['key']} = {value[:110]}" + ("…" if len(value) > 110 else ""))

print()
print("=== assets 资产 ===")
print(db.execute("SELECT kind, COUNT(*), SUM(size) FROM assets GROUP BY kind").fetchall())
