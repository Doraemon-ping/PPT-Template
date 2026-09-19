"""对着正在运行的服务做一次刀具库全链路自检（建 → 改 → 传图 → 排序 → 删），随后清理。

用法：python tools/live_tool_e2e.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8002"
PNG = b"\x89PNG\r\n\x1a\n" + b"e2e-pixel" * 30


def call(path, method="GET", body=None, token="", raw=None, content_type=None):
    request = urllib.request.Request(BASE + path, method=method)
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


status, body = call("/api/machining-dfm/tools")
print("GET /tools:", status, "count =", body["count"])
before = body["count"]

status, body = call("/api/machining-dfm/auth/login", "POST",
                    {"role": "admin", "password": "TP23456"})
token = body["token"]
print("登录 admin:", status)

status, body = call("/api/machining-dfm/tools", "POST",
                    {"grp": "hp", "tp": "自检临时刀具", "cat": "hm", "d": 12, "ln": 75,
                     "n": 4000, "vf": 900, "life": 120, "price": 260}, token=token)
tool = body["tool"]
print("POST 新增:", status, tool["tp"], tool["id"], "count =", body["count"])

status, body = call(f"/api/machining-dfm/tools/{tool['id']}", "PATCH", {"price": 300}, token=token)
print("PATCH 单字段:", status, "price =", body["tool"]["price"], "| tp 未动 =", body["tool"]["tp"])

status, body = call(f"/api/machining-dfm/tools/{tool['id']}", "PATCH", {"cat": "不存在"}, token=token)
print("PATCH 非法类型:", status, str(body)[:80])

status, body = call(f"/api/machining-dfm/tools/{tool['id']}/photo", "PUT",
                    token=token, raw=PNG, content_type="image/png")
photo_url = body["tool"]["photo_url"]
print("PUT 图片:", status, photo_url)

status, payload = call(photo_url)
print("GET 图片:", status, "字节一致 =", payload == PNG)

status, body = call(f"/api/machining-dfm/tools/{tool['id']}/photo", "PUT",
                    token=token, raw=b"pk", content_type="application/zip")
print("PUT 非法类型:", status, str(body)[:60])

status, body = call("/api/machining-dfm/tools/reorder", "POST", {"ids": [tool["id"]]}, token=token)
print("POST 排序（不完整列表）:", status, str(body)[:80])

status, body = call(f"/api/machining-dfm/tools/{tool['id']}", "DELETE", token=token)
print("DELETE:", status, "remaining =", body["removed"]["remaining"], "| 引用项目 =", len(body["usage"]))

status, body = call("/api/machining-dfm/tools")
print("GET /tools 复查:", status, "count =", body["count"], "回到原值 =", body["count"] == before)
status, body = call("/api/machining-dfm/libraries")
print("夹具/检具/设备未受影响:", body["counts"])

print()
print("=== 字典表（库分类 / 类型）自检 ===")

status, state = call("/api/machining-dfm/tool-dictionaries")
print("GET /tool-dictionaries:", status,
      "| 库分类", len(state["groups"]), "项:", [item["code"] for item in state["groups"]],
      "| 类型", len(state["categories"]), "项")

status, fields = call("/api/machining-dfm/tools/fields")
cat_field = [item for item in fields["fields"] if item["key"] == "cat"][0]
print("字段登记表类型下拉:", len(cat_field["choices"]), "项，首个 =", cat_field["choices"][0],
      "| references =", cat_field.get("references"))
print("字典驱动的归属:", [(item["value"], item["scope"]) for item in cat_field["choices"] if item["scope"] == "nc"])

status, body = call("/api/machining-dfm/tool-categories", "POST",
                    {"code": "e2e1", "label": "自检类型", "scope": "cut"}, token=token)
print("POST 自定义类型:", status, body["category"] if status == 200 else str(body)[:80])

status, body = call("/api/machining-dfm/tools", "POST",
                    {"grp": "hld", "tp": "归属自检刀具", "cat": "e2e1"}, token=token)
print("POST 归属不符（刀柄 + 切削类型）:", status, str(body)[:100])

status, body = call("/api/machining-dfm/tools", "POST",
                    {"grp": "hp", "tp": "自检字典刀具", "cat": "e2e1"}, token=token)
dict_tool = body["tool"]
print("POST 使用自定义类型:", status, dict_tool["cat"])

status, body = call("/api/machining-dfm/tool-categories/e2e1", "DELETE", token=token)
print("DELETE 被引用的类型:", status, str(body)[:100])

status, body = call("/api/machining-dfm/tool-groups/hp", "PATCH",
                    {"label": "高压项目刀具（自检改名）"}, token=token)
renamed = status == 200
status2, fields = call("/api/machining-dfm/tools/fields")
grp_field = [item for item in fields["fields"] if item["key"] == "grp"][0]
shown = [item["label"] for item in grp_field["choices"] if item["value"] == "hp"][0]
print("PATCH 改内置分类名称:", status, "→ 字段登记表显示:", shown)
call("/api/machining-dfm/tool-groups/hp", "PATCH", {"label": "高压项目刀具"}, token=token)
status, fields = call("/api/machining-dfm/tools/fields")
grp_field = [item for item in fields["fields"] if item["key"] == "grp"][0]
restored = [item["label"] for item in grp_field["choices"] if item["value"] == "hp"][0]
print("名称已还原:", restored, "| 还原成功 =", restored == "高压项目刀具" and renamed)

status, body = call("/api/machining-dfm/tool-groups/hp", "DELETE", token=token)
print("DELETE 内置库分类:", status, str(body)[:100])
status, body = call("/api/machining-dfm/tool-categories/hm", "DELETE", token=token)
print("DELETE 内置类型:", status, str(body)[:100])

status, body = call(f"/api/machining-dfm/tools/{dict_tool['id']}", "DELETE", token=token)
print("清理刀具:", status, "remaining =", body["removed"]["remaining"])
status, body = call("/api/machining-dfm/tool-categories/e2e1", "DELETE", token=token)
print("清理自定义类型:", status, body.get("removed") if status == 200 else str(body)[:80])
status, state = call("/api/machining-dfm/tool-dictionaries")
print("字典复查: 库分类", len(state["groups"]), "项 / 类型", len(state["categories"]), "项 | 使用计数", state["usage"])
status, body = call("/api/machining-dfm/tools")
print("刀具总数回到原值 =", body["count"] == before, "(", body["count"], ")")
