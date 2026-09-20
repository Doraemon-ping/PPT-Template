"""重构安全网：递归导出 FastAPI 应用的全部路由（含新版懒加载 _IncludedRouter）。

用法：.venv\\Scripts\\python.exe tools_audit/dump_routes.py <输出文件>
重构前后各跑一次，逐条 diff，证明 HTTP 契约没有增减。
"""
import json
import sys
from pathlib import Path


def walk(routes, prefix=""):
    """把一个 app/router 的 routes 摊平成 [(方法, 完整路径, 端点名)]。"""
    found = []
    for route in routes:
        kind = type(route).__name__
        if kind == "_IncludedRouter":
            # 新版 FastAPI 把 include_router 的结果包成节点，前缀藏在 include_context 里
            ctx = getattr(route, "include_context", None)
            sub_prefix = getattr(ctx, "prefix", "") or ""
            found.extend(walk(getattr(route.original_router, "routes", []), prefix + sub_prefix))
            continue
        path = getattr(route, "path", None)
        if path is None:
            continue
        methods = sorted(getattr(route, "methods", None) or [])
        if methods:
            for method in methods:
                found.append({"method": method, "path": prefix + path,
                              "name": getattr(route, "name", "")})
        else:
            found.append({"method": "", "path": prefix + path,
                          "name": getattr(route, "name", "")})
    return found


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    # 重构后统一走 app.main:create_app；重构前只有 app.services.machining:app，做个兜底
    try:
        from app.main import create_app
        app = create_app()
    except ImportError:
        from app.services.machining import app
    entries = sorted(walk(app.routes), key=lambda item: (item["path"], item["method"]))
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "routes.json")
    target.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(entries)} 条路由 → {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
