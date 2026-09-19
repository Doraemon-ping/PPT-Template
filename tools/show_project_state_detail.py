"""看工序/选型/版本快照里的具体内容（只读，判断外键与派生字段的现状）。"""

from __future__ import annotations

import io
import json
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

db = sqlite3.connect("file:data/machining_dfm/machining_dfm.sqlite3?mode=ro", uri=True)
db.row_factory = sqlite3.Row
state = json.loads(db.execute("SELECT state_json FROM projects ORDER BY updated DESC LIMIT 1").fetchone()["state_json"])
globals_ = state["G"]

print("=== 工序列表 ===")
for index, process in enumerate(state["pr"]):
    tools = process.get("tl", [])
    print(f"  [{index}] nm={process.get('nm')!r} mc={process.get('mc')!r} mid={process.get('mid')!r} cI={'有图' if process.get('cI') else None} tl={len(tools)} fixP={process.get('fixP')} eqP={process.get('eqP')}")

print("\n=== 刀具行样本（第 1 条完整）===")
row = state["pr"][0]["tl"][0]
for key, value in row.items():
    shown = f"<{len(value)/1024:.1f}KB 图片>" if isinstance(value, str) and len(value) > 2000 else value
    print(f"  {key:6s} = {shown!r}")

print("\n=== 刀具行的 id / tp 与刀具库的对应 ===")
tools_db = [dict(r) for r in db.execute("SELECT id,tp,grp,cat FROM tools LIMIT 400")]
by_tp = {}
for item in tools_db:
    by_tp.setdefault(item["tp"], []).append(item["id"])
for row in state["pr"][0]["tl"][:6]:
    matched = by_tp.get(row.get("tp"), [])
    print(f"  tl.id={str(row.get('id'))[:16]!r} tp={row.get('tp')!r} 刀具库里同名 {len(matched)} 条")

print("\n=== 夹具/检具选型（名称引用）===")
print("  G.fixQ :", json.dumps(globals_.get("fixQ"), ensure_ascii=False)[:300])
print("  G.fixQC:", json.dumps(globals_.get("fixQC"), ensure_ascii=False)[:200])
print("  G.insp :", json.dumps(globals_.get("insp"), ensure_ascii=False)[:300])
print("  G.inspQ:", json.dumps(globals_.get("inspQ"), ensure_ascii=False)[:200])
print("  G.icnX :", json.dumps(globals_.get("icnX"), ensure_ascii=False)[:200])
print("  G.fcnX :", json.dumps(globals_.get("fcnX"), ensure_ascii=False)[:200])

print("\n=== 版本快照 G._vSnap ===")
snap = globals_.get("_vSnap") or {}
for key, value in list(snap.items())[:12]:
    print(f"  {key:8s} → {str(value)[:80]}")

print("\n=== 问题清单 ===")
for issue in state["is"]:
    print("  ", json.dumps({k: v for k, v in issue.items()}, ensure_ascii=False)[:220])

print("\n=== 图片类字段现状 ===")
print("  G.pI 是 data URL:", str(globals_.get("pI"))[:40])
print("  工序 cI 是 data URL:", str(state["pr"][0].get("cI"))[:40])
