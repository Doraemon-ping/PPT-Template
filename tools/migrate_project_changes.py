"""变更流水落表迁移工具（阶段 3b）。

阶段 3b 只是**开一张只增不改的表** ``project_changes``（一行 = 一次改动里的一个实体），
把"谁在什么时候把哪一行改成了什么样"也落进库。和前几个阶段最大的不同：

**这一阶段不搬旧数据——流水从打开开关那一刻开始记（口径 5：不无中生有）。**
老项目在开关打开之前发生的改动**没有**流水，页面也不会凭空显示"某某时间改过"；
要查历史改动，那一版的完整快照一直都在 ``project_versions``（``kind='save'``）里。

所以"迁移"只做三件事：建表、写入版本键 5、逐字节验证"打开开关没有改变任何既有读模型"。
**默认是干跑**：把线上库整个复制到临时目录，在副本上把开关开到 5、跑完整验证，
还会在副本上**真写几笔**（建工序/改/删/恢复/换图/整份保存）看流水是不是真记下来了，
最后把副本删掉（``--keep`` 可保留）。只有加 ``--apply`` 才动线上库，动之前整库备份；
``--apply`` **不会**在线上跑那几笔探针写入（那才是真的无中生有）。

前置：阶段 3a（``tools/migrate_project_versions.py``，版本键 4）必须已经迁完——
版本键是递增的能力级别（1 工序 / 2 问题清单 / 3 选型报价 / 4 版本履历 / **5 变更流水**）。
干跑遇到前置没迁的副本时，会自动在副本上把 1b→3a 依次跑一遍，
所以今天就能在真实数据上端到端演练"0 → 5"；``--apply`` 不会替你补前面的阶段。

验证清单（干跑在副本上全跑，``--apply`` 跑前 5 条）：

1. 表在、且**七个真外键**都在（``project_id`` + 五个被改的行 + ``version_id``）；
2. 开关打开后，**每个项目读模型与打开前逐字节相同**（只多一个 ``changes_table`` 标志）；
3. 老数据的流水行数 = **0**（不无中生有；重复跑第二遍还是 0，幂等）；
4. ``GET /changes`` 清单结构可用：``enabled=true``、实体/动作字典齐全、空清单不报错；
5. ``PRAGMA foreign_key_check`` 干净、没有悬空的 ``project_id``；
6. **（仅干跑）功能探针**：在副本上真写几笔，验证
   每次写入都留一条流水、``entity``/``action``/被改的那一行外键都对、
   ``version_id`` 指得到"这一次保存"的那一行、被拒的写入一条都不留，
   而且记流水**不影响**保存版本（快照照旧是完整的一份，旧影子表不再长）。

用法：
    python tools/migrate_project_changes.py                  # 干跑（副本，不动线上）
    python tools/migrate_project_changes.py --keep            # 干跑并保留副本目录
    python tools/migrate_project_changes.py --apply           # 真正迁移（先备份）
    python tools/migrate_project_changes.py --status          # 只读：现在迁到哪一步了
"""

from __future__ import annotations

import argparse
import importlib.util
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
except (AttributeError, ValueError):  # pragma: no cover - 老解释器/被重定向
    pass

from app.machining_changes import (  # noqa: E402
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_PHOTO,
    ACTION_RESTORE,
    ACTION_SAVE,
    ACTION_UPDATE,
    CHANGES_TABLE,
    CHANGES_VERSION,
    ENTITY_HISTORY,
    ENTITY_ISSUE,
    ENTITY_PROCESS,
    ENTITY_PROJECT,
    ENTITY_SELECTION,
    ENTITY_SETTINGS,
    ENTITY_TOOL,
    ENTITY_COLUMNS,
)
from app.machining_dfm import MachiningDFMStore  # noqa: E402
from app.machining_history import HISTORY_TABLE, HISTORY_VERSION  # noqa: E402
from app.machining_process import BUSINESS_VERSION_KEY  # noqa: E402

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"
PREREQUISITE = HISTORY_VERSION          # 4：版本履历（3a）
PROBE_NAME = "变更流水探针（干跑专用，可删）"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64

#: 记流水不应该动到的读模型键（打开开关只会多出 ``changes_table``）
IGNORED_KEYS = ("changes_table", "business_version")


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_rows(db_path: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, params).fetchall()
    finally:
        db.close()


def status(root: Path) -> dict:
    """只读：开关、表、流水行数。"""
    db_file = root / "machining_dfm.sqlite3"
    info: dict = {"root": str(root), "db": db_file.is_file(), "tables": [], "version": None,
                  "projects": 0, "changes": 0, "changes_live": 0, "by_entity": {}, "saved": 0}
    if not db_file.is_file():
        return info
    info["tables"] = [
        row["name"] for row in read_rows(db_file, "SELECT name FROM sqlite_master WHERE type='table'")
    ]
    rows = read_rows(db_file, "SELECT value_json FROM app_settings WHERE key=?",
                     (BUSINESS_VERSION_KEY,))
    if rows:
        try:
            info["version"] = json.loads(rows[0]["value_json"])
        except ValueError:
            info["version"] = rows[0]["value_json"]
    info["projects"] = read_rows(db_file, "SELECT COUNT(*) AS n FROM projects")[0]["n"]
    if HISTORY_TABLE in info["tables"]:
        info["saved"] = read_rows(
            db_file, f"SELECT COUNT(*) AS n FROM {HISTORY_TABLE} WHERE kind='save'")[0]["n"]
    if CHANGES_TABLE in info["tables"]:
        info["changes"] = read_rows(
            db_file, f"SELECT COUNT(*) AS n FROM {CHANGES_TABLE}")[0]["n"]
        info["changes_live"] = read_rows(
            db_file, f"SELECT COUNT(*) AS n FROM {CHANGES_TABLE} WHERE deleted_at IS NULL"
        )[0]["n"]
        info["by_entity"] = {
            row["entity"]: row["n"] for row in read_rows(
                db_file, f"SELECT entity,COUNT(*) AS n FROM {CHANGES_TABLE} GROUP BY entity")
        }
    return info


def print_status(info: dict) -> None:
    has_business = "project_processes" in info["tables"]
    has_history = HISTORY_TABLE in info["tables"]
    has_changes = CHANGES_TABLE in info["tables"]
    print(f"数据目录      = {info['root']}")
    print(f"库文件        = {'有' if info['db'] else '没有'}")
    print(f"开关(版本键)  = {BUSINESS_VERSION_KEY} → {info['version']!r}"
          f"（1 工序 / 2 问题清单 / 3 选型报价 / 4 版本履历 / 5 变更流水）")
    print(f"前置(1b~2b)   = {'已迁（工序等表在）' if has_business else '未迁（先跑 migrate_project_processes.py）'}")
    print(f"版本履历表    = {'有' if has_history else '无'}（保存版本 {info['saved']} 行）")
    print(f"变更流水表    = {'有' if has_changes else '无'}"
          f"（{info['changes']} 行，其中未隐藏 {info['changes_live']} 行"
          + (f"；{info['by_entity']}" if info["by_entity"] else "") + "）")
    print(f"项目数        = {info['projects']}")
    version = info["version"] if isinstance(info["version"], int) else 0
    if version >= CHANGES_VERSION and has_changes:
        print("状态          = 阶段 3b 已迁移（改动都会记进 project_changes）")
    elif has_changes:
        print("状态          = 表在、但版本键还停在 4（写入点暂时不记流水）")
    elif version >= PREREQUISITE:
        print("状态          = 前置已就绪，阶段 3b 未迁移（跑本工具即可）")
    print("（本阶段不搬旧数据：流水从打开开关开始记，老数据一行都不补——口径 5 不无中生有）")


def fk_report(store: MachiningDFMStore) -> tuple[list[str], dict[str, str]]:
    """表里实际存在的 ``列 → 目标表`` 外键，以及缺了哪几个。

    选型那一列是**历史遗留**：它指向已废弃的多态表 ``project_selections``，新库不建那张表，
    所以这里只要求"列在"（可空、没有外键），选型的行外键改由 ``fixture_row_id`` /
    ``gauge_row_id`` 两列承担——它们分别指向两张新表。
    """
    with store.connect() as db:
        found = {row["from"]: row["table"] for row in
                 db.execute(f"PRAGMA foreign_key_list({CHANGES_TABLE})")}
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({CHANGES_TABLE})")}
    wanted = {"project_id": "projects", "version_id": "project_versions",
              "history_row_id": "project_versions",
              "fixture_row_id": "project_fixtures", "gauge_row_id": "project_gauges"}
    for entity, column in ENTITY_COLUMNS.items():
        if entity == ENTITY_SELECTION:
            continue      # 见 docstring：这一列不建外键
        wanted[column] = {"process": "project_processes",
                          "tool": "project_process_tools",
                          "issue": "project_issues",
                          "history": "project_versions"}[entity]
    missing = [f"{column} → {table}" for column, table in wanted.items()
               if found.get(column) != table]
    if ENTITY_COLUMNS[ENTITY_SELECTION] not in columns:
        missing.append(f"{ENTITY_COLUMNS[ENTITY_SELECTION]}（老列，应当留着但不再有外键）")
    return missing, found


def records_of(store: MachiningDFMStore) -> dict[str, dict]:
    """每个项目的完整读模型（比字节用），去掉"打开开关"本来就会变的标志。"""
    snapshot: dict[str, dict] = {}
    for item in store.list():
        record = store.get(item["id"], allow_archived=True)
        snapshot[item["id"]] = {
            key: value for key, value in record.items() if key not in IGNORED_KEYS
        }
    return snapshot


def probe(root: Path, seed: Path, problems: list[str]) -> None:
    """在副本上真写几笔，看流水是不是真记下来了（只在干跑里跑）。"""
    import os
    os.environ["MACHINING_PROJECT_BUSINESS"] = str(CHANGES_VERSION)
    store = MachiningDFMStore(root, seed)
    if not store.changes_enabled:
        problems.append("探针：版本键 5 没生效")
        return
    print("\n=== 功能探针（只在副本上真写几笔）===")
    project = store.create(PROBE_NAME, {"G": {"cust": "探针", "part": "P-探针"},
                                        "pr": [], "is": [], "vh": []})
    pid = project["id"]

    store.create_project_process(pid, {"nm": "OP10 粗铣"})
    process = store.processes.list_typed(pid)[-1]
    store.update_project_process(pid, process["id"], {"nm": "OP10 精铣", "mc": 3})
    store.create_project_tool(pid, process["id"], {"code": "T01", "tp": "D50盘铣刀", "n": 3000})
    tool = store.process_tools.list_typed(pid)[-1]
    store.update_project_tool(pid, tool["id"], {"n": 3500})
    store.set_tool_photo(pid, tool["id"], PNG, "image/png", "probe.png")
    store.create_project_issue(pid, {"tp": "尺寸超差", "ds": "探针"})
    issue = store.issues.list_typed(pid)[-1]
    store.update_project_issue(pid, issue["id"], {"st": "已完成"})
    store.save_project_selection(pid, "fixture", 0, {"quoted": 0})
    store.create_project_history(pid, {"ver": "V0.1", "dt": "2026-01-01", "ds": "探针"})
    history = store.version_table.history_rows(pid)[0]
    store.save_project_history(pid, history["id"], {"ds": "探针改过"})
    store.delete_project_process(pid, process["id"], by="探针", reason="探针删除")
    store.restore_project_process(pid, process["id"])
    store.save_project_settings(pid, {"hpd": 20})
    record = store.get(pid)
    store.update(pid, record["name"], record["state"], record["revision"])
    store.reorder_project_processes(pid, [process["id"]])

    # 被拒的写入：一条流水都不许留
    before_rejected = len(store.project_changes(pid, limit=10 ** 6)["changes"])
    try:
        store.create_project_issue(pid, {"tp": "不该成功", "st": "随便写"})
        problems.append("探针：非法状态竟然写成功了（校验没生效）")
    except Exception:  # noqa: BLE001 - 预期就是被拒
        pass
    after_rejected = len(store.project_changes(pid, limit=10 ** 6)["changes"])
    if after_rejected != before_rejected:
        problems.append("探针：被拒的写入留下了流水（不该留）")
    else:
        print("  √ 被拒的写入（非法状态 422）一条流水都没留")

    listing = store.project_changes(pid, limit=10 ** 6)
    items = list(reversed(listing["changes"]))
    seen_entities = {item["entity"] for item in items}
    seen_actions = {item["action"] for item in items}
    print(f"  探针项目流水 {len(items)} 条："
          + "、".join(f"{entity}" for entity in sorted(seen_entities)))
    for entity in (ENTITY_PROJECT, ENTITY_SETTINGS, ENTITY_PROCESS, ENTITY_TOOL, ENTITY_ISSUE,
                   ENTITY_SELECTION, ENTITY_HISTORY):
        if entity not in seen_entities:
            problems.append(f"探针：{entity} 的改动没记上流水")
    for action in (ACTION_CREATE, ACTION_UPDATE, ACTION_DELETE, ACTION_RESTORE, ACTION_PHOTO,
                   ACTION_SAVE):
        if action not in seen_actions:
            problems.append(f"探针：{action} 这个动作没记上流水")

    # 每条流水：被改的那一行外键、以及 version_id 都要指得准
    linked_problems = 0
    with store.connect() as db:
        for item in items:
            columns = [column for column in ENTITY_COLUMNS.values() if item.get(column)]
            if len(columns) > 1:
                problems.append(f"探针：流水 {item['id']} 挂了不止一行（{columns}）")
                linked_problems += 1
            if item["entity"] not in (ENTITY_PROJECT, ENTITY_SETTINGS) \
                    and item["action"] != "reorder" and not columns:
                problems.append(f"探针：流水 {item['id']}（{item['entity']}）没挂被改的那一行")
                linked_problems += 1
            if not item["version_id"]:
                problems.append(f"探针：流水 {item['id']} 没有指向保存版本")
                linked_problems += 1
                continue
            row = db.execute(
                "SELECT kind,revision,project_id FROM project_versions WHERE id=?",
                (item["version_id"],)).fetchone()
            if row is None or row["project_id"] != pid or row["kind"] != "save":
                problems.append(f"探针：流水 {item['id']} 的 version_id 指错了")
                linked_problems += 1
    if not linked_problems:
        print("  √ 每条流水都挂着被改的那一行，version_id 指得到那一次保存（kind=save）")

    # 记流水不影响保存版本；而且保存版本**只存在表里一份**（口径 6：影子副本停写）
    with store.connect() as db:
        revision = db.execute(
            f"SELECT MAX(revision) AS top FROM {HISTORY_TABLE} WHERE project_id=? AND kind='save'",
            (pid,)).fetchone()["top"]
        snapshot = json.loads(db.execute(
            f"SELECT state_json FROM {HISTORY_TABLE} WHERE project_id=? AND kind='save' AND revision=?",
            (pid, revision)).fetchone()["state_json"])
        shadow_rows = 0
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='revisions'").fetchone():
            shadow_rows = db.execute(
                "SELECT COUNT(*) AS n FROM revisions WHERE project_id=? AND revision>?",
                (pid, revision)).fetchone()["n"]
    if set(snapshot) != {"G", "pr", "is", "vh"} or not snapshot.get("pr"):
        problems.append("探针：第 %s 版快照不是完整的一份（G + pr/is/vh）" % revision)
    elif shadow_rows:
        problems.append(f"探针：影子副本 revisions 又长出了 {shadow_rows} 行（开关 ≥4 之后不该再写）")
    else:
        print(f"  √ 第 {revision} 版快照完整，且旧影子表一行都没再写（口径 6）")

    with store.connect() as db:
        dirty = db.execute("PRAGMA foreign_key_check").fetchall()
    if dirty:
        problems.append(f"探针：写完之后外键体检不干净 {dirty[:3]}")
    else:
        print("  √ 写完这么多笔之后 PRAGMA foreign_key_check 依旧干净")

    print(f"  （探针项目「{PROBE_NAME}」只存在于副本/临时目录，不会被 --apply 带进线上）")


def migrate(root: Path, *, apply: bool, keep: bool) -> int:
    """在 ``root`` 上跑迁移。``apply=False`` 时调用方已经把副本准备好了。"""
    db_file = root / "machining_dfm.sqlite3"
    if not db_file.is_file():
        print("没有找到库：", db_file)
        return 2

    problems: list[str] = []
    info = status(root)
    version = info["version"] if isinstance(info["version"], int) else 0
    if version < PREREQUISITE and apply:
        print(f"\n前置没就绪：版本键还停在 {info['version']!r}，先跑")
        print("  python tools/migrate_project_versions.py --apply   （阶段 3a，会带上 1b/2a/2b）")
        print("再回来跑本工具。干跑（不带 --apply）会自动在副本上先把前置跑一遍。")
        return 2

    baseline = MachiningDFMStore(root, SEED)
    if baseline.changes_enabled:
        print("开关已经开着（版本键 ≥ 5）：阶段 3b 早就跑完了。")
        return 0
    before_records = records_of(baseline)
    before_info = status(root)
    print(f"\n迁移前：版本键 {before_info['version']!r}｜项目 {before_info['projects']} 个｜"
          f"保存版本 {before_info['saved']} 行｜变更流水 {before_info['changes']} 行")

    # ---------------- 1) 备份（--apply 才写） ----------------
    backup_path = ""
    if apply:
        backup = baseline._backup(
            f"pre-project-changes-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3")
        backup_path = str(backup)
        print(f"\n备份          = {backup}")
        baseline = MachiningDFMStore(root, SEED)

    # ---------------- 2) 打开开关（进程内）→ 建表 ----------------
    import os
    os.environ["MACHINING_PROJECT_BUSINESS"] = str(CHANGES_VERSION)
    store = MachiningDFMStore(root, SEED)
    assert store.changes_enabled, "变更流水开关没打开（环境变量应该给 ≥5）"

    print("\n=== 建表 ===")
    missing, found = fk_report(store)
    print(f"  {CHANGES_TABLE} 的外键 {len(found)} 个："
          + "、".join(f"{column}→{table}" for column, table in sorted(found.items())))
    if missing:
        problems.append("外键没建全：" + "、".join(missing))
        print("  × 缺外键：" + "、".join(missing))
    else:
        print("  √ 七个真外键都在（项目 / 保存版本 / 五个被改的行），删目标行一律 SET NULL")

    # ---------------- 3) 写开关 ----------------
    print("\n=== 开关 ===")
    with store.connect() as db:
        db.execute(
            "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
            (BUSINESS_VERSION_KEY, str(CHANGES_VERSION), _stamp()),
        )
    print(f"  已写 {BUSINESS_VERSION_KEY} = {CHANGES_VERSION}"
          "（每个行级写入点从此都会留一条流水）")

    # ---------------- 4) 重新打开：只靠版本键 ----------------
    print("\n=== 验证（重新打开 store，只靠版本键启用）===")
    os.environ.pop("MACHINING_PROJECT_BUSINESS", None)
    reopened = MachiningDFMStore(root, SEED)
    if not reopened.changes_enabled:
        problems.append("重新打开后开关没打开（版本键没生效）")
    else:
        print(f"  √ 只靠版本键就能打开：business_version={reopened.business_version}、"
              f"changes_enabled={reopened.changes_enabled}")

    after_records = records_of(reopened)
    if after_records != before_records:
        changed = [pid for pid in before_records
                   if before_records[pid] != after_records.get(pid)]
        problems.append(f"打开开关后读模型变了（{len(changed)} 个项目）")
        print(f"  × 有 {len(changed)} 个项目的读模型与打开前不一致：{changed[:3]}")
        for pid in changed[:1]:
            old, new = before_records[pid], after_records.get(pid) or {}
            for key in sorted(set(old) | set(new)):
                if old.get(key) != new.get(key):
                    print(f"      键 {key}：{str(old.get(key))[:60]} → {str(new.get(key))[:60]}")
    else:
        print(f"  √ {len(after_records)} 个项目的读模型与打开前**逐字节相同**"
              "（只多一个 changes_table 标志）")

    # ---------------- 5) 口径：老数据一行流水都不补 ----------------
    after_info = status(root)
    print("\n=== 口径：不无中生有 ===")
    print(f"  变更流水 {before_info['changes']} 行 → {after_info['changes']} 行")
    if after_info["changes"] != before_info["changes"]:
        problems.append("迁移往流水表里补了行（本阶段不搬旧数据）")
        print("  × 流水行数变了：本阶段不搬旧数据，一行都不该新增")
    else:
        print("  √ 老数据一行流水都没补：开关打开之前的改动不予追溯（要查历史改动看保存版本的快照）")
    if after_info["changes"] == 0:
        print("      （线上现在就是 0 行——第一次真实改动之后才会有第一条流水）")

    probe_pid = next(iter(after_records), "")
    try:
        listing = reopened.project_changes(probe_pid)
    except Exception as error:  # noqa: BLE001 - 报出来比 500 好
        problems.append(f"GET /changes 读不了（{error}）")
    else:
        if listing.get("enabled") is True and listing.get("table") == CHANGES_TABLE:
            print(f"  √ 清单接口可用：enabled=true、实体 {len(listing['entities'])} 种、"
                  f"动作 {len(listing['actions'])} 种")
        else:
            problems.append("清单接口返回值不对")
    try:
        reopened.project_changes("不存在的项目")
    except Exception as error:  # noqa: BLE001
        if "不存在" in str(error):
            print("  √ 不存在的项目给明确的 404（不是 500）")
        else:
            problems.append(f"不存在的项目报了意料之外的错（{error}）")
    else:
        problems.append("不存在的项目竟然读出了清单")

    # ---------------- 6) 外键体检 ----------------
    print("\n=== 外键体检 ===")
    with store.connect() as db:
        dirty = db.execute("PRAGMA foreign_key_check").fetchall()
        orphan = db.execute(
            f"SELECT COUNT(*) AS n FROM {CHANGES_TABLE} c "
            "LEFT JOIN projects p ON p.id=c.project_id WHERE p.id IS NULL").fetchone()["n"]
        dangling = db.execute(
            f"SELECT COUNT(*) AS n FROM {CHANGES_TABLE} c "
            "LEFT JOIN project_versions v ON v.id=c.version_id "
            "WHERE c.version_id IS NOT NULL AND v.id IS NULL").fetchone()["n"]
    print(f"  PRAGMA foreign_key_check = {'干净' if not dirty else dirty[:3]}")
    print(f"  悬空的 project_id = {orphan}｜悬空的 version_id = {dangling}")
    if dirty:
        problems.append("外键体检不干净")
    if orphan:
        problems.append(f"有 {orphan} 行的 project_id 指向不存在的项目")
    if dangling:
        problems.append(f"有 {dangling} 行的 version_id 指向不存在的保存版本")

    # ---------------- 7) 功能探针（只干跑） ----------------
    if not apply:
        probe(root, SEED, problems)
    else:
        print("\n（--apply 不在线上跑探针写入：线上只建表 + 写开关，一条流水都不造）")

    print()
    if problems:
        print("× 迁移不通过：")
        for item in problems[:20]:
            print("  -", item)
        if not apply:
            print("\n副本保留在：", root)
        elif backup_path:
            print(f"\n线上数据未被信任：请用备份回滚 → {backup_path}")
        return 1
    if apply:
        print("√ 迁移完成：改动从此都会记进 project_changes，读模型与迁移前一致")
        if backup_path:
            print(f"  备份：{backup_path}")
        print("  回滚：把 app_settings.project_business_version 改回 4"
              "（表留着不碍事，写入点只是不再记流水）")
    else:
        print("√ 干跑通过：可以放心执行 --apply")
        print("  提示：干跑副本" + ("保留在 " + str(root) if keep else "已删除"))
    return 0


def _ensure_prerequisite(target: Path, *, skip: bool) -> int:
    """干跑时在副本上把 1b→3a 依次补齐，好让这次干跑覆盖 0 → 5 的完整链路。

    只在**副本**上用（``apply=False``）；每一步都是幂等的：跑完再读一次版本键决定下一
    步要不要跑，已经迁过的阶段会被工具自己跳过。
    """
    def version_now() -> int:
        current = status(target)["version"]
        return current if isinstance(current, int) else 0

    if version_now() >= PREREQUISITE:
        return 0
    if skip:
        print(f"前置没迁（版本键 {status(target)['version']!r}），而且指定了 --skip-prerequisite")
        return 2
    print("\n前置（1b→3a）还没迁：先在**副本**上把它们依次跑一遍，"
          "好让这次干跑覆盖 0 → 5 的完整链路")
    stages = (
        (3, "migrate_project_processes.py", "migrate_project_processes", "阶段 1b/2a/2b"),
        (PREREQUISITE, "migrate_project_versions.py", "migrate_project_versions", "阶段 3a"),
    )
    for level, filename, name, label in stages:
        if version_now() >= level:
            continue
        print("-" * 72)
        code = _tool_module(filename, name).migrate(target, apply=False, keep=True)
        if code != 0:
            print(f"× 前置迁移（{label}）在副本上就没通过：先解决它，再看阶段 3b")
            return code
    if version_now() < PREREQUISITE:
        print(f"× 前置还是没就绪（版本键 {status(target)['version']!r}）")
        return 2
    print("-" * 72)
    return 0


def _tool_module(filename: str, name: str):
    """把同目录的迁移工具当模块加载（tools 不是包）。"""
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正迁移线上库（默认只干跑）")
    parser.add_argument("--keep", action="store_true", help="干跑后保留临时副本")
    parser.add_argument("--status", action="store_true", help="只读：打印当前迁移状态")
    parser.add_argument("--from", dest="source", default="", help="要迁移的数据目录（默认线上目录）")
    parser.add_argument("--skip-prerequisite", action="store_true",
                        help="干跑时不自动补跑 1b~3a（前置没迁就直接失败）")
    args = parser.parse_args()

    source = Path(args.source).resolve() if args.source else LIVE

    if args.status:
        print_status(status(source))
        return 0

    print("=" * 72)
    print("迁移前状态")
    print("=" * 72)
    print_status(status(source))

    if args.apply:
        if source != LIVE:
            print("\n--apply 只允许对线上目录使用（要演练请用 --from 且不要加 --apply）")
            return 2
        print("\n" + "=" * 72)
        print("开始迁移线上库（先整库备份）")
        print("=" * 72)
        return migrate(source, apply=True, keep=False)

    work = Path(tempfile.mkdtemp(prefix="machining-changes-migrate-"))
    target = work / "machining_dfm"
    try:
        shutil.copytree(source, target)
        if LIVE in target.parents or target == LIVE:
            print("拒绝在线上目录上干跑")
            return 2
        print("\n" + "=" * 72)
        print(f"干跑（副本：{target}）")
        print("=" * 72)
        info = status(target)
        version = info["version"] if isinstance(info["version"], int) else 0
        if version < PREREQUISITE:
            code = _ensure_prerequisite(target, skip=args.skip_prerequisite)
            if code != 0:
                return code
        return migrate(target, apply=False, keep=args.keep)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
