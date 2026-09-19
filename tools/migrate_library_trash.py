"""阶段 4 迁移：给 8 张基础库/字典表补"逻辑删除三列"（回收站的前置结构）。

做两件事：
1. **补列**：``machines``/``tools``/``fixtures``/``gauges`` 与四张字典表
   （``tool_groups``/``tool_categories``/``fixture_centers``/``gauge_categories``）
   各加 ``deleted_at`` / ``deleted_by`` / ``deleted_reason``（可空）+ 回收站索引。
   新库由 DDL 建；老库由 store 打开时的 ``ensure_trash_columns`` 自愈，
   这个工具负责"带备份、带验证、可复核"地走一遍。
2. **验证**（默认干跑，在**副本**上做）：
   * 加列前后每个项目的读模型**逐字节相同**；
   * ``PRAGMA foreign_key_check`` 与 ``integrity_check`` 干净；
   * 回收站接口能列出内容（项目级 + 全局）；
   * 副本上真删一行 → 进回收站（带删除人/原因）→ 恢复 → 回到原样。

**加列是纯结构变更**：``ALTER TABLE ADD COLUMN`` 只加可空列，不动任何既有数据、不重写表。

用法::

    .venv\\Scripts\\python.exe tools\\migrate_library_trash.py            # 干跑（副本）
    .venv\\Scripts\\python.exe tools\\migrate_library_trash.py --status   # 只读看现状
    .venv\\Scripts\\python.exe tools\\migrate_library_trash.py --apply    # 先整库备份再动线上
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_dfm import MachiningDFMStore  # noqa: E402

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"

#: 本阶段补列的 8 张表（4 张本体库 + 4 张字典）
TRASH_TABLES = (
    "machines", "tools", "fixtures", "gauges",
    "tool_groups", "tool_categories", "fixture_centers", "gauge_categories",
)
COLUMNS = ("deleted_at", "deleted_by", "deleted_reason")


def _kb(size: int) -> str:
    return f"{size / 1024:.1f} KB"


def status(root: Path) -> dict:
    """只读：8 张表有没有三列、回收站里有多少行。"""
    db_file = root / "machining_dfm.sqlite3"
    info: dict = {"root": str(root), "db": db_file.is_file(), "tables": {}, "version": None}
    if not db_file.is_file():
        return info
    db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        info["version"] = db.execute(
            "SELECT value_json FROM app_settings WHERE key='project_business_version'"
        ).fetchone()
        info["version"] = json.loads(info["version"][0]) if info["version"] else None
        existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in TRASH_TABLES:
            if table not in existing:
                info["tables"][table] = {"exists": False}
                continue
            columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
            info["tables"][table] = {
                "exists": True,
                "columns": [column for column in COLUMNS if column in columns],
                "rows": int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]),
                "trash": int(db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE deleted_at IS NOT NULL"
                ).fetchone()[0]) if "deleted_at" in columns else None,
            }
    finally:
        db.close()
    return info


def print_status(info: dict) -> None:
    print(f"数据目录      = {info['root']}")
    print(f"库文件        = {'在' if info['db'] else '不在'}")
    print(f"能力级别      = {info['version']}")
    for table, item in info["tables"].items():
        if not item.get("exists"):
            print(f"  {table:18s} 表不存在（还没建）")
            continue
        mark = "三列齐全 ✓" if len(item["columns"]) == 3 else f"缺列：{set(COLUMNS) - set(item['columns'])}"
        trash = "—" if item["trash"] is None else item["trash"]
        print(f"  {table:18s} {mark}｜在用/总数 {item['rows']}｜回收站 {trash}")


def _all_projects(store: MachiningDFMStore) -> list[dict]:
    """在用项目 + 已删除项目（``list(archived=True)`` 只给已删除的那一批）。"""
    seen: dict[str, dict] = {row["id"]: row for row in store.list()}
    for row in store.list(archived=True):
        seen.setdefault(row["id"], row)
    return list(seen.values())


def _fingerprints(store: MachiningDFMStore) -> dict[str, str]:
    """每个项目的**数据**指纹（加列前后要比这个；``revision``/``updated`` 每次都变，不比）。"""
    marks: dict[str, str] = {}
    for row in _all_projects(store):
        record = store.get(row["id"], allow_archived=True)
        marks[row["id"]] = json.dumps(record["state"], ensure_ascii=False, sort_keys=True)
    return marks


def _checks(db) -> tuple[str, list]:
    return (
        db.execute("PRAGMA integrity_check").fetchone()[0],
        db.execute("PRAGMA foreign_key_check").fetchall(),
    )


def verify(root: Path, *, label: str, before_marks: dict[str, str] | None = None,
           report: dict | None = None) -> bool:
    """打开 store（老库会自动补列），跑一遍验证项；返回是否全绿。"""
    ok = True
    store = MachiningDFMStore(root, SEED)
    print(f"\n[{label}] 打开 store（老库在这里补列）")
    with store.connect() as db:
        for table in TRASH_TABLES:
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            missing = [column for column in COLUMNS if column not in columns]
            mark = "✓" if not missing else f"✗ 缺 {missing}"
            print(f"  三列 {table:18s} {mark}")
            ok = ok and not missing
        integrity, fk = _checks(db)
        print(f"  integrity_check   = {integrity}")
        print(f"  foreign_key_check = {fk or '干净 ✓'}")
        ok = ok and integrity == "ok" and not fk

    after_marks = _fingerprints(store)
    if before_marks is not None:
        same = after_marks == before_marks
        print(f"  读模型逐字节不变   = {'✓' if same else '✗ 有差异'}")
        if not same:
            for pid in set(before_marks) | set(after_marks):
                if before_marks.get(pid) != after_marks.get(pid):
                    print(f"    ✗ 项目 {pid} 的读模型变了")
        ok = ok and same

    # 回收站接口可用（项目级 + 全局）
    for row in _all_projects(store):
        body = store.project_trash(row["id"])
        print(f"  项目回收站        = {row['name'][:24]} → {len(body['items'])} 条")
        ok = ok and body.get("enabled") is True
    global_trash = store.library_trash()
    print(f"  全局回收站        = {len(global_trash['items'])} 条")
    ok = ok and global_trash.get("enabled") is True

    # 真删一行 → 进回收站 → 恢复 → 回到原样（只在**副本**上做）
    if report is not None:
        with store.connect() as db:
            row = db.execute(
                "SELECT id FROM machines WHERE deleted_at IS NULL ORDER BY sort_order LIMIT 1"
            ).fetchone()
        if row is None:
            print("  删/恢复闭环       = 跳过（设备库没有在用行）")
        else:
            machine_id = row["id"]
            # 比"库行数据"（旧短键视图没有 updated，删/恢复不该改任何字段）
            before = json.dumps(store.machines.list_legacy(), ensure_ascii=False, sort_keys=True)
            store.machines.delete(machine_id, by="admin", reason="迁移自检")
            trashed = [item for item in store.library_trash()["items"]
                       if item["record_id"] == machine_id]
            print(f"  删一行 → 回收站   = {trashed[0]['title'][:20] if trashed else '✗ 没进回收站'}"
                  f"（删除人 {trashed[0]['deleted_by'] if trashed else '—'}）")
            ok = ok and bool(trashed)
            store.machines.restore(machine_id, by="admin")
            after = json.dumps(store.machines.list_legacy(), ensure_ascii=False, sort_keys=True)
            print(f"  恢复 → 回到原样   = {'✓' if after == before else '✗ 数据不一致'}")
            ok = ok and after == before
            report["probe"] = {"machines": machine_id, "in_trash": bool(trashed)}
    report and report.update({"ok": ok})
    return ok


def run(root: Path, *, apply: bool, keep: bool) -> int:
    db_file = root / "machining_dfm.sqlite3"
    if not db_file.is_file():
        print(f"✗ 找不到库文件：{db_file}")
        return 2
    before_info = status(root)
    print("迁移前：")
    print_status(before_info)
    missing_before = {
        table for table, item in before_info["tables"].items()
        if item.get("exists") and len(item.get("columns") or []) != 3
    }

    if apply:
        baseline = MachiningDFMStore(root, SEED)
        marks = _fingerprints(baseline)
        backup = baseline._backup("pre-library-trash")
        print(f"\n备份          = {backup}")
        # **线上只做只读验证**：删/恢复闭环那条写探针只在干跑副本上跑
        # （2026-09-18 修正：之前 --apply 也跑了写探针，虽然当场恢复且数据一致，
        #   但会改掉那一行的 updated 时间戳 —— 线上不做任何写探针。）
        ok = verify(root, label="线上（已备份，只读验证）", before_marks=marks)
        print(f"\n加列结果      = {'全绿 ✓' if ok else '✗ 有问题，请用备份回滚'}")
        print(f"库体积        = {_kb(db_file.stat().st_size)}")
        print("删/恢复闭环   = 已在干跑副本上验证过（线上不做写探针）")
        print("回收站工具    = tools/migrate_library_trash.py --status 再看一遍")
        return 0 if ok else 1

    work = Path(tempfile.mkdtemp(prefix="machining-trash-"))
    target = work / root.name
    try:
        shutil.copytree(root, target)
        copy_db = target / "machining_dfm.sqlite3"
        print(f"\n干跑副本      = {target}")
        baseline = MachiningDFMStore(target, SEED)
        marks = _fingerprints(baseline)
        # 把三列拆掉，模拟"阶段 4 之前的老库"
        with baseline.connect() as db:
            db.execute("PRAGMA foreign_keys=OFF")
            for table in TRASH_TABLES:
                db.execute(f"DROP INDEX IF EXISTS idx_machining_dfm_{table}_trash")
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                for column in COLUMNS:
                    if column in columns:
                        db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        print("\n[副本] 已还原成「没有三列」的老库形态，开始补列 + 验证")
        report = {}
        ok = verify(target, label="干跑副本", before_marks=marks, report=report)
        print(f"\n干跑结果      = {'全绿 ✓' if ok else '✗ 有问题'}")
        print(f"库体积        = {_kb(copy_db.stat().st_size)}（原库 {_kb(db_file.stat().st_size)}）")
        print(f"待补列的表    = {sorted(missing_before) or '无（线上已经补过）'}")
        print("\n线上数据一个字没动。确认无误后跑：--apply")
        return 0 if ok else 1
    finally:
        if keep:
            print(f"（--keep：副本保留在 {work}）")
        else:
            shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="给基础库/字典表补逻辑删除三列（回收站）")
    parser.add_argument("--status", action="store_true", help="只读看现状")
    parser.add_argument("--apply", action="store_true", help="先备份再动线上库")
    parser.add_argument("--keep", action="store_true", help="干跑后保留副本目录")
    parser.add_argument("--source", default="", help="换一个数据目录（默认线上）")
    args = parser.parse_args()
    root = Path(args.source).resolve() if args.source else LIVE
    if args.status:
        print_status(status(root))
        return 0
    return run(root, apply=args.apply, keep=args.keep)


if __name__ == "__main__":
    raise SystemExit(main())
