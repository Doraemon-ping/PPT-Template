"""列出机加 DFM 的路由（只读），确认 1b 的工序接口都注册上了。"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.machining_dfm import router_for  # noqa: E402

router = router_for(lambda: None, Path("static/machining_dfm"))
targets = ("processes", "tools/{tool_id}", "project-settings", "photos/{slot}")
print("1b 工序接口：")
for route in router.routes:
    path = getattr(route, "path", "")
    if "/processes" in path or "/tools/{tool_id}" in path:
        methods = ",".join(sorted(getattr(route, "methods", []) or []))
        print(f"  {methods:22s} {path}")
print()
print("总路由数:", len(router.routes))
