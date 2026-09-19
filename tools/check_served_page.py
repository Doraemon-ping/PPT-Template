"""检查线上页面：脚本/样式标签版本号是否统一、静态资源是否都 200（含曾经的 404 host.css）。"""

from __future__ import annotations

import re
import urllib.request

BASE = "http://127.0.0.1:8002"
html = urllib.request.urlopen(BASE + "/machining-dfm", timeout=30).read().decode("utf-8")

assets = re.findall(r'<(?:script src|link[^>]+href)="([^"]+)"', html)
assets = [a for a in assets if a.startswith("/static/")]
print("页面引用的静态资源:")
versions = set()
failed = []
for asset in assets:
    versions.add(asset.split("?v=")[-1] if "?v=" in asset else "(无版本号)")
    try:
        with urllib.request.urlopen(BASE + asset, timeout=30) as response:
            body = response.read()
        print(f"  HTTP {response.status} {len(body):>8} {asset}")
        if response.status != 200:
            failed.append(asset)
    except Exception as error:  # noqa: BLE001
        print(f"  HTTP 失败      {asset} → {error}")
        failed.append(asset)

print("版本号统一:", ", ".join(sorted(versions)))
print("版本号数量为 1:", len(versions) == 1)
print("全部 200:", not failed, failed)
