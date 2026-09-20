"""把项目对应的机加工序拆出来看：迁移后 project_processes / project_process_tools 里长什么样。

线上还没建这两张表，所以本工具把线上库整份复制到临时目录，**在副本上真拆一次**
（用的就是迁移工具那条路径 apply_split），然后逐列打印，跑完删掉副本。

用法：
    python tools/show_project_process_rows.py             # 概览：工序逐列 + 刀具行网格
    python tools/show_project_process_rows.py --tool 1     # 第 1 行刀具行的逐列明细
    python tools/show_project_process_rows.py --keep       # 保留副本目录，便于自己翻库
    python tools/show_project_process_rows.py --revision 3 # 看某个历史版本的工序长什么样
"""

from __future__ import annotations

import argparse
import json
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

from app.machining_dfm import MachiningDFMStore  # noqa: E402
from app.domains.process import (  # noqa: E402
    NC_KEYS,
    PROCESS_ATTACHMENTS,
    PROCESS_FIELDS,
    TOOL_ATTACHMENTS,
    TOOL_FIELDS,
)

LIVE = BASE / "data" / "machining_dfm"
SEED = BASE / "app" / "resources" / "machining_dfm_seed"

#: 网格里按旧键顺序显示的主要列
GRID_KEYS = ("id", "tp", "ds", "d", "n", "vf", "ln", "ps", "cn", "bg", "cat")
SNAP_KEYS = ("tool_id", "tool_grp", "tool_price", "tool_life", "hld_id", "hld_price",
             "acc_id", "acc_price")


def is_blank(value) -> bool:
    return value in (None, "", 0, 0.0, "{}", "[]")


def cell(value, width: int = 0) -> str:
    if value is None:
        text = "NULL"
    elif isinstance(value, str):
        text = repr(value.replace("\n", "\\n")) if value else "''"
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = repr(value)
    return text if not width else text[:width]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", type=int, default=-1, help="打印第 N 行刀具行的逐列明细（从 1 数）")
    parser.add_argument("--keep", action="store_true", help="保留副本目录")
    parser.add_argument("--revision", type=int, default=0, help="用某个历史版本拆（默认当前版本）")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="machining-process-rows-"))
    root = work / "machining_dfm"
    shutil.copytree(LIVE, root)

    db = sqlite3.connect(f"file:{root / 'machining_dfm.sqlite3'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        projects = db.execute("SELECT id,name,revision FROM projects").fetchall()
    finally:
        db.close()

    os.environ["MACHINING_PROJECT_BUSINESS"] = "1"
    base = MachiningDFMStore(root, SEED)  # 关着开关的读模型拿库与旧 pr
    store = MachiningDFMStore(root, SEED)

    for project in projects:
        pid, name = project["id"], project["name"]
        revision = args.revision or int(project["revision"])
        record = base.get(pid, revision)
        state = record["state"]
        library, machines = state.get("tdb") or [], state.get("mdb") or []
        legacy_pr = state.get("pr") or []

        print("=" * 96)
        print(f"项目：{name}")
        print(f"版本：v{revision}" + ("（当前）" if revision == project["revision"] else "（历史快照）"))
        print("=" * 96)
        if not legacy_pr:
            print("这个版本里没有工序。\n")
            continue

        from app.domains.process import apply_split

        report = apply_split(store.processes, store.process_tools, pid, state,
                             tools_library=library, machines=machines)
        rows = store.processes.list_typed(pid, include_deleted=True)
        tools = store.process_tools.list_typed(pid, include_deleted=True)

        print(f"旧 state_json 里的 pr[]：{len(legacy_pr)} 道工序 / "
              f"{sum(len(p.get('tl') or []) for p in legacy_pr)} 行刀具行")
        print(f"拆进表之后：project_processes {len(rows)} 行 · "
              f"project_process_tools {len(tools)} 行")
        print()

        machine_by_id = {str(item.get("id")): item for item in machines}

        # ---------------- 工序行逐列 ----------------
        for index, row in enumerate(rows):
            legacy = legacy_pr[index] if index < len(legacy_pr) else {}
            print(f"—— project_processes 第 {index + 1} 行  id = {row['id']}")
            print(f"   project_id        = {cell(row['project_id'])}")
            print(f"   sort_order        = {row['sort_order']}   ← 页面上第 {row['sort_order'] + 1} 道")
            for field in PROCESS_FIELDS:
                # list_typed 出来的行是"旧短键"视图（API 就按这个口径说话），所以按 key 取
                value = row.get(field.key)
                if field.key == "mid":
                    machine = machine_by_id.get(str(value or ""))
                    if machine:
                        extra = f"（设备库：{machine.get('brand')} {machine.get('model')}" \
                                f" · ¥{machine.get('price')}）"
                    else:
                        extra = "（设备库里**找不到这台设备**）"
                elif field.key == "nc":
                    counts = value if isinstance(value, dict) else {}
                    extra = "（" + " ".join(f"{key}={counts.get(key)}" for key in NC_KEYS) + "）"
                else:
                    extra = ""
                print(f"   {field.column:<17} = {cell(value):<26} ← {field.key:<7} "
                      f"{field.label}{extra}")
            snapshot = row.get("machine_snapshot") or {}
            if snapshot:
                print(f"   machine_snapshot  = {cell(snapshot, 200)}")
                print(f"                       → 选这道工序设备时，设备库那一行的副本"
                      f"（换设备会重写，库改价不影响已存快照）")
            photo_column = PROCESS_ATTACHMENTS[0].column
            print(f"   {photo_column:<17} = "
                  f"{cell(row.get(PROCESS_ATTACHMENTS[0].legacy_key)):<26} "
                  f"← {PROCESS_ATTACHMENTS[0].legacy_key}     夹具示意图（附件 id）")
            print(f"   deleted_at/by/reason = {cell(row['deleted_at'])} / "
                  f"{cell(row['deleted_by'])} / {cell(row['deleted_reason'])}   ← 逻辑删除，永不清行")
            print(f"   created / updated    = {row['created']} / {row['updated']}")
            mine = [tool for tool in tools if tool["process_id"] == row["id"]]
            print(f"   这一道工序的刀具行     = {len(mine)} 行"
                  f"（旧数据 {len(legacy.get('tl') or [])} 行，"
                  f"{'对得上' if len(mine) == len(legacy.get('tl') or []) else '**对不上**'}）")
            print()

        # ---------------- 刀具行网格 ----------------
        # 按"工序顺序 + 行内顺序"排，跟页面上看到的次序一致（表里是按 sort_order 排的）
        order = {row["id"]: index for index, row in enumerate(rows)}
        tools.sort(key=lambda tool: (order.get(tool["process_id"], 99), tool.get("sort_order") or 0))
        print(f"—— project_process_tools：{len(tools)} 行（按工序分组，列名用旧键标注）")
        header = "".join(f"{key:>10}" for key in GRID_KEYS)
        print(f"   {'行':<4}{'工序':<6}{header}{'tool_id':>34}{'价':>8}{'寿命':>8}")
        for index, tool in enumerate(tools, start=1):
            process_index = next((i for i, row in enumerate(rows) if row["id"] == tool["process_id"]), -1)
            cells = "".join(f"{str(cell(tool.get(key)))[:9]:>10}" for key in GRID_KEYS)
            bound = str(tool.get("tool_id") or "")
            price = tool.get("tool_price")
            life = tool.get("tool_life")
            print(f"   {index:<4}{('OP' + str(process_index + 1)) if process_index >= 0 else '?':<6}"
                  f"{cells}{bound[:32]:>34}"
                  f"{(f'{price:g}' if price is not None else 'NULL'):>8}"
                  f"{(f'{life:g}' if life is not None else 'NULL'):>8}")
        print()

        # ---------------- 快照/绑定统计 ----------------
        bound = [tool for tool in tools if tool.get("tool_id")]
        no_price = [tool for tool in tools if not tool.get("tool_price_snapshot")
                    and not tool.get("tool_life_snapshot")]
        print("—— 刀具库绑定与快照")
        print(f"   绑到刀具库的：{len(bound)}/{len(tools)} 行"
              f"（{report['bind']}）")
        print(f"   库里没录价格/寿命的：{len(no_price)} 行 → 这几行成本按 0 计，"
              f"页面上会提示「刀具库未录价格」")
        print(f"   刀柄/配件选型：hld_id 有值 {sum(1 for t in tools if t.get('hld_id'))} 行 · "
              f"acc_id 有值 {sum(1 for t in tools if t.get('acc_id'))} 行")
        print()

        # ---------------- 某一行刀具的逐列明细 ----------------
        if 0 < args.tool <= len(tools):
            tool = tools[args.tool - 1]
            print(f"—— project_process_tools 第 {args.tool} 行的逐列明细（id = {tool['id']}）")
            for key in ("id", "project_id", "process_id", "sort_order"):
                print(f"   {key:<24} = {cell(tool.get(key))}")
            for field in TOOL_FIELDS:
                value = tool.get(field.key)
                print(f"   {field.column:<24} = {cell(value):<28} ← {field.key:<9} {field.label}")
            for spec in TOOL_ATTACHMENTS:
                print(f"   {spec.column:<24} = {cell(tool.get(spec.legacy_key)):<28} "
                      f"← {spec.legacy_key:<9} {spec.kind}")
            print(f"   {'deleted_at/by/reason':<24} = {cell(tool.get('deleted_at'))} / "
                  f"{cell(tool.get('deleted_by'))} / {cell(tool.get('deleted_reason'))}")
            print(f"   {'created / updated':<24} = {tool.get('created')} / {tool.get('updated')}")
            print("   （_ct/_vc/_vf/_fz 没有列：读的时候按 D/n/vf/ln/刃数现算）")
            print()

        # ---------------- 反证：表单独能还原旧 pr ----------------
        from app.domains.process import legacy_processes

        rebuilt = legacy_processes(store.processes, store.process_tools, pid,
                                   asset_store=store.assets, inline_assets=False)
        def strip_mi(items):
            return [{k: v for k, v in item.items() if k != "mi"} for item in (items or [])]
        same = strip_mi(rebuilt) == strip_mi(legacy_pr)
        print(f"—— 反证：只凭这两张表还原旧 pr[]（忽略读时现算的 mi）→ "
              f"{'√ 与 state_json 完全一致' if same else '× 不一致'}")

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print("\n副本保留在：", root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
