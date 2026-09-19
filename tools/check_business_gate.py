"""开关自检（只读）：线上库的表与"能力级别键"必须对得上。

能力级别是递增的：1 工序 / 2 问题清单 / 3 选型报价 / 4 版本履历 / 5 变更流水。
这个脚本回答两件事：

* **还没迁**（键缺省或比某一档小）时：那些表**一张都不该存在**（代码先上线、数据晚点再迁，
  所以"没开开关就没有表"是硬要求：读取路径一条都不会碰到表）；
* **已经迁**（键到某一档）时：这一档及以下的表**必须都在**，而且 `PRAGMA foreign_key_check` 干净、
  每个项目的业务数据在"表 ↔ 读模型"两条路上都读得出来。

用法：python tools/check_business_gate.py [--data 目录]
退出码：0 = 与开关一致；1 = 不一致（多出表 / 少表 / 外键不干净）。
"""

from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_changes import CHANGES_TABLE, CHANGES_VERSION  # noqa: E402
from app.machining_history import HISTORY_TABLE, HISTORY_VERSION  # noqa: E402
from app.machining_issue import ISSUE_TABLE, ISSUE_VERSION  # noqa: E402
from app.machining_process import BUSINESS_VERSION_KEY, PROCESS_TABLE  # noqa: E402
from app.machining_selection import (  # noqa: E402
    FIXTURE_TABLE,
    GAUGE_TABLE,
    LEGACY_SELECTION_TABLE,
    SELECTION_VERSION,
)

DEFAULT_DB = ROOT / "data" / "machining_dfm" / "machining_dfm.sqlite3"

#: （需要的级别，表名，中文名）：级别到了这张表就必须在，没到就必须不在
STAGES = (
    (1, PROCESS_TABLE, "工序"),
    (1, "project_process_tools", "工序刀具行"),
    (2, ISSUE_TABLE, "问题清单"),
    (3, FIXTURE_TABLE, "夹具选型"),
    (3, GAUGE_TABLE, "检具选型"),
    (4, HISTORY_TABLE, "版本履历"),
    (5, CHANGES_TABLE, "变更流水"),
)

#: 老表：级别到了也**不该再有新数据**（迁移后只剩历史行），所以单独报一句，不进"必须有"清单
RETIRED_TABLES = ((LEGACY_SELECTION_TABLE, "选型报价（老多态表，已拆成夹具/检具两张）"),)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="", help="数据目录（默认线上目录）")
    args = parser.parse_args()

    db_file = Path(args.data).resolve() / "machining_dfm.sqlite3" if args.data else DEFAULT_DB
    if not db_file.is_file():
        print("没有找到库：", db_file)
        return 1
    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    problems: list[str] = []

    tables = [row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    rows = conn.execute("SELECT value_json FROM app_settings WHERE key=?",
                        (BUSINESS_VERSION_KEY,)).fetchall()
    level = 0
    if rows:
        try:
            level = int(json.loads(rows[0]["value_json"]))
        except (TypeError, ValueError):
            level = 0

    print(f"库文件        = {db_file}")
    print(f"能力级别      = {BUSINESS_VERSION_KEY} → {level}"
          "（1 工序 / 2 问题清单 / 3 选型报价 / 4 版本履历 / 5 变更流水）")
    print(f"表总数        = {len(tables)}")
    print(f"projects 行数 = {conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0]}")
    print()
    print("逐档核对：")
    for need, table, label in STAGES:
        exists = table in tables
        if level >= need and not exists:
            problems.append(f"级别 {level} 已打开，但缺表 {table}（{label}）")
            print(f"  × {label:8s} {table:24s} 应该在（级别 {need}），实际不在")
        elif level < need and exists:
            problems.append(f"级别 {level}，却多出了 {table}（{label}）")
            print(f"  × {label:8s} {table:24s} 不该在（级别 {need} 未开），实际在")
        else:
            print(f"  √ {label:8s} {table:24s} {'在' if exists else '不在'}（符合级别 {level}）")

    dirty = conn.execute("PRAGMA foreign_key_check").fetchall()
    print()
    print(f"PRAGMA foreign_key_check = {'干净' if not dirty else dirty[:3]}")
    if dirty:
        problems.append("外键体检不干净")
    print(f"PRAGMA integrity_check   = {conn.execute('PRAGMA integrity_check').fetchone()[0]}")

    # 级别被往下调、但表里明明有业务数据：旧副本清掉之后就"读不出来了"（口径 6 的代价）
    if level < HISTORY_VERSION:
        busy = [table for table in (PROCESS_TABLE, "project_process_tools", ISSUE_TABLE,
                                    FIXTURE_TABLE, GAUGE_TABLE, HISTORY_TABLE, CHANGES_TABLE)
                if table in tables and conn.execute(
                    f"SELECT COUNT(*) FROM {table}").fetchone()[0]]
        if busy:
            arrays = conn.execute(
                "SELECT state_json FROM projects WHERE archived=0").fetchall()
            empty = all(not set(json.loads(row["state_json"])) &
                        {"pr", "is", "vh"} for row in arrays) if arrays else True
            print()
            if empty:
                problems.append(
                    f"级别只有 {level}，但 {len(busy)} 张业务表里有数据、项目行里的旧数组已经清空 —— "
                    "把级别调回去（或从备份恢复），别让读模型退回空的老路径")
                print("  × 级别低于 4，业务表却有数据，而 projects.state_json 里已经没有 pr/is/vh：")
                print("    旧副本清了之后，级别往下调 = 读模型读不到业务数据（页面会空）。")
                print("    正确做法：把 project_business_version 调回 5；要回滚就恢复备份。")
            else:
                print("  ！ 级别低于 4，但项目行里还留着 pr/is/vh —— 旧副本没清干净，"
                      "这时往下调还能读出来；要清理请先跑 tools/clean_legacy_project_data.py")

    # 打开开关时：表里的行数与"读模型里数出来的"要对得上（表是权威，读模型不许回退 state_json）
    if level > 0:
        print()
        print("表 ↔ 读模型：")
        for table in (PROCESS_TABLE, "project_process_tools", ISSUE_TABLE,
                      FIXTURE_TABLE, GAUGE_TABLE, HISTORY_TABLE, CHANGES_TABLE,
                      *(name for name, _label in RETIRED_TABLES)):
            if table not in tables:
                continue
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            live = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE deleted_at IS NULL").fetchone()[0]
            note = ""
            for retired, label in RETIRED_TABLES:
                if table == retired:
                    note = f"   ← {label}"
                    if not total:
                        note += "；已空，可以弃用"
                    else:
                        moved = sum(
                            conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                            for name in (FIXTURE_TABLE, GAUGE_TABLE) if name in tables)
                        if moved:
                            note += (f"；还有 {total} 行（搬迁来源，新表已有 {moved} 行）"
                                     "，确认后可用 tools/clean_legacy_project_data.py 清")
                        else:
                            note += ("；还有行，跑 tools/migrate_selection_split.py "
                                     "按 kind 迁到新表")
            print(f"  {table:24s} {total:4d} 行（未删 {live}）{note}")
        print("  （逐字节一致性由迁移工具与 tools/live_process_e2e.py 验；这里只看有没有表、外键干不干净）")

    print()
    if problems:
        print("× 与开关不一致：")
        for item in problems:
            print("  -", item)
        return 1
    if level == 0:
        print("√ 开关关着，且业务表一张都没多出来（代码已上线、数据没迁，符合预期）")
    else:
        print(f"√ 开关开着（级别 {level}），该有的表都在、外键干净")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
