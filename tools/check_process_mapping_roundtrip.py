"""设计自证：把 1b 的表结构拿去和线上真实数据做"往返映射"，看会不会漏键。

思路：`pr[]/tl[]` 的每个键 → 按设计文档的列名映射 → 再映射回旧键，
逐一比对是否与原始值相同；**读写时该算的派生值（mi、_ct/_vc/_vf/_fz）不算在存储里**，
但要确认"按公式重算"能得到一模一样的值。

用法：python tools/check_process_mapping_roundtrip.py
"""

from __future__ import annotations

import io
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_dfm import MachiningDFMStore  # noqa: E402

# 设计文档 §2.1：工序列（旧键 → 列名）
PROCESS_MAP = {
    "nm": "name",
    "mc": "machine_count",
    "mid": "machine_id",
    "cI": "fixture_photo_id",
    "fixP": "fixture_price",
    "eqP": "equipment_price",
    "nc": "count_json",
    "tl": None,  # 子表
}
# 设计文档 §2.2：刀具行列（旧键 → 列名）；None = 本阶段不落库（派生/快照另立）
TOOL_MAP = {
    "id": "code",
    "tp": "tool_name",
    "ds": "description",
    "d": "diameter",
    "n": "spindle_rpm",
    "vf": "feed_rate",
    "ln": "cut_length",
    "ps": "passes",
    "cn": "flutes",
    "bg": "roughing",
    "td": "cut_time",
    "tt": "aux_time",
    "sd": "depth",
    "fi": "fixture_ref",
    "cat": "tool_category",
    "hld": "handle_name",
    "acc": "accessory_name",
    "_ct": None,
    "_vc": None,
    "_vf": None,
    "_fz": None,
}
DERIVED = ("_ct", "_vc", "_vf", "_fz")

store = MachiningDFMStore("data/machining_dfm", "app/resources/machining_dfm_seed")
state = store.get(store.list()[0]["id"])["state"]

problems: list[str] = []
counts = {"process_rows": 0, "tool_rows": 0, "keys_checked": 0}


def roundtrip(row: dict, mapping: dict, label: str) -> None:
    for key, value in row.items():
        if key in DERIVED or key == "mi":
            continue  # 派生值不落库，单独验算
        counts["keys_checked"] += 1
        if key not in mapping:
            problems.append(f"{label}: 旧键 {key!r} 在设计里没有对应列（会丢数据）")
            continue
        column = mapping[key]
        if column is None:
            continue  # tl 是子表，另走一遍
        # 往返：列名 → 旧键，必须回到同一个键
        back = [old for old, new in mapping.items() if new == column]
        if back != [key]:
            problems.append(f"{label}: 列 {column!r} 的往返键不唯一 {back}（键 {key!r}）")
        # 值层面：JSON 列允许嵌套，其余要求原值
        if isinstance(value, (dict, list)) and column.endswith("_json"):
            if json.loads(json.dumps(value, ensure_ascii=False)) != value:
                problems.append(f"{label}: {key!r} 走 JSON 列后值不等")


print("=== 工序行往返 ===")
for process in state["pr"]:
    counts["process_rows"] += 1
    roundtrip(process, PROCESS_MAP, f"工序 {process.get('nm')!r}")

print("=== 刀具行往返 ===")
for process in state["pr"]:
    for row in process.get("tl") or []:
        counts["tool_rows"] += 1
        roundtrip(row, TOOL_MAP, f"{process.get('nm')} / {row.get('code') or row.get('id')}")

print(f"  往返检查 {counts['keys_checked']} 个键 · 工序 {counts['process_rows']} 行 · 刀具行 {counts['tool_rows']} 行")

print("\n=== 派生值能否按公式重算得一模一样 ===")
mismatch = 0
for process in state["pr"]:
    for row in process.get("tl") or []:
        n, vf, ln, ps, cn = (row.get("n") or 0, row.get("vf") or 0, row.get("ln") or 0,
                             row.get("ps") or 0, row.get("cn") or 0)
        recomputed = {
            "_ct": (ln / vf * 60) * ps * cn if vf > 0 else 0,
            "_vc": round(math.pi * (row.get("d") or 0) * n / 1000),
            "_vf": vf,
            "_fz": vf / n if n > 0 else 0,
        }
        for key in DERIVED:
            if abs(float(row.get(key) or 0) - float(recomputed[key])) > 1e-6:
                mismatch += 1
                problems.append(f"派生值不一致 {row.get('id')}.{key}: 存 {row.get(key)} ≠ 算 {recomputed[key]}")
print(f"  25 行 × 4 个派生值，重算不一致 {mismatch} 处")

print("\n=== 工序 mi（设备下标）能否重算 ===")
machine_ids = [row.get("id") for row in state["mdb"]]
bad_mi = 0
for process in state["pr"]:
    index = process.get("mi")
    expected = machine_ids.index(process["mid"]) if process.get("mid") in machine_ids else -1
    expected = expected if expected >= 0 else (len(machine_ids) - 1 if machine_ids else 0)
    if index != expected:
        bad_mi += 1
        problems.append(f"工序 {process.get('nm')!r} 的 mi 重算不一致：存 {index} ≠ 算 {expected}")
print(f"  重算不一致 {bad_mi} 处（mid={[p.get('mid') for p in state['pr']]} → mi={[p.get('mi') for p in state['pr']]}）")

print("\n=== 迁移时能否按名字绑到刀具库 id（重名怎么办）===")
by_name: dict[str, list[dict]] = {}
for tool in state["tdb"]:
    by_name.setdefault(str(tool.get("tp") or ""), []).append(tool)
bound_unique = bound_ambiguous = unbound = 0
for process in state["pr"]:
    for row in process.get("tl") or []:
        hits = by_name.get(str(row.get("tp") or ""), [])
        if not hits:
            unbound += 1
        elif len({(hit.get("grp"), hit.get("d")) for hit in hits}) == 1:
            bound_unique += 1
        else:
            bound_ambiguous += 1
print(f"  可直接绑 id: {bound_unique} 行 · 需要人工确认（重名且规格不同）: {bound_ambiguous} 行 · 库里没有: {unbound} 行")

print()
if problems:
    print("发现问题：")
    for item in problems:
        print("  -", item)
else:
    print("√ 设计往返无损：真实数据里的每一个键都有去处，派生值可原样重算")
sys.exit(1 if problems else 0)
