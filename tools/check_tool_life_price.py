"""核对刀具库的价格/寿命到底填了没有——决定 1b 阶段"快照价"要快照哪些列。"""

from __future__ import annotations

import io
import sys

sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_dfm import MachiningDFMStore  # noqa: E402

store = MachiningDFMStore("data/machining_dfm", "app/resources/machining_dfm_seed")
state = store.get(store.list()[0]["id"])["state"]
tools = state["tdb"]
rows = [tool for process in state["pr"] for tool in (process.get("tl") or [])]

print("刀具库", len(tools), "行")
print("  life>0 :", sum(1 for tool in tools if (tool.get("life") or 0) > 0))
print("  price>0:", sum(1 for tool in tools if (tool.get("price") or 0) > 0))
print("  life 取值:", sorted({tool.get("life") for tool in tools}, key=lambda v: (v is None, v))[:10])
print("  price 取值样例:", sorted({tool.get("price") for tool in tools}, key=lambda v: (v is None, v))[:10])
print("  两个都>0 的行:", sum(1 for tool in tools if (tool.get("life") or 0) > 0 and (tool.get("price") or 0) > 0))

by_name = {tool.get("tp"): tool for tool in tools}
print("\n刀具行 → 库行 的取值：")
for row in rows[:10]:
    hit = by_name.get(row.get("tp")) or {}
    life, price = hit.get("life"), hit.get("price")
    cost = (price or 0) / life if (life or 0) > 0 else 0
    print(f"  {str(row.get('tp'))[:26]:28s} cat={str(row.get('cat')):6s} "
          f"库(life={life}, price={price}, d={hit.get('d')}, n={hit.get('n')}) → toolCost={cost}")
