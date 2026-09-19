"""对着正在运行的服务做夹具库 + 检具库全链路自检，跑完把数据还原。

覆盖：字段登记表 / 分组行级 CRUD / 逐字段 PATCH / 图片上传删除 / 类别新增删除（含 cascade）
/ 内置类别保护 / 类别不可改名 / 旧接口 PUT /libraries 兼容 / bootstrap 里的 icnX·fcnX。
用法：python tools/live_fixture_gauge_e2e.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8002"
API = BASE + "/api/machining-dfm"
PNG = b"\x89PNG\r\n\x1a\n" + b"e2e-pixel" * 30


def q(value) -> str:
    """路径里的中文要按 URL 编码（前端用 encodeURIComponent，这里是同一套规则）。"""
    return urllib.parse.quote(str(value), safe="")


def call(path, method="GET", body=None, token="", raw=None, content_type=None):
    request = urllib.request.Request(path if path.startswith("http") else API + path, method=method)
    if token:
        request.add_header("Authorization", "Bearer " + token)
    data = raw
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request.add_header("Content-Type", "application/json")
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, data=data, timeout=40) as response:
            payload = response.read()
            if response.headers.get("Content-Type", "").startswith("application/json"):
                return response.status, json.loads(payload.decode("utf-8"))
            return response.status, payload
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


failures: list[str] = []


def expect(label, ok, detail=""):
    print(("  ✓ " if ok else "  ✗ ") + label + (f" → {detail}" if detail else ""))
    if not ok:
        failures.append(label)


print("== 1. 字段登记表 ==")
for endpoint, headers, first_key in (
    ("/fixtures/fields", ["模具中心", "名称", "价格 ¥", "制造周期 天", "备注"], "center"),
    ("/gauges/fields", ["检具类别", "检具名称", "检具图号", "产品尺寸 mm", "检具尺寸 mm",
                        "价格 万¥", "设计周期 天", "制造周期 天"], "type"),
):
    status, body = call(endpoint)
    labels = [f["label"] + (f" {f['unit']}" if f["unit"] else "") for f in body["fields"]]
    expect(f"{endpoint} 表头", status == 200 and labels == headers, str(labels))
    expect(f"{endpoint} 类别来自字典表", body["fields"][0]["key"] == first_key
           and body["fields"][0].get("references", "").startswith(("fixture_", "gauge_")),
           str(body["fields"][0].get("references")))
    expect(f"{endpoint} 首列下拉非空", len(body["fields"][0]["choices"]) > 0,
           str(len(body["fields"][0]["choices"])))

print("\n== 2. 登录并清理上次中断留下的自检数据 ==")
status, body = call("/auth/login", "POST", {"role": "admin", "password": "TP23456"})
token = body["token"]
expect("admin 登录", status == 200)
status, body = call("/library-dictionaries")
for item in body["centers"]:
    if item["name"].startswith("8888"):
        call("/fixture-centers/" + q(item["name"]) + "?cascade=1", "DELETE", token=token)
        print("  清理遗留模具中心:", item["name"])
for item in body["categories"]:
    if item["name"].startswith("8888"):
        call("/gauge-categories/" + q(item["name"]) + "?cascade=1", "DELETE", token=token)
        print("  清理遗留检具类别:", item["name"])

print("\n== 3. 基础状态（迁移后应有真实数据）==")
status, fixtures = call("/fixtures")
status_g, gauges = call("/gauges")
expect("夹具行数 > 0", fixtures["count"] > 0, str(fixtures["count"]))
expect("检具行数 > 0", gauges["count"] > 0, str(gauges["count"]))
expect("夹具行带 id 与短键", bool(fixtures["fixtures"][0].get("id")) and "center" in fixtures["fixtures"][0])
expect("检具行带 id 与短键", bool(gauges["gauges"][0].get("id")) and "prdSize" in gauges["gauges"][0])

status, dicts = call("/library-dictionaries")
expect("字典接口", status == 200 and len(dicts["centers"]) == 4 and len(dicts["categories"]) == 5,
       f"centers={len(dicts['centers'])} categories={len(dicts['categories'])}")
expect("字典带引用计数", sum(dicts["usage"]["centers"].values()) == fixtures["count"],
       f"{sum(dicts['usage']['centers'].values())} vs {fixtures['count']}")
expect("字典带引用计数（检具）", sum(dicts["usage"]["categories"].values()) == gauges["count"],
       f"{sum(dicts['usage']['categories'].values())} vs {gauges['count']}")
print("  模具中心:", [item["name"] for item in dicts["centers"]])
print("  检具类别:", [item["name"] for item in dicts["categories"]])

print("\n== 4. 未登录写入被拒 ==")
status, _ = call("/fixtures", "POST", {"center": "1025减震模具中心", "name": "越权"})
expect("POST /fixtures 401", status == 401, str(status))
status, _ = call("/fixture-centers", "POST", {"name": "越权中心"})
expect("POST /fixture-centers 401", status == 401, str(status))

print("\n== 5. 自定义模具中心 + 夹具行级 CRUD ==")
status, body = call("/fixture-centers", "POST", {"name": "8888自检模具中心"}, token=token)
expect("新增模具中心", status == 200 and body["row"]["builtin"] is False, str(status))
status, body = call("/fixture-centers", "POST", {"name": "8888自检模具中心"}, token=token)
expect("重复新增 409", status == 409, str(status))
status, body = call("/fixture-centers", "POST", {"name": ""}, token=token)
expect("空名 422", status == 422, str(status))

status, body = call("/fixture-centers/" + q("8888自检模具中心"), "PATCH", {"name": "改个名"}, token=token)
expect("改名 422（外键是中文名）", status == 422, str(body)[:60])
status, body = call("/fixture-centers/" + q("8888自检模具中心"), "PATCH", {"sort_order": 3}, token=token)
expect("改排序 200", status == 200 and body["row"]["sort_order"] == 3, str(status))

status, body = call("/fixtures", "POST",
                    {"center": "8888自检模具中心", "name": "自检夹具", "price": 100, "mc": 5,
                     "rmk": "e2e"}, token=token)
fixture = body["fixture"]
expect("新增夹具", status == 200 and fixture["center"] == "8888自检模具中心"
       and fixture["mc"] == 5 and fixture["photo_url"] is None, str(status))
status, body = call(f"/fixtures/{fixture['id']}", "PATCH", {"price": 250.5}, token=token)
expect("PATCH 单字段（其他字段不动）", status == 200 and body["fixture"]["price"] == 250.5
       and body["fixture"]["name"] == "自检夹具", str(body["fixture"]["price"]))
status, body = call(f"/fixtures/{fixture['id']}", "PATCH", {"center": "万向模具中心"}, token=token)
expect("未知类别 422", status == 422, str(body)[:60])
status, body = call("/fixtures", "POST", {"center": "8888自检模具中心", "name": "越界",
                                          "price": -5}, token=token)
expect("负数价格 422", status == 422, str(body)[:60])

status, body = call(f"/fixtures/{fixture['id']}/photo", "PUT", token=token, raw=PNG,
                    content_type="image/png")
photo_url = body["fixture"]["photo_url"]
expect("上传夹具图片", status == 200 and photo_url.startswith("/api/machining-dfm/assets/"), photo_url)
status, blob = call(BASE + photo_url)
expect("图片可下载且字节一致", status == 200 and blob == PNG, f"{status} {len(blob) if isinstance(blob, bytes) else blob}")
status, body = call(f"/fixtures/{fixture['id']}", "PATCH", {"rmk": "带图"}, token=token)
expect("改字段不影响图片", status == 200 and body["fixture"]["photo_url"] == photo_url, "")
status, body = call(f"/fixtures/{fixture['id']}/photo", "DELETE", token=token)
expect("删除图片", status == 200 and body["fixture"]["photo_url"] is None, "")

status, body = call(f"/fixtures/{fixture['id']}", "DELETE", token=token)
expect("删除夹具", status == 200, str(status))

print("\n== 6. 类别删除保护与级联 ==")
status, body = call("/fixture-centers/" + q("8888自检模具中心"), "DELETE", token=token)
expect("空的自定义类别可删", status == 200, str(status))
status, body = call("/fixture-centers/" + q("1025减震模具中心"), "DELETE", token=token)
expect("内置类别 409（即使为空）", status == 409, str(body)[:60])
status, body = call("/fixture-centers/" + q("1025减震模具中心") + "?cascade=1", "DELETE", token=token)
expect("内置类别带 cascade 也不删", status == 409, str(body)[:60])

# 级联删除必须用自定义类别（内置类别受保护，与刀具分类一致）
status, body = call("/fixture-centers", "POST", {"name": "8888级联模具中心"}, token=token)
expect("新增级联用自定义类别", status == 200, str(status))
status, body = call("/fixtures", "POST",
                    {"center": "8888级联模具中心", "name": "级联自检夹具", "price": 1}, token=token)
cascade_id = body["fixture"]["id"]
status, body = call("/fixture-centers/" + q("8888级联模具中心") + "?cascade=1", "DELETE", token=token)
expect("cascade=1 连同数据删除", status == 200 and body["removed"]["removed_rows"] == 1,
       str(body if isinstance(body, str) else body.get("removed")))
fixture_ids = {row["id"] for row in call("/fixtures")[1]["fixtures"]}
expect("级联行已消失", cascade_id not in fixture_ids, str(cascade_id))
status, body = call("/fixture-centers", "POST", {"name": "8888有数据模具中心"}, token=token)
status, body = call("/fixtures", "POST",
                    {"center": "8888有数据模具中心", "name": "占用自检夹具", "price": 1}, token=token)
occupied_id = body["fixture"]["id"]
status, body = call("/fixture-centers/" + q("8888有数据模具中心"), "DELETE", token=token)
expect("有数据未带 cascade 409", status == 409, str(body)[:70])
status, body = call("/fixture-centers/" + q("8888有数据模具中心") + "?cascade=1", "DELETE", token=token)
expect("带 cascade 后删掉", status == 200 and body["removed"]["removed_rows"] == 1, str(status))

print("\n== 7. 检具库同样一套 ==")
status, body = call("/gauge-categories", "POST", {"name": "8888自检检具类别"}, token=token)
expect("新增检具类别", status == 200, str(status))
status, body = call("/gauges", "POST",
                    {"type": "8888自检检具类别", "name": "自检检具", "drw": "E2E-1",
                     "prdSize": "10*20*30", "inspSize": "40*50*60", "price": 1.5, "dc": 7,
                     "mc": 14}, token=token)
gauge = body["gauge"]
expect("新增检具", status == 200 and gauge["type"] == "8888自检检具类别" and gauge["dc"] == 7, str(status))
status, body = call(f"/gauges/{gauge['id']}", "PATCH", {"price": 2.25}, token=token)
expect("检具 PATCH 单字段", status == 200 and body["gauge"]["price"] == 2.25
       and body["gauge"]["drw"] == "E2E-1", str(body["gauge"]["price"]))
status, body = call("/gauges", "POST", {"type": "不存在类别", "name": "越界"}, token=token)
expect("检具未知类别 422", status == 422, str(body)[:60])
status, body = call("/gauge-categories/" + q("测量支架"), "DELETE", token=token)
expect("内置检具类别 409", status == 409, str(body)[:60])
status, body = call("/gauge-categories/" + q("8888自检检具类别") + "?cascade=1", "DELETE", token=token)
expect("检具类别级联删除", status == 200 and body["removed"]["removed_rows"] == 1,
       str(body.get("removed")))
gauge_ids = {row["id"] for row in call("/gauges")[1]["gauges"]}
expect("级联检具行已消失", gauge["id"] not in gauge_ids, str(gauge["id"]))

print("\n== 8. 旧接口兼容 ==")
status, body = call("/libraries")
expect("GET /libraries 计数", status == 200 and set(body["counts"]) == {"mdb", "tdb", "fdb", "idb"},
       str(body["counts"]))
expect("fdb/idb 是数字计数", isinstance(body["counts"]["fdb"], int) and isinstance(body["counts"]["idb"], int),
       f"{body['counts']['fdb']} {body['counts']['idb']}")
expect("旧读模型仍带 icnX/fcnX", len(body["libraries"]["icnX"]) == 5 and len(body["libraries"]["fcnX"]) == 4,
       f"{len(body['libraries']['icnX'])} {len(body['libraries']['fcnX'])}")
expect("旧短键契约未变", set(body["libraries"]["fdb"][0]) == {"id", "center", "name", "price", "mc", "rmk", "img"}
       and set(body["libraries"]["idb"][0]) == {"id", "type", "name", "drw", "prdSize", "inspSize",
                                                "price", "dc", "mc", "img"},
       str(sorted(set(body["libraries"]["fdb"][0]))))

status, bootstrap = call("/bootstrap")
expect("bootstrap 带 G.icnX/G.fcnX", len(bootstrap["project"]["state"]["G"]["icnX"]) == 5
       and len(bootstrap["project"]["state"]["G"]["fcnX"]) == 4, "")

# 整体保存：只更新命中的行、只补录类别，绝不删数据
target = fixtures["fixtures"][0]
status, body = call("/libraries", "PUT",
                    {"fdb": [{"center": target["center"], "name": target["name"],
                              "price": target["price"], "mc": target["mc"], "rmk": "e2e整体保存", "img": ""}],
                     "idb": [], "icnX": ["毛坯检具", "8888临时检具类别"], "fcnX": []}, token=token)
expect("PUT /libraries 兼容", status == 200 and body["counts"]["fdb"]["updated"] == 1,
       str(body["counts"]["fdb"]))
expect("部分提交不删数据（回归）", body["counts"]["fdb"]["removed"] == []
       and body["counts"]["idb"]["removed"] == [] and call("/fixtures")[1]["count"] == fixtures["count"],
       f"夹具 {call('/fixtures')[1]['count']} vs {fixtures['count']}")
hit = [row for row in call("/fixtures")[1]["fixtures"] if row["id"] == target["id"]]
expect("整体保存改到同一行（id 不变）", len(hit) == 1 and hit[0]["rmk"] == "e2e整体保存", str(len(hit)))
expect("idb 空数组不删数据", call("/gauges")[1]["count"] == gauges["count"], "")
status, body = call("/library-dictionaries")
expect("类别只补录不覆盖", "8888临时检具类别" in [item["name"] for item in body["categories"]]
       and "测量支架" in [item["name"] for item in body["categories"]], "")
status, body = call("/gauge-categories/" + q("8888临时检具类别"), "DELETE", token=token)
expect("清理临时类别", status == 200, str(status))

print("\n== 9. 还原数据 ==")
status, body = call(f"/fixtures/{target['id']}", "PATCH", {"rmk": target["rmk"]}, token=token)
expect("备注已还原", status == 200 and body["fixture"]["rmk"] == target["rmk"], repr(target["rmk"]))
status, fixtures_after = call("/fixtures")
status, gauges_after = call("/gauges")
expect("夹具行数还原", fixtures_after["count"] == fixtures["count"],
       f"{fixtures_after['count']} vs {fixtures['count']}")
expect("检具行数还原", gauges_after["count"] == gauges["count"], f"{gauges_after['count']} vs {gauges['count']}")
status, dicts_after = call("/library-dictionaries")
expect("字典还原", len(dicts_after["centers"]) == 4 and len(dicts_after["categories"]) == 5,
       f"{len(dicts_after['centers'])} {len(dicts_after['categories'])}")

print("\n" + ("全部通过 ✓" if not failures else "失败项:\n - " + "\n - ".join(failures)))
raise SystemExit(1 if failures else 0)
