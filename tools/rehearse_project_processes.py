"""1b 演练（用**生产模块**）：在线上库的临时副本上，把工序真正拆进两张表再读回来。

与 ``tools/reference_process_mapping.py``（纯函数草案）不同，这里直接调用
``app/machining_process.py`` 里的生产代码：

1. 副本上打开工序开关（环境变量），建表；
2. ``apply_split`` 把线上项目的 ``pr[]`` 逐行落进 ``project_processes`` / ``project_process_tools``；
3. ``store.get()`` 读回来，与迁移前的读模型**逐字节**比对（含派生值、键序）；
4. 成本基线指纹必须不变（``tools/baselines/process_cost_baseline.json``）；
5. 打印绑定报告（唯一/直径消歧/重名未绑/库里没有）与快照价缺失统计。

线上库**只读**：副本建在临时目录，跑完即删。

用法：python tools/rehearse_project_processes.py
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="machining-process-e2e-"))
    try:
        return rehearse(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def rehearse(work: Path) -> int:
    import os

    os.environ["MACHINING_PROJECT_BUSINESS"] = "1"
    from app.machining_dfm import MachiningDFMStore
    from app.domains.process import apply_split, legacy_processes

    target = work / "machining_dfm"
    shutil.copytree(ROOT / "data" / "machining_dfm", target)
    assert ROOT / "data" / "machining_dfm" not in target.parents, "拒绝在线上目录上演练"

    store = MachiningDFMStore(target, ROOT / "app" / "resources" / "machining_dfm_seed")
    assert store.project_business is True, "副本上开关没打开"
    project = store.list()[0]
    pid = project["id"]
    print(f"副本：{target}")
    print(f"项目：{project['name']} v{project['revision']}")

    before = store.get(pid)["state"]
    before_pr = json.dumps(before["pr"], ensure_ascii=False)
    before_pr_canonical = json.dumps(before["pr"], ensure_ascii=False, sort_keys=True)
    print(f"\n=== 1) 迁移前 ===")
    print(f"  工序 {len(before['pr'])} 道 · 刀具行 "
          f"{sum(len(p.get('tl') or []) for p in before['pr'])} 行 · pr[] 共 {len(before_pr)} 字节")

    report = apply_split(
        store.processes, store.process_tools, pid, before,
        tools_library=before.get("tdb") or [], machines=before.get("mdb") or [],
    )
    print("\n=== 2) 落表 ===")
    print(f"  工序行 {store.processes.count(pid, include_deleted=True)} 行 · "
          f"刀具行 {store.process_tools.count(pid, include_deleted=True)} 行")
    print(f"  绑库：唯一 {report['bind'].get('unique', 0)} · 直径消歧 {report['bind'].get('by_size', 0)} · "
          f"重名未绑 {report['bind'].get('ambiguous', 0)} · 库里没有 {report['bind'].get('missing', 0)}")
    print(f"  快照价/寿命为 0（库里没录价）的刀具行：{report['price_missing']}")

    after = store.get(pid)["state"]
    after_pr = json.dumps(after["pr"], ensure_ascii=False)
    after_pr_canonical = json.dumps(after["pr"], ensure_ascii=False, sort_keys=True)
    problems: list[str] = []
    print("\n=== 3) 读回来比对 ===")
    if after_pr == before_pr:
        print(f"  √ pr[] 与迁移前**逐字节相同**（{len(after_pr)} 字节，含键序）")
    else:
        problems.append("pr[] 字节不一致")
        print(f"  × pr[] 字节不同：迁移前 {len(before_pr)} 字节 → 现在 {len(after_pr)} 字节")
        old_rows, new_rows = before["pr"], after["pr"]
        if len(old_rows) != len(new_rows):
            problems.append(f"工序数量 {len(old_rows)} → {len(new_rows)}")
        for index, (old, new) in enumerate(zip(old_rows, new_rows)):
            if list(old) != list(new):
                print(f"    工序 {index} 键序不同：{list(old)} → {list(new)}")
            for key in old:
                if key == "tl":
                    for position, (old_tool, new_tool) in enumerate(zip(old["tl"], new["tl"])):
                        for tool_key in old_tool:
                            if old_tool[tool_key] != new_tool.get(tool_key):
                                problems.append(
                                    f"工序 {index} 刀具行 {position}.{tool_key}: "
                                    f"{old_tool[tool_key]!r} → {new_tool.get(tool_key)!r}")
                    continue
                if old[key] != new.get(key):
                    problems.append(f"工序 {index}.{key}: {old[key]!r} → {new.get(key)!r}")
    canonical_same = before_pr_canonical == after_pr_canonical
    print(f"  {'√' if canonical_same else '×'} 键值集合（忽略键序）"
          f"{'一致' if canonical_same else '不一致'}")

    print("\n=== 4) 成本基线指纹 ===")
    baseline_file = ROOT / "tools" / "baselines" / "process_cost_baseline.json"
    baseline = json.loads(baseline_file.read_text(encoding="utf-8")) if baseline_file.is_file() else None
    if baseline is None:
        print("  （没有基线文件，跳过）")
    else:
        old_totals, new_totals = baseline["totals"], {}
        rows = [tool for process in after["pr"] for tool in (process.get("tl") or [])]
        by_name: dict[str, list[dict]] = {}
        for tool in after.get("tdb") or []:
            by_name.setdefault(str(tool.get("tp") or ""), []).append(tool)
        total = 0.0
        for tool in rows:
            hits = by_name.get(str(tool.get("tp") or ""), [])
            life, price = (hits[0].get("life") or 0, hits[0].get("price") or 0) if hits else (0, 0)
            total += price / life if life > 0 else 0
        new_totals["tool_cost_per_min"] = round(total, 8)
        new_totals["process_count"] = len(after["pr"])
        new_totals["tool_row_count"] = len(rows)
        for key in ("tool_cost_per_min", "process_count", "tool_row_count"):
            same = old_totals.get(key) == new_totals.get(key)
            print(f"  {'√' if same else '×'} {key}: 基线 {old_totals.get(key)} → 现在 {new_totals.get(key)}")
            if not same:
                problems.append(f"成本基线 {key} 变了")

    print()
    if problems:
        print("× 演练发现问题：")
        for item in problems[:20]:
            print("  -", item)
        return 1
    print("√ 演练通过：工序落表后读模型与成本数字**逐字节不变**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
