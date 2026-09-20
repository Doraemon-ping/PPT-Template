# -*- coding: utf-8 -*-
"""重构后的真机冒烟：用真库、真路由、真 HTTP 打一遍主要读写链路。

不改动生产库：整个 data 目录先复制到临时目录，再让应用指向那份副本。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="dfm_smoke_"))
shutil.copytree(ROOT / "data", WORK / "data")

# 让应用把可写数据根指到临时副本：冒烟里的写入绝不落到生产库
os.environ["DFM_APP_ROOT"] = str(WORK)
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.deps import build_store  # noqa: E402
from app.core.config import DATA_DIR, SEED_DIR  # noqa: E402
from app.main import create_app  # noqa: E402

ROOT_DIR = DATA_DIR / "machining_dfm"
SEED_FILE = SEED_DIR
print("可写数据根:", DATA_DIR)
print("库目录:", ROOT_DIR)
print("种子目录:", SEED_FILE.is_dir(), SEED_FILE)
assert Path(DATA_DIR).is_relative_to(WORK), f"数据根没指到临时目录：{DATA_DIR}"

app = create_app()
client = TestClient(app)
failures = []


def check(label, condition, detail=""):
    print(f"  {'√' if condition else '×'} {label}" + (f"  {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(f"{label} {detail}")


print("\n== 1. 基础端点 ==")
r = client.get("/health")
check("GET /health 200", r.status_code == 200, r.text[:80])
check("契约版本 1.0", r.json().get("contract_version") == "1.0", r.text[:80])
r = client.get("/")
check("GET / 跳转单页", r.status_code in (200, 307), str(r.status_code))
r = client.get("/machining-dfm")
check("GET /machining-dfm 有页面", r.status_code == 200 and b"<html" in r.content[:400].lower())

print("\n== 2. 引导与项目 ==")
r = client.get("/api/machining-dfm/bootstrap")
check("bootstrap 200", r.status_code == 200, r.text[:120])
boot = r.json() if r.status_code == 200 else {}
check("bootstrap 带 project/projects/config",
      {"project", "projects", "config"} <= set(boot), str(list(boot)))
project_id = boot.get("project", {}).get("id")
check("拿到项目 id", bool(project_id), str(project_id))

r = client.get(f"/api/machining-dfm/projects/{project_id}")
check("读项目 200", r.status_code == 200, r.text[:120])
model = r.json()
check("读模型有 G/pr/is/vh", {"G", "pr", "is", "vh"} <= set(model.get("state", {})), str(list(model.get("state", {}))))

print("\n== 3. 登录与权限 ==")
r = client.post("/api/machining-dfm/auth/login", json={"role": "admin", "password": "TP23456"})
check("管理员登录 200", r.status_code == 200, r.text[:120])
token = r.json().get("token") if r.status_code == 200 else None
check("拿到令牌", bool(token))
auth = {"Authorization": f"Bearer {token}"}
r = client.post("/api/machining-dfm/auth/login", json={"role": "admin", "password": "wrong"})
check("错口令 401", r.status_code == 401, str(r.status_code))
r = client.post("/api/machining-dfm/machines", json={"name": "偷偷加设备"})
check("无令牌写库 401", r.status_code == 401, str(r.status_code))

print("\n== 4. 基础库（设备/刀具/夹具/检具） ==")
for path, key in (("machines", "machines"), ("tools", "tools"), ("fixtures", "fixtures"), ("gauges", "gauges")):
    r = client.get(f"/api/machining-dfm/{path}")
    body = r.json() if r.status_code == 200 else {}
    check(f"GET /{path} 200 且带 {key}/fields/count",
          r.status_code == 200 and {key, "fields", "count"} <= set(body), r.text[:100])

r = client.get("/api/machining-dfm/fixture-centers")
check("GET /fixture-centers 200", r.status_code == 200, r.text[:100])
r = client.get("/api/machining-dfm/gauge-categories")
check("GET /gauge-categories 200", r.status_code == 200, r.text[:100])
r = client.get("/api/machining-dfm/library-dictionaries")
check("GET /library-dictionaries 200", r.status_code == 200, r.text[:100])

print("\n== 5. 项目级业务（工序/问题/选型/履历/流水/项目信息） ==")
for path, key in (("processes", "processes"), ("issues", "issues"),
                  ("fixtures", "slots"), ("gauges", "slots"),
                  ("history", "rows"), ("changes", "changes")):
    r = client.get(f"/api/machining-dfm/projects/{project_id}/{path}")
    ok = r.status_code == 200
    check(f"GET /projects/{{id}}/{path} 200", ok, r.text[:100])
r = client.get(f"/api/machining-dfm/projects/{project_id}/settings")
check("GET 项目信息 200", r.status_code == 200, r.text[:100])
r = client.get("/api/machining-dfm/project-settings/fields")
check("GET 项目信息字段表 200", r.status_code == 200, r.text[:100])

print("\n== 6. 真写一次：设备行级读写 ==")
r = client.post("/api/machining-dfm/machines", json={"name": "__冒烟设备__", "brand": "SMOKE"}, headers=auth)
check("新增设备 200", r.status_code == 200, r.text[:150])
machine_id = r.json().get("machine", {}).get("id") if r.status_code == 200 else None
if machine_id:
    r = client.patch(f"/api/machining-dfm/machines/{machine_id}", json={"brand": "SMOKE2"}, headers=auth)
    check("改设备 200", r.status_code == 200, r.text[:150])
    r = client.delete(f"/api/machining-dfm/machines/{machine_id}?force=true", headers=auth)
    check("删设备（逻辑删除）200", r.status_code == 200, r.text[:150])

print("\n== 7. 回收站与导出 ==")
r = client.get("/api/machining-dfm/trash", headers=auth)
check("GET /trash 200", r.status_code == 200, r.text[:120])
r = client.get(f"/api/machining-dfm/projects/{project_id}/trash", headers=auth)
check("GET 项目回收站 200", r.status_code == 200, r.text[:120])
r = client.get(f"/api/machining-dfm/projects/{project_id}/export.zip")
check("导出 zip 200 且是 PK", r.status_code == 200 and r.content[:2] == b"PK", r.text[:120])
check("zip 带 content-disposition", "attachment" in r.headers.get("content-disposition", ""),
      r.headers.get("content-disposition", ""))

print("\n== 8. PPT 数据源契约 ==")
r = client.get("/api/ppt-provider/v1/sources")
check("GET /api/ppt-provider/v1/sources 200", r.status_code == 200, r.text[:150])
if r.status_code == 200:
    sources = r.json()
    ids = [item.get("id") for item in (sources if isinstance(sources, list) else sources.get("sources", []))]
    check("数据源列表非空", bool(ids), str(sources)[:150])
    if ids:
        sid = ids[0]
        r = client.get(f"/api/ppt-provider/v1/sources/{sid}/projects")
        check(f"GET 数据源 {sid} 项目列表 200", r.status_code == 200, r.text[:150])

print("\n== 9. 静态资源 ==")
r = client.get("/static/machining_dfm/index.html")
check("静态页面 200", r.status_code == 200, str(r.status_code))

shutil.rmtree(WORK, ignore_errors=True)
print()
if failures:
    print("× 冒烟发现问题：")
    for item in failures:
        print("  -", item)
    raise SystemExit(1)
print("√ 冒烟全部通过")
