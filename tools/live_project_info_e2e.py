"""对着正在运行的服务做「项目信息落表」全链路自检，跑完把数据还原。

覆盖：字段登记表 / 单字段 PATCH（行级保存 + 每次留版本）/ 校验拒绝（422 不改数据）
/ 图片上传与清除（附件库 + 回收）/ 读模型 G 逐键不变（图片按字节比对）
/ 迁移归档（projects_legacy_v1）与 projects.state_json 不再夹带 G / 历史版本仍可还原。

用法：python tools/live_project_info_e2e.py
"""

from __future__ import annotations

import base64
import io
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8002"
API = BASE + "/api/machining-dfm"
ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "machining_dfm" / "machining_dfm.sqlite3"
PNG = b"\x89PNG\r\n\x1a\n" + b"project-info-e2e" * 12

failures: list[str] = []
notes: list[str] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    print(("  √ " if ok else "  × ") + label + (f" → {extra}" if extra else ""))
    if not ok:
        failures.append(label + (f" → {extra}" if extra else ""))


def call(path, method="GET", body=None, raw=None, content_type=None):
    # 附件地址（/api/...）本来就是完整路径，只补主机名，别再拼一次前缀
    if path.startswith("http"):
        url = path
    elif path.startswith("/api"):
        url = BASE + path
    else:
        url = API + path
    request = urllib.request.Request(url, method=method)
    data = raw
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request.add_header("Content-Type", "application/json")
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, data=data, timeout=60) as response:
            payload = response.read()
            if response.headers.get("Content-Type", "").startswith("application/json"):
                return response.status, json.loads(payload.decode("utf-8"))
            return response.status, payload
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def db_rows(query, params=()):
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(query, params).fetchall()


print("=" * 78)
print("一、迁移结果：项目信息已落表，老 JSON 已瘦身，历史快照原样保留")
print("=" * 78)
status, bootstrap = call("/bootstrap")
check("bootstrap 可用", status == 200, str(status))
project = bootstrap["project"]
pid = project["id"]
print("     当前项目:", project["name"], "v" + str(project["revision"]))

settings_rows = db_rows("SELECT * FROM project_settings WHERE project_id=?", (pid,))
check("project_settings 里有这个项目的一行", len(settings_rows) == 1, f"{len(settings_rows)} 行")
row = dict(settings_rows[0])
check("客户名称已落列", row["customer"] == project["state"]["G"]["cust"], repr(row["customer"]))
check("零件名称已落列", row["part"] == project["state"]["G"]["part"], repr(row["part"]))
check("产能参数已落列", row["hours_per_day"] == float(project["state"]["G"]["hpd"]), f"hpd={row['hours_per_day']}")
check("产品图片已进附件库", bool(row["product_photo_id"]), str(row["product_photo_id"]))
check("extra_json 不再夹带图片", not any(
    isinstance(value, str) and value.startswith("data:")
    for value in json.loads(row["extra_json"] or "{}").values()
), row["extra_json"][:60])

raw_state = db_rows("SELECT state_json FROM projects WHERE id=?", (pid,))[0][0]
check("projects.state_json 不再有 G", "G" not in json.loads(raw_state), str(sorted(json.loads(raw_state))))
archived = db_rows("SELECT state_json FROM projects_legacy_v1 WHERE id=?", (pid,))
check("迁移前状态已归档", len(archived) == 1 and "G" in json.loads(archived[0][0]), f"{len(archived)} 行")
version = db_rows("SELECT value_json FROM app_settings WHERE key='project_schema_version'")
check("schema 版本键已写", bool(version) and json.loads(version[0][0]) == 1, version[0][0] if version else "缺失")

# 图片：URL 换成了附件地址，但字节必须和迁移前那份 data URL 完全一样
before_g = json.loads(archived[0][0])["G"] if archived else {}
old_photo = before_g.get("pI") or ""
new_photo = project["state"]["G"].get("pI") or ""
status, blob = call(new_photo) if new_photo.startswith("/api") else (0, b"")
if old_photo.startswith("data:") and blob:
    expected = base64.b64decode(old_photo.split(",", 1)[1])
    check("产品图片换成附件地址后字节一致", blob == expected, f"{len(blob)} B vs {len(expected)} B")
else:
    notes.append("归档里没有 data URL 图片，跳过字节比对")

print()
print("=" * 78)
print("二、字段登记表与单字段保存（每次保存都留版本）")
print("=" * 78)
status, fields = call("/project-settings/fields")
check("字段登记表可读", status == 200 and len(fields.get("fields", [])) == 19, f"{len(fields.get('fields', []))} 个字段")
labels = {item["key"]: item["label"] for item in fields.get("fields", [])}
check("字段带中文标签", labels.get("cust") == "客户名称", str(labels.get("cust")))

revisions_before = db_rows("SELECT COUNT(*) FROM revisions WHERE project_id=?", (pid,))[0][0]
status, settings = call(f"/projects/{pid}/settings")
check("项目信息接口可读", status == 200 and "settings" in settings, str(status))
current = settings["settings"]

# 单字段保存：值改成原值不变（只验证链路，不动真实数据）
status, result = call(f"/projects/{pid}/settings", method="PATCH",
                      body={"custVer": current.get("custVer", "")})
check("PATCH 单字段成功", status == 200 and "project" in result, str(status))
after = result["project"]
check("版本号 +1", after["revision"] == project["revision"] + 1, f"{project['revision']} → {after['revision']}")
revisions_after = db_rows("SELECT COUNT(*) FROM revisions WHERE project_id=?", (pid,))[0][0]
check("历史版本多留一条", revisions_after == revisions_before + 1, f"{revisions_before} → {revisions_after}")

# 整份保存（旧页面仍在用 PUT）：提交"全部字段 + 图片"，确认它不会把没提到的字段打回默认值
SFIELDS = ("cust", "part", "prj", "custVer", "dfmDate", "hpd", "sft", "dpm", "avl",
           "len", "wid", "hgt", "wgt", "showFlow", "bInspType", "bInspPrice",
           "fInspType", "fInspPrice", "msInspPrice")
full = {key: current[key] for key in SFIELDS}
full["pI"] = current.get("product_url")
full["pf"] = current.get("product2_url")
full["bInspImg"] = current.get("blank_insp_url")
full["fInspImg"] = current.get("final_insp_url")
status, _ = call(f"/projects/{pid}/settings", method="PUT", body=full)
check("整份 PUT 项目信息成功", status == 200, str(status))
row_after_put = dict(db_rows("SELECT * FROM project_settings WHERE project_id=?", (pid,))[0])
check("整份 PUT 没有把字段打回默认值",
      all(abs(float(row_after_put[column]) - float(row[column])) < 1e-9 for column in
          ("hours_per_day", "shifts", "days_per_month", "availability")),
      f"hpd={row_after_put['hours_per_day']} sft={row_after_put['shifts']} avl={row_after_put['availability']}")
check("整份 PUT 没有把产品图片弄丢",
      row_after_put["product_photo_id"] == row["product_photo_id"], str(row_after_put["product_photo_id"]))
raw_state = db_rows("SELECT state_json FROM projects WHERE id=?", (pid,))[0][0]
check("整份 PUT 后 state_json 仍然只有三张数组", sorted(json.loads(raw_state)) == ["is", "pr", "vh"], "")

# 校验：超上限必须 422，且不改数据
status, detail = call(f"/projects/{pid}/settings", method="PATCH", body={"hpd": 99})
check("超上限被拒（422）", status == 422, f"{status} {str(detail)[:60]}")
status, detail = call(f"/projects/{pid}/settings", method="PATCH", body={"prj": "xx"})
check("非法选项被拒（422）", status == 422, f"{status} {str(detail)[:60]}")
row_now = dict(db_rows("SELECT * FROM project_settings WHERE project_id=?", (pid,))[0])
check("被拒的请求没有改数据", row_now["hours_per_day"] == float(current["hpd"]), str(row_now["hours_per_day"]))

print()
print("=" * 78)
print("三、项目图片上传与清除（走附件库，清除后回收）")
print("=" * 78)
assets_before = db_rows("SELECT COUNT(*) FROM assets")[0][0]
status, uploaded = call(f"/projects/{pid}/photos/product2", method="PUT", raw=PNG, content_type="image/png")
check("上传 product2 图片成功", status == 200 and "project" in uploaded, str(status))
url = uploaded["project"]["state"]["G"].get("pf") if status == 200 else None
check("G.pf 变成附件地址", bool(url) and url.startswith("/api/machining-dfm/assets/"), str(url))
status, blob = call(url) if url else (0, b"")
check("附件可下载且字节一致", blob == PNG, f"{len(blob)} B")
check("附件登记表 +1", db_rows("SELECT COUNT(*) FROM assets")[0][0] == assets_before + 1, "")

status, cleared = call(f"/projects/{pid}/photos/product2", method="DELETE")
check("清除 product2 图片成功", status == 200 and cleared["project"]["state"]["G"]["pf"] is None, str(status))
check("附件登记表回落到原值", db_rows("SELECT COUNT(*) FROM assets")[0][0] == assets_before, "")
row_now = dict(db_rows("SELECT * FROM project_settings WHERE project_id=?", (pid,))[0])
check("表里 product2_photo_id 已清空", row_now["product2_photo_id"] is None, str(row_now["product2_photo_id"]))

# 旧「工艺设置」页传检具图片走的是"整份 PUT + data URL"，这条路径也必须进附件库
data_url = "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")
legacy_body = dict(full)
legacy_body["bInspImg"] = data_url
status, legacy = call(f"/projects/{pid}/settings", method="PUT", body=legacy_body)
check("整份 PUT 里的 data URL 图片被收进附件库", status == 200, str(status))
blank_url = legacy["project"]["state"]["G"].get("bInspImg") if status == 200 else None
check("G.bInspImg 变成附件地址", bool(blank_url) and blank_url.startswith("/api/machining-dfm/assets/"), str(blank_url))
status, blob = call(blank_url) if blank_url else (0, b"")
check("检具图片字节一致", blob == PNG, f"{len(blob)} B")
assets_after_data_url = db_rows("SELECT COUNT(*) FROM assets")[0][0]
check("附件登记表 +1", assets_after_data_url == assets_before + 1, f"{assets_before} → {assets_after_data_url}")

legacy_body["bInspImg"] = None
status, legacy = call(f"/projects/{pid}/settings", method="PUT", body=legacy_body)
check("整份 PUT 清空检具图片后附件被回收",
      status == 200 and db_rows("SELECT COUNT(*) FROM assets")[0][0] == assets_before, str(status))

print()
print("=" * 78)
print("四、读模型与报表链路")
print("=" * 78)
status, bootstrap = call("/bootstrap")
state = bootstrap["project"]["state"]
check("bootstrap 里 G 键齐全（29 个业务键 + 类别缓存）", len(state["G"]) >= 29, f"{len(state['G'])} 键")
check("工序数组仍在", len(state["pr"]) >= 1 and len(state["is"]) >= 1, f"pr={len(state['pr'])} is={len(state['is'])}")
check("工序里的刀具行仍在", any(len(item.get("tl") or []) for item in state["pr"]), "")
with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
    snapshot = conn.execute(
        "SELECT state_json FROM revisions WHERE project_id=? ORDER BY revision DESC LIMIT 1", (pid,)
    ).fetchone()
snapshot_state = json.loads(snapshot[0])
check("最新版本快照仍是完整读模型（含 G）", set(snapshot_state) >= {"G", "pr", "is", "vh"}, str(sorted(snapshot_state)))
check("最新快照的工艺数组与当前一致",
      [item.get("nm") for item in snapshot_state["pr"]] == [item.get("nm") for item in state["pr"]], "")

print()
print("=" * 78)
print(("全部通过 √ " + "；".join(notes)) if not failures else "发现问题：\n - " + "\n - ".join(failures))
print("=" * 78)
print("数据还原情况：项目信息只做过「值不变」的 PATCH 与整份 PUT；product2 图片与检具图片都已清除回原状。")
sys.exit(1 if failures else 0)
