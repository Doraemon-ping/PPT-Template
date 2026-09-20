"""外键清单审计：把库里所有表的外键列出来，并标出「有关联但没有外键」的地方。

用法：
    python tools/audit_foreign_keys.py            # 看线上库
    python tools/audit_foreign_keys.py --with-process   # 连工序表一起看（副本上建表后再审）
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from app.domains.changes import CHANGES_VERSION  # noqa: E402
from app.machining_dfm import MachiningDFMStore  # noqa: E402
from app.domains.history import HISTORY_VERSION  # noqa: E402
from app.domains.issue import ISSUE_VERSION  # noqa: E402
from app.domains.process import BUSINESS_VERSION  # noqa: E402
from app.domains.selection import SELECTION_VERSION  # noqa: E402

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"

#: 期望有关联的列 → 应该指向哪张表（人工核对表，代码改了就更新这里）
#: 只登记"**已经**用真外键表达"的关联；故意保持软引用的写在 SOFT 里。
EXPECTED = {
    "projects": {},
    "revisions": {"project_id": "projects"},
    "project_settings": {"project_id": "projects",
                         "product_photo_id": "assets", "product2_photo_id": "assets",
                         "blank_insp_photo_id": "assets", "final_insp_photo_id": "assets"},
    "project_processes": {"project_id": "projects", "fixture_photo_id": "assets",
                          # 设备：共享设备库行删掉时 ON DELETE SET NULL，型号/价格仍按快照算（口径 4）
                          "machine_id": "machines"},
    "project_process_tools": {"project_id": "projects", "process_id": "project_processes",
                              "tool_photo_id": "assets",
                              # 刀具/刀柄/配件三列同理：库行删掉不挡删除，价格寿命走快照
                              "tool_id": "tools", "handle_id": "tools", "accessory_id": "tools"},
    "project_issues": {"project_id": "projects", "process_id": "project_processes",
                       "before_photo_id": "assets", "after_photo_id": "assets"},
    # 选型拆成两张项目级表（2026 结构与口径调整）：
    # 夹具选型只指向"模具中心字典 + 夹具库"，检具选型只指向"检具类别字典 + 检具库"；
    # 老的多态表 project_selections 只作为迁移来源，新库不再创建它。
    "project_fixtures": {"project_id": "projects",
                         "fixture_center": "fixture_centers",
                         "fixture_id": "fixtures"},
    "project_gauges": {"project_id": "projects",
                       "gauge_category": "gauge_categories",
                       "gauge_id": "gauges"},
    "project_versions": {"project_id": "projects"},
    # 变更流水（3b）：项目 + "这一次保存的版本" + 各业务表的"被改的那一行"，全是真外键。
    # 选型那两列按 kind 分列挂到两张新表；老的 selection_row_id 只留一个可空列（老表在新库里不存在，
    # 建外键反而会让整张流水表插不进去），所以它不在这一份清单里。
    "project_changes": {"project_id": "projects", "version_id": "project_versions",
                        "process_row_id": "project_processes",
                        "tool_row_id": "project_process_tools",
                        "issue_row_id": "project_issues",
                        "fixture_row_id": "project_fixtures",
                        "gauge_row_id": "project_gauges",
                        "history_row_id": "project_versions"},
    "machines": {"photo_id": "assets", "doc_id": "assets"},
    "tools": {"photo_id": "assets", "category": "tool_categories", "tool_group": "tool_groups"},
    "fixtures": {"photo_id": "assets", "center": "fixture_centers"},
    "gauges": {"photo_id": "assets", "category": "gauge_categories"},
    "tool_groups": {},
    "tool_categories": {},
    "fixture_centers": {},
    "gauge_categories": {},
    # 设备库旧壳 ``equipment`` 已于 2026-09-18 清掉（SCHEMA 里也不再创建它），
    # 所以这里不再登记；老库里如果还有这张表，它没有外键，不影响核对
    "assets": {},
    "app_settings": {},
    "auth_settings": {},
}

#: **老库上允许存在**、但新库不再建的外键：不算"清单没登记"，也不能当缺失。
#: 选型拆表后 ``project_changes.selection_row_id`` 指向的老表在新库里都不创建，
#: 所以新库上这一列只是普通可空列；老库上那个外键留着不影响任何东西（历史行还指得到那一行）。
LEGACY_FKS: tuple[tuple[str, str, str], ...] = (
    ("project_changes", "selection_row_id", "project_selections"),
)

#: **已废弃的表**：老库里可能还在（迁移来源/历史），新库不创建。
#: 它们在老库上带着自己那套外键，检查时只做"看一眼"，既不要求、也不算"清单没登记"。
LEGACY_TABLES: dict[str, dict[str, str]] = {
    # 选型拆表前的那张多态表（2026 结构调整）：夹具/检具现在各一张表
    "project_selections": {"project_id": "projects",
                           "fixture_center": "fixture_centers",
                           "gauge_category": "gauge_categories",
                           "fixture_id": "fixtures",
                           "gauge_id": "gauges"},
}

#: **故意不建外键**的"看着像引用"的列 → 为什么（是口径决定的，不是漏了）
#: 现在项目业务数据里的关联列**全部**是真外键，所以这里是空的（留个位置给以后要破例的列）。
SOFT: tuple[tuple[str, str], ...] = ()

#: 虽然是**真外键**、但按口径必须用 ON DELETE SET NULL 的列（不是软引用，写在这里是给人工核对用）
SET_NULL: tuple[tuple[str, str], ...] = (
    ("project_processes.machine_id", "设备库行删掉 → 外键置空但**不挡住删除**，型号/价格仍走 "
                                     "machine_snapshot 快照（口径 4）；读模型的 mid 也按快照回退"),
    ("project_process_tools.tool_id", "刀具库行删/改名后，仍按 tool_price/tool_life 快照算价"),
    ("project_process_tools.handle_id", "同上：刀柄选型，快照 hld_price"),
    ("project_process_tools.accessory_id", "同上：配件选型，快照 acc_price"),
    ("project_fixtures.fixture_center", "字典用名字做主键；中心从字典里删掉 → 外键置空，"
                                        "这一格不再出现在报价表里，行留着当历史"),
    ("project_gauges.gauge_category", "同上（检具类别字典）"),
    ("project_fixtures.fixture_id", "夹具库行删掉 → 外键置空，价格/周期仍走 price_snapshot/days_snapshot，"
                                    "选型不丢（口径 4）"),
    ("project_gauges.gauge_id", "同上（检具库）"),
    # 变更流水（3b）：被改的那一行/那一版被物理删掉时（口径 2 下不会发生），
    # 外键置空但**流水行留着**——标签里写着当时改的是谁，历史不因为删行而消失
    ("project_changes.version_id", "保存版本被物理删掉 → 置空；流水行仍在（阶段 4 回收站才真删）"),
    ("project_changes.process_row_id", "被改的工序行被物理删掉 → 置空，流水行仍在"),
    ("project_changes.tool_row_id", "被改的刀具行被物理删掉 → 置空，流水行仍在"),
    ("project_changes.issue_row_id", "被改的问题行被物理删掉 → 置空，流水行仍在"),
    ("project_changes.fixture_row_id", "被改的夹具选型格被物理删掉 → 置空，流水行仍在"),
    ("project_changes.gauge_row_id", "同上（检具选型格）"),
    ("project_changes.history_row_id", "被改的履历行被物理删掉 → 置空，流水行仍在"),
)


def audit(db_path: Path, only: tuple[str, ...] = ()) -> int:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        tables = [row["name"] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        print(f"库：{db_path}")
        print(f"表：{len(tables)} 张" + (f"（只看 {'、'.join(only)}）" if only else ""))
        print()
        missing: list[str] = []
        extra: list[str] = []
        for table in tables:
            if only and table not in only:
                continue
            fks = db.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            pairs = {row["from"]: row["table"] for row in fks}
            expect = EXPECTED.get(table, {})
            print(f"—— {table}")
            if fks:
                for row in fks:
                    print(f"     {row['from']:<20} → {row['table']}.{row['to']:<18}"
                          f" ON UPDATE {row['on_update']} ON DELETE {row['on_delete']}")
            else:
                print("     （没有外键）")
            if table in LEGACY_TABLES:
                # 废弃表：老库里还在，只列出来给人看一眼，不参与"缺/多"核对
                print("     ↑ 已废弃（选型拆成 project_fixtures / project_gauges 两张表）；"
                      "新库不再创建这张表，这里只做展示")
                print()
                continue
            for column, target in expect.items():
                if pairs.get(column) != target:
                    missing.append(f"{table}.{column} 应该 → {target}（现在没有）")
            for column, target in pairs.items():
                if column in expect:
                    continue
                if (table, column, target) in LEGACY_FKS:
                    continue      # 老库遗留（见 LEGACY_FKS）：允许存在，不当异常
                extra.append(f"{table}.{column} → {target}（清单里没登记）")
            print()
        # 检查外键约束是否真的开着（PRAGMA foreign_keys 是连接级的）
        print("=" * 78)
        print("结论")
        print("=" * 78)
        if missing:
            print("· 缺外键：")
            for item in missing:
                print("   -", item)
        else:
            print("· 清单里要求的外键都在 ✓")
        if extra:
            print("· 清单未登记（可能是有意为之的软引用）：")
            for item in extra:
                print("   -", item)
        print()
        print("· 故意保持**软引用**（不建外键）的列，原因：")
        if not SOFT:
            print("   （没有：有关联的列现在全是真外键）")
        for column, why in SOFT:
            print(f"   {column}")
            print(f"      {why}")
        print()
        print("· 老库遗留、新库不再建的外键（不算缺失，也不算异常）：")
        for table, column, target in LEGACY_FKS:
            present = any(str(row["from"]) == column and str(row["table"]) == target
                          for row in db.execute(f"PRAGMA foreign_key_list({table})"))
            print(f"   {table}.{column} → {target}"
                  f"（这个库里：{'有，留着不影响；新库不建' if present else '没有，新库就是不建'}）")
        print()
        print("· 是**真外键**、但按口径用 ON DELETE SET NULL 的列（删库行不挡住删除，价格走快照）：")
        for column, why in SET_NULL:
            print(f"   {column}")
            print(f"      {why}")
        # assets 的引用关系：谁的照片列指向 assets
        print()
        print("· 指向 assets 的列（附件引用）：")
        for table in tables:
            if only and table not in only:
                continue
            for row in db.execute(f"PRAGMA foreign_key_list({table})"):
                if row["table"] == "assets":
                    print(f"   {table}.{row['from']}")
    finally:
        db.close()
    return 1 if missing else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-process", action="store_true", help="在副本上建好工序表后再审")
    args = parser.parse_args()

    if not args.with_process:
        return audit(LIVE / "machining_dfm.sqlite3")

    work = Path(tempfile.mkdtemp(prefix="machining-fk-audit-"))
    root = work / "machining_dfm"
    shutil.copytree(LIVE, root)
    # 能力级别开到 3b（=5）：工序、问题清单、选型报价、版本履历、变更流水五批新表都建出来再一起审
    os.environ["MACHINING_PROJECT_BUSINESS"] = str(
        max(BUSINESS_VERSION, ISSUE_VERSION, SELECTION_VERSION, HISTORY_VERSION, CHANGES_VERSION))
    MachiningDFMStore(root, SEED)  # 开关打开 → 把新表都建出来
    code = audit(root / "machining_dfm.sqlite3")
    shutil.rmtree(work, ignore_errors=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
