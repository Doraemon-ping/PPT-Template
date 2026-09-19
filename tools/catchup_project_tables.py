# -*- coding: utf-8 -*-
"""补迁：把"表空、JSON 满"的项目（另存为出来的副本等）搬进各域的表。

背景（口径 7）：`POST /projects` 过去只把整份读模型写进 `projects.state_json`，
业务表一行都不建 —— 于是"另存为新项目"出来的项目永远是双存储形态：读模型走 JSON，
页面上那些工序行**没有行 id**，行级保存无从下手。新代码已经把"新建项目"这条路补上
（`create(..., import_tables=True)`），本工具负责把**已经存在的**这种项目补迁过来。

判据（每个项目独立判断，逐域幂等）：
* 这一域的表里没有行，而 JSON 里有数据 → 拆进表；
* 表里已经有行 → 那一域一个字都不动（口径 2：不做物理删除、不先清空再灌）；
* 全部拆完，`projects.state_json` 变成 `{}`（不留影子副本）。

核对：读模型里**原有字段一个都不能丢**；只允许补上派生/默认值
（`_ct/_vc/_vf/_fz` 读时算的、`cat/hld/acc/fi` 刀具库绑定结果、`cI/eqP/fixP` 工序空槽位）。

用法：
    python tools/catchup_project_tables.py            # 干跑（副本上，打印逐字段核对）
    python tools/catchup_project_tables.py --status    # 只读：哪些项目还是"表空 JSON 满"
    python tools/catchup_project_tables.py --apply     # 真搬线上库（先整库备份）
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

LIVE = (ROOT / "data" / "machining_dfm").resolve()
SEED = ROOT / "app" / "resources" / "machining_dfm_seed"

#: 各域 → (表名, 读模型里对应的键)
DOMAINS: tuple[tuple[str, str, str], ...] = (
    ("processes", "project_processes", "pr"),
    ("issues", "project_issues", "is"),
    ("history", "project_versions", "vh"),
)

#: 允许"多出来"的字段：派生值 + 库绑定结果 + 空槽位（拆表后会补上，老路不补）
DERIVED_KEYS = {"_ct", "_vc", "_vf", "_fz", "cat", "hld", "acc", "fi", "cI", "eqP", "fixP"}


def table_names(root: Path) -> set[str]:
    db_file = root / "machining_dfm.sqlite3"
    if not db_file.is_file():
        return set()
    with sqlite3.connect(f"file:{db_file}?mode=ro", uri=True) as db:
        return {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}


def project_shape(store: MachiningDFMStore, project_id: str, tables: set[str]) -> dict[str, int]:
    """这个项目各域表里有多少行。"""
    shape: dict[str, int] = {}
    with store.connect() as db:
        for label, table, _key in DOMAINS:
            if table not in tables:
                shape[label] = 0
                continue
            if table == "project_versions":
                sql = f"SELECT COUNT(*) FROM {table} WHERE project_id=? AND kind='history'"
            else:
                sql = f"SELECT COUNT(*) FROM {table} WHERE project_id=?"
            shape[label] = db.execute(sql, (project_id,)).fetchone()[0]
        for label, table in (("fixtures", "project_fixtures"), ("gauges", "project_gauges")):
            shape[label] = db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project_id,)
            ).fetchone()[0] if table in tables else 0
    return shape


def pending_projects(store: MachiningDFMStore, tables: set[str]) -> list[dict]:
    """哪些项目"表空、JSON 满"（按域给明细）。"""
    pending: list[dict] = []
    for item in store.list():
        project_id = item["id"]
        state = store.get(project_id, allow_archived=True)["state"]
        counts = project_shape(store, project_id, tables)
        general = state.get("G") or {}
        wants: dict[str, bool] = {
            "processes": bool(state.get("pr")) and counts["processes"] == 0,
            "issues": bool(state.get("is")) and counts["issues"] == 0,
            "history": bool(state.get("vh")) and counts["history"] == 0,
            "selections": any(str(value or "").strip() for key in
                              ("fixQ", "fixQC", "insp", "inspQ")
                              for value in (general.get(key) or [])) and counts["fixtures"] == 0,
        }
        if any(wants.values()):
            pending.append({"id": project_id, "name": item["name"], "wants": wants,
                            "counts": counts, "state": state})
    return pending


def print_status(store: MachiningDFMStore, tables: set[str]) -> list[dict]:
    print("数据目录      =", store.root)
    print("库文件        = 有（%d 张表）" % len(tables))
    print("项目数        =", len(store.list()))
    pending = pending_projects(store, tables)
    if not pending:
        print("状态          = 全部项目都已经落表（没有「表空、JSON 满」的项目）")
        return pending
    print("状态          = 有 %d 个项目需要补迁：" % len(pending))
    for item in pending:
        wanted = "、".join(label for label, flag in item["wants"].items() if flag)
        print(f"  {item['id'][:8]}「{item['name'][:34]}」要补：{wanted}"
              f"｜表里已有：{item['counts']}")
    return pending


def compare(before, after, path: str, problems: list[str]) -> None:
    """核对读模型：原有字段一个都不能丢，只允许多出派生/默认值。"""
    if isinstance(before, dict):
        for key, value in before.items():
            if key not in after:
                problems.append(f"{path}.{key} 补迁后丢了")
                continue
            compare(value, after[key], f"{path}.{key}", problems)
        for key in after:
            if key not in before and key not in DERIVED_KEYS:
                problems.append(f"{path}.{key} 补迁后凭空多出来（不是派生/默认值）")
    elif isinstance(before, list):
        if len(before) != len(after):
            problems.append(f"{path} 行数变了：{len(before)} → {len(after)}")
            return
        for index, (left, right) in enumerate(zip(before, after)):
            compare(left, right, f"{path}[{index}]", problems)
    elif before != after:
        problems.append(f"{path} 值变了：{before!r} → {after!r}")


def run(root: Path, *, apply: bool) -> int:
    db_file = root / "machining_dfm.sqlite3"
    if not db_file.is_file():
        print("没有找到库：", db_file)
        return 2
    tables = table_names(root)
    store = MachiningDFMStore(root, SEED)
    print("=" * 72)
    print("补迁前")
    print("=" * 72)
    pending = print_status(store, tables)
    if not pending:
        return 0

    backup_path = ""
    if apply:
        backup = store._backup(
            f"pre-catchup-tables-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3")
        backup_path = str(backup)
        print()
        print("备份          =", backup_path)
        store = MachiningDFMStore(root, SEED)

    before = {item["id"]: item["state"] for item in pending}
    print()
    print("=" * 72)
    print("开始补迁（逐域：表里有行就跳过那一域）")
    print("=" * 72)
    reports: dict[str, dict] = {}
    for item in pending:
        reports[item["id"]] = store.import_state(item["id"], item["state"]) or {}

    problems: list[str] = []
    print()
    print("=" * 72)
    print("核对（读模型不丢字段 / 表里有行 / JSON 清空）")
    print("=" * 72)
    for item in pending:
        project_id = item["id"]
        record = store.get(project_id, allow_archived=True)
        after_state = record["state"]
        local: list[str] = []
        compare(before[project_id], after_state, "state", local)
        counts = project_shape(store, project_id, tables)
        with store.connect() as db:
            stored = db.execute("SELECT state_json FROM projects WHERE id=?",
                                (project_id,)).fetchone()[0]
        domains = reports[project_id].get("domains", {})
        state_empty = stored.strip() in ("{}", "")
        print(f"  {project_id[:8]}「{item['name'][:28]}」"
              f" 拆了 {'、'.join(domains) or '（无需拆）'}"
              f"｜表里：{counts}｜state_json={'{}' if state_empty else stored[:40]}")
        if local:
            problems.extend(f"{project_id[:8]}：{text}" for text in local)
            for text in local[:6]:
                print("      ×", text)
        if not state_empty:
            problems.append(f"{project_id[:8]}：state_json 没清空（{stored[:40]}）")
        for label, _table, _key in DOMAINS:
            if item["wants"].get(label) and counts[label] == 0:
                problems.append(f"{project_id[:8]}：{label} 说要补却是 0 行")

    with store.connect() as db:
        bad = db.execute("PRAGMA foreign_key_check").fetchall()
        ok = db.execute("PRAGMA integrity_check").fetchone()[0]
    print()
    print("foreign_key_check =", "干净" if not bad else bad[:3])
    print("integrity_check   =", ok)
    if bad or ok != "ok":
        problems.append(f"库体检不过：foreign_key_check={bad[:2]} integrity_check={ok}")

    print()
    if problems:
        print("发现问题（库已备份，可以回退）：")
        for problem in problems:
            print("  -", problem)
        return 1
    if not apply:
        print("√ 干跑通过：字段一个没丢、表里有行、JSON 清空、外键干净（线上库一个字节都没动）")
        return 0
    print("√ 补迁完成：这些项目从此「表是最小单元」，页面上每行都有行 id、能行级保存")
    print("  备份 =", backup_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真搬线上库（默认只干跑）")
    parser.add_argument("--keep", action="store_true", help="干跑后保留临时副本")
    parser.add_argument("--status", action="store_true", help="只读：打印当前状态")
    parser.add_argument("--from", dest="source", default="", help="要处理的数据目录（默认线上目录）")
    args = parser.parse_args()

    source = Path(args.source).resolve() if args.source else LIVE
    if args.status:
        store = MachiningDFMStore(source, SEED)
        print_status(store, table_names(source))
        return 0

    if args.apply:
        if source != LIVE:
            print("--apply 只允许对线上目录使用（要演练请用 --from 且不要加 --apply）")
            return 2
        return run(source, apply=True)

    work = Path(tempfile.mkdtemp(prefix="machining-catchup-tables-"))
    target = work / "machining_dfm"
    try:
        shutil.copytree(source, target)
        if LIVE in target.parents or target == LIVE:
            print("拒绝在线上目录上干跑")
            return 2
        print("=" * 72)
        print("干跑（副本：" + str(target) + "）")
        print("=" * 72)
        code = run(target, apply=False)
    finally:
        if args.keep:
            print("\n副本保留在：", target)
        else:
            shutil.rmtree(work, ignore_errors=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
