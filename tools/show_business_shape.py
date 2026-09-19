"""把线上项目里"工序 / 工序刀具行 / 问题清单"的真实字段形状挖出来（只读）。

用途：1b 阶段（project_processes + project_process_tools）建表前，先看清每个键：
谁在写、是不是派生、是不是按名字引用库、有没有价格快照。
"""

from __future__ import annotations

import io
import json
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_dfm import MachiningDFMStore  # noqa: E402

store = MachiningDFMStore("data/machining_dfm", "app/resources/machining_dfm_seed")
project = store.list()[0]
state = store.get(project["id"])["state"]


def shape(rows: list[dict], label: str) -> None:
    print(f"\n=== {label}：{len(rows)} 行 ===")
    keys: "OrderedDict[str, Counter]" = OrderedDict()
    for row in rows:
        for key, value in row.items():
            keys.setdefault(key, Counter())[type(value).__name__] += 1
    for key, types in keys.items():
        sample = ""
        for row in rows:
            if key in row and row[key] not in (None, "", [], {}):
                sample = json.dumps(row[key], ensure_ascii=False)[:70]
                break
        print(f"  {key:8s} {'/'.join(f'{t}×{n}' for t, n in types.items()):22s} 样例 {sample}")
    covered = sum(1 for row in rows if row)
    print(f"  非空行 {covered}/{len(rows)}；键集合 {'完全一致' if len({tuple(sorted(r)) for r in rows}) == 1 else '不一致：' + str([sorted(r) for r in rows])}")


shape(state["pr"], "工序 pr[]")
tool_rows = [tool for process in state["pr"] for tool in (process.get("tl") or [])]
shape(tool_rows, "工序刀具行 pr[].tl[]")
shape(state["is"], "问题清单 is[]")
shape(state["vh"], "版本履历 vh[]")

print("\n=== 工序里的嵌套小对象 ===")
for process in state["pr"]:
    print("  nc =", json.dumps(process.get("nc"), ensure_ascii=False))
    print("  cI =", json.dumps(process.get("cI"), ensure_ascii=False),
          "| fixP =", json.dumps(process.get("fixP"), ensure_ascii=False),
          "| eqP =", json.dumps(process.get("eqP"), ensure_ascii=False))
    break

print("\n=== 派生字段（前端算的） ===")
derived = ("_ct", "_vc", "_vf", "_fz")
for key in derived:
    values = [tool.get(key) for tool in tool_rows if key in tool]
    print(f"  {key}: {len(values)}/{len(tool_rows)} 行有值，样例 {values[:6]}")

print("\n=== 刀具行与刀具库的对应关系（按名字 / 按 id） ===")
tools = state["tdb"]
by_name = {tool.get("tp"): tool for tool in tools}
matched = sum(1 for tool in tool_rows if tool.get("tp") in by_name)
print(f"  刀具行 {len(tool_rows)} 行，按 tp（名字）能在刀具库找到 {matched} 行")
print(f"  刀具行里带 id 的：{sum(1 for tool in tool_rows if tool.get('id'))} 行（id 样例 {tool_rows[0].get('id') if tool_rows else None}）")
print(f"  刀具库里带 id 的：{sum(1 for tool in tools if tool.get('id'))} 行")
same_names = [name for name, count in Counter(tool.get("tp") for tool in tools).items() if count > 1]
print(f"  刀具库里重名刀具：{len(same_names)} 个 {same_names[:5]}")

print("\n=== 问题清单的 pr（工序引用） ===")
names = [process.get("nm") for process in state["pr"]]
print("  工序名:", names)
print("  问题清单引用的 pr:", [row.get("pr") for row in state["is"]])

print("\n=== 夹具/检具选型（G 里的旧结构） ===")
for key in ("fixQ", "fixQC", "insp", "inspQ"):
    print(f"  {key} = {json.dumps(state['G'].get(key), ensure_ascii=False)[:160]}")
