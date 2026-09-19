"""工序 + 问题清单 + 选型报价落表迁移工具（阶段 1b + 2a + 2b）。

阶段 1b：把项目 ``pr[]`` 拆进 ``project_processes`` / ``project_process_tools``；
阶段 2a：把项目 ``is[]`` 拆进 ``project_issues``（外键指向工序表与附件库）；
阶段 2b：把 ``G.fixQ/fixQC/insp/inspQ`` 拆进 ``project_selections``
（外键指向夹具库/检具库与两个类别字典，库行被删时按快照继续算价）。

**默认是干跑**：把线上库整个复制到临时目录，在副本上跑完整迁移并逐字节核对读模型，
最后把副本删掉（``--keep`` 可保留）。只有加 ``--apply`` 才会动线上库，而且动之前先整库备份。

迁移顺序（每一步都可重复执行）：

1. 整库备份 → ``backups/pre-project-business-<时间戳>.sqlite3``（``--apply`` 才写）；
2. 原始 ``state_json`` 归档进 ``processes_legacy_v1``（万一要回滚，或要人工核对）；
3. 逐项目 ``apply_split``：工序进 ``project_processes``、刀具行进 ``project_process_tools``；
   按名字绑刀具库 id，重名用组+直径消歧，仍不唯一就留空并**报告**，绝不猜；
4. 逐项目 ``apply_issue_split``：问题清单进 ``project_issues``，按**工序当前名字**绑
   ``process_id`` 外键（同名多道工序时留空，只存名字快照）；
5. 逐项目 ``apply_selection_split``：选型报价进 ``project_selections``，**每个类别一格**
   （未选型的格子也要有行，否则"是否报价"的勾选会丢）；按旧串绑库里唯一那条，重名不猜；
6. 写 ``app_settings.project_business_version = 3``（这一步等于"开关打开"，写在最后）；
7. 重新打开 store（不带环境变量，纯靠版本键）验证：``pr[]``/``is[]``/选型四个数组与迁移前
   **逐字节相同**（含键序）、成本基线指纹不变、行数与旧数据一致。

用法：
    python tools/migrate_project_processes.py                 # 干跑（副本，不动线上）
    python tools/migrate_project_processes.py --keep           # 干跑并保留副本目录
    python tools/migrate_project_processes.py --apply          # 真正迁移（先备份）
    python tools/migrate_project_processes.py --status         # 只读：现在迁到哪一步了
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
# 不换掉 sys.stdout（那样会打断 pytest 的捕获、也不便于被别的工具 import）：
# 只把编码调成 utf-8，Windows 控制台照样能打中文。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover - 老解释器/被重定向
    pass

from app.machining_dfm import MachiningDFMStore  # noqa: E402
from app.machining_issue import (  # noqa: E402
    ISSUE_TABLE,
    ISSUE_VERSION,
    apply_issue_split,
    legacy_issues,
)
from app.machining_process import BUSINESS_VERSION, BUSINESS_VERSION_KEY  # noqa: E402
from app.machining_selection import (  # noqa: E402
    FIXTURE_TABLE,
    GAUGE_TABLE,
    LEGACY_SELECTION_TABLE,
    SELECTION_ARRAY_KEYS,
    SELECTION_VERSION,
    apply_selection_split,
    copy_legacy_rows,
    legacy_selection_arrays,
)

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"
ARCHIVE = "processes_legacy_v1"
BASELINE = BASE / "tools" / "baselines" / "process_cost_baseline.json"


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _selection_expected(general: dict) -> dict:
    """迁移前这四个键的"页面可见值"。

    老项目里可能**根本没有**这几个键（页面上 `applyData`/`init` 会给它们补默认值：
    ``fixQ`` 补四个空串、``fixQC`` 补四个 1、``insp``/``inspQ`` 各五个）。
    所以比对的不是"键在不在"，而是"页面看到的值一不一样"：缺键的那一侧按页面默认值算。
    """
    result: dict = {}
    for key in SELECTION_ARRAY_KEYS:
        value = general.get(key)
        result[key] = list(value) if isinstance(value, list) else None
    return result


def _selection_problems(before: dict, after: dict) -> list[str]:
    """逐个键比对：缺键的一侧按"页面默认值"补齐再比。"""
    problems: list[str] = []
    for key in SELECTION_ARRAY_KEYS:
        old = before.get(key)
        new = after.get(key)
        if old is None:
            # 旧数据没有这个键：只要新值是"全默认"（选型全空串、报价全 1）就算一致
            blank = "" if key in ("fixQ", "insp") else 1
            if not isinstance(new, list) or any(item != blank for item in new):
                problems.append(
                    f"{key}：旧数据没有这个键，迁移后却是 {json.dumps(new, ensure_ascii=False)}"
                )
            continue
        if not isinstance(new, list) or json.dumps(old, ensure_ascii=False) != json.dumps(new, ensure_ascii=False):
            problems.append(f"{key}：{json.dumps(old, ensure_ascii=False)} → "
                            f"{json.dumps(new, ensure_ascii=False)}")
    return problems


def read_rows(db_path: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql, params).fetchall()
    finally:
        db.close()


def status(root: Path) -> dict:
    """只读：开关、表、归档、行数。"""
    db_file = root / "machining_dfm.sqlite3"
    info: dict = {"root": str(root), "db": db_file.is_file(), "tables": [], "version": None,
                  "projects": 0, "processed": 0, "archived": 0, "tools_rows": 0, "issue_rows": 0,
                  "fixture_rows": 0, "gauge_rows": 0, "legacy_selection_rows": 0}
    if not db_file.is_file():
        return info
    info["tables"] = [
        row["name"] for row in read_rows(db_file, "SELECT name FROM sqlite_master WHERE type='table'")
    ]
    rows = read_rows(db_file, "SELECT value_json FROM app_settings WHERE key=?", (BUSINESS_VERSION_KEY,))
    if rows:
        try:
            info["version"] = json.loads(rows[0]["value_json"])
        except ValueError:
            info["version"] = rows[0]["value_json"]
    info["projects"] = read_rows(db_file, "SELECT COUNT(*) AS n FROM projects")[0]["n"]
    if "project_processes" in info["tables"]:
        info["processed"] = read_rows(db_file, "SELECT COUNT(*) AS n FROM project_processes")[0]["n"]
    if "project_process_tools" in info["tables"]:
        info["tools_rows"] = read_rows(db_file, "SELECT COUNT(*) AS n FROM project_process_tools")[0]["n"]
    if ISSUE_TABLE in info["tables"]:
        info["issue_rows"] = read_rows(db_file, f"SELECT COUNT(*) AS n FROM {ISSUE_TABLE}")[0]["n"]
    # 选型现在是两张项目级表（夹具/检具）；老的多态表只作为迁移来源
    for table, key in ((FIXTURE_TABLE, "fixture_rows"), (GAUGE_TABLE, "gauge_rows"),
                       (LEGACY_SELECTION_TABLE, "legacy_selection_rows")):
        if table in info["tables"]:
            info[key] = read_rows(db_file, f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]
    if ARCHIVE in info["tables"]:
        info["archived"] = read_rows(db_file, f"SELECT COUNT(*) AS n FROM {ARCHIVE}")[0]["n"]
    return info


def print_status(info: dict) -> None:
    has_tables = "project_processes" in info["tables"]
    has_issues = ISSUE_TABLE in info["tables"]
    has_selections = FIXTURE_TABLE in info["tables"] or GAUGE_TABLE in info["tables"]
    print(f"数据目录      = {info['root']}")
    print(f"库文件        = {'有' if info['db'] else '没有'}")
    print(f"开关(版本键)  = {BUSINESS_VERSION_KEY} → {info['version']!r}")
    print(f"工序表        = {'有' if has_tables else '无'}")
    print(f"问题清单表    = {'有' if has_issues else '无'}（{info['issue_rows']} 行）")
    print(f"夹具选型表    = {'有' if FIXTURE_TABLE in info['tables'] else '无'}"
          f"（{info['fixture_rows']} 行）")
    print(f"检具选型表    = {'有' if GAUGE_TABLE in info['tables'] else '无'}"
          f"（{info['gauge_rows']} 行）")
    if info["legacy_selection_rows"]:
        print(f"老选型表      = {LEGACY_SELECTION_TABLE} 还有 {info['legacy_selection_rows']} 行"
              "（迁移会按 kind 搬进上面两张表）")
    print(f"归档表        = {ARCHIVE} → {info['archived']} 个项目")
    print(f"项目数        = {info['projects']}")
    print(f"工序行/刀具行 = {info['processed']} / {info['tools_rows']}")
    version = info["version"] if isinstance(info["version"], int) else 0
    if version >= SELECTION_VERSION and has_selections:
        print("状态          = 阶段 2b 已迁移（工序 + 问题清单 + 选型报价都走表）")
    elif version >= ISSUE_VERSION and has_issues:
        if has_selections:
            print("状态          = 阶段 2b 表在、但版本键还停在 2（读模型仍走 extra_json 的选型）")
        else:
            print("状态          = 阶段 2a 已迁移（工序 + 问题清单走表；选型报价还没迁）")
    elif version >= BUSINESS_VERSION and has_tables:
        if has_issues:
            print("状态          = 阶段 2a 表在、但版本键还停在 1（读模型仍走 state_json 的 is[]）")
        else:
            print("状态          = 只有阶段 1b 已迁移（工序走表；问题清单还没迁）")
    elif info["version"] and not has_tables:
        print("状态          = ⚠ 开关开着但表不在（下次启动会补建，表为空 → 读模型仍回退 state_json）")
    else:
        print("状态          = 未迁移（开关关着，读模型走 state_json）")


def migrate(root: Path, *, apply: bool, keep: bool) -> int:
    """在 ``root`` 上跑迁移。``apply=False`` 时调用方已经把副本准备好了。"""
    db_file = root / "machining_dfm.sqlite3"
    if not db_file.is_file():
        print("没有找到库：", db_file)
        return 2

    # 1) 先**开关关着**打开一次：拿迁移前的读模型当基准。
    #    注意不能拿 state_json 里的 pr 当基准——读模型会给工序补 mi 下标，
    #    而且绑刀具库要用读模型里的 tdb（state_json 里没有库）。
    baseline = MachiningDFMStore(root, SEED)
    if baseline.project_business:
        print("开关已经开着：这次迁移早就跑完了。要核对请用 tools/rehearse_project_processes.py")
        return 0

    problems: list[str] = []
    backup_path = ""

    # ---------------- 1) 备份 + 归档 ----------------
    with baseline.connect() as db:
        rows = db.execute("SELECT id,name,revision,state_json FROM projects").fetchall()
        db.execute(
            f"CREATE TABLE IF NOT EXISTS {ARCHIVE}("
            "id TEXT PRIMARY KEY,name TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 0,"
            "state_json TEXT NOT NULL,archived_at TEXT NOT NULL)"
        )
    already = {row["id"] for row in read_rows(db_file, f"SELECT id FROM {ARCHIVE}")}
    pending = [row for row in rows if row["id"] not in already]
    if apply and pending:
        backup = baseline._backup(f"pre-project-business-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3")
        backup_path = str(backup)
        print(f"备份          = {backup}")
        # 备份之后重新打开，确保后面每一步都落在有备份的库上
        baseline = MachiningDFMStore(root, SEED)
    elif apply:
        print("备份          = 跳过（归档已有记录，本次没有新项目要迁）")

    before: dict[str, dict] = {}
    for row in rows:
        state = json.loads(row["state_json"])
        # 迁移前的读模型（开关关着 = 走 state_json），这是比对的基准
        read_model = baseline.get(row["id"])["state"]
        general = read_model.get("G") or {}
        selection_json = json.dumps({key: general.get(key) for key in SELECTION_ARRAY_KEYS},
                                    ensure_ascii=False)
        before[row["id"]] = {
            "name": row["name"],
            "revision": int(row["revision"]),
            "pr_json": json.dumps(read_model.get("pr", []), ensure_ascii=False),
            "pr": read_model.get("pr", []),
            "is_json": json.dumps(read_model.get("is", []), ensure_ascii=False),
            "is": read_model.get("is", []),
            "sel_json": selection_json,
            "expected_sel": _selection_expected(general),
            "general": general,
            "state_json": row["state_json"],
            "tools_library": read_model.get("tdb") or [],
            "machines": read_model.get("mdb") or [],
            "tools": [tool for process in read_model.get("pr", []) for tool in (process.get("tl") or [])],
            "process_count": len(read_model.get("pr", [])),
            "issue_count": len(read_model.get("is", [])),
            "selection_count": sum(1 for key in ("fixQ", "insp")
                                   for value in (general.get(key) or []) if str(value or "")),
            "quoted_off": sum(1 for key in ("fixQC", "inspQ")
                              for value in (general.get(key) or []) if value == 0),
            "state": state,
        }

    if pending and apply:
        with baseline.connect() as db:
            for row in pending:
                db.execute(
                    f"INSERT OR REPLACE INTO {ARCHIVE}(id,name,revision,state_json,archived_at) "
                    "VALUES(?,?,?,?,?)",
                    (row["id"], row["name"], int(row["revision"]), row["state_json"], _stamp()),
                )
        print(f"归档          = {len(pending)} 个项目进 {ARCHIVE}（迁移前的 state_json 原样保存）")

    # 2) 开关打开（进程内）：建表 + 拆表。能力级别递增，这一次直接开到 2b（= 3）
    import os
    os.environ["MACHINING_PROJECT_BUSINESS"] = str(SELECTION_VERSION)
    store = MachiningDFMStore(root, SEED)
    assert store.project_business, "工序开关没打开（应该由环境变量打开）"
    assert store.project_issues_enabled, "问题清单开关没打开（环境变量应该给 ≥2）"
    assert store.selections_enabled, "选型报价开关没打开（环境变量应该给 ≥3）"

    # ---------------- 2) 逐项目拆表 ----------------
    print("\n=== 拆表 ===")
    reports: dict[str, dict] = {}
    for row in rows:
        project_id = row["id"]
        payload = before[project_id]
        if not payload["process_count"]:
            print(f"  项目「{payload['name']}」：没有工序，跳过")
            reports[project_id] = {"process_count": 0, "tool_count": 0, "bind": {}, "price_missing": 0,
                                   "skipped": False, "existing_rows": 0}
            continue
        report = apply_split_safe(store, project_id, payload)
        reports[project_id] = report
        label = "已有行，跳过（幂等）" if report.get("skipped") else "已拆"
        print(
            f"  项目「{payload['name']}」：{label}｜原 {payload['process_count']} 道工序 / "
            f"{len(payload['tools'])} 行刀具行 → 表里 "
            f"{store.processes.count(project_id, include_deleted=True)} / "
            f"{store.process_tools.count(project_id, include_deleted=True)} 行"
        )
        bind = report.get("bind", {})
        print(
            f"      绑刀具库：唯一 {bind.get('unique', 0)} · 直径消歧 {bind.get('by_size', 0)} · "
            f"重名未绑 {bind.get('ambiguous', 0)} · 库里没有 {bind.get('missing', 0)}"
            f"｜库里没价（成本按 0）的刀具行 {report.get('price_missing', 0)}"
        )
        if bind.get("ambiguous"):
            names = bind.get("ambiguous_names") or []
            print(f"      ⚠ 重名未绑（留空，等人工或页面上重选）：{'、'.join(names[:5])}")
        missing_machines = report.get("machine_missing") or []
        if missing_machines:
            # 设备列现在是真外键：库里没有这台就写不进去，读模型这一格的 mid 会变空
            print(f"      ⚠ 有 {len(missing_machines)} 道工序的设备在设备库里找不到"
                  f"（外键留空，mid 会变空）：{'、'.join(sorted(set(missing_machines))[:5])}")

    # ---------------- 2b) 问题清单（阶段 2a） ----------------
    # 外键指向工序表，所以必须在工序拆完之后做；按"工序当前名字"绑 process_id。
    print("\n=== 拆问题清单 ===")
    issue_reports: dict[str, dict] = {}
    for row in rows:
        project_id = row["id"]
        payload = before[project_id]
        if not payload["issue_count"]:
            print(f"  项目「{payload['name']}」：没有问题清单，跳过")
            issue_reports[project_id] = {"issues": 0, "linked": 0, "missing": 0, "ambiguous": 0,
                                         "skipped": False, "existing_rows": 0}
            continue
        report = apply_issue_split(
            store.issues, project_id, payload["state"],
            process_rows=store.processes.list_typed(project_id, include_deleted=True),
        )
        issue_reports[project_id] = report
        label = "已有行，跳过（幂等）" if report.get("skipped") else "已拆"
        print(
            f"  项目「{payload['name']}」：{label}｜原 {payload['issue_count']} 条 → 表里 "
            f"{store.issues.count(project_id, include_deleted=True)} 行"
        )
        print(f"      绑工序外键：对上 {report.get('linked', 0)} · 找不到 {report.get('missing', 0)} · "
              f"同名多道未绑 {report.get('ambiguous', 0)}")
        for key, label_ in (("missing_names", "找不到的工序名"), ("ambiguous_names", "同名多道")):
            names = report.get(key) or []
            if names:
                print(f"      ⚠ {label_}（留空 + 只存名字快照，等人工重选）：{'、'.join(names[:5])}")

    # ---------------- 2c) 选型（阶段 2b → 拆成夹具/检具两张项目级表） ----------------
    # 外键指向夹具/检具库与两个类别字典，所以放在最后一道。
    # 数据来源按优先级取：**先看老的多态表**（它才是"表已经落过数据"的权威），
    # 老表这个项目一行都没有，才从旧数组（extra_json 的 fixQ/fixQC/insp/inspQ）拆。
    print("\n=== 拆选型（夹具选型 / 检具选型）===")
    selection_reports: dict[str, dict] = {}
    table_names = {item["name"] for item in
                   read_rows(db_file, "SELECT name FROM sqlite_master WHERE type='table'")}
    has_legacy_selection = LEGACY_SELECTION_TABLE in table_names
    for row in rows:
        project_id = row["id"]
        payload = before[project_id]
        legacy_rows = read_rows(db_file, "SELECT * FROM project_selections WHERE project_id=?",
                                (project_id,)) if has_legacy_selection else []
        if legacy_rows and not store.selections.count(project_id, include_deleted=True):
            report = copy_legacy_rows(store.selections, project_id,
                                     [dict(item) for item in legacy_rows])
            source = f"老表 {len(legacy_rows)} 行按 kind 分表搬过来"
            report.update({"skipped": False, "bound": 0, "missing": 0, "ambiguous": 0})
        else:
            report = apply_selection_split(
                store.selections, project_id, payload["general"],
                categories=store._selection_categories(),
                library=store._selection_library(),
            )
            source = ("两张新表里已有行，跳过（幂等）" if report.get("skipped")
                      else "从旧数组拆（每个类别一格）")
        selection_reports[project_id] = report
        print(
            f"  项目「{payload['name']}」：{source}｜旧数组里选中的格子 "
            f"{payload['selection_count']}（其中关掉报价的 {payload['quoted_off']} 格）→ "
            f"夹具 {store.selections.fixtures.count(project_id, include_deleted=True)} 行 · "
            f"检具 {store.selections.gauges.count(project_id, include_deleted=True)} 行"
        )
        if report.get("bound") or report.get("missing") or report.get("ambiguous"):
            print(f"      绑夹具/检具库：唯一对上 {report.get('bound', 0)} · "
                  f"库里没有 {report.get('missing', 0)} · 同名多条未绑 {report.get('ambiguous', 0)}")
        for line in (report.get("details") or [])[:6]:
            print(f"      ⚠ {line}")

    # ---------------- 3) 写开关 ----------------
    print("\n=== 开关 ===")
    if apply:
        with store.connect() as db:
            db.execute(
                "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
                (BUSINESS_VERSION_KEY, str(SELECTION_VERSION), _stamp()),
            )
        print(f"  已写 {BUSINESS_VERSION_KEY} = {SELECTION_VERSION}"
              "（工序 + 问题清单 + 选型报价从此都走表）")
    else:
        print("  干跑：不写版本键（副本上写了也无所谓，下面验证时直接用它）")

    # ---------------- 4) 打开开关后逐字节验证 ----------------
    print("\n=== 验证（重新打开 store，只靠版本键启用）===")
    if not apply:
        with store.connect() as db:
            db.execute(
                "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
                (BUSINESS_VERSION_KEY, str(SELECTION_VERSION), _stamp()),
            )
    import os as _os
    _os.environ.pop("MACHINING_PROJECT_BUSINESS", None)
    reopened = MachiningDFMStore(root, SEED)
    if not reopened.project_business:
        problems.append("重新打开后开关没打开（版本键没生效）")
    for project_id, payload in before.items():
        record = reopened.get(project_id)
        after_json = json.dumps(record["state"].get("pr", []), ensure_ascii=False)
        if after_json == payload["pr_json"]:
            print(f"  项目「{payload['name']}」：√ pr[] 与迁移前逐字节相同"
                  f"（{len(after_json.encode('utf-8'))} 字节，含键序）")
        else:
            problems.append(f"项目 {payload['name']}：pr[] 字节不一致")
            print(f"  项目「{payload['name']}」：× pr[] 字节不同 "
                  f"（迁移前 {len(payload['pr_json'].encode('utf-8'))} → 现在 {len(after_json.encode('utf-8'))} 字节）")
            problems += diff_pr(payload["pr"], record["state"].get("pr", []))
        if payload["process_count"]:
            got = reopened.processes.count(project_id, include_deleted=True)
            if got != payload["process_count"]:
                problems.append(f"项目 {payload['name']}：工序行数 {payload['process_count']} → {got}")
            # "表是唯一权威"要证明，但**不能**在线上库上动手：
            # 直接问一句"光凭两张表能不能还原出迁移前的 pr"就够了。
            from app.machining_process import legacy_processes

            from_tables = legacy_processes(
                reopened.processes, reopened.process_tools, project_id,
                asset_store=reopened.assets, inline_assets=False,
            )
            # 比的时候要忽略 mi：它不是表里的数据，而是读模型每次按"设备库里的位置"现算的
            # （口径 5：派生字段不落库），所以两张表本来就不负责还原它。
            if _strip_mi(from_tables) != _strip_mi(payload["pr"]):
                problems.append(f"项目 {payload['name']}：只凭两张表还原不出迁移前的 pr")
            else:
                print("      √ 只凭两张表就能完整还原 pr（表是唯一权威，不用看 state_json）")
            if not apply:
                # 干跑（副本）上可以再做个更狠的证明：把 state_json.pr 清掉，读模型必须不变
                with reopened.connect() as db:
                    db.execute("UPDATE projects SET state_json=? WHERE id=?",
                               (_compact_without_pr(payload["state_json"]), project_id))
                probe = reopened.get(project_id)["state"].get("pr", [])
                if json.dumps(probe, ensure_ascii=False) != payload["pr_json"]:
                    problems.append(f"项目 {payload['name']}：清掉 state_json.pr 后读模型变了")
                else:
                    print("      √ （副本上）把 state_json.pr 清掉后读模型依旧")

        # ---- 问题清单：与 pr 同一套证明方式 ----
        after_issues = json.dumps(record["state"].get("is", []), ensure_ascii=False)
        if after_issues == payload["is_json"]:
            print(f"      √ is[] 与迁移前逐字节相同（{len(after_issues.encode('utf-8'))} 字节，含键序）")
        else:
            problems.append(f"项目 {payload['name']}：is[] 字节不一致")
            print(f"      × is[] 字节不同（迁移前 {len(payload['is_json'].encode('utf-8'))} → "
                  f"现在 {len(after_issues.encode('utf-8'))} 字节）")
        if payload["issue_count"]:
            got = reopened.issues.count(project_id, include_deleted=True)
            if got != payload["issue_count"]:
                problems.append(f"项目 {payload['name']}：问题清单行数 {payload['issue_count']} → {got}")
            from_tables_is = legacy_issues(
                reopened.issues, project_id,
                process_rows=reopened.processes.list_typed(project_id, include_deleted=True),
                asset_store=reopened.assets,
            )
            if json.dumps(from_tables_is, ensure_ascii=False) != payload["is_json"]:
                problems.append(f"项目 {payload['name']}：只凭问题清单表还原不出迁移前的 is")
            else:
                print("      √ 只凭问题清单表就能完整还原 is（表是唯一权威）")
            if not apply:
                with reopened.connect() as db:
                    current = db.execute(
                        "SELECT state_json FROM projects WHERE id=?", (project_id,)
                    ).fetchone()[0]
                    db.execute("UPDATE projects SET state_json=? WHERE id=?",
                               (_compact_without(current, "is"), project_id))
                probe_is = reopened.get(project_id)["state"].get("is", [])
                if json.dumps(probe_is, ensure_ascii=False) != payload["is_json"]:
                    problems.append(f"项目 {payload['name']}：清掉 state_json.is 后读模型变了")
                else:
                    print("      √ （副本上）把 state_json.is 清掉后读模型依旧")

        # ---- 选型报价：四个数组（选型 + 是否报价）与 pr/is 同一套证明方式 ----
        # 注意这里比的是"页面看到的值"：老项目可能压根没有这四个键（页面自己补默认值），
        # 迁移后变成"全空串 / 全 1"的默认数组，页面上完全一样，不算差异。
        after_general = record["state"].get("G") or {}
        after_sel = {key: after_general.get(key) for key in SELECTION_ARRAY_KEYS}
        expected_sel = payload["expected_sel"]
        diff = _selection_problems(expected_sel, after_sel)
        if not diff:
            text = json.dumps(after_sel, ensure_ascii=False)
            print(f"      √ 选型四个数组与迁移前一致（{len(text.encode('utf-8'))} 字节，含键序）")
            if any(expected_sel.get(key) is None for key in SELECTION_ARRAY_KEYS):
                print("        （旧数据没有的键，迁移后按页面默认值补成了空串/1，页面看到的值不变）")
        else:
            problems.append(f"项目 {payload['name']}：选型四个数组与迁移前不一致")
            print(f"      × 选型四个数组对不上：\n          - " + "\n          - ".join(diff))
        from_tables_sel = legacy_selection_arrays(
            reopened.selections, project_id,
            categories=reopened._selection_categories(),
            library=reopened._selection_library(),
        )
        if _selection_problems(expected_sel, dict(from_tables_sel or {})):
            problems.append(f"项目 {payload['name']}：只凭选型表还原不出迁移前的四个数组")
            print(f"        （只凭表还原出来的是："
                  f"{json.dumps(from_tables_sel, ensure_ascii=False)}）")
        else:
            print("      √ 只凭选型表就能完整还原选型与报价勾选（表是唯一权威）")
        if not apply:
            # 再狠一点：把 extra_json 里那四个键清掉，读模型必须不变
            with reopened.connect() as db:
                current_extra = db.execute(
                    "SELECT extra_json FROM project_settings WHERE project_id=?", (project_id,)
                ).fetchone()
                if current_extra is not None:
                    stripped = json.loads(current_extra[0] or "{}")
                    for key in SELECTION_ARRAY_KEYS:
                        stripped.pop(key, None)
                    db.execute(
                        "UPDATE project_settings SET extra_json=? WHERE project_id=?",
                        (json.dumps(stripped, ensure_ascii=False, separators=(",", ":")), project_id),
                    )
            probe_general = (reopened.get(project_id)["state"].get("G") or {})
            probe_sel = {key: probe_general.get(key) for key in SELECTION_ARRAY_KEYS}
            if _selection_problems(expected_sel, probe_sel):
                problems.append(f"项目 {payload['name']}：清掉 extra_json 里的选型后读模型变了")
            else:
                print("      √ （副本上）把 extra_json 里的四个旧数组清掉后读模型依旧")

    # ---------------- 5) 成本基线 ----------------
    # 基线是给**线上那一个项目**录的指纹；只有被测数据集确实是那个项目时才比，
    # 否则（比如在临时副本上做别的数据）会拿不同数据比出假差异。
    print("\n=== 成本基线 ===")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else None
    if baseline is None:
        print("  （没有基线文件，跳过）")
    else:
        identity = baseline.get("project") or {}
        match_id = identity.get("id") in before
        if not match_id:
            print(f"  跳过：基线录的项目是「{identity.get('name') or identity.get('id')}」，"
                  f"这次迁的不是它")
        else:
            payload = before[identity["id"]]
            totals = baseline.get("totals", {})
            rows_now = [tool for process in reopened.get(identity["id"])["state"].get("pr", [])
                        for tool in (process.get("tl") or [])]
            checks = (
                ("process_count", totals.get("process_count"), payload["process_count"]),
                ("tool_row_count", totals.get("tool_row_count"), len(rows_now)),
            )
            for label, expected, actual in checks:
                if expected is None:
                    continue
                same = expected == actual
                print(f"  {'√' if same else '×'} {label}：基线 {expected} → 现在 {actual}")
                if not same:
                    problems.append(f"成本基线 {label} 变了：{expected} → {actual}")

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
        print("√ 迁移完成：pr[]/is[] 逐字节不变，读模型已走表（开关已打开）")
        if backup_path:
            print(f"  备份：{backup_path}")
    else:
        print("√ 干跑通过：可以放心执行 --apply")
        print("  提示：干跑副本" + ("保留在 " + str(root) if keep else "已删除"))
    return 0


def apply_split_safe(store: MachiningDFMStore, project_id: str, payload: dict) -> dict:
    """拆表：刀具库/设备库用**读模型**里的（state_json 里没有库）。"""
    from app.machining_process import apply_split

    return apply_split(
        store.processes, store.process_tools, project_id, payload["state"],
        tools_library=payload.get("tools_library") or [],
        machines=payload.get("machines") or [],
    )


def _strip_mi(rows: list | None) -> list:
    """把工序行里的 ``mi`` 去掉：它是读模型按下标现算的派生值，不是表里的数据。"""
    return [{key: value for key, value in row.items() if key != "mi"}
            for row in (rows or []) if isinstance(row, dict)]


def diff_pr(old_rows: list, new_rows: list) -> list[str]:
    problems: list[str] = []
    if len(old_rows) != len(new_rows):
        problems.append(f"工序数量 {len(old_rows)} → {len(new_rows)}")
    for index, (old, new) in enumerate(zip(old_rows, new_rows)):
        if list(old) != list(new):
            problems.append(f"工序 {index} 键序不同")
        for key in old:
            if key == "tl":
                for position, (old_tool, new_tool) in enumerate(zip(old["tl"], new["tl"])):
                    for tool_key in old_tool:
                        if old_tool[tool_key] != new_tool.get(tool_key):
                            problems.append(
                                f"工序 {index} 刀具行 {position}.{tool_key}: "
                                f"{old_tool[tool_key]!r} → {new_tool.get(tool_key)!r}"
                            )
                continue
            if old[key] != new.get(key):
                problems.append(f"工序 {index}.{key}: {old[key]!r} → {new.get(key)!r}")
    return problems


def _compact_without(state_json: str, key: str) -> str:
    """去掉 ``state_json`` 里的某个数组再压缩（干跑时的"表是唯一权威"硬证明用）。"""
    state = json.loads(state_json)
    state.pop(key, None)
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def _compact_without_pr(state_json: str) -> str:
    return _compact_without(state_json, "pr")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正迁移线上库（默认只干跑）")
    parser.add_argument("--keep", action="store_true", help="干跑后保留临时副本")
    parser.add_argument("--status", action="store_true", help="只读：打印当前迁移状态")
    parser.add_argument("--from", dest="source", default="", help="要迁移的数据目录（默认线上目录）")
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

    work = Path(tempfile.mkdtemp(prefix="machining-process-migrate-"))
    target = work / "machining_dfm"
    try:
        shutil.copytree(source, target)
        if LIVE in target.parents or target == LIVE:
            print("拒绝在线上目录上干跑")
            return 2
        print("\n" + "=" * 72)
        print(f"干跑（副本：{target}）")
        print("=" * 72)
        code = migrate(target, apply=False, keep=args.keep)
        return code
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
