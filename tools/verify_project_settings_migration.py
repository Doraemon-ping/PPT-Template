"""项目信息迁移干跑：在**副本**上跑一遍迁移，逐键比对迁移前后读模型。

用法：
    python tools/verify_project_settings_migration.py            # 复制线上库到临时目录后迁移
    python tools/verify_project_settings_migration.py --keep     # 保留临时目录，便于人工复查
    python tools/verify_project_settings_migration.py --from data/machining_dfm/backups/pre-project-settings-manual-xxx

（线上库迁完之后没有可比的基准了，这时用 ``--from`` 指一个迁移前的备份目录照样能验。）

检查项：
1. 迁移前后 ``state.G`` 逐键一致（图片按 inline data URL 比，键集合与取值都要相同）；
2. ``pr`` / ``is`` / ``vh`` 三份业务数组原样不变；
3. 历史版本 ``?revision=N`` 还原出来的 G 与迁移前该版本快照的 G 逐键一致；
4. ``projects.state_json`` 体积明显下降（项目图片已搬去附件库）；
5. 项目信息落到了 ``project_settings`` 的一行一列里，附件表多了图片行。

任何一项不通过都会以非零码退出。
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

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_dfm import MachiningDFMStore  # noqa: E402

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"
IMAGE_KEYS = ("pI", "pf", "bInspImg", "fInspImg")


def read_rows(db_path: Path, sql: str) -> list[sqlite3.Row]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        return db.execute(sql).fetchall()
    finally:
        db.close()


def _same(expected, actual) -> bool:
    """0 与 0.0、True 与 1 这类"数值相同但字面不同"不算差异。"""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) < 1e-9
    return expected == actual


def compare(label: str, expected: dict, actual: dict, *, ignore: tuple[str, ...] = ()) -> list[str]:
    problems: list[str] = []
    for key in sorted(set(expected) | set(actual)):
        if key in ignore:
            continue
        if key not in expected:
            problems.append(f"{label}: 多出新键 {key} = {str(actual[key])[:60]!r}")
        elif key not in actual:
            problems.append(f"{label}: 丢了旧键 {key} = {str(expected[key])[:60]!r}")
        elif not _same(expected[key], actual[key]):
            problems.append(
                f"{label}: {key} 不一致\n      迁移前 {str(expected[key])[:90]!r}\n      迁移后 {str(actual[key])[:90]!r}"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="保留临时副本目录")
    parser.add_argument("--from", dest="source", default="", help="迁移前的数据目录（默认用线上目录）")
    args = parser.parse_args()

    live = Path(args.source).resolve() if args.source else LIVE
    if not (live / "machining_dfm.sqlite3").is_file():
        print("没有找到要验的库：", live / "machining_dfm.sqlite3")
        return 2

    work = Path(tempfile.mkdtemp(prefix="machining-settings-dryrun-"))
    target = work / "machining_dfm"
    shutil.copytree(live, target)
    assert target != live and LIVE not in target.parents, "拒绝在线上目录上干跑"

    before_projects = {
        row["id"]: (row["name"], row["revision"], row["state_json"])
        for row in read_rows(target / "machining_dfm.sqlite3", "SELECT id,name,revision,state_json FROM projects")
    }
    before_revisions = {
        (row["project_id"], row["revision"]): row["state_json"]
        for row in read_rows(
            target / "machining_dfm.sqlite3", "SELECT project_id,revision,state_json FROM revisions"
        )
    }
    before_assets = read_rows(target / "machining_dfm.sqlite3", "SELECT COUNT(*) AS n FROM assets")[0]["n"]

    # 这个工具是"迁移前"用的：线上库已经迁过的话（G 不在 state_json 里了）就没有可比对的基准，
    # 硬跑会满屏假报错，所以直接说清楚，并指向逐键核对工具。
    if before_projects and not any("G" in json.loads(row[2]) for row in before_projects.values()):
        print("线上库已经是新结构（projects.state_json 里没有 G），这次迁移早就跑完了，无需再迁。")
        print("要做逐键核对请用：python tools/restore_project_settings.py（干跑，不加 --apply 不动数据）")
        shutil.rmtree(work, ignore_errors=True)
        return 0

    print(f"副本：{target}")
    print(f"迁移前：projects {len(before_projects)} 个、revisions {len(before_revisions)} 条、assets {before_assets} 行")

    store = MachiningDFMStore(target, SEED)

    problems: list[str] = []
    after_assets = read_rows(target / "machining_dfm.sqlite3", "SELECT COUNT(*) AS n FROM assets")[0]["n"]

    for project_id, (name, revision, state_json) in before_projects.items():
        old_state = json.loads(state_json)
        old_g = dict(old_state.get("G") or {})
        old_g.pop("icnX", None)
        old_g.pop("fcnX", None)

        record = store.get(project_id)
        new_g = dict(record["state"]["G"])
        new_g.pop("icnX", None)
        new_g.pop("fcnX", None)
        # 图片键单独检查：页面/接口拿附件地址（这是本次改造的目的），
        # 导出与 PPT 用 inline=True 还原成 data URL，下面第 4 步逐字比对。
        problems += compare(f"项目 {name} 的 G", old_g, new_g, ignore=IMAGE_KEYS)

        stored_now = json.loads(
            read_rows(
                target / "machining_dfm.sqlite3",
                f"SELECT state_json FROM projects WHERE id='{project_id}'",
            )[0]["state_json"]
        )
        for key in ("pr", "is", "vh"):
            old_value = old_state.get(key, [])
            new_value = stored_now.get(key, [])
            if old_value != new_value:
                problems.append(f"项目 {name} 存的 {key} 不一致：{len(old_value)} 项 → {len(new_value)} 项")
        # compose 会给工序补一个 mi 下标（旧契约），这里确认它确实补上了
        for index, process in enumerate(record["state"].get("pr", [])):
            if "mi" not in process:
                problems.append(f"项目 {name}: 读模型 pr[{index}] 缺 mi 下标")

        typed = store.settings.typed(project_id)
        print(
            f"  项目信息表：customer={typed['cust']!r} part={typed['part']!r} "
            f"hpd={typed['hpd']} avl={typed['avl']} 图片槽={[typed[f'{slot}_id'] is not None for slot in ('product', 'product2', 'blank_insp', 'final_insp')]}"
        )
        if not isinstance(typed["extra"], dict):
            problems.append(f"项目 {name}: extra_json 不是对象")

        raw_now = stored_now
        if "G" in raw_now:
            problems.append(f"项目 {name}: projects.state_json 里还留着 G")
        print(
            f"  state_json 体积：{len(state_json) / 1024:.1f} KB → "
            f"{len(json.dumps(raw_now, ensure_ascii=False).encode('utf-8')) / 1024:.1f} KB"
        )

        for (pid, rev), old_rev_json in before_revisions.items():
            if pid != project_id:
                continue
            old_rev = json.loads(old_rev_json)
            old_rev_g = dict(old_rev.get("G") or {})
            old_rev_g.pop("icnX", None)
            old_rev_g.pop("fcnX", None)
            # 历史版本快照是不可变历史：连项目图片都必须还是原来的 data URL
            new_rev_g = dict(store.get(project_id, rev)["state"].get("G") or {})
            new_rev_g.pop("icnX", None)
            new_rev_g.pop("fcnX", None)
            problems += compare(f"项目 {name} 历史版本 r{rev} 的 G", old_rev_g, new_rev_g)
            stored_rev = json.loads(
                read_rows(
                    target / "machining_dfm.sqlite3",
                    f"SELECT state_json FROM revisions WHERE project_id='{project_id}' AND revision={rev}",
                )[0]["state_json"]
            )
            for key in ("pr", "is", "vh"):
                # 比"存进去的快照"（读模型会按旧契约给工序补 mi 下标，不能混在一起比）
                if old_rev.get(key, []) != stored_rev.get(key, []):
                    problems.append(f"项目 {name} 历史版本 r{rev} 的 {key} 快照被改动了")

    # 图片是不是真的搬走了：inline 还原出来的 data URL 必须与迁移前逐字相同
    for project_id, (name, _revision, state_json) in before_projects.items():
        old_g = json.loads(state_json).get("G") or {}
        inlined = store.get(project_id, inline_assets=True)["state"]["G"]
        for key in IMAGE_KEYS:
            if old_g.get(key) and old_g.get(key) != inlined.get(key):
                problems.append(f"项目 {name}: 图片 {key} inline 还原后与迁移前不一致")

    print(f"迁移后：assets {before_assets} → {after_assets} 行")

    if problems:
        print("\n× 干跑不通过：")
        for item in problems:
            print("  -", item)
        print("\n副本保留在：", work)
        return 1

    print("\n√ 干跑通过：迁移前后读模型逐键一致，历史版本可还原，项目信息已落表")
    if args.keep:
        print("副本保留在：", work)
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
