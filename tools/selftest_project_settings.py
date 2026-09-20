"""ProjectSettings 自检：临时库里建表、写读、图片、旧 G 还原（不碰线上数据）。"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.db.assets import AssetStore  # noqa: E402
from app.domains.project import ProjectSettings  # noqa: E402

root = Path(tempfile.mkdtemp(prefix="project-settings-"))
db_path = root / "t.sqlite3"

STATE = {
    "G": {
        "cust": "赛力斯 SERES",
        "part": "蓄电池支架 Battery Bracket",
        "prj": "hp",
        "custVer": "V2.1",
        "dfmDate": "2026-09-17",
        "hpd": 22,
        "sft": 2,
        "dpm": 28,
        "avl": 0.85,
        "len": 0,
        "wid": 0,
        "hgt": 0,
        "wgt": 0,
        "showFlow": 1,
        "bInspType": "",
        "bInspPrice": 0,
        "fInspType": "",
        "fInspPrice": 0,
        "msInspPrice": 0,
        "pI": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==",
        "pf": None,
        "bInspImg": None,
        "fInspImg": None,
        "lang": "zh",
        "_vSnap": {"_pr": 2, "cust": '"赛力斯 SERES"'},
    }
}


def connect():
    db = sqlite3.connect(db_path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


with connect() as db:
    db.execute("CREATE TABLE projects(id TEXT PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO projects(id,name) VALUES('p1','测试项目')")
assets = AssetStore(root, connect)
assets.schema(connect())
settings = ProjectSettings(connect, assets)
settings.schema(connect())

print("=== 1. 旧数据迁入（apply_state，宽松模式）===")
settings.apply_state("p1", STATE, lenient=True)
row = settings.find("p1")
print("  列存了什么：")
for column in ("customer", "part", "project_type", "hours_per_day", "availability", "product_photo_id"):
    print(f"    {column:18s} = {row[column]!r}")

print("\n=== 2. 旧读模型还原（G 逐键比对）===")
restored = settings.legacy_g("p1", inline=True)
expected = {key: value for key, value in STATE["G"].items()}
same = set(restored) == set(expected)
print("  键集合一致:", same, "" if same else (set(expected) ^ set(restored)))
differ = [key for key in expected if restored[key] != expected[key]]
print("  取值不一致的键:", differ or "无")
print("  lang 兜底:", repr(restored.get("lang")), " _vSnap 兜底:", repr(restored.get("_vSnap"))[:40])

print("\n=== 3. 行级保存（只改一个字段）===")
settings.save("p1", {"cust": "赛力斯（改）"}, partial=True)
row = settings.find("p1")
print("  customer =", row["customer"], "| part 未动 =", row["part"], "| hpd 未动 =", row["hours_per_day"])

print("\n=== 4. 非行级保存（整份覆盖：没给的键回默认）===")
settings.save("p1", {"cust": "甲"}, partial=False)
row = settings.find("p1")
print("  customer =", row["customer"], "| hpd 回默认 =", row["hours_per_day"])

print("\n=== 5. 校验（坏值必须 422）===")
from fastapi import HTTPException  # noqa: E402

for payload in ({"hpd": 99}, {"prj": "xx"}, {"hpd": "abc"}, {"hpd": -1}):
    try:
        settings.save("p1", payload, partial=True)
        print("  ", payload, "→ 竟然通过了 ✗")
    except HTTPException as exc:
        print("  ", payload, "→", exc.status_code, exc.detail)

print("\n=== 6. 图片：换图 / 清空 / 附件不重复占用 ===")
typed = settings.typed("p1")
print("  product_url:", typed["product_url"])
before = connect().execute("SELECT COUNT(*) FROM assets").fetchone()[0]
settings.clear_photo("p1", "product")
after = connect().execute("SELECT COUNT(*) FROM assets").fetchone()[0]
print("  清空后 assets 行数:", before, "→", after, "| typed.product_id =", settings.typed("p1")["product_id"])

print("\n=== 7. 未知键继续兜底（新键不丢）===")
settings.save("p1", {"someFutureKey": {"a": 1}}, partial=True)
print("  restored.someFutureKey =", settings.legacy_g("p1").get("someFutureKey"))

print("\n=== 8. 字段登记表（前端按这个渲染）===")
spec = settings.fields_spec()
print("  字段数:", len(spec["fields"]), "| 附件槽:", [item["slot"] for item in spec["attachments"]])
print("  第一个字段:", json.dumps(spec["fields"][0], ensure_ascii=False))
print("\n临时目录:", root)
