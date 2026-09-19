"""清掉"旧数据副本"（业务数据早就落表了，这些是历史遗留的第二份）。

改造这几步（1b 工序 → 2a 问题清单 → 2b 选型报价 → 3a 版本履历 → 3b 变更流水）每走一步，
都会留一份**回滚用的旧副本**：

| 副本 | 是什么 | 谁还在用 |
| --- | --- | --- |
| `projects.state_json` 里的 `pr`/`is`/`vh` | 旧读模型的形状，与业务表是同一份数据 | 开关 < 4 时的回滚路径 |
| `revisions` | 每次保存的整份快照（3a 之前是唯一版本来源） | 开关 < 4 时的回滚路径 + 3a 迁移工具的输入 |
| `projects_legacy_v1` | 项目信息（`G`）拆表前的整份 `state_json` | 人工核对/回滚 |
| `processes_legacy_v1` | 工序拆表前的整份 `state_json` | 人工核对/回滚 |
| `equipment_legacy_v1` / `fixtures_legacy_v1` / `gauges_legacy_v1` / `tools_legacy_v1` | 基础库类型化之前的 `payload_json` 旧壳 | 只在"表还是空的"时候当搬迁来源 |
| `equipment` | **设备库**类型化之前的 `payload_json` 旧壳（288 KB，里面的图片还是内联的） | 同上；线上 `library_schema_version = 2` 之后早就不读了 |

**为什么要有这个工具**：老副本和真数据长得一样，看库结构时全是干扰；而且同一份数据两条路走，
迟早会跑偏。清掉它们**不丢业务数据**：工序/刀具行/问题清单/选型/保存版本/履历/流水
都在各自的表里，每次保存也不再往旧副本里写第二份（口径 6：哪一级落表了，那一级的影子副本停写）。

**清掉之后就只剩"从备份恢复"这一条回滚路**，所以：

* 默认**干跑**：整库复制到临时目录，在副本上真删 + 真验证（还会在副本上再保存一次，
  确认旧副本**不会长回来**），跑完删掉副本（`--keep` 保留）；
* `--apply` 才动线上库，动之前整库备份；
* 开关（`project_business_version`）**低于 4 时拒绝清理** —— 那种情况下这些副本就是
  正在用的数据，清掉等于删数据。

验证清单（干跑全跑，`--apply` 跑前 5 条）：

1. 每个项目的读模型与清理前**逐字节相同**（清的必须是"重复的那一份"）；
2. 业务表的行数一行不变（工序/刀具行/问题清单/选型/保存版本/履历/流水）；
3. 被删的表**没有长回来**（关掉开关重开一次，代码不该再建它们）；
4. `PRAGMA foreign_key_check` / `integrity_check` 干净；
5. 库体积变小（旧副本全是整份快照，通常几 MB）；
6. （仅干跑）清理之后再**保存一次**：旧影子表和 `state_json` 里的数组都不会回来。

用法：
    python tools/clean_legacy_project_data.py              # 干跑（副本，不动线上）
    python tools/clean_legacy_project_data.py --keep        # 干跑并保留副本目录
    python tools/clean_legacy_project_data.py --apply       # 真清理（先整库备份）
    python tools/clean_legacy_project_data.py --status      # 只读：还剩哪些旧副本
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

from app.machining_changes import CHANGES_TABLE  # noqa: E402
from app.machining_dfm import PROJECT_ARRAYS, MachiningDFMStore  # noqa: E402
from app.machining_history import HISTORY_TABLE, HISTORY_VERSION  # noqa: E402
from app.machining_process import BUSINESS_VERSION_KEY  # noqa: E402

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"

#: 要清掉的旧副本表（存在才删）。左边这张是"每一次保存的整份快照"，
#: 中间六张是各阶段拆表时留下的旧壳，最后一张 ``equipment`` 是设备库类型化之前的旧壳
#: （288 KB，含内联图片；代码只在"老库还没迁"时才读它，线上早就没人读了）。
LEGACY_TABLES = (
    "revisions",
    "projects_legacy_v1",
    "processes_legacy_v1",
    "equipment_legacy_v1",
    "fixtures_legacy_v1",
    "gauges_legacy_v1",
    "tools_legacy_v1",
    "equipment",
)

#: 清之前必须先确认"新表里有东西"的旧壳：表空了就说明还没迁完，不能删搬迁来源
GUARDED_TABLES = {"equipment": ("machines", "台设备")}

#: 清完之后业务表必须一行不少（表名 → 中文名）
BUSINESS_TABLES = (
    ("project_processes", "工序"),
    ("project_process_tools", "工序刀具行"),
    ("project_issues", "问题清单"),
    ("project_fixtures", "夹具选型"),
    ("project_gauges", "检具选型"),
    (HISTORY_TABLE, "保存版本 + 履历"),
    (CHANGES_TABLE, "变更流水"),
)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kb(size: int) -> str:
    return f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.2f} MB"


def read_rows(db_path: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, params).fetchall()
    finally:
        db.close()


def status(root: Path) -> dict:
    """只读：还剩哪些旧副本、每个项目的 state_json 里还留着什么。"""
    db_file = root / "machining_dfm.sqlite3"
    info: dict = {"root": str(root), "db": db_file.is_file(), "version": None, "projects": 0,
                  "legacy": {}, "state_arrays": {}, "business": {}, "size": 0}
    if not db_file.is_file():
        return info
    info["size"] = db_file.stat().st_size
    rows = read_rows(db_file, "SELECT value_json FROM app_settings WHERE key=?",
                     (BUSINESS_VERSION_KEY,))
    if rows:
        try:
            info["version"] = json.loads(rows[0]["value_json"])
        except ValueError:
            info["version"] = rows[0]["value_json"]
    names = {row["name"] for row in read_rows(
        db_file, "SELECT name FROM sqlite_master WHERE type='table'")}
    for table in LEGACY_TABLES:
        if table in names:
            info["legacy"][table] = read_rows(db_file, f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
    for table, _label in BUSINESS_TABLES:
        if table in names:
            info["business"][table] = read_rows(db_file, f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
    for row in read_rows(db_file, "SELECT id,name,state_json FROM projects ORDER BY updated DESC"):
        state = json.loads(row["state_json"])
        info["projects"] += 1
        info["state_arrays"][row["id"]] = {
            "name": row["name"],
            "keys": [key for key in PROJECT_ARRAYS if key in state],
            "bytes": len(row["state_json"].encode()),
        }
    return info


def print_status(info: dict) -> None:
    print(f"数据目录      = {info['root']}")
    print(f"库文件        = {'有' if info['db'] else '没有'}"
          + (f"（{_kb(info['size'])}）" if info["db"] else ""))
    print(f"开关(版本键)  = {BUSINESS_VERSION_KEY} → {info['version']!r}"
          "（1 工序 / 2 问题清单 / 3 选型报价 / 4 版本履历 / 5 变更流水）")
    print(f"项目数        = {info['projects']}")
    if info["legacy"]:
        print("旧副本表      =")
        for table, count in info["legacy"].items():
            print(f"    {table:24s} {count:5d} 行")
    else:
        print("旧副本表      = 无（已经清干净了）")
    for pid, item in info["state_arrays"].items():
        keys = "、".join(item["keys"]) or "（空）"
        print(f"    {item['name'][:24]:26s} state_json 里还留着：{keys}（{item['bytes']} 字节）")
    if info["business"]:
        print("业务表行数    = " + "｜".join(
            f"{label} {info['business'].get(table, 0)}" for table, label in BUSINESS_TABLES))


def records_of(store: MachiningDFMStore) -> dict[str, dict]:
    """每个项目的读模型（逐字节比对的基准）。"""
    return {row["id"]: store.get(row["id"]) for row in store.list()}


def clean(root: Path, *, apply: bool, keep: bool) -> int:
    db_file = root / "machining_dfm.sqlite3"
    if not db_file.is_file():
        print("没有找到库：", db_file)
        return 2

    problems: list[str] = []
    before_info = status(root)
    version = before_info["version"] if isinstance(before_info["version"], int) else 0
    if version < HISTORY_VERSION:
        print(f"\n开关还停在 {before_info['version']!r}（< {HISTORY_VERSION}）："
              "这些副本现在**就是正在用的数据**，不能清。")
        print("  先跑 python tools/migrate_project_versions.py --apply （阶段 3a）再回来。")
        return 2
    if not before_info["legacy"]:
        print("\n没有旧副本可清：库里已经是干干净净一份数据。")
        print_status(before_info)
        return 0
    baseline = MachiningDFMStore(root, SEED)
    before_records = records_of(baseline)
    before_business = dict(before_info["business"])
    before_size = before_info["size"]
    print("\n清理前：")
    print_status(before_info)

    # ---------------- 1) 备份（--apply 才写） ----------------
    if apply:
        backup = baseline._backup(
            f"pre-clean-legacy-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3")
        print(f"\n备份          = {backup}")
        print("                （回滚路径从此就是这一份备份；旧副本删掉之后不再有第二份）")

    # ---------------- 2) 删表 + 清项目行里的重复数组 ----------------
    print("\n=== 清理 ===")
    dropped: list[str] = []
    with baseline.connect() as db:
        for table in LEGACY_TABLES:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                              (table,)).fetchone():
                continue
            guard = GUARDED_TABLES.get(table)
            if guard:
                target, label = guard
                kept = db.execute(f"SELECT COUNT(*) FROM {target}").fetchone()[0] \
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                  (target,)).fetchone() else 0
                if not kept:
                    print(f"  留手：{target} 是空的（{label} 0），{table} 是它唯一的搬迁来源，跳过不删")
                    continue
            count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            db.execute(f"DROP TABLE {table}")
            dropped.append(f"{table}（{count} 行）")
        print("  删掉：" + ("、".join(dropped) if dropped else "（没有需要删的表）"))

        trimmed: list[str] = []
        for row in db.execute("SELECT id,name,state_json FROM projects ORDER BY updated DESC").fetchall():
            state = json.loads(row["state_json"])
            arrays = {key: state.get(key, []) for key in PROJECT_ARRAYS}
            kept = baseline._stored_arrays(db, row["id"], arrays, row["state_json"])
            if kept == row["state_json"]:
                continue
            db.execute("UPDATE projects SET state_json=? WHERE id=?", (kept, row["id"]))
            trimmed.append(f"{row['name'][:24]}（{_kb(len(row['state_json'].encode()))} → "
                           f"{_kb(len(kept.encode()))}，留 {sorted(json.loads(kept).keys()) or '{}'}）")
        print("  projects.state_json：" + ("\n      " + "\n      ".join(trimmed) if trimmed
                                          else "（本来就是干净的，没动）"))
    # 删掉的行只是变成空闲页，不 VACUUM 的话文件大小一点不变（旧副本通常几 MB）
    with baseline.connect() as db:
        db.execute("VACUUM")
    print(f"  已 VACUUM（把删掉的行真正还给文件）：{_kb(before_size)} → "
          f"{_kb((root / 'machining_dfm.sqlite3').stat().st_size)}")

    # ---------------- 3) 重开：表没长回来 + 读模型没变 ----------------
    print("\n=== 验证（重新打开 store）===")
    reopened = MachiningDFMStore(root, SEED)
    back = [table for table in LEGACY_TABLES if any(
        row["name"] == table for row in read_rows(
            root / "machining_dfm.sqlite3",
            "SELECT name FROM sqlite_master WHERE type='table'"))]
    if back:
        problems.append("删掉的表又长回来了：" + "、".join(back))
        print("  × 这些表又出现了：", "、".join(back))
    else:
        print(f"  √ {len(LEGACY_TABLES)} 张旧副本表都没长回来（代码不再建它们）")

    after_records = records_of(reopened)
    if after_records != before_records:
        changed = [pid for pid in before_records if before_records[pid] != after_records.get(pid)]
        problems.append(f"读模型变了（{len(changed)} 个项目）")
        print(f"  × 有 {len(changed)} 个项目的读模型与清理前不一致：{changed[:3]}")
        for pid in changed[:1]:
            before, after = before_records[pid], after_records[pid]
            for key in sorted(set(before) | set(after)):
                if before.get(key) != after.get(key) and key != "state":
                    print(f"      字段 {key} 变了")
            for key in sorted(set(before.get("state", {})) | set(after.get("state", {}))):
                if before["state"].get(key) != after["state"].get(key):
                    left = json.dumps(before["state"].get(key), ensure_ascii=False)
                    right = json.dumps(after["state"].get(key), ensure_ascii=False)
                    print(f"      state.{key}: {len(left)} 字节 → {len(right)} 字节")
    else:
        print(f"  √ {len(after_records)} 个项目的读模型与清理前**逐字节相同**"
              "（清的确实只是重复的那一份）")

    after_info = status(root)
    for table, label in BUSINESS_TABLES:
        if before_business.get(table, 0) != after_info["business"].get(table, 0):
            problems.append(f"{label} 行数变了")
            print(f"  × {label}：{before_business.get(table, 0)} → {after_info['business'].get(table, 0)}")
    if not problems:
        print("  √ 业务表行数一行没变（" + "｜".join(
            f"{label} {after_info['business'].get(table, 0)}" for table, label in BUSINESS_TABLES) + "）")

    with reopened.connect() as db:
        dirty = db.execute("PRAGMA foreign_key_check").fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    if dirty or integrity != "ok":
        problems.append(f"库体检不干净（foreign_key_check={dirty[:3]}、integrity_check={integrity}）")
        print("  × 体检不干净：", dirty[:3], integrity)
    else:
        print("  √ PRAGMA foreign_key_check 干净、integrity_check = ok")

    saved = before_size - after_info["size"]
    print(f"  √ 库体积 {_kb(before_size)} → {_kb(after_info['size'])}"
          f"（少 {_kb(max(saved, 0))}）")

    # ---------------- 4) 仅干跑：再保存一次，旧副本不会回来 ----------------
    if not apply:
        print("\n=== 干跑探针：清理之后再保存一次 ===")
        pid = reopened.list()[0]["id"]
        record = reopened.get(pid)
        reopened.update(pid, record["name"], record["state"], record["revision"])
        with reopened.connect() as db:
            names = {row["name"] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            still = [table for table in LEGACY_TABLES if table in names]
            stored = json.loads(db.execute(
                "SELECT state_json FROM projects WHERE id=?", (pid,)).fetchone()[0])
        if still:
            problems.append("保存之后旧副本又出现了：" + "、".join(still))
            print("  × 保存一次之后又出现了：", "、".join(still))
        else:
            print("  √ 保存一次之后旧副本表依旧不存在（是真停写，不是删了一次就算）")
        if stored:
            problems.append(f"保存之后 state_json 又写回了 {sorted(stored)}")
            print(f"  × state_json 又写回了：{sorted(stored)}")
        else:
            print("  √ state_json 依然是 {}（表里有的那份不再重复存）")
        print(f"  （探针只在副本上跑：线上的 revision 一个都没动）")

    print()
    if problems:
        print("× 有问题，先别 --apply：")
        for item in problems:
            print("  -", item)
        return 1
    if apply:
        print("√ 清理完成：旧副本已删，读模型逐字节不变，业务数据一行没少")
        print("  回滚 = 把上面那份整库备份复制回 data/machining_dfm/machining_dfm.sqlite3")
    else:
        print("√ 干跑通过：可以放心执行 --apply")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="清掉旧数据副本（默认干跑）")
    parser.add_argument("--apply", action="store_true", help="真清理（先整库备份）")
    parser.add_argument("--status", action="store_true", help="只读：还剩哪些旧副本")
    parser.add_argument("--keep", action="store_true", help="干跑后保留副本目录")
    parser.add_argument("--from", dest="source", default="", help="换一个数据目录（默认线上）")
    args = parser.parse_args()

    root = Path(args.source).resolve() if args.source else LIVE
    if args.status:
        print("=" * 72)
        print("旧副本现状（只读）")
        print("=" * 72)
        print_status(status(root))
        return 0

    if args.apply:
        print("=" * 72)
        print("开始清理线上库的旧副本（先整库备份）")
        print("=" * 72)
        return clean(root, apply=True, keep=args.keep)

    work = Path(tempfile.mkdtemp(prefix="machining-legacy-clean-"))
    target = work / root.name
    shutil.copytree(root, target)
    print("=" * 72)
    print(f"干跑（副本：{target}）")
    print("=" * 72)
    try:
        return clean(target, apply=False, keep=args.keep)
    finally:
        if args.keep:
            print("\n副本保留在：", target)
        else:
            shutil.rmtree(work, ignore_errors=True)
            print("\n提示：干跑副本已删除（--keep 可保留）")


if __name__ == "__main__":
    raise SystemExit(main())
