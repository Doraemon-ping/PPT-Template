"""线上核对：报表/PPT 服务（/api/ppt-provider/v1）拿到的快照仍然是"逐字段可用"的。

项目信息搬进表之后，这条链路最容易被悄悄改坏（少一个绑定键、图片不再是 data URL），
所以单独查一遍：字段绑定里的项目信息、图片绑定里的内联 data URL、表格绑定里的工序/刀具行/四个库。
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8002"
failures: list[str] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    print(("  √ " if ok else "  × ") + label + (f" → {extra}" if extra else ""))
    if not ok:
        failures.append(label)


def get(path: str):
    try:
        with urllib.request.urlopen(BASE + path, timeout=90) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def pick(bindings: dict, prefix: str):
    """绑定键形如 G_cust_90e189f4eb：前缀匹配取第一个。"""
    for key, value in bindings.items():
        if key.startswith(prefix + "_"):
            return key, value
    return None, None


status, sources = get("/api/ppt-provider/v1/sources")
check("数据源接口可用", status == 200 and bool(sources.get("sources")), str(status))

status, payload = get("/api/ppt-provider/v1/sources/machining-dfm/projects")
check("项目列表接口可用", status == 200 and bool(payload.get("projects")), str(status))
project = payload["projects"][0]
print("     项目:", project["name"], "v" + str(project["revision"]),
      "| 客户:", project.get("customer"), "| 零件:", project.get("part"))

status, snap = get("/api/ppt-provider/v1/sources/machining-dfm/projects/" + project["id"] + "/snapshot")
check("快照接口可用", status == 200 and "data" in snap, str(status))
data = snap.get("data") or {}
fields = data.get("f") or {}
tables = data.get("t") or {}
images = data.get("i") or {}
check("快照结构完整（f/t/i/catalog）", {"f", "t", "i"} <= set(data) and "catalog" in snap, str(sorted(data)))

# 字段绑定：项目信息必须是原值
key, value = pick(fields, "G_cust")
check("客户名称绑定到原值", value == project.get("customer"), f"{key} = {value!r}")
key, value = pick(fields, "G_part")
check("零件名称绑定到原值", value == project.get("part"), f"{key} = {value!r}")
for field in ("hpd", "sft", "dpm", "avl", "prj", "custVer", "dfmDate"):
    key, value = pick(fields, "G_" + field)
    if key is None:
        failures.append(f"字段绑定缺 G_{field}")
        print(f"  × 字段绑定缺 G_{field}")
    else:
        print(f"  √ 字段绑定 G_{field} = {value!r}")

# 图片绑定：产品图片必须内联成 data URL（PPT 要字节，不能是 URL）
key, value = pick(images, "G_pI")
text = value[0] if isinstance(value, list) and value else (value if isinstance(value, str) else "")
check("产品图片内联为 data URL", isinstance(text, str) and text.startswith("data:image/"), f"{key} → {str(text)[:32]}")

# 表格绑定：工序 / 刀具行 / 四个基础库 / 问题清单
for prefix, name in (("pr", "工序"), ("pr_tl", "工序刀具行"), ("mdb", "设备库"), ("tdb", "刀具库"),
                     ("fdb", "夹具库"), ("idb", "检具库"), ("is", "问题清单")):
    key, value = pick(tables, prefix)
    rows = value if isinstance(value, list) else []
    check(f"表格绑定 {name}（{prefix}）非空", bool(rows), f"{key} → {len(rows)} 行")
key, process_rows = pick(tables, "pr")
check("工序里带着刀具行", any((row.get("tl") or []) for row in (process_rows or [])), "")
key, tool_rows = pick(tables, "pr_tl")
check("工序刀具行带刀具名", bool(tool_rows) and bool(tool_rows[0].get("tp")), str((tool_rows or [{}])[0].get("tp")))
check("目录（catalog）五段齐全",
      sorted((snap.get("catalog") or {}).keys()) == ["derived", "fields", "images", "results", "tables"],
      str(sorted((snap.get("catalog") or {}).keys())))
print("     快照大小:", len(json.dumps(data, ensure_ascii=False)) // 1024, "KB｜",
      f"字段 {len(fields)} 个、表格 {len(tables)} 张、图片 {len(images)} 张")

print()
print("全部通过 √" if not failures else "发现问题：\n - " + "\n - ".join(failures))
sys.exit(1 if failures else 0)
