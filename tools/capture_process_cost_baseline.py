"""把"改造前的成本数字"冻结成基线（只读，写一份 JSON 到 tools/baselines/）。

1b 阶段把工序/刀具行落表、把刀具引用从名字改成 id 之后，验收的铁律是**报价数字逐位不变**。
没有改造前的基线就无从比对，所以先冻一份：

1. `pr[]` 的每个业务字段（图片键只记哈希，避免把 59 KB data URL 写进仓库）；
2. 每个刀具行的全部字段 + 前端 `calcT()` 重算出的 `_ct/_vc/_vf/_fz`（同时比对"库里存的派生值"是否已经过期）；
3. 按前端 `toolCost()` 的现行语义（按刀具名找库行、取 price/life）算出的每行成本与合计；
4. 夹具/检具选型的键与费用合计；
5. 整体指纹（sha256），改造后任何一处数字变化都能被立刻发现。
   **指纹不含 `revision`**：它是"保存过几次"的计数，不是报价数字——冻结基线之后项目又保存过
   几次，也照样应该是"完全一致"（否则这条判据每次保存都会变红，等于没用）。

用法：
    python tools/capture_process_cost_baseline.py            # 打印 + 写基线
    python tools/capture_process_cost_baseline.py --check    # 只比对当前值与基线，不覆盖
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_dfm import MachiningDFMStore  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tools" / "baselines" / "process_cost_baseline.json"
IMAGE_KEYS = ("cI",)


# ---------------- 前端公式（legacy_app.js 的 calcT / toolCost / fixQuote / inspQuote）----------------

def calc_t(tool: dict) -> dict:
    n = tool.get("n") or 0
    vf = tool.get("vf") or 0
    ln = tool.get("ln") or 0
    ps = tool.get("ps") or 0
    cn = tool.get("cn") or 0
    return {
        "_ct": (ln / vf * 60) * ps * cn if vf > 0 else 0,
        "_vc": round(math.pi * (tool.get("d") or 0) * n / 1000),
        "_vf": vf,
        "_fz": vf / n if n > 0 else 0,
    }


def tool_cost(tool: dict, tools_by_name: dict) -> tuple[float, float, float]:
    """现行语义：按刀具名找库行（重名取第一行），life>0 才给 price/life。"""
    hits = tools_by_name.get(str(tool.get("tp") or ""))
    if not hits:
        return 0.0, 0.0, 0.0
    price, life = hits[0].get("price") or 0, hits[0].get("life") or 0
    return (price / life if life > 0 else 0.0), price, life


def shorten_images(payload):
    """图片键只留哈希与长度：基线要能进 git，不能塞 data URL。"""
    if isinstance(payload, dict):
        out = {}
        for key, value in payload.items():
            if key in IMAGE_KEYS and isinstance(value, str) and value:
                out[key] = {"sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], "chars": len(value)}
            else:
                out[key] = shorten_images(value)
        return out
    if isinstance(payload, list):
        return [shorten_images(item) for item in payload]
    if isinstance(payload, float):
        return round(payload, 6)
    return payload


def build() -> dict:
    store = MachiningDFMStore(ROOT / "data" / "machining_dfm", ROOT / "app" / "resources" / "machining_dfm_seed")
    project = store.list()[0]
    state = store.get(project["id"])["state"]
    tools = state["tdb"]
    tools_by_name: dict[str, list[dict]] = {}
    for tool in tools:
        tools_by_name.setdefault(str(tool.get("tp") or ""), []).append(tool)

    processes, tool_total, stale_derived, missing_tool, unbound_price = [], 0.0, [], [], 0
    for index, process in enumerate(state["pr"]):
        rows = []
        for row in process.get("tl") or []:
            recomputed = calc_t(row)
            stored = {key: row.get(key) for key in ("_ct", "_vc", "_vf", "_fz")}
            if any(
                abs(float(stored[key] or 0) - float(recomputed[key] or 0)) > 1e-6
                for key in ("_ct", "_vc", "_vf", "_fz")
            ):
                stale_derived.append({"process": process.get("nm"), "code": row.get("id"), "stored": stored, "recomputed": recomputed})
            cost, price, life = tool_cost(row, tools_by_name)
            if not tools_by_name.get(str(row.get("tp") or "")):
                missing_tool.append({"process": process.get("nm"), "code": row.get("id"), "tp": row.get("tp")})
            if price == 0 and life == 0:
                unbound_price += 1
            tool_total += cost
            rows.append({"fields": shorten_images(row), "recomputed": recomputed, "cost_per_min": round(cost, 8),
                         "library_price": price, "library_life": life})
        processes.append({
            "index": index,
            "fields": shorten_images({key: value for key, value in process.items() if key != "tl"}),
            "tool_rows": rows,
            "tool_cost_sum": round(sum(row["cost_per_min"] for row in rows), 8),
        })

    general = state["G"]
    fixtures = {}
    for key in ("fixQ", "fixQC", "insp", "inspQ"):
        fixtures[key] = general.get(key)
    # 选型合计：按 G 的键去夹具/检具库取价（前端 fixQuoteTable / inspQuoteTable 的口径）
    fixture_db, gauge_db = state["fdb"], state["idb"]
    fixture_total, gauge_total = 0.0, 0.0
    for slot, key in enumerate(general.get("fixQ") or []):
        if not key:
            continue
        center, _, name = str(key).partition("|")
        for row in fixture_db:
            if (row.get("center") or "") == center and (row.get("name") or "") == name:
                fixture_total += row.get("price") or 0
                break
    for slot, key in enumerate(general.get("insp") or []):
        if not key:
            continue
        parts = str(key).split("|")
        if len(parts) < 3:
            continue
        for row in gauge_db:
            if (row.get("type") or "") == parts[0] and (row.get("name") or "") == parts[1] and (row.get("drw") or "") == parts[2]:
                gauge_total += row.get("price") or 0
                break

    payload = {
        "project": {"id": project["id"], "name": project["name"], "revision": project["revision"]},
        "processes": processes,
        "totals": {
            "tool_cost_per_min": round(tool_total, 8),
            "fixture_price_sum": round(fixture_total, 4),
            "gauge_price_sum": round(gauge_total, 4),
            "process_count": len(state["pr"]),
            "tool_row_count": sum(len(process.get("tl") or []) for process in state["pr"]),
        },
        "selections": fixtures,
        "diagnostics": {
            "stale_derived_rows": stale_derived,
            "tool_rows_not_found_in_library": missing_tool,
            "tool_rows_with_zero_library_price": unbound_price,
        },
    }
    payload["fingerprint"] = fingerprint(payload)
    return payload


#: 算指纹时**排除**的项目字段：`revision` 每次保存都会涨，它涨**不代表**报价数字变了。
#: （原来把它算进指纹里，于是"冻结基线之后又保存过几次"就会报"与基线不一致"——
#:   2026-09-18 迁移当天就是这样：基线冻在 v41，线上已经到 v65，业务数字一位没变却红了。）
FINGERPRINT_SKIP = ("revision",)


def fingerprint(payload: dict) -> str:
    """业务数字的指纹（不含 `revision` 这类"只表示保存过几次"的字段）。"""
    data = json.loads(json.dumps(payload, ensure_ascii=False))
    for key in FINGERPRINT_SKIP:
        data.get("project", {}).pop(key, None)
    data.pop("fingerprint", None)
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="与已有基线比对，不覆盖")
    args = parser.parse_args()

    current = build()
    print("=== 项目 ===")
    print(" ", current["project"]["name"], "v" + str(current["project"]["revision"]))
    print("=== 合计 ===")
    for key, value in current["totals"].items():
        print(f"  {key:26s} = {value}")
    print("=== 诊断 ===")
    diagnostics = current["diagnostics"]
    print(f"  派生值已过期的行        : {len(diagnostics['stale_derived_rows'])}")
    for row in diagnostics["stale_derived_rows"][:5]:
        print(f"      {row['process']} / {row['code']}: 存 {row['stored']} ≠ 重算 {row['recomputed']}")
    print(f"  按名字在刀具库找不到的行 : {len(diagnostics['tool_rows_not_found_in_library'])}")
    print(f"  库价/寿命为 0 的行       : {diagnostics['tool_rows_with_zero_library_price']}")
    print("  指纹:", current["fingerprint"])

    if args.check:
        if not BASELINE.is_file():
            print("\n没有基线文件可比：", BASELINE)
            return 2
        previous = json.loads(BASELINE.read_text(encoding="utf-8"))
        # 两侧都按**当前**规则重算指纹：老基线文件里那个值可能带着 revision（规则改过）
        if fingerprint(previous) == current["fingerprint"]:
            print("\n√ 与基线完全一致（指纹 " + current["fingerprint"] + "）")
            return 0
        print("\n× 与基线不一致！逐项差异：")
        for key in previous["totals"]:
            if previous["totals"][key] != current["totals"][key]:
                print(f"    {key}: 基线 {previous['totals'][key]} → 现在 {current['totals'][key]}")
        for index, process in enumerate(previous["processes"]):
            now = current["processes"][index] if index < len(current["processes"]) else {}
            if process.get("fields") != now.get("fields"):
                print(f"    工序 {index} 字段变了：{process.get('fields')} → {now.get('fields')}")
            for row_index, row in enumerate(process.get("tool_rows", [])):
                now_row = (now.get("tool_rows") or [])[row_index] if index < len(current["processes"]) and row_index < len(now.get("tool_rows") or []) else {}
                if row.get("cost_per_min") != now_row.get("cost_per_min"):
                    print(f"    工序 {index} 刀具行 {row_index} 成本变了：{row.get('cost_per_min')} → {now_row.get('cost_per_min')}")
        if previous.get("selections") != current.get("selections"):
            print(f"    选型四个数组变了：{previous.get('selections')} → {current.get('selections')}")
        if previous.get("diagnostics") != current.get("diagnostics"):
            print(f"    诊断变了：{previous.get('diagnostics')} → {current.get('diagnostics')}")
        print(f"    基线保存于 v{previous.get('project', {}).get('revision')}，现在是"
              f" v{current['project']['revision']}（revision 不参与指纹：只表示又保存过几次）")
        print("    基线指纹", fingerprint(previous), "现在指纹", current["fingerprint"])
        return 1

    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(current, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("\n基线已写入:", BASELINE.relative_to(ROOT), f"（{BASELINE.stat().st_size / 1024:.1f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
