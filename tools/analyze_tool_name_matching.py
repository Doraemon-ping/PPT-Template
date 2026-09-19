"""1b 设计依据：把"按刀具名匹配库"会踩到几行算清楚（只读）。"""

from __future__ import annotations

import io
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_dfm import MachiningDFMStore  # noqa: E402

store = MachiningDFMStore("data/machining_dfm", "app/resources/machining_dfm_seed")
state = store.get(store.list()[0]["id"])["state"]
tools = state["tdb"]
rows = [tool for process in state["pr"] for tool in (process.get("tl") or [])]

by_name: dict[str, list[dict]] = defaultdict(list)
for tool in tools:
    by_name[str(tool.get("tp") or "")].append(tool)

# 前端 toolCost() 的逻辑：命中第一行就用它的 life/price；命中不到返回 0
ambiguous, missing, same_first = [], [], 0
for row in rows:
    hits = by_name.get(str(row.get("tp") or ""), [])
    if not hits:
        missing.append(row.get("tp"))
    elif len(hits) > 1:
        prices = {(hit.get("price"), hit.get("life")) for hit in hits}
        ambiguous.append((row.get("tp"), len(hits), len(prices)))

print(f"刀具行 {len(rows)} 行｜刀具库 {len(tools)} 行")
print(f"  名字在库里唯一的行        : {len(rows) - len(ambiguous) - len(missing)}")
print(f"  名字在库里重名（命中第一行）: {len(ambiguous)}")
for name, count, distinct in ambiguous[:10]:
    print(f"      {name[:38]:40s} 库里 {count} 行，规格/价格组合 {distinct} 种")
print(f"  名字在库里找不到的行      : {len(missing)} {missing}")

print("\n重名刀具会不会跨刀具组（hp/dp）？")
cross = 0
for name, hits in by_name.items():
    groups = {hit.get("grp") for hit in hits}
    if len(hits) > 1 and len(groups) > 1:
        cross += 1
print(f"  同名且跨组的刀具名: {cross} 个")

print("\n刀具库里的空名字/重复 id:")
print("  空名字行:", sum(1 for tool in tools if not str(tool.get("tp") or "").strip()))
ids = Counter(tool.get("id") for tool in tools)
print("  重复 id:", [key for key, count in ids.items() if count > 1][:5])

print("\n当前 25 行刀具行的费用口径（按前端 toolCost：price/life）：")
total = 0.0
for row in rows:
    hits = by_name.get(str(row.get("tp") or ""), [])
    life, price = (hits[0].get("life") or 0, hits[0].get("price") or 0) if hits else (0, 0)
    total += price / life if life > 0 else 0
print(f"  合订单件刀具成本 = {total:.4f} 元/min（这是报表里的数，改成 id 引用后必须一模一样）")
