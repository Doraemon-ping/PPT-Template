# -*- coding: utf-8 -*-
"""只读：看"另存为"出来的项目（表空、JSON 满）在页面上能不能改工序。

重点看两件事：
1. 读模型里的工序行有没有**行 id**（没有 id，页面的行级保存就无从下手）；
2. 工序/问题接口在这种项目上给什么（空表 → 读模型回退 state_json？）。
"""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8002/api/machining-dfm"
COPY = "04ea8ca4507f43838587d6889534458f"
MAIN = "b1f786630dc24006a9839f3a7f8fa3f1"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


for label, pid in (("主项目（表里有行）", MAIN), ("另存为副本（表空、JSON 满）", COPY)):
    print("=" * 70)
    print(label, pid[:8])
    print("=" * 70)
    status, record = get(f"/projects/{pid}")
    state = record.get("state") or {}
    print("  读模型 state_json 键 =", sorted(state.keys()))
    print("  state_json 长度 =", len(json.dumps(state, ensure_ascii=False)))
    print("  pr 行数 =", len(state.get("pr") or []),
          "｜is 行数 =", len(state.get("is") or []))
    for index, item in enumerate((state.get("pr") or [])[:2]):
        print(f"    pr[{index}] 键 = {sorted(item.keys())}")
        print(f"    pr[{index}].id = {item.get('id')!r}   nm = {item.get('nm')!r}")
        tools = item.get("tl") or []
        print(f"    刀具 {len(tools)} 把，tl[0].id = {(tools[0].get('id') if tools else None)!r}")
    for path in ("/processes", "/issues", "/fixtures/0", "/gauges/0"):
        try:
            status, payload = get(f"/projects/{pid}{path}")
        except urllib.error.HTTPError as error:
            print(f"  GET {path:14s} -> {error.code} {error.read().decode('utf-8')[:80]}")
            continue
        if isinstance(payload, dict):
            keys = sorted(payload.keys())
            count = payload.get("count", payload.get("total", ""))
            print(f"  GET {path:14s} -> {status} 键={keys[:8]}"
                  + (f" 行数={count}" if count != "" else ""))
        else:
            print(f"  GET {path:14s} -> {status} {type(payload).__name__}")
    print()
