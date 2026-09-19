# -*- coding: utf-8 -*-
"""在**线上数据的副本**上验证"选型拆成两张项目级表"这件事。

验四件事（全部只碰副本，线上 sha256 前后要一样）：

1. 老库打开就补建 ``project_fixtures`` / ``project_gauges``，并给 ``project_changes``
   补上 ``fixture_row_id`` / ``gauge_row_id`` 两列（``ALTER TABLE ADD COLUMN``，老库也能加）；
2. 老的多态表 ``project_selections`` 的行**按 kind 搬进两张新表**（行 id 保留）；
3. 搬家前后**读模型逐字节一致**（页面上四个数组一个字都不变）；
4. ``PRAGMA foreign_key_check`` 干净、``integrity_check`` ok，且新表里没有 kind 列。

用法：python _audit/probe_selection_split.py [probe 目录名]
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.machining_dfm import LEGACY_SELECTION_TABLE, MachiningDFMStore  # noqa: E402
from app.machining_selection import (  # noqa: E402
    FIXTURE_TABLE,
    GAUGE_TABLE,
    KIND_FIXTURE,
    KIND_GAUGE,
)

LIVE = ROOT / "data" / "machining_dfm"
SEED = ROOT / "app" / "resources" / "machining_dfm_seed"
ARRAYS = ("fixQ", "fixQC", "insp", "inspQ")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "probe8"
    probe = ROOT / "_audit" / name
    if probe.exists():
        shutil.rmtree(probe)
    (probe / "data").mkdir(parents=True)
    shutil.copytree(LIVE, probe / "data" / "machining_dfm")

    live_before = sha(LIVE / "machining_dfm.sqlite3")
    print("线上库 sha256(前) =", live_before[:16])

    import os
    os.environ["DFM_APP_ROOT"] = str(probe)
    os.environ["MACHINING_PROJECT_BUSINESS"] = "5"

    store = MachiningDFMStore(probe / "data" / "machining_dfm", SEED)
    db_file = probe / "data" / "machining_dfm" / "machining_dfm.sqlite3"

    with store.connect() as db:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {table: [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
                   for table in (FIXTURE_TABLE, GAUGE_TABLE, "project_changes")}
        legacy_rows = [dict(row) for row in db.execute(
            f"SELECT * FROM {LEGACY_SELECTION_TABLE} ORDER BY project_id,sort_order")] \
            if LEGACY_SELECTION_TABLE in tables else []

    print()
    print("=== 1) 打开老库后的表结构 ===")
    print("夹具选型表 %s：%s" % (FIXTURE_TABLE, "在" if FIXTURE_TABLE in tables else "不在"))
    print("检具选型表 %s：%s" % (GAUGE_TABLE, "在" if GAUGE_TABLE in tables else "不在"))
    print("夹具表列 =", ", ".join(columns[FIXTURE_TABLE]))
    print("检具表列 =", ", ".join(columns[GAUGE_TABLE]))
    print("两种表都有 kind 列吗 = %s（应该是 False：拆表后没有多态列）"
          % ("kind" in columns[FIXTURE_TABLE] or "kind" in columns[GAUGE_TABLE]))
    late = [column for column in ("fixture_row_id", "gauge_row_id")
            if column in columns["project_changes"]]
    print("project_changes 补上的新列 =", late or "（没有——文件里是不是漏了 ensure_late_columns？）")

    print()
    print("=== 2) 老表的行（迁移来源） ===")
    print("老表行数 =", len(legacy_rows),
          "（夹具 %d / 检具 %d）" % (
              len([row for row in legacy_rows if row.get("kind") == "fixture"]),
              len([row for row in legacy_rows if row.get("kind") == "gauge"])))

    # 逐项目：记录搬家前的四个数组（读模型口径）→ 走一次真实写入（懒迁移 + 保存一格）
    print()
    print("=== 3) 懒迁移 + 保存一格，前后四个数组逐一比对 ===")
    problems: list[str] = []
    for row in store.list():
        project_id = row["id"]
        record = store.get(project_id, allow_archived=True)
        before = {key: (record["state"].get("G") or {}).get(key) for key in ARRAYS}
        before_json = json.dumps(before, ensure_ascii=False)

        # 第一步：只搬家（这一步必须**一字不改**地还原读模型）
        report = store._seed_selections(project_id)
        seeded_record = store.get(project_id, allow_archived=True)
        seeded = {key: (seeded_record["state"].get("G") or {}).get(key) for key in ARRAYS}
        seeded_json = json.dumps(seeded, ensure_ascii=False)
        if before_json != seeded_json:
            problems.append("项目 %s 搬家后四个数组变了：%s → %s"
                            % (project_id[:8], before_json, seeded_json))

        # 第二步：真的改一格（切"是否报价"），只有那一格该变
        store.save_project_selection(project_id, KIND_FIXTURE, 0, {"quoted": 0})
        after_record = store.get(project_id, allow_archived=True)
        after = {key: (after_record["state"].get("G") or {}).get(key) for key in ARRAYS}
        for key in ARRAYS:
            if key == "fixQC":
                continue
            if json.dumps(before.get(key), ensure_ascii=False) != json.dumps(
                    after.get(key), ensure_ascii=False):
                problems.append("项目 %s 改了夹具第 1 格的报价，却动了 %s：%s → %s"
                                % (project_id[:8], key, before.get(key), after.get(key)))

        fixtures = store.selections.fixtures.list_typed(project_id, include_deleted=True)
        gauges = store.selections.gauges.list_typed(project_id, include_deleted=True)
        print("  项目 %s「%s」" % (project_id[:8], record["name"]))
        print("     懒迁移来源 = %s（夹具 %d 行 · 检具 %d 行）"
              % (report.get("source"), len(fixtures), len(gauges)))
        print("     搬家前后四个数组逐字节一致 = %s" % ("是" if before_json == seeded_json else "否"))
        print("     读模型 fixQ  = %s" % json.dumps(after["fixQ"], ensure_ascii=False)[:110])
        print("     读模型 insp  = %s" % json.dumps(after["insp"], ensure_ascii=False)[:110])
        print("     改一格后 fixQC（只该第 1 位变） = %s" % json.dumps(after["fixQC"], ensure_ascii=False))

    print()
    print("=== 4) 校验 ===")
    with store.connect() as db:
        bad = db.execute("PRAGMA foreign_key_check").fetchall()
        ok = db.execute("PRAGMA integrity_check").fetchone()[0]
        change_rows = db.execute(
            "SELECT entity,action,label,fixture_row_id,gauge_row_id,selection_row_id "
            "FROM project_changes WHERE entity='selection' "
            "ORDER BY (fixture_row_id IS NULL AND gauge_row_id IS NULL), created DESC LIMIT 3"
        ).fetchall()
        migrated_rows = db.execute(
            "SELECT COUNT(*) FROM project_changes WHERE entity='selection' "
            "AND (fixture_row_id IS NULL AND gauge_row_id IS NULL)").fetchone()[0]
    print("foreign_key_check =", "干净" if not bad else bad[:3])
    print("integrity_check   =", ok)
    print("这次保存写下的选型流水（应当挂在新表的行上）：")
    for row in change_rows:
        print("   %s %s | %s | fixture=%s gauge=%s 老列=%s"
              % (row["entity"], row["action"], row["label"],
                 (row["fixture_row_id"] or "-")[:8], (row["gauge_row_id"] or "-")[:8],
                 (row["selection_row_id"] or "-")[:8]))
    print("迁移前就有的老流水行（仍只有老列） = %d 行（历史照样读得出来）" % migrated_rows)

    live_after = sha(LIVE / "machining_dfm.sqlite3")
    print()
    print("线上库 sha256(后) =", live_after[:16])
    print("线上库没被动过 =", live_before == live_after)
    if not bad and ok == "ok" and live_before == live_after and not problems:
        print()
        print("√ 副本上验证通过：拆表 + 懒迁移 + 读模型逐字节一致，线上文件一个字节都没动")
        print("  副本在：", db_file)
        return 0
    for problem in problems:
        print("  ×", problem)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
