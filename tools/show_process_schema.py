"""打印工序落表（1b）涉及的表结构：真实建表 SQL + 线上现状核对。

用法：
    python tools/show_process_schema.py            # 在临时库上建表并打印 DDL
    python tools/show_process_schema.py --live     # 顺带核对线上库里这些表存在与否
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

import os  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402

from app.machining_dfm import MachiningDFMStore  # noqa: E402

SEED = BASE / "app" / "resources" / "machining_dfm_seed"
LIVE = BASE / "data" / "machining_dfm"
NEW_TABLES = ("project_processes", "project_process_tools", "processes_legacy_v1")


def dump(db_path: Path, names: tuple[str, ...]) -> None:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        for name in names:
            row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            if row is None:
                print(f"—— {name}：**不存在**")
                continue
            print(f"—— {name}")
            print(row["sql"] + ";")
            for index in db.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                (name,),
            ):
                print(f"    {index['sql']};")
            print()
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="同时核对线上库")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="machining-process-schema-"))
    root = work / "machining_dfm"
    shutil.copytree(LIVE, root)  # 拿线上数据在副本上建表，DDL 与线上将来的一模一样
    os.environ["MACHINING_PROJECT_BUSINESS"] = "1"
    MachiningDFMStore(root, SEED)
    # 归档表平时由迁移工具建，这里照抄工具的建表语句，便于一起看结构
    db = sqlite3.connect(root / "machining_dfm.sqlite3")
    try:
        db.execute(
            "CREATE TABLE IF NOT EXISTS processes_legacy_v1("
            "id TEXT PRIMARY KEY,name TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 0,"
            "state_json TEXT NOT NULL,archived_at TEXT NOT NULL)"
        )
        db.commit()
    finally:
        db.close()

    print("=" * 78)
    print("1b 新增/改动的表（工序落表）")
    print("=" * 78)
    dump(root / "machining_dfm.sqlite3", NEW_TABLES)

    print("=" * 78)
    print("旧载荷表（1b **没有**改动，仍在原地）")
    print("=" * 78)
    dump(root / "machining_dfm.sqlite3", ("projects", "projects_legacy_v1", "revisions", "assets"))
    db = sqlite3.connect(f"file:{root / 'machining_dfm.sqlite3'}?mode=ro", uri=True)
    try:
        kinds = db.execute("SELECT kind,COUNT(*) FROM assets GROUP BY kind ORDER BY kind").fetchall()
    finally:
        db.close()
    print("assets.kind 现有取值（1b 只是多了一种取值 process_photo，**列结构没变**）：")
    for kind, count in kinds:
        print(f"  {kind}: {count}")
    print()

    print("=" * 78)
    print("列 ↔ 旧键映射（接口说的还是旧短键，落库用下面这些列名）")
    print("=" * 78)
    from app.machining_process import (
        LEGACY_PROCESS_KEYS,
        LEGACY_TOOL_KEYS,
        PROCESS_ATTACHMENTS,
        PROCESS_FIELDS,
        SNAPSHOT_KEYS,
        TOOL_ATTACHMENTS,
        TOOL_FIELDS,
    )

    def show(fields, title):
        print(f"—— {title}（{len(fields)} 列 + id/project_id/sort_order/deleted_*/created/updated）")
        for field in fields:
            print(f"    {field.key:<6} → {field.column:<24} {field.kind:<8} 默认 {field.default!r:<8} {field.label}")

    show(PROCESS_FIELDS, "project_processes")
    show(TOOL_FIELDS, "project_process_tools")
    for title, specs in (("工序附件列", PROCESS_ATTACHMENTS), ("刀具附件列", TOOL_ATTACHMENTS)):
        print(f"—— {title}")
        for spec in specs:
            print(f"    {spec.slot:<20} → {spec.column:<20} 种类 {spec.kind:<14} 旧键 {spec.legacy_key!r}")
    print("—— 快照列（口径 4：选型当时的价格/寿命，跟库表价格分开）")
    for key in SNAPSHOT_KEYS:
        print(f"    {key}")
    derived = [key for key in LEGACY_TOOL_KEYS if key in {"_ct", "_vc", "_vf", "_fz"}]
    print(f"—— **不进表**的旧键（读的时候现算）")
    print(f"    刀具行：{derived}（加工时间/切削速度/每齿进给/每转进给）")
    print(f"    工序行：['mi']（设备在设备库里的下标）")

    if args.live:
        print("=" * 78)
        print("线上库现状（迁移前）")
        print("=" * 78)
        dump(LIVE / "machining_dfm.sqlite3", NEW_TABLES)
        db = sqlite3.connect(f"file:{LIVE / 'machining_dfm.sqlite3'}?mode=ro", uri=True)
        try:
            names = [row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
        finally:
            db.close()
        print(f"线上现有 {len(names)} 张表：")
        for name in names:
            mark = "  ← 1b 新增（迁移后才会出现）" if name in NEW_TABLES else ""
            print(f"  {name}{mark}")

    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
