# -*- coding: utf-8 -*-
"""选型拆表迁移：把老的多态表 ``project_selections`` 按 kind 搬进两张新表。

背景（2026 结构调整）：夹具选型和检具选型本来挤在一张多态表里（一行用 kind 区分，
夹具的列和检具的列混在一起、各自一半永远为空）。现在拆成两张"项目级"表：

* ``project_fixtures``：夹具选型（模具中心字典 + 夹具库）
* ``project_gauges``：检具选型（检具类别字典 + 检具库）

搬家**不改数据**：行 id、快照、价格、勾选全部照搬，读模型逐字节一致。老表**留着不动**
（它是这次搬家的来源，也是一份天然备份），要清掉请用 tools/clean_legacy_project_data.py。

和 stages 1b~3b 不一样，这一步**不动能力版本键**（还是 3：选型报价落表），
所以它自己判断"搬没搬过"，而不是看开关。

用法：
    python tools/migrate_selection_split.py            # 干跑（在副本上，打印逐字节比对）
    python tools/migrate_selection_split.py --status    # 只读：看看现在什么状态
    python tools/migrate_selection_split.py --apply     # 真的搬线上库（先整库备份）
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.machining_dfm import MachiningDFMStore  # noqa: E402
from app.domains.selection import (  # noqa: E402
    FIXTURE_TABLE,
    GAUGE_TABLE,
    KIND_FIXTURE,
    KIND_GAUGE,
    LEGACY_SELECTION_TABLE,
    SELECTION_VERSION,
)
from app.domains.process import BUSINESS_VERSION_KEY  # noqa: E402

LIVE = (ROOT / "data" / "machining_dfm").resolve()
SEED = ROOT / "app" / "resources" / "machining_dfm_seed"

#: 读模型里唯一允许变的东西：这几个字段是"数据落在哪张表"的实现细节，
#: 拆表**不该**动它们，所以这里留空——真要变了就是 bug，比对会报出来。
IGNORED_KEYS: tuple[str, ...] = ()


def table_names(db_path: Path) -> set[str]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()


def read_rows(db_path: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, params).fetchall()
    finally:
        db.close()


def status(root: Path) -> dict:
    db_file = root / "machining_dfm.sqlite3"
    info: dict = {"root": root, "has_db": db_file.is_file()}
    if not info["has_db"]:
        return info
    with sqlite3.connect(f"file:{db_file}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        names = {row["name"] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        settings = {row["key"]: row["value_json"] for row in db.execute(
            "SELECT key,value_json FROM app_settings")} if "app_settings" in names else {}
        info.update({
            "version": int(settings.get(BUSINESS_VERSION_KEY, 0) or 0),
            "projects": db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            if "projects" in names else 0,
            "legacy_table": LEGACY_SELECTION_TABLE in names,
            "fixture_table": FIXTURE_TABLE in names,
            "gauge_table": GAUGE_TABLE in names,
        })
        if info["legacy_table"]:
            info["legacy_rows"] = db.execute(
                f"SELECT COUNT(*) FROM {LEGACY_SELECTION_TABLE}").fetchone()[0]
            info["legacy_fixture"] = db.execute(
                f"SELECT COUNT(*) FROM {LEGACY_SELECTION_TABLE} WHERE kind=?",
                (KIND_FIXTURE,)).fetchone()[0]
            info["legacy_gauge"] = db.execute(
                f"SELECT COUNT(*) FROM {LEGACY_SELECTION_TABLE} WHERE kind=?",
                (KIND_GAUGE,)).fetchone()[0]
            info["legacy_projects"] = db.execute(
                f"SELECT COUNT(DISTINCT project_id) FROM {LEGACY_SELECTION_TABLE}").fetchone()[0]
        if info["fixture_table"]:
            info["fixture_rows"] = db.execute(f"SELECT COUNT(*) FROM {FIXTURE_TABLE}").fetchone()[0]
        if info["gauge_table"]:
            info["gauge_rows"] = db.execute(f"SELECT COUNT(*) FROM {GAUGE_TABLE}").fetchone()[0]
    return info


def print_status(info: dict) -> None:
    print("数据目录      =", info["root"])
    print("库文件        =", "有" if info.get("has_db") else "没有")
    if not info.get("has_db"):
        return
    print("项目数        =", info["projects"])
    print("能力级别      =", f"{BUSINESS_VERSION_KEY} → {info['version']}"
          f"（选型报价落表要从 {SELECTION_VERSION} 起）")
    print("夹具选型表    =", f"{FIXTURE_TABLE}"
          + (f"（{info.get('fixture_rows', 0)} 行）" if info.get("fixture_table") else "不在"))
    print("检具选型表    =", f"{GAUGE_TABLE}"
          + (f"（{info.get('gauge_rows', 0)} 行）" if info.get("gauge_table") else "不在"))
    if info.get("legacy_table"):
        print(f"老多态表      = {LEGACY_SELECTION_TABLE} 还有 {info.get('legacy_rows', 0)} 行"
              f"（夹具 {info.get('legacy_fixture', 0)} / 检具 {info.get('legacy_gauge', 0)}，"
              f"涉及 {info.get('legacy_projects', 0)} 个项目）")
    else:
        print("老多态表      = 没有（新库不建这张表）")
    moved = info.get("fixture_rows", 0) + info.get("gauge_rows", 0)
    if not info["legacy_table"]:
        print("状态          = 不需要迁（新库里没有老表）")
    elif moved:
        print("状态          = 已经搬过（新表里有行）；第一次写某个项目的选型时会自动补齐")
    elif info["version"] < SELECTION_VERSION:
        print("状态          = 开关还没到 3：先把 tools/migrate_project_processes.py 跑完")
    else:
        print("状态          = 待搬（老表有行、新表还空；跑本工具即可）")


def records_of(store: MachiningDFMStore) -> dict[str, dict]:
    """每个项目的完整读模型（比字节用）。"""
    snapshot: dict[str, dict] = {}
    for item in store.list():
        record = store.get(item["id"], allow_archived=True)
        snapshot[item["id"]] = {
            key: value for key, value in record.items() if key not in IGNORED_KEYS
        }
    return snapshot


def migrate(root: Path, *, apply: bool) -> int:
    """把 ``root`` 里老表的选型行按 kind 搬进两张新表。

    读模型在搬家前后必须**逐字节一致**——不一致就说明搬家改坏了东西，
    ``apply`` 模式下也会停下来报失败（库已备份，可回退）。
    """
    db_file = root / "machining_dfm.sqlite3"
    if not db_file.is_file():
        print("没有找到库：", db_file)
        return 2
    info = status(root)
    if not info.get("legacy_table"):
        print("新库里没有老的多态表，不需要搬。")
        return 0
    if info["version"] < SELECTION_VERSION:
        print(f"能力级别还是 {info['version']}（不到 {SELECTION_VERSION}）：先跑 "
              "tools/migrate_project_processes.py")
        return 2

    store = MachiningDFMStore(root, SEED)
    before = records_of(store)
    before_json = json.dumps(before, ensure_ascii=False, sort_keys=True)

    print("=" * 72)
    print("搬家前")
    print("=" * 72)
    for project_id, record in before.items():
        general = (record.get("state") or {}).get("G") or {}
        print(f"  {project_id[:8]}「{record.get('name', '')[:34]}」"
              f" fixQ={json.dumps(general.get('fixQ'), ensure_ascii=False)}"
              f" insp={json.dumps(general.get('insp'), ensure_ascii=False)[:60]}")

    backup_path = ""
    if apply:
        backup = store._backup(
            f"pre-selection-split-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3")
        backup_path = str(backup)
        print()
        print("备份          =", backup_path)
        store = MachiningDFMStore(root, SEED)      # 备份后重开，后面每一步都落在有备份的库上

    print()
    print("=" * 72)
    print("开始搬家（按 kind 分表）")
    print("=" * 72)
    moved: dict[str, dict] = {}
    for project_id in before:
        report = store._seed_selections(project_id)
        moved[project_id] = report or {}

    after = records_of(store)
    after_json = json.dumps(after, ensure_ascii=False, sort_keys=True)

    print()
    print("=" * 72)
    print("搬家后（每个项目搬了多少）")
    print("=" * 72)
    for project_id, report in moved.items():
        rows = store.selections.list_typed(project_id)
        fixtures = [row for row in rows if row["kind"] == KIND_FIXTURE]
        gauges = [row for row in rows if row["kind"] == KIND_GAUGE]
        print(f"  {project_id[:8]}「{before[project_id].get('name', '')[:34]}」"
              f" 来源={report.get('source', '（已经有行，跳过）')}"
              f" 夹具 {len(fixtures)} 行 · 检具 {len(gauges)} 行")

    print()
    print("=" * 72)
    print("核对")
    print("=" * 72)
    problems: list[str] = []
    if before_json != after_json:
        problems.append("读模型变了（拆表不该改读模型）")
        for project_id in before:
            old = json.dumps(before[project_id], ensure_ascii=False, sort_keys=True)
            new = json.dumps(after.get(project_id), ensure_ascii=False, sort_keys=True)
            if old != new:
                print(f"  × {project_id[:8]} 的读模型不一致")
                for key in sorted(set(before[project_id]) | set(after.get(project_id, {}))):
                    old_value = json.dumps(before[project_id].get(key), ensure_ascii=False,
                                           sort_keys=True)
                    new_value = json.dumps(after.get(project_id, {}).get(key), ensure_ascii=False,
                                           sort_keys=True)
                    if old_value != new_value:
                        print(f"      {key}: {old_value[:90]} → {new_value[:90]}")
    else:
        print("  √ 读模型逐字节一致（页面上四个数组一个字都没变）")

    with store.connect() as db:
        bad = db.execute("PRAGMA foreign_key_check").fetchall()
        ok = db.execute("PRAGMA integrity_check").fetchone()[0]
        legacy = db.execute(f"SELECT COUNT(*) FROM {LEGACY_SELECTION_TABLE}").fetchone()[0]
        if bad:
            problems.append(f"外键有问题：{bad[:2]}")
        if ok != "ok":
            problems.append(f"integrity_check = {ok}")
    print(f"  √ foreign_key_check={'干净' if not bad else bad[:2]}｜integrity_check={ok}"
          f"｜老表 {legacy} 行原样留着（搬家来源 + 天然备份）")

    # 老表每一行都要能在新表里找到（行 id 照搬）
    missing: list[str] = []
    with store.connect() as db:
        for row in db.execute(f"SELECT id,kind FROM {LEGACY_SELECTION_TABLE}"):
            table = FIXTURE_TABLE if row["kind"] == KIND_FIXTURE else GAUGE_TABLE
            if db.execute(f"SELECT 1 FROM {table} WHERE id=?", (row["id"],)).fetchone() is None:
                missing.append(f"{row['kind']}:{row['id'][:8]}")
    if missing:
        problems.append(f"老表有 {len(missing)} 行没搬到新表：{missing[:3]}")
        print(f"  × 老表有 {len(missing)} 行没搬到新表：{missing[:3]}")
    else:
        print("  √ 老表里每一行都能在新表里按**同一个行 id**找到")

    print()
    if problems:
        print("发现问题（库已备份，可以回退）：")
        for problem in problems:
            print("  -", problem)
        return 1
    if not apply:
        print("√ 干跑通过：搬家不改读模型、外键干净、老表每一行都搬到位")
        print("  这次是在副本上跑的，线上库一个字节都没动。要真搬请加 --apply")
        return 0
    print("√ 迁移完成：选型已按 kind 落在两张新表里，读模型一字未变")
    print("  备份 =", backup_path)
    print("  老表没动：确认一段时间没问题后，可用 tools/clean_legacy_project_data.py 清")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真的搬线上库（默认只干跑）")
    parser.add_argument("--keep", action="store_true", help="干跑后保留临时副本")
    parser.add_argument("--status", action="store_true", help="只读：打印当前状态")
    parser.add_argument("--from", dest="source", default="", help="要处理的数据目录（默认线上目录）")
    args = parser.parse_args()

    source = Path(args.source).resolve() if args.source else LIVE
    if args.status:
        print_status(status(source))
        return 0

    print("=" * 72)
    print("搬家前状态")
    print("=" * 72)
    print_status(status(source))

    if args.apply:
        if source != LIVE:
            print("\n--apply 只允许对线上目录使用（要演练请用 --from 且不要加 --apply）")
            return 2
        print()
        return migrate(source, apply=True)

    work = Path(tempfile.mkdtemp(prefix="machining-selection-split-"))
    target = work / "machining_dfm"
    try:
        shutil.copytree(source, target)
        if LIVE in target.parents or target == LIVE:
            print("拒绝在线上目录上干跑")
            return 2
        print()
        print("=" * 72)
        print("干跑（副本：" + str(target) + "）")
        print("=" * 72)
        code = migrate(target, apply=False)
    finally:
        if args.keep:
            print("\n副本保留在：", target)
        else:
            shutil.rmtree(work, ignore_errors=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
