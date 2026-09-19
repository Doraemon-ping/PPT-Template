"""对照前端读取的字段，打印真实接口的响应结构（键名 + 抽样）。"""

from __future__ import annotations

import json
import urllib.request

API = "http://127.0.0.1:8002/api/machining-dfm"


def get(path):
    with urllib.request.urlopen(API + path, timeout=40) as response:
        return json.loads(response.read().decode("utf-8"))


def shape(value, depth=0):
    if isinstance(value, dict):
        return {key: shape(item, depth + 1) for key, item in list(value.items())[:12]} if depth < 2 else "{...}"
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value and depth < 2 else []
    return type(value).__name__


for path in ("/fixtures", "/fixture-centers", "/fixtures/fields", "/gauges", "/gauge-categories"):
    try:
        body = get(path)
    except Exception as error:  # noqa: BLE001
        print(f"{path} -> 错误 {error}")
        continue
    print(f"\n=== {path} ===")
    print("顶层键:", list(body))
    print("结构:", json.dumps(shape(body), ensure_ascii=False)[:600])
    if "rows" in body:
        print("rows 首项:", json.dumps(body["rows"][0] if body["rows"] else None, ensure_ascii=False)[:200])
    if "fixtures" in body:
        print("fixtures 首项:", json.dumps(body["fixtures"][0], ensure_ascii=False)[:260])
    if "gauges" in body:
        print("gauges 首项:", json.dumps(body["gauges"][0], ensure_ascii=False)[:260])
    if "fields" in body:
        spec = body["fields"]
        print("fields 键:", list(spec) if isinstance(spec, dict) else type(spec).__name__)
        if isinstance(spec, dict) and spec.get("fields"):
            print("首字段:", json.dumps(spec["fields"][0], ensure_ascii=False)[:260])
    if "usage" in body:
        print("usage:", json.dumps(body["usage"], ensure_ascii=False)[:200])
