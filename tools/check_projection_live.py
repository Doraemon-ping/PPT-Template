"""真实数据上跑一遍投影链（成本表/PPT 用）：确认四个库拆表后结果照旧。

链路与线上一致：`store.compose(project.state)` → `report_runtime` → `normalize`（DFM 适配器）。
用法：python tools/check_projection_live.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.machining_dfm import MachiningDFMStore  # noqa: E402
from app.machining_projection import report_runtime  # noqa: E402
from app.native_forms import normalize  # noqa: E402

store = MachiningDFMStore(ROOT / "data" / "machining_dfm", ROOT / "app" / "resources" / "machining_dfm_seed")
projects = store.list()
print("项目数:", len(projects))

with_fixture_choice = 0
with_gauge_choice = 0
for item in projects:
    project = store.get(item["id"])
    state = project["state"]
    composed = store.compose(state)
    general = state.get("G") or {}
    fix_q = general.get("fixQ") or []
    insp = general.get("insp") or []
    data, catalog = normalize(report_runtime(composed), include_legacy_aliases=False)
    data.pop("runtime", None)
    if fix_q:
        with_fixture_choice += 1
    if insp:
        with_gauge_choice += 1
    if fix_q or insp:
        print(f"  {item['name'][:26]:28} 夹具选型 {len(fix_q)} 检具选型 {len(insp)}"
              f" | 投影 f={len(data.get('f') or [])} i={len(data.get('i') or [])}"
              f" t={len(data.get('t') or [])} derived={len(data.get('derived') or [])}"
              f" | 目录 {len(catalog)}")

# 抽查：选型键要能在库里查到价格（拆表后价格仍在旧短键上）
composed = store.compose(store.get(projects[0]["id"])["state"])
fixtures = {f"{row['center']}|{row['name']}": row for row in composed["fdb"]}
gauges = {f"{row['type']}|{row['name']}|{row['drw']}": row for row in composed["idb"]}
print("夹具库条目:", len(fixtures), "检具库条目:", len(gauges))
sample_fixture = next(iter(fixtures.items()))
sample_gauge = next(iter(gauges.items()))
print("  夹具样例:", sample_fixture[0][:40], "价格", sample_fixture[1]["price"], "周期", sample_fixture[1]["mc"])
print("  检具样例:", sample_gauge[0][:40], "价格", sample_gauge[1]["price"], "设计", sample_gauge[1]["dc"])
print("有夹具选型的项目:", with_fixture_choice, "| 有检具选型的项目:", with_gauge_choice)
print("完成（无异常）")
