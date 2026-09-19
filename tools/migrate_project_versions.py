"""版本履历落表迁移工具（阶段 3a）。

阶段 3a 把项目上**两套互不相干的"版本"**合并进 ``project_versions`` 一张表：

* 旧 ``revisions`` 表（每次保存一行全量快照，线上 60 行）→ ``kind='save'``；
* ``projects.state_json.vh[]``（页面上「版本履历」的行）→ ``kind='history'``。

**默认是干跑**：把线上库整个复制到临时目录，在副本上跑完整迁移并逐字节核对，最后把副本删掉
（``--keep`` 可保留）。只有加 ``--apply`` 才会动线上库，而且动之前先整库备份。

前置：阶段 1b/2a/2b（``tools/migrate_project_processes.py``）必须已经迁完——
版本编号是递增的能力级别（1 工序 / 2 问题清单 / 3 选型报价 / **4 版本履历**）。
干跑遇到前置没迁的副本时，会**先在副本上把 1b/2a/2b 跑一遍**再跑 3a，
所以今天就能在真实数据上端到端演练"0 → 4"；``--apply`` 不会替你补前面的阶段。

迁移顺序（每一步都可重复执行）：

1. 前置检查：``saved`` 用的表在不在、版本键到没到 3；
2. 体检（**写任何数据之前**）：``state_json`` 是不是合法 JSON、``vh`` 是不是数组、
   每条履历是不是对象、每个旧快照是不是合法 JSON —— 有一样不对就**拒绝迁移**，
   绝不替人猜、更不静默丢；
3. 整库备份 → ``backups/pre-project-versions-<时间戳>.sqlite3``（``--apply`` 才写）；
4. 逐项目 ``apply_history_split``：``revisions`` 行原样搬进 ``kind='save'``；
   ``state_json.vh[]`` 按下标进 ``kind='history'``（行 id 用 ``<项目 id>-h<下标>``，幂等）；
5. 写 ``app_settings.project_business_version = 4``（等于"开关打开"，写在最后）；
6. 重新打开 store（不带环境变量，纯靠版本键）验证：

   * ``GET /versions`` 的列表与迁移前 ``revisions`` **完全一致**（版本号/名字/时间）；
   * 随便挑几版 ``?revision=N``：还原出来的 ``state_json`` 与旧 ``revisions`` 逐字节相同；
   * ``vh[]`` 与迁移前逐字节相同（含键序）；只凭 ``project_versions`` 也能还原出同样的 ``vh``；
   * 每份保存版本的快照与 ``revisions`` 里那一行逐字节相同（影子副本对得上，回滚无损）；
   * ``PRAGMA foreign_key_check`` 干净。

用法：
    python tools/migrate_project_versions.py                  # 干跑（副本，不动线上）
    python tools/migrate_project_versions.py --keep            # 干跑并保留副本目录
    python tools/migrate_project_versions.py --apply           # 真正迁移（先备份）
    python tools/migrate_project_versions.py --status          # 只读：现在迁到哪一步了
"""

from __future__ import annotations

import argparse
import importlib.util
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
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover - 老解释器/被重定向
    pass

from app.machining_dfm import MachiningDFMStore  # noqa: E402
from app.machining_history import (  # noqa: E402
    HISTORY_TABLE,
    HISTORY_VERSION,
    apply_history_split,
    history_preflight,
    legacy_history,
    version_listing,
)
from app.machining_process import BUSINESS_VERSION_KEY  # noqa: E402
from app.machining_selection import SELECTION_VERSION  # noqa: E402

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"


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
    """只读：开关、表、行数。"""
    db_file = root / "machining_dfm.sqlite3"
    info: dict = {"root": str(root), "db": db_file.is_file(), "tables": [], "version": None,
                  "projects": 0, "revisions": 0, "saved": 0, "history": 0, "history_live": 0}
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
    if "revisions" in info["tables"]:
        info["revisions"] = read_rows(db_file, "SELECT COUNT(*) AS n FROM revisions")[0]["n"]
    if HISTORY_TABLE in info["tables"]:
        info["saved"] = read_rows(
            db_file, f"SELECT COUNT(*) AS n FROM {HISTORY_TABLE} WHERE kind='save'")[0]["n"]
        info["history"] = read_rows(
            db_file, f"SELECT COUNT(*) AS n FROM {HISTORY_TABLE} WHERE kind='history'")[0]["n"]
        info["history_live"] = read_rows(
            db_file, f"SELECT COUNT(*) AS n FROM {HISTORY_TABLE} "
                     "WHERE kind='history' AND deleted_at IS NULL")[0]["n"]
    return info


def print_status(info: dict) -> None:
    has_business = "project_processes" in info["tables"]
    has_history = HISTORY_TABLE in info["tables"]
    print(f"数据目录      = {info['root']}")
    print(f"库文件        = {'有' if info['db'] else '没有'}")
    print(f"开关(版本键)  = {BUSINESS_VERSION_KEY} → {info['version']!r}"
          f"（1 工序 / 2 问题清单 / 3 选型报价 / 4 版本履历）")
    print(f"前置(1b~2b)   = {'已迁（工序等表在）' if has_business else '未迁（先跑 migrate_project_processes.py）'}")
    print(f"revisions 表  = {'有' if 'revisions' in info['tables'] else '无'}（{info['revisions']} 行）")
    print(f"版本履历表    = {'有' if has_history else '无'}"
          f"（保存版本 {info['saved']} 行 / 履历 {info['history']} 行，其中在用 {info['history_live']} 行）")
    print(f"项目数        = {info['projects']}")
    version = info["version"] if isinstance(info["version"], int) else 0
    if version >= HISTORY_VERSION and has_history:
        print("状态          = 阶段 3a 已迁移（保存版本 + 版本履历都在 project_versions）")
    elif has_history:
        print("状态          = 表在、但版本键还停在 3（读模型仍走 revisions / state_json.vh）")
    elif version >= SELECTION_VERSION:
        print("状态          = 前置已就绪，阶段 3a 未迁移（跑本工具即可）")
    print("（本阶段只搬数据，不改读模型口径：保存版本与版本履历合成一张表，用 kind 分开）")


def migrate(root: Path, *, apply: bool, keep: bool) -> int:
    """在 ``root`` 上跑迁移。``apply=False`` 时调用方已经把副本准备好了。"""
    db_file = root / "machining_dfm.sqlite3"
    if not db_file.is_file():
        print("没有找到库：", db_file)
        return 2

    info = status(root)
    version = info["version"] if isinstance(info["version"], int) else 0
    if version < SELECTION_VERSION:
        print(f"\n前置没就绪：版本键还停在 {info['version']!r}，先跑")
        print("  python tools/migrate_project_processes.py --apply   （阶段 1b+2a+2b）")
        print("再回来跑本工具。干跑（不带 --apply）会自动在副本上先把前置跑一遍。")
        return 2

    baseline = MachiningDFMStore(root, SEED)
    if baseline.history_enabled:
        print("开关已经开着（版本键 ≥ 4）：阶段 3a 早就跑完了。")
        return 0
    if baseline.business_version < SELECTION_VERSION:
        print(f"⚠ 进程内看到的版本是 {baseline.business_version}，与库里的键不一致，先确认环境变量")
        return 2

    # ---------------- 1) 体检（写数据之前） ----------------
    with baseline.connect() as db:
        projects = db.execute("SELECT id,name,revision,state_json FROM projects").fetchall()
        # 老库才有这张表；已经清过旧副本的库没有（那种库其实也没什么可搬的）
        revisions = db.execute(
            "SELECT project_id,revision,name,state_json,created FROM revisions ORDER BY project_id,revision"
        ).fetchall() if "revisions" in info["tables"] else []
    if "revisions" not in info["tables"]:
        print("  提示：库里没有旧 ``revisions`` 表（旧副本已清理），这一趟只搬 state_json.vh")
    by_project: dict[str, list[sqlite3.Row]] = {}
    for row in revisions:
        by_project.setdefault(row["project_id"], []).append(row)
    payloads = [
        {"id": row["id"], "name": row["name"], "state_json": row["state_json"],
         "revisions": by_project.get(row["id"], [])}
        for row in projects
    ]
    print("\n=== 体检（写数据之前）===")
    print(f"  项目 {len(payloads)} 个｜revisions 共 {len(revisions)} 行")
    vh_total = 0
    for payload in payloads:
        try:
            state = json.loads(payload["state_json"] or "{}")
        except ValueError:
            continue
        rows = state.get("vh")
        vh_total += len(rows) if isinstance(rows, list) else 0
    print(f"  state_json.vh 共 {vh_total} 条")
    problems = history_preflight(payloads)
    if problems:
        print("  × 体检不通过（**没有写任何数据**）：")
        for item in problems[:20]:
            print("    -", item)
        print("\n这些人要先人工确认怎么处理，迁移不会替人猜。")
        return 1
    print("  √ 体检通过：旧数据形态都能原样搬进表")

    # 抽几版，把**开关关着时**的读模型记下来当基准：迁移后必须一模一样。
    # （这里只在副本/线上读，不改数据；历史上线后 pr/is 走表是 1b/2a 的口径，
    #   所以比的是 vh 这一路，以及 ?revision=N 能正常打开。）
    picks: dict[str, list[tuple[int, str]]] = {}
    for payload in payloads:
        rows = sorted(payload["revisions"], key=lambda item: int(item["revision"]))
        positions = sorted({0, len(rows) // 2, len(rows) - 1})
        collected: list[tuple[int, str]] = []
        for position in positions:
            if not rows:
                break
            revision = int(rows[position]["revision"])
            state = baseline.get(payload["id"], revision)["state"]
            collected.append((revision, json.dumps(state.get("vh", []), ensure_ascii=False)))
        picks[payload["id"]] = collected

    # ---------------- 2) 备份 ----------------
    backup_path = ""
    if apply:
        backup = baseline._backup(
            f"pre-project-versions-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3")
        backup_path = str(backup)
        print(f"\n备份          = {backup}")
        baseline = MachiningDFMStore(root, SEED)

    # ---------------- 3) 开关打开（进程内）：建表 ----------------
    import os
    os.environ["MACHINING_PROJECT_BUSINESS"] = str(HISTORY_VERSION)
    store = MachiningDFMStore(root, SEED)
    assert store.history_enabled, "版本履历开关没打开（环境变量应该给 ≥4）"

    # ---------------- 4) 逐项目搬 ----------------
    print("\n=== 搬版本数据 ===")
    reports: dict[str, dict] = {}
    for payload in payloads:
        project_id = payload["id"]
        report = apply_history_split(store.version_table, project_id,
                                     json.loads(payload["state_json"] or "{}"),
                                     revisions=payload["revisions"])
        reports[project_id] = report
        label = "表里已有行，跳过（幂等）" if report.get("skipped") else "已搬"
        print(f"  项目「{payload['name']}」：{label}｜旧 revisions {len(payload['revisions'])} 行 / "
              f"旧 vh {len(json.loads(payload['state_json'] or '{}').get('vh') or [])} 条 → 表里 "
              f"{len(store.version_table.save_rows(project_id))} 个保存版本 + "
              f"{len(store.version_table.history_rows(project_id))} 行履历")
        if report.get("extras"):
            print(f"      ⚠ 有 {report['extras']} 行履历带登记表以外的键，已原样存进 extra_json 兜底列")

    # ---------------- 5) 写开关 ----------------
    print("\n=== 开关 ===")
    with store.connect() as db:
        db.execute(
            "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
            (BUSINESS_VERSION_KEY, str(HISTORY_VERSION), _stamp()),
        )
    print(f"  已写 {BUSINESS_VERSION_KEY} = {HISTORY_VERSION}"
          "（保存版本 + 版本履历从此都走 project_versions）")

    # ---------------- 6) 打开开关后逐字节验证 ----------------
    print("\n=== 验证（重新打开 store，只靠版本键启用）===")
    os.environ.pop("MACHINING_PROJECT_BUSINESS", None)
    reopened = MachiningDFMStore(root, SEED)
    if not reopened.history_enabled:
        problems.append("重新打开后开关没打开（版本键没生效）")

    for payload in payloads:
        project_id = payload["id"]
        label = f"项目「{payload['name']}」"
        old_revisions = payload["revisions"]
        listing = version_listing(reopened.version_table, project_id)
        wanted = [
            {"revision": int(row["revision"]), "name": str(row["name"] or ""),
             "created": str(row["created"] or "")}
            for row in sorted(old_revisions, key=lambda item: -int(item["revision"]))
        ]
        got = [{key: item[key] for key in ("revision", "name", "created")} for item in listing]
        if got == wanted:
            print(f"  {label}：√ 保存版本列表与迁移前的 revisions 完全一致（{len(got)} 个版本）")
        else:
            problems.append(f"{label}：保存版本列表与 revisions 不一致")
            print(f"  {label}：× 保存版本列表对不上（旧 {len(wanted)} → 新 {len(got)}）")
            for old_item, new_item in zip(wanted, got):
                if old_item != new_item:
                    print(f"      {old_item} → {new_item}")

        # 每份快照逐字节相同（影子副本对得上 → 回滚无损）
        mismatched = 0
        with reopened.connect() as db:
            for row in old_revisions:
                now = db.execute(
                    f"SELECT state_json AS s FROM {HISTORY_TABLE} WHERE project_id=? AND kind='save' AND revision=?",
                    (project_id, int(row["revision"])),
                ).fetchone()
                if now is None or now["s"] != row["state_json"]:
                    mismatched += 1
        if mismatched:
            problems.append(f"{label}：有 {mismatched} 份保存版本的快照与 revisions 不一致")
        else:
            print(f"      √ {len(old_revisions)} 份保存版本快照与 revisions 逐字节相同（回滚无损）")

        # 抽几版验证 ?revision=N：能打开，而且 vh[] 与"开关关着时"的读模型一致
        for revision, vh_before_rev in picks.get(project_id, []):
            try:
                record = reopened.get(project_id, int(revision))
            except Exception as error:  # noqa: BLE001 - 报出来比 500 好
                problems.append(f"{label}：第 {revision} 版打不开（{error}）")
                continue
            vh_rev = json.dumps(record["state"].get("vh", []), ensure_ascii=False)
            if vh_rev == vh_before_rev:
                print(f"      √ 第 {revision} 版 ?revision= 的 vh[] 与迁移前一致")
            else:
                problems.append(f"{label}：第 {revision} 版 vh[] 与迁移前不一致")
                print(f"      × 第 {revision} 版 vh[]：{vh_before_rev[:80]} → {vh_rev[:80]}")

        # vh[]：与迁移前逐字节相同 + 只凭表也能还原
        state_before = json.loads(payload["state_json"] or "{}")
        vh_before = json.dumps(state_before.get("vh", []), ensure_ascii=False)
        vh_now = json.dumps(reopened.get(project_id)["state"].get("vh", []), ensure_ascii=False)
        if vh_now == vh_before:
            print(f"      √ vh[] 与迁移前逐字节相同（{len(vh_now.encode('utf-8'))} 字节，含键序）")
        else:
            problems.append(f"{label}：vh[] 字节不一致")
            print(f"      × vh[] 字节不同：{vh_before[:120]} → {vh_now[:120]}")
        from_tables = legacy_history(reopened.version_table, project_id)
        # 注意：老项目 vh 本来就空的时候，迁移出来也是 0 行履历 —— 这时 legacy_history 返回 None
        # （表的权威信号是"有没有履历行"，没有就回退 state_json）是**正确**的，不是问题。
        # 只有"老数据里明明有履历、迁完却读不到"才算问题。
        if not state_before.get("vh"):
            if from_tables is None:
                print("      √ 老 vh 本来是空的：表里 0 行履历，读模型按设计回退 state_json.vh")
            elif json.dumps(from_tables, ensure_ascii=False) != vh_before:
                problems.append(f"{label}：老 vh 是空的，表里却还原出了别的履历")
            else:
                print("      √ 老 vh 是空的：表里 0 行履历，还原结果同样是空")
        elif from_tables is None:
            problems.append(f"{label}：表里没有履历行，读模型仍在回退 state_json")
        elif json.dumps(from_tables, ensure_ascii=False) != vh_before:
            problems.append(f"{label}：只凭 project_versions 还原不出迁移前的 vh")
        else:
            print("      √ 只凭 project_versions 就能完整还原 vh（表是唯一权威）")

        if not apply and state_before.get("vh"):
            # 干跑（副本）上的硬证明：把 state_json.vh 清掉，读模型必须不变
            with reopened.connect() as db:
                stripped = dict(state_before)
                stripped.pop("vh", None)
                db.execute("UPDATE projects SET state_json=? WHERE id=?",
                           (json.dumps(stripped, ensure_ascii=False, separators=(",", ":")), project_id))
            probe = json.dumps(reopened.get(project_id)["state"].get("vh", []), ensure_ascii=False)
            if probe != vh_before:
                problems.append(f"{label}：清掉 state_json.vh 后读模型变了")
            else:
                print("      √ （副本上）把 state_json.vh 清掉后读模型依旧")

    # ---------------- 7) 外键体检 ----------------
    print("\n=== 外键体检 ===")
    with reopened.connect() as db:
        dirty = db.execute("PRAGMA foreign_key_check").fetchall()
        saved = db.execute(
            f"SELECT COUNT(*) AS n FROM {HISTORY_TABLE} WHERE kind='save'").fetchone()["n"]
        history = db.execute(
            f"SELECT COUNT(*) AS n FROM {HISTORY_TABLE} WHERE kind='history'").fetchone()["n"]
        orphan = db.execute(
            f"SELECT COUNT(*) AS n FROM {HISTORY_TABLE} v "
            "LEFT JOIN projects p ON p.id=v.project_id WHERE p.id IS NULL").fetchone()["n"]
    print(f"  project_versions = 保存版本 {saved} 行 + 履历 {history} 行")
    print(f"  PRAGMA foreign_key_check = {'干净' if not dirty else dirty[:3]}")
    print(f"  悬空的 project_id = {orphan}")
    if dirty:
        problems.append("外键体检不干净")
    if orphan:
        problems.append(f"有 {orphan} 行的 project_id 指向不存在的项目")

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
        print("√ 迁移完成：保存版本 + 版本履历都在 project_versions，读模型与迁移前一致")
        if backup_path:
            print(f"  备份：{backup_path}")
        print("  回滚：把 app_settings.project_business_version 改回 3（revisions 表还是影子副本，"
              "一行都没少）")
    else:
        print("√ 干跑通过：可以放心执行 --apply")
        print("  提示：干跑副本" + ("保留在 " + str(root) if keep else "已删除"))
    return 0


def _business_module():
    """把同目录的 migrate_project_processes.py 当模块加载（tools 不是包）。"""
    path = Path(__file__).with_name("migrate_project_processes.py")
    spec = importlib.util.spec_from_file_location("migrate_project_processes", path)
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
                        help="干跑时不自动补跑 1b/2a/2b（前置没迁就直接失败）")
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

    work = Path(tempfile.mkdtemp(prefix="machining-versions-migrate-"))
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
        if version < SELECTION_VERSION:
            if args.skip_prerequisite:
                print(f"前置没迁（版本键 {info['version']!r}），而且指定了 --skip-prerequisite")
                return 2
            print("\n前置（1b/2a/2b）还没迁：先在**副本**上把它跑一遍，"
                  "好让这次干跑覆盖 0 → 4 的完整链路")
            print("-" * 72)
            code = _business_module().migrate(target, apply=False, keep=True)
            print("-" * 72)
            if code != 0:
                print("× 前置迁移在副本上就没通过：先解决它，再看阶段 3a")
                return code
        return migrate(target, apply=False, keep=args.keep)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
