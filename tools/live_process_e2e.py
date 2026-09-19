"""工序落表（1b）线上全链路自检：对着**运行中的服务**验证"表 ↔ 读模型"一致、行级保存生效。

只在迁移之后有意义（开关关着时自动跳过，退出码 0）。为了不污染线上数据，
只做**可逆**的动作：把某个刀具行的一个字段改成哨兵值 → 核对读模型与版本快照 → 再改回原值。
中间任何一步失败都会在 finally 里把原值写回去。

用法：
    python tools/live_process_e2e.py
    python tools/live_process_e2e.py --base http://127.0.0.1:8002
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

SENTINEL = 1234.5


def call(base: str, path: str, *, method: str = "GET", payload: dict | None = None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read().decode("utf-8"))
        except ValueError:
            return error.code, {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8002")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    projects = call(base, "/api/machining-dfm/projects")[1]["projects"]
    if not projects:
        print("线上没有项目，跳过")
        return 0
    project = projects[0]
    pid = project["id"]
    print(f"项目：{project['name']} · v{project['revision']}")

    status, listing = call(base, f"/api/machining-dfm/projects/{pid}/processes")
    if status == 404:
        print("× 服务上没有工序接口（HTTP 404）：跑着的还是老进程，重启 run_service.py 再验。")
        return 1
    if status == 409:
        print("工序落表还没启用（开关关着），跳过。迁移后请重跑本自检。")
        return 0
    if status != 200:
        print(f"× 读工序列表失败：HTTP {status} {listing}")
        return 1

    problems: list[str] = []
    processes = listing["processes"]
    print(f"工序行 {len(processes)} 道 · 刀具行 {sum(len(row.get('tools') or []) for row in processes)} 行"
          f" · 回收站 {len(listing['deleted_processes'])}/{len(listing['deleted_tools'])}")

    # 1) 表 ↔ 读模型一致
    read_model = call(base, f"/api/machining-dfm/projects/{pid}")[1]["state"]["pr"]
    if len(read_model) != len(processes):
        problems.append(f"工序数不一致：表 {len(processes)} vs 读模型 {len(read_model)}")
    for index, row in enumerate(processes):
        legacy = read_model[index] if index < len(read_model) else {}
        for key in ("nm", "mc", "mid"):
            if row.get(key) != legacy.get(key):
                problems.append(f"工序 {index} 的 {key}：表 {row.get(key)!r} vs 读模型 {legacy.get(key)!r}")
        tools = row.get("tools") or []
        legacy_tools = legacy.get("tl") or []
        if len(tools) != len(legacy_tools):
            problems.append(f"工序 {index} 刀具行数：表 {len(tools)} vs 读模型 {len(legacy_tools)}")
        for position, tool in enumerate(tools):
            if position >= len(legacy_tools):
                break
            if tool.get("code") != legacy_tools[position].get("id"):
                problems.append(f"工序 {index} 刀具 {position} 刀号：表 {tool.get('code')!r} "
                                f"vs 读模型 {legacy_tools[position].get('id')!r}")
            if abs(float(tool.get("vf") or 0) - float(legacy_tools[position].get("vf") or 0)) > 1e-9:
                problems.append(f"工序 {index} 刀具 {position} 的 vf 表里与读模型不一致")
    print("  " + ("√ 表里的工序/刀具行与读模型逐项一致" if not problems else "× 表与读模型有出入"))

    # 2) 行级保存：改一个字段 → 读模型与版本快照都要跟着变 → 再改回去
    tool = None
    for row in processes:
        if row.get("tools"):
            tool = row["tools"][0]
            break
    if tool is None:
        print("  没有刀具行，跳过行级保存检查")
    else:
        original = tool.get("vf")
        print(f"\n行级保存检查（刀具行 {tool['id']} · vf：{original} → {SENTINEL} → 回 {original}）")
        try:
            status, result = call(base, f"/api/machining-dfm/projects/{pid}/tools/{tool['id']}",
                                  method="PATCH", payload={"vf": SENTINEL})
            if status != 200:
                problems.append(f"行级 PATCH 失败：HTTP {status} {result}")
            else:
                record = result["project"]
                patched = [item for row in record["state"]["pr"] for item in (row.get("tl") or [])
                           if item.get("id") == tool.get("code")]
                if patched and abs(float(patched[0].get("vf") or 0) - SENTINEL) < 1e-9:
                    print(f"  √ 读模型已更新（v{record['revision']}）")
                else:
                    problems.append("PATCH 之后读模型里的 vf 没变")
                snapshot = call(base, f"/api/machining-dfm/projects/{pid}?revision={record['revision']}")[1]
                snapshot_tools = [item for row in snapshot["state"]["pr"] for item in (row.get("tl") or [])
                                  if item.get("id") == tool.get("code")]
                if snapshot_tools and abs(float(snapshot_tools[0].get("vf") or 0) - SENTINEL) < 1e-9:
                    print(f"  √ 版本 v{record['revision']} 的快照里也是新值（每次保存都留版本）")
                else:
                    problems.append(f"版本 v{record['revision']} 的快照里没有新值")
        finally:
            status, result = call(base, f"/api/machining-dfm/projects/{pid}/tools/{tool['id']}",
                                  method="PATCH", payload={"vf": original})
            if status == 200:
                back = [item for row in result["project"]["state"]["pr"] for item in (row.get("tl") or [])
                        if item.get("id") == tool.get("code")]
                if back and abs(float(back[0].get("vf") or 0) - float(original or 0)) < 1e-9:
                    print(f"  √ 已改回原值 {original}（v{result['project']['revision']}）")
                else:
                    problems.append("改回原值失败：读模型里的 vf 不是原值")
            else:
                problems.append(f"改回原值失败：HTTP {status} {result}")

    print()
    if problems:
        print("× 线上自检发现问题：")
        for item in problems[:20]:
            print("  -", item)
        return 1
    print("√ 线上自检通过：表与读模型一致，行级保存生效且每次都留了版本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
