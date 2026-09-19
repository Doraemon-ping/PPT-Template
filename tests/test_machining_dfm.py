import base64
import json
import sqlite3

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.machining_dfm import MachiningDFMStore, router_for

PHOTO_BYTES = b"\x89PNG\r\n\x1a\n" + b"pixel" * 40
DOC_BYTES = b"%PDF-1.4 minimal document"


def photo_data_url() -> str:
    return "data:image/png;base64," + base64.b64encode(PHOTO_BYTES).decode()


def sample_state(part="P-001"):
    return {
        "mdb": [{"brand": "A", "model": "M1"}],
        "tdb": [],
        "pr": [{"nm": "OP10", "tl": []}],
        "is": [],
        "fdb": [],
        "idb": [],
        "vh": [],
        "G": {"cust": "客户 A", "part": part},
    }


def write_seed_dir(root):
    """A tiny split seed: two normal machines plus the fallback row."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "machines.json").write_text(json.dumps({"machines": [
        {"id": "m-alpha", "brand": "Alpha", "model": "A1", "rapid": 40, "tc": 1.5, "spm": 10000, "atc": 24},
        {"id": "m-beta", "brand": "Beta", "model": "B2", "rapid": 30, "tc": 2, "spm": 8000, "atc": 20},
        {"id": "m-custom", "brand": "自定义", "model": "", "is_fallback": True},
    ]}, ensure_ascii=False), encoding="utf-8")
    (root / "project.json").write_text(json.dumps({
        "G": {"cust": "客户 A", "part": "P-001"},
        "pr": [{"nm": "OP10", "tl": [], "mid": "m-beta"}],
        "is": [],
        "vh": [],
    }, ensure_ascii=False), encoding="utf-8")
    for name in ("tools", "fixtures", "gauges"):
        (root / f"{name}.json").write_text("[]", encoding="utf-8")
    (root / "categories.json").write_text(json.dumps({"icnX": [], "fcnX": []}), encoding="utf-8")
    return root


@pytest.fixture()
def seed_dir(tmp_path):
    return write_seed_dir(tmp_path / "seed")


@pytest.fixture()
def store(tmp_path, seed_dir):
    return MachiningDFMStore(tmp_path / "data" / "machining_dfm", seed_dir)


def admin_headers(client) -> dict:
    token = client.post(
        "/api/machining-dfm/auth/login", json={"role": "admin", "password": "TP23456"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def make_client(store, tmp_path) -> TestClient:
    static = tmp_path / "static" / "machining_dfm"
    static.mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<h1>machining</h1>", encoding="utf-8")
    app = FastAPI()
    app.include_router(router_for(lambda: store, tmp_path / "static"))
    return TestClient(app)


# ---------------------------------------------------------------- projects


def test_seed_update_history_and_soft_delete(store):
    projects = store.list()
    assert len(projects) == 1
    project = store.get(projects[0]["id"])
    assert project["state"]["G"]["part"] == "P-001"
    assert project["revision"] == 1

    state = sample_state("P-002")
    saved = store.update(project["id"], "更新后的项目", state, 1)
    assert saved["revision"] == 2
    assert [item["revision"] for item in store.versions(project["id"])] == [2, 1]
    assert store.get(project["id"], 1)["state"]["G"]["part"] == "P-001"

    with pytest.raises(HTTPException) as conflict:
        store.update(project["id"], "过期保存", state, 1)
    assert conflict.value.status_code == 409

    store.archive(project["id"], True)
    assert store.list() == []
    assert store.list(True)[0]["archived"] is True
    with pytest.raises(HTTPException) as deleted:
        store.get(project["id"])
    assert deleted.value.status_code == 410
    store.archive(project["id"], False)
    assert store.list()[0]["id"] == project["id"]


def test_project_snapshots_and_shared_data_are_decoupled(store):
    project_id = store.list()[0]["id"]
    with store.connect() as db:
        raw = json.loads(db.execute("SELECT state_json FROM projects WHERE id=?", (project_id,)).fetchone()[0])
        settings_row = db.execute(
            "SELECT * FROM project_settings WHERE project_id=?", (project_id,)
        ).fetchone()
        auth = db.execute("SELECT password_hash FROM auth_settings WHERE role='admin'").fetchone()[0]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    # 项目信息（G）已独立成表：state_json 只留三份业务数组，一行一列存项目信息
    assert set(raw) == {"pr", "is", "vh"}
    assert settings_row is not None
    assert set(settings_row.keys()) >= {"project_id", "customer", "part", "project_type", "hours_per_day"}
    assert {"machines", "assets", "tools", "fixtures", "gauges", "auth_settings", "app_settings"} <= tables
    assert "project_settings" in tables
    # 设备库不再进项目数据：工序里只有稳定 id，设备信息由组合视图提供。
    assert raw["pr"][0]["mid"] == "m-beta"
    assert "mi" not in raw["pr"][0]
    machines = store.get(project_id)["state"]["mdb"]
    assert [row["brand"] for row in machines] == ["Alpha", "Beta", "自定义"]
    assert machines[1]["model"] == "B2"
    assert store.get(project_id)["state"]["pr"][0]["mi"] == 1  # 兼容旧前端的派生下标
    assert "TP23456" not in auth
    # 读模型里的 G 仍然齐全（项目信息来自表，共享库类别仍在）
    general = store.get(project_id)["state"]["G"]
    assert general["icnX"] and general["fcnX"]
    assert set(general) >= {"cust", "part", "hpd", "avl", "prj", "len", "wid", "hgt", "wgt", "showFlow"}


def test_empty_machine_library_stays_empty_after_restart(store):
    # 清空只能走行级删除（旧接口整体保存只增改不删）
    for row in store.machines.list_typed():
        store.machines.delete(row["id"])

    restarted = MachiningDFMStore(store.root, store.seed_file)
    assert restarted.machines.count() == 0
    assert restarted.libraries()["mdb"] == []


def test_legacy_index_reference_is_stored_as_machine_id(store):
    project_id = store.list()[0]["id"]
    state = sample_state("P-IDX")
    state["pr"] = [{"nm": "OP10", "tl": [], "mi": 1}]
    store.update(project_id, "旧前端保存", state, 1)
    with store.connect() as db:
        stored = json.loads(db.execute("SELECT state_json FROM projects WHERE id=?", (project_id,)).fetchone()[0])
    assert stored["pr"][0]["mid"] == "m-beta"
    assert "mi" not in stored["pr"][0]

    state["pr"] = [{"nm": "OP20", "tl": [], "mi": 99}]
    store.update(project_id, "越界下标", state, 2)
    with store.connect() as db:
        stored = json.loads(db.execute("SELECT state_json FROM projects WHERE id=?", (project_id,)).fetchone()[0])
    assert stored["pr"][0]["mid"] == "m-custom"  # 越界落到兜底机型，不丢引用


# ---------------------------------------------------------------- machines


def test_machine_crud_is_row_level(store, tmp_path):
    client = make_client(store, tmp_path)
    headers = admin_headers(client)

    listed = client.get("/api/machining-dfm/machines").json()
    assert listed["count"] == 3
    assert listed["fallback_id"] == "m-custom"
    assert [field["key"] for field in listed["fields"]] == [
        "brand", "model", "xyz", "pa", "rpa", "rapid", "tc", "spm", "atc", "price", "desc",
    ]

    created = client.post(
        "/api/machining-dfm/machines",
        headers=headers,
        json={"brand": "Gamma", "model": "G3", "xyz": "600×400×300", "pa": "±0.01", "rpa": "±0.005",
              "rapid": 48, "tc": 1.8, "spm": 12000, "atc": 30, "price": 88.5, "desc": "立加"},
    )
    assert created.status_code == 200
    machine = created.json()["machine"]
    assert machine["brand"] == "Gamma" and machine["price"] == 88.5
    assert machine["photo_url"] is None and machine["doc_url"] is None
    machine_id = machine["id"]

    patched = client.patch(
        f"/api/machining-dfm/machines/{machine_id}", headers=headers, json={"rapid": 55.5}
    ).json()["machine"]
    assert patched["rapid"] == 55.5
    assert patched["brand"] == "Gamma" and patched["atc"] == 30  # 只改提交的字段

    for bad in ({"rapid": -1}, {"atc": 99999}, {"brand": "x" * 200}, {"rapid": "快"}):
        assert client.patch(
            f"/api/machining-dfm/machines/{machine_id}", headers=headers, json=bad
        ).status_code == 422

    ids = [row["id"] for row in client.get("/api/machining-dfm/machines").json()["machines"]]
    reordered = client.post(
        "/api/machining-dfm/machines/reorder", headers=headers, json={"ids": list(reversed(ids))}
    ).json()["machines"]
    assert [row["id"] for row in reordered] == list(reversed(ids))
    assert client.post(
        "/api/machining-dfm/machines/reorder", headers=headers, json={"ids": ids[:-1]}
    ).status_code == 422

    default = client.put(f"/api/machining-dfm/machines/{machine_id}/default", headers=headers).json()
    assert [row["id"] for row in default["machines"] if row["is_fallback"]] == [machine_id]

    assert client.delete(f"/api/machining-dfm/machines/{machine_id}", headers=headers).status_code == 200
    assert client.get("/api/machining-dfm/machines").json()["count"] == 3


def test_machine_writes_require_the_admin_token(store, tmp_path):
    client = make_client(store, tmp_path)
    assert client.post("/api/machining-dfm/machines", json={"brand": "X"}).status_code == 401
    process = client.post(
        "/api/machining-dfm/auth/login", json={"role": "process", "password": "TP123456"}
    ).json()["token"]
    assert client.post(
        "/api/machining-dfm/machines", headers={"Authorization": f"Bearer {process}"}, json={"brand": "X"}
    ).status_code == 403
    assert client.get("/api/machining-dfm/machines").status_code == 200  # 读取放开给选择器


def test_delete_guard_reports_referencing_projects(store, tmp_path):
    client = make_client(store, tmp_path)
    headers = admin_headers(client)
    blocked = client.delete("/api/machining-dfm/machines/m-beta", headers=headers)
    assert blocked.status_code == 409
    assert "引用" in blocked.json()["detail"]
    forced = client.delete("/api/machining-dfm/machines/m-beta?force=true", headers=headers)
    assert forced.status_code == 200
    assert forced.json()["removed"]["id"] == "m-beta"
    assert forced.json()["usage"][0]["project"]


# ---------------------------------------------------------------- assets


def test_photo_and_doc_are_files_with_metadata(store, tmp_path):
    client = make_client(store, tmp_path)
    headers = admin_headers(client)

    stored = client.put(
        "/api/machining-dfm/machines/m-alpha/photo",
        headers={**headers, "Content-Type": "image/png"},
        content=PHOTO_BYTES,
    ).json()["machine"]
    assert stored["photo_url"].startswith("/api/machining-dfm/assets/")
    photo_id = stored["photo_id"]
    on_disk = list((store.root / "assets" / "machine_photo").rglob("*.png"))
    assert len(on_disk) == 1 and on_disk[0].read_bytes() == PHOTO_BYTES

    with store.connect() as db:
        row = db.execute("SELECT kind,mime,size,sha256,path FROM assets WHERE id=?", (photo_id,)).fetchone()
    assert (row["kind"], row["mime"], row["size"]) == ("machine_photo", "image/png", len(PHOTO_BYTES))
    assert row["path"].startswith("machine_photo/")

    fetched = client.get(stored["photo_url"])
    assert fetched.status_code == 200
    assert fetched.content == PHOTO_BYTES
    assert fetched.headers["etag"] == f'"{row["sha256"]}"'
    assert client.get(stored["photo_url"], headers={"If-None-Match": fetched.headers["etag"]}).status_code == 304

    document = client.put(
        "/api/machining-dfm/machines/m-alpha/doc?name=manual.pdf",
        headers={**headers, "Content-Type": "application/pdf"},
        content=DOC_BYTES,
    ).json()["machine"]
    assert document["doc_name"] == "manual.pdf"
    assert document["doc_url"].endswith("?download=1")
    download = client.get(document["doc_url"])
    assert download.status_code == 200 and download.content == DOC_BYTES
    assert "manual.pdf" in download.headers.get("content-disposition", "")

    # 相同字节 + 相同名称去重：只留一份文件和一条元数据。
    client.put(
        "/api/machining-dfm/machines/m-beta/photo",
        headers={**headers, "Content-Type": "image/png"},
        content=PHOTO_BYTES,
    )
    assert len(list((store.root / "assets" / "machine_photo").rglob("*.png"))) == 1
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM assets WHERE kind='machine_photo'").fetchone()[0] == 1
    # 其中一台清除图片，不能删掉另一台仍在使用的文件。
    cleared = client.delete("/api/machining-dfm/machines/m-alpha/photo", headers=headers).json()["machine"]
    assert cleared["photo_url"] is None
    remaining = [row for row in client.get("/api/machining-dfm/machines").json()["machines"]
                 if row["id"] == "m-beta"][0]
    assert remaining["photo_url"] is not None
    assert len(list((store.root / "assets" / "machine_photo").rglob("*.png"))) == 1
    assert client.get(remaining["photo_url"]).status_code == 200

    assert client.delete("/api/machining-dfm/machines/m-beta/doc", headers=headers).status_code == 200


def test_asset_limits_and_unknown_asset(store, tmp_path):
    client = make_client(store, tmp_path)
    headers = admin_headers(client)
    assert client.put(
        "/api/machining-dfm/machines/m-alpha/photo",
        headers={**headers, "Content-Type": "image/png"},
        content=b"",
    ).status_code == 422
    assert client.put(
        "/api/machining-dfm/machines/m-alpha/doc",
        headers={**headers, "Content-Type": "application/pdf"},
        content=b"x" * (3 * 1024 * 1024),
    ).status_code == 413
    assert client.put(
        "/api/machining-dfm/machines/m-alpha/photo",
        headers={**headers, "Content-Type": "application/zip"},
        content=b"pk",
    ).status_code == 415
    assert client.get("/api/machining-dfm/assets/deadbeef").status_code == 404


def test_legacy_library_save_keeps_machine_ids(store, tmp_path):
    client = make_client(store, tmp_path)
    headers = admin_headers(client)
    before = [row["id"] for row in client.get("/api/machining-dfm/machines").json()["machines"]]
    response = client.put(
        "/api/machining-dfm/libraries",
        headers=headers,
        json={"mdb": [
            {"brand": "Alpha", "model": "A1", "rapid": 44, "img": photo_data_url()},
            {"brand": "Beta", "model": "B2", "rapid": 30},
        ], "tdb": [], "fdb": [], "idb": [], "icnX": [], "fcnX": []},
    )
    assert response.status_code == 200
    after = client.get("/api/machining-dfm/machines").json()["machines"]
    # 按 (品牌,型号) 匹配：命中的两行 id 不变，提交里没有的兜底行也保留（只增改不删）
    assert [row["id"] for row in after] == before
    assert after[0]["rapid"] == 44 and after[0]["photo_url"] is not None
    assert after[2]["brand"] == "自定义" and after[2]["is_fallback"] is True
    # 兜底机型仍然只有一条，且末行约定不变
    fallback = client.get("/api/machining-dfm/machines").json()["fallback_id"]
    assert fallback == before[2]
    assert [row["is_fallback"] for row in after] == [False, False, True]
    # 删除只能走行级接口（普通行直接删；兜底行会被保护）
    assert client.delete(f"/api/machining-dfm/machines/{before[0]}", headers=headers).status_code == 200
    remaining = client.get("/api/machining-dfm/machines").json()
    assert remaining["count"] == 2
    assert remaining["machines"][-1]["is_fallback"] is True


# ---------------------------------------------------------------- router / compat


def test_router_crud_uses_dedicated_store(store, tmp_path):
    client = make_client(store, tmp_path)
    boot = client.get("/api/machining-dfm/bootstrap")
    assert boot.status_code == 200
    project = boot.json()["project"]
    assert project["state"]["G"]["part"] == "P-001"
    assert str(store.root) == boot.json()["data_dir"]
    assert client.get("/api/machining-dfm/defaults").json()["G"]["part"] == "P-001"

    assert client.put("/api/machining-dfm/libraries", json={}).status_code == 422
    assert client.put("/api/machining-dfm/libraries", json={"tdb": [], "fdb": [], "idb": []}).status_code == 401
    process = client.post(
        "/api/machining-dfm/auth/login", json={"role": "process", "password": "TP123456"}
    ).json()["token"]
    assert client.put(
        "/api/machining-dfm/libraries",
        headers={"Authorization": f"Bearer {process}"},
        json={"tdb": [], "fdb": [], "idb": []},
    ).status_code == 403
    headers = admin_headers(client)
    changed = client.put(
        "/api/machining-dfm/config",
        headers=headers,
        json={"site_title": "机加后台", "autosave_ms": 1500},
    )
    assert changed.status_code == 200
    assert changed.json()["site_title"] == "机加后台"

    created = client.post(
        "/api/machining-dfm/projects", json={"name": "第二个项目", "state": sample_state("P-NEW")}
    )
    assert created.status_code == 200
    assert created.json()["revision"] == 1

    archived = client.post(
        f"/api/machining-dfm/projects/{created.json()['id']}/archive?archived=true", json={},
        headers=admin_headers(client),
    )
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    # 旧归档入口与"删除项目"同口径：不登录不给用（曾经是裸奔的）
    assert client.post(
        f"/api/machining-dfm/projects/{created.json()['id']}/archive?archived=true", json={}
    ).status_code == 401
    assert client.get("/api/machining-dfm/projects?archived=true").json()["projects"][0]["id"] == created.json()["id"]
    assert client.get("/machining-dfm").text == "<h1>machining</h1>"
    assert client.get("/api/machining-dfm/libraries").json()["counts"]["mdb"] == 3


def test_invalid_state_is_rejected(store):
    with pytest.raises(HTTPException) as error:
        store.create("坏数据", {"G": []})
    assert error.value.status_code == 422


# ---------------------------------------------------------------- legacy DB upgrade

LEGACY_SCHEMA = """
CREATE TABLE projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL,
    state_json TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE revisions(project_id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL,
    state_json TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(project_id, revision));
CREATE TABLE equipment(id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL,
    payload_json TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE tools(id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL, payload_json TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE fixtures(id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL, payload_json TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE gauges(id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL, payload_json TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE auth_settings(role TEXT PRIMARY KEY, salt TEXT NOT NULL, password_hash TEXT NOT NULL,
    iterations INTEGER NOT NULL, updated TEXT NOT NULL);
CREATE TABLE app_settings(key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated TEXT NOT NULL);
"""


@pytest.fixture()
def legacy_root(tmp_path):
    """A database in the pre-refactor shape: equipment payloads with inline images."""
    root = tmp_path / "data" / "machining_dfm"
    root.mkdir(parents=True)
    db = sqlite3.connect(root / "machining_dfm.sqlite3")
    db.executescript(LEGACY_SCHEMA)
    now = "2026-01-01T00:00:00+00:00"
    machines = [
        {"brand": "Alpha", "model": "A1", "rapid": 40, "tc": 1.5, "spm": 10000, "atc": 24,
         "xyz": "500×400×300", "pa": "±0.005", "rpa": "±0.003", "desc": "立加"},
        {"brand": "Beta", "model": "B2", "rapid": 36, "tc": 2, "spm": 12000, "atc": 30,
         "img": photo_data_url()},
        {"brand": "自定义", "model": "", "rapid": 30, "tc": 2, "spm": 8000, "atc": 20},
        {"brand": "Beta", "model": "B3", "rapid": 20, "tc": 1, "spm": 9000, "atc": 12},
    ]
    for index, payload in enumerate(machines):
        db.execute(
            "INSERT INTO equipment(id,sort_order,payload_json,updated) VALUES(?,?,?,?)",
            (f"eq-{index}", index, json.dumps(payload, ensure_ascii=False), now),
        )
    tools = [
        {"tp": "D50面铣刀", "cat": "f", "d": 50, "ln": 0, "n": 3000, "vf": 3000,
         "life": 0, "price": 0, "grp": "hp", "tI": ""},
        {"tp": "D12合金铣刀", "cat": "hm", "d": 12, "ln": 75, "n": 4000, "vf": 900,
         "life": 120, "price": 260, "grp": "hp", "tI": photo_data_url()},
        {"tp": "BT30刀柄", "cat": "cn", "d": 0, "ln": 0, "n": 0, "vf": 0,
         "life": 0, "price": 800, "grp": "hld", "tI": ""},
        # 旧版本遗留的分类代码（migCat 之前）：按原名归一化，不能被外键挡住
        {"tp": "PCD倒角刀", "cat": "chamfer", "d": 6, "ln": 0, "n": 6000, "vf": 600,
         "life": 0, "price": 0, "grp": "hp", "tI": ""},
        # 完全未知的分类码：迁移时自动补录进类型字典（标注来源 legacy）
        {"tp": "试验刀具", "cat": "zzz", "d": 8, "ln": 0, "n": 2000, "vf": 400,
         "life": 0, "price": 0, "grp": "hp", "tI": ""},
    ]
    for index, payload in enumerate(tools):
        db.execute(
            "INSERT INTO tools(id,sort_order,payload_json,updated) VALUES(?,?,?,?)",
            (f"tl-{index}", index, json.dumps(payload, ensure_ascii=False), now),
        )
    fixtures = [
        {"center": "1025减震模具中心", "name": "四轴机加夹具", "price": 12000, "mc": 30,
         "rmk": "", "img": ""},
        {"center": "1025减震模具中心", "name": "五轴机加夹具", "price": 35000, "mc": 45,
         "rmk": "含外购件", "img": photo_data_url()},
        # 类别字典里没有的模具中心：迁移时自动补录（source=legacy）
        {"center": "9999试验模具中心", "name": "试验夹具", "price": 800, "mc": 0,
         "rmk": "试验", "img": ""},
    ]
    for index, payload in enumerate(fixtures):
        db.execute(
            "INSERT INTO fixtures(id,sort_order,payload_json,updated) VALUES(?,?,?,?)",
            (f"fx-{index}", index, json.dumps(payload, ensure_ascii=False), now),
        )
    gauges = [
        {"type": "毛坯检具", "name": "左后纵梁毛坯检具", "drw": "9020045309-01",
         "prdSize": "1138*700*461", "inspSize": "1200*1000*1400", "price": 12.5,
         "dc": 15, "mc": 40, "img": ""},
        {"type": "测量支架", "name": "三坐标测量支架", "drw": "BP13-G7020001312-01",
         "prdSize": "", "inspSize": "830*600*572", "price": 3.2, "dc": 7, "mc": 20,
         "img": ""},
        # 类别字典里没有的检具类别：迁移时自动补录（source=legacy）
        {"type": "试验检具类别", "name": "试验检具", "drw": "T-001", "prdSize": "10*20*30",
         "inspSize": "40*50*60", "price": 1, "dc": 1, "mc": 2, "img": ""},
    ]
    for index, payload in enumerate(gauges):
        db.execute(
            "INSERT INTO gauges(id,sort_order,payload_json,updated) VALUES(?,?,?,?)",
            (f"gg-{index}", index, json.dumps(payload, ensure_ascii=False), now),
        )
    state = {"G": {"cust": "旧客户", "part": "LEGACY-1"},
             "pr": [{"nm": "OP10", "tl": [], "mi": 1}, {"nm": "OP20", "tl": [], "mi": 3}],
             "is": [], "vh": []}
    db.execute(
        "INSERT INTO projects(id,name,revision,state_json,created,updated,archived) VALUES(?,?,?,?,?,?,0)",
        ("legacy-project", "旧项目", 1, json.dumps(state, ensure_ascii=False), now, now),
    )
    db.execute(
        "INSERT INTO revisions(project_id,revision,name,state_json,created) VALUES(?,?,?,?,?)",
        ("legacy-project", 1, "旧项目", json.dumps(state, ensure_ascii=False), now),
    )
    for key, value in {
        "libraries_initialized": True,
        "category_schema_version": 1,
        "site_title": "机加 DFM 项目工作台",
        "autosave_ms": 1200,
        "token_secret": "0" * 64,
        "inspection_categories": [],
        "fixture_categories": [],
    }.items():
        db.execute(
            "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?)",
            (key, json.dumps(value, ensure_ascii=False), now),
        )
    db.commit()
    db.close()
    return root


def test_legacy_payload_database_is_migrated(legacy_root, seed_dir):
    store = MachiningDFMStore(legacy_root, seed_dir)
    machines = store.machines.list_typed()
    assert [row["brand"] for row in machines] == ["Alpha", "Beta", "自定义", "Beta"]
    assert machines[1]["xyz"] == "" and machines[1]["rapid"] == 36
    assert machines[0]["xyz"] == "500×400×300" and machines[0]["pa"] == "±0.005"
    # 图片从 payload 搬到了磁盘，行里只剩外键与 URL。
    assert machines[1]["photo_url"].startswith("/api/machining-dfm/assets/")
    photo_files = list((legacy_root / "assets" / "machine_photo").rglob("*.png"))
    assert len(photo_files) == 1 and photo_files[0].read_bytes() == PHOTO_BYTES
    assert machines[2]["is_fallback"] is True
    assert store.machines.default_ref() == machines[2]["id"]

    # 工序引用从下标换成稳定 id：index 1 → Beta/B2，index 3 → Beta/B3。
    assert store.get("legacy-project")["state"]["pr"][0]["mid"] == machines[1]["id"]
    assert store.get("legacy-project")["state"]["pr"][1]["mid"] == machines[3]["id"]
    with store.connect() as db:
        stored = json.loads(db.execute(
            "SELECT state_json FROM projects WHERE id='legacy-project'"
        ).fetchone()[0])
        assert "mi" not in stored["pr"][0] and "mi" not in stored["pr"][1]
        assert db.execute("SELECT COUNT(*) FROM equipment_legacy_v1").fetchone()[0] == 4
        assert json.loads(db.execute(
            "SELECT value_json FROM app_settings WHERE key='library_schema_version'"
        ).fetchone()[0]) == 2

    # 迁移幂等：再启动一次不会重复插入，id 保持不变。
    again = MachiningDFMStore(legacy_root, seed_dir)
    assert [row["id"] for row in again.machines.list_typed()] == [row["id"] for row in machines]
    assert again.get("legacy-project")["state"]["pr"][0]["mid"] == machines[1]["id"]
    assert (legacy_root / "backups" / "pre-typed-machines.sqlite3").is_file()


def test_provider_snapshot_keeps_inline_photo_and_image_slot(legacy_root, seed_dir):
    from app.machining_projection import report_runtime
    from app.native_forms import normalize

    store = MachiningDFMStore(legacy_root, seed_dir)
    plain = store.get("legacy-project")
    assert plain["state"]["mdb"][1]["img"].startswith("/api/machining-dfm/assets/")

    inlined = store.get("legacy-project", inline_assets=True)
    assert inlined["state"]["mdb"][1]["img"].startswith("data:image/png;base64,")
    data, catalog = normalize(report_runtime(inlined["state"]), include_legacy_aliases=False)
    # PPT 图片槽位仍然存在，且值为 data URL（与拆分前逐字段一致）。
    assert catalog["images"]
    assert any(
        isinstance(value, list) and value and str(value[0]).startswith("data:image/")
        for key, value in data["i"].items()
    )


def test_projection_uses_machine_id_not_position(legacy_root, seed_dir):
    from app.machining_projection import report_runtime

    store = MachiningDFMStore(legacy_root, seed_dir)
    machines = store.machines.list_typed()
    state = store.get("legacy-project")["state"]
    tool = {"ln": 100, "vf": 1000, "ps": 1, "cn": 1, "d": 10, "n": 3000, "td": 500, "tt": 2, "sd": 1}
    state["pr"] = [{"nm": "OP10", "tl": [dict(tool)], "mid": machines[3]["id"], "mc": 1}]  # rapid=20
    slow = report_runtime(state)["computed"]["processes"][0]["noncut_seconds"]
    state["pr"] = [{"nm": "OP10", "tl": [dict(tool)], "mid": machines[0]["id"], "mc": 1}]  # rapid=40
    fast = report_runtime(state)["computed"]["processes"][0]["noncut_seconds"]
    assert slow > fast


# ---------------------------------------------------------------- 刀具库（tools）


TOOL_PAGE_HEADERS = [
    "库分类", "型号", "类型", "D mm", "长度L mm", "转速n rpm", "进给vf mm/min", "寿命 min", "价格 ¥",
]
TOOL_LEGACY_KEYS = {"tp", "d", "n", "vf", "cat", "tI", "life", "price", "grp", "ln"}


def test_tool_field_registry_matches_page(store):
    spec = store.tool_fields()
    headers = [item["label"] + (f" {item['unit']}" if item["unit"] else "") for item in spec["fields"]]
    assert headers == TOOL_PAGE_HEADERS
    assert [item["key"] for item in spec["fields"]] == ["grp", "tp", "cat", "d", "ln", "n", "vf", "life", "price"]
    # 库分类与类型取值来自登记表，页面不再各写一份字典。
    groups = spec["fields"][0]
    assert [item["value"] for item in groups["choices"]] == ["hp", "dp", "hld", "acc"]
    assert dict((item["value"], item["label"]) for item in groups["choices"])["hld"] == "刀柄"
    categories = spec["fields"][2]
    codes = {item["value"] for item in categories["choices"]}
    assert {"cn", "im", "other", "f", "hm", "hd"} <= codes
    assert len(codes) == 49  # 47 个刀具分类 + 国内/进口
    # 自动列只描述、不入库
    assert [item["key"] for item in spec["derived"]] == ["fz", "vc"]
    assert "fz" not in {item["key"] for item in spec["fields"]}


def test_tool_crud_validates_choices_and_numbers(store):
    created = store.tools.create(
        {"grp": "hp", "tp": "D12合金铣刀", "cat": "hm", "d": 12, "ln": 75, "n": 4000, "vf": 900,
         "life": 120, "price": 260}
    )
    assert created["tp"] == "D12合金铣刀" and created["d"] == 12.0 and created["price"] == 260.0
    assert store.tools.count() == 1

    with pytest.raises(HTTPException) as bad_group:
        store.tools.create({"grp": "xx", "tp": "坏分类"})
    assert bad_group.value.status_code == 422 and "库分类" in bad_group.value.detail
    with pytest.raises(HTTPException) as bad_cat:
        store.tools.create({"tp": "坏类型", "cat": "milling"})
    assert bad_cat.value.status_code == 422 and "类型" in bad_cat.value.detail
    with pytest.raises(HTTPException) as negative:
        store.tools.update(created["id"], {"price": -1})
    assert negative.value.status_code == 422
    with pytest.raises(HTTPException) as too_big:
        store.tools.update(created["id"], {"d": 99999})
    assert too_big.value.status_code == 422

    # 部分更新只动提交的那一列（每行独立保存）
    updated = store.tools.update(created["id"], {"price": 300})
    assert updated["price"] == 300.0 and updated["tp"] == "D12合金铣刀" and updated["d"] == 12.0
    assert updated["updated"] > created["updated"]

    # 旧短键视图：键名与拆分前逐字段一致（成本表按 tp 查 life/price）
    legacy = store.tools.list_legacy()[0]
    assert TOOL_LEGACY_KEYS <= set(legacy)
    assert legacy["tp"] == "D12合金铣刀" and legacy["tI"] is None

    removed = store.tools.delete(created["id"])
    assert removed["tp"] == "D12合金铣刀" and removed["remaining"] == 0
    # 口径 2：删除是逻辑删除 —— 行还在库里（回收站可见），再删一次是 409 而不是 404
    assert [item["id"] for item in store.tools.trash()] == [created["id"]]
    with pytest.raises(HTTPException) as again:
        store.tools.delete(created["id"])
    assert again.value.status_code == 409
    # 恢复之后又能用了，而且 id 不变
    restored = store.tools.restore(created["id"])
    assert restored["id"] == created["id"] and restored["tp"] == "D12合金铣刀"
    assert store.tools.trash() == []


def test_tool_reorder_and_legacy_library_write(store):
    ids = [store.tools.create({"tp": f"T{i}", "cat": "hm"})["id"] for i in range(3)]
    with pytest.raises(HTTPException) as dup:
        store.tools.reorder([ids[0], ids[0], ids[2]])
    assert dup.value.status_code == 422
    with pytest.raises(HTTPException) as partial:
        store.tools.reorder(ids[:2])
    assert partial.value.status_code == 422
    ordered = store.tools.reorder([ids[2], ids[1], ids[0]])
    assert [row["id"] for row in ordered] == [ids[2], ids[1], ids[0]]

    # 旧页面整体保存（PUT /libraries 带 tdb）：按 (库分类, 型号) 匹配，id 保持不变。
    result = store.tools.replace_legacy([
        {"grp": "hp", "tp": "T1", "cat": "hm", "d": 8, "n": 5000, "vf": 1000, "life": 60, "price": 120},
        {"grp": "hp", "tp": "T2", "cat": "hm", "price": 800},
    ])
    assert result["updated"] == 2 and result["inserted"] == 0 and result["removed"] == []
    by_name = {row["tp"]: row for row in store.tools.list_typed()}
    assert set(by_name) == {"T0", "T1", "T2"}  # 只增改不删：T0 仍在库里
    assert by_name["T1"]["id"] == ids[1] and by_name["T1"]["d"] == 8.0
    assert by_name["T2"]["price"] == 800.0
    # 显式 prune（维护/迁移用）才会删掉提交里没有的行
    pruned = store.tools.replace_legacy([{"grp": "hp", "tp": "T1", "cat": "hm"}], prune=True)
    assert [row["tp"] for row in store.tools.list_typed()] == ["T1"]
    assert {item["tp"] for item in pruned["removed"]} == {"T2", "T0"}
    store.tools.replace_legacy([
        {"grp": "hp", "tp": "T1", "cat": "hm", "d": 8, "n": 5000, "vf": 1000, "life": 60, "price": 120},
        {"grp": "hld", "tp": "T2", "cat": "cn", "price": 800},
        {"grp": "hp", "tp": "T0", "cat": "hm"},
    ])

    libraries = store.libraries()
    assert sorted(row["tp"] for row in libraries["tdb"]) == ["T0", "T1", "T2"]
    assert libraries["fdb"] == [] and libraries["idb"] == []


def test_tool_photo_upload_is_deduplicated(store, tmp_path):
    first = store.tools.create({"tp": "带图刀具"})
    second = store.tools.create({"tp": "同图刀具"})
    client = make_client(store, tmp_path)
    headers = admin_headers(client)

    uploaded = client.put(
        f"/api/machining-dfm/tools/{first['id']}/photo",
        headers={**headers, "Content-Type": "image/png"},
        content=PHOTO_BYTES,
    ).json()["tool"]
    assert uploaded["photo_url"].startswith("/api/machining-dfm/assets/")
    assert client.get(uploaded["photo_url"]).content == PHOTO_BYTES

    client.put(
        f"/api/machining-dfm/tools/{second['id']}/photo",
        headers={**headers, "Content-Type": "image/png"},
        content=PHOTO_BYTES,
    )
    assert len(list((store.root / "assets" / "tool_photo").rglob("*.png"))) == 1

    # 清掉一行图片时不能删掉另一行仍在用的文件
    cleared = client.delete(f"/api/machining-dfm/tools/{first['id']}/photo", headers=headers).json()["tool"]
    assert cleared["photo_url"] is None
    assert (store.root / "assets" / "tool_photo").rglob("*.png")
    assert store.tools.find(second["id"])["photo_id"] is not None

    assert client.put(
        f"/api/machining-dfm/tools/{first['id']}/photo",
        headers={**headers, "Content-Type": "application/zip"},
        content=b"pk",
    ).status_code == 415
    assert client.delete(f"/api/machining-dfm/tools/{first['id']}", headers=headers).status_code == 200
    assert client.get("/api/machining-dfm/tools/fields").json()["derived"][0]["key"] == "fz"


def test_router_tools_crud_and_usage(store, tmp_path):
    client = make_client(store, tmp_path)
    headers = admin_headers(client)
    created = client.post(
        "/api/machining-dfm/tools",
        headers=headers,
        json={"grp": "hp", "tp": "D16合金铣刀", "cat": "hm", "d": 16, "n": 3000, "vf": 900},
    ).json()
    tool_id = created["tool"]["id"]
    assert created["count"] == 1
    listed = client.get("/api/machining-dfm/tools").json()
    assert [item["tp"] for item in listed["tools"]] == ["D16合金铣刀"]
    assert listed["fields"]["fields"][0]["key"] == "grp"

    patched = client.patch(
        f"/api/machining-dfm/tools/{tool_id}", headers=headers, json={"price": 480}
    ).json()["tool"]
    assert patched["price"] == 480.0
    assert client.patch(
        f"/api/machining-dfm/tools/{tool_id}", headers=headers, json={"cat": "不存在"}
    ).status_code == 422
    assert client.post("/api/machining-dfm/tools/reorder", headers=headers, json={"ids": []}).status_code == 422

    # 项目里的工序刀具行按名称引用刀具库：删除不阻塞，只回报引用它的项目。
    project_id = store.list()[0]["id"]
    state = sample_state("P-TOOL")
    state["pr"] = [{"nm": "OP10", "tl": [{"tp": "D16合金铣刀", "hld": "BT30刀柄", "acc": ""}]}]
    store.update(project_id, "带刀具的项目", state, 1)
    assert store.tool_usage("D16合金铣刀", "hp") == [
        {"project_id": project_id, "project": "带刀具的项目", "process": "OP10"}
    ]
    assert store.tool_usage("BT30刀柄", "hld")[0]["process"] == "OP10"
    assert store.tool_usage("无关刀具", "hp") == []
    removed = client.delete(f"/api/machining-dfm/tools/{tool_id}", headers=headers).json()
    assert removed["removed"]["remaining"] == 0
    assert removed["usage"][0]["project"] == "带刀具的项目"


def test_legacy_tool_payload_is_migrated(legacy_root, seed_dir):
    store = MachiningDFMStore(legacy_root, seed_dir)
    rows = store.tools.list_typed()
    assert [row["tp"] for row in rows] == ["D50面铣刀", "D12合金铣刀", "BT30刀柄", "PCD倒角刀", "试验刀具"]
    assert rows[0]["grp"] == "hp" and rows[2]["grp"] == "hld"
    assert rows[1]["cat"] == "hm" and rows[2]["cat"] == "cn"
    assert rows[1]["d"] == 12.0 and rows[1]["price"] == 260.0
    # 旧分类码 chamfer 按原名归一化成 pc（PCD倒角刀）；未知码 zzz 自动补录进字典
    assert rows[3]["cat"] == "pc"
    assert rows[4]["cat"] == "zzz"
    codes = {item["code"]: item for item in store.tool_dict.categories()}
    assert codes["pc"]["label"] == "PCD倒角刀" and codes["pc"]["source"] == "seed"
    assert codes["zzz"]["source"] == "legacy" and codes["zzz"]["builtin"] is False
    assert "chamfer" not in codes
    # 图片从 payload 搬到磁盘，行里只剩外键与 URL（旧读模型仍是 tI）。
    assert rows[1]["photo_url"].startswith("/api/machining-dfm/assets/")
    assert store.tools.list_legacy()[1]["tI"] == rows[1]["photo_url"]
    files = list((legacy_root / "assets" / "tool_photo").rglob("*.png"))
    assert len(files) == 1 and files[0].read_bytes() == PHOTO_BYTES

    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM tools_legacy_v1").fetchone()[0] == 5
        assert json.loads(db.execute(
            "SELECT value_json FROM app_settings WHERE key='tool_library_schema_version'"
        ).fetchone()[0]) == 3
        assert db.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 5
        # 分类/类型是独立字典表，tools 通过外键引用
        foreign_keys = {(row[2], row[3], row[4]) for row in db.execute("PRAGMA foreign_key_list(tools)")}
        assert ("tool_groups", "tool_group", "code") in foreign_keys
        assert ("tool_categories", "category", "code") in foreign_keys
        assert db.execute("SELECT COUNT(*) FROM tool_groups").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM tool_categories").fetchone()[0] == 50  # 49 内置 + 1 旧数据补录
        # 外键真的生效：直接写一个字典里没有的分类会被数据库拒绝
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO tools(id,sort_order,tool_group,name,category,created,updated) "
                "VALUES('x',0,'nope','越权刀具','hm','t','t')"
            )
    assert (legacy_root / "backups" / "pre-typed-tools.sqlite3").is_file()

    # 幂等：再启动一次不会重复插入，id 与顺序都保持不变。
    again = MachiningDFMStore(legacy_root, seed_dir)
    assert [row["id"] for row in again.tools.list_typed()] == [row["id"] for row in rows]
    assert again.tools.count() == 5
    assert again.libraries()["tdb"][0]["tp"] == "D50面铣刀"


def test_dictionaries_are_split_tables_and_drive_the_page(store, tmp_path):
    client = make_client(store, tmp_path)
    headers = admin_headers(client)
    state = client.get("/api/machining-dfm/tool-dictionaries").json()
    assert [item["code"] for item in state["groups"]] == ["hp", "dp", "hld", "acc"]
    assert state["groups"][2]["label"] == "刀柄" and state["groups"][0]["builtin"] is True
    scopes = {item["code"]: item["scope"] for item in state["categories"]}
    assert scopes["cn"] == "nc" and scopes["im"] == "nc" and scopes["hm"] == "cut"
    assert state["usage"] == {"groups": {}, "categories": {}}

    # 页面下拉的取值与中文名来自字典表（改了名称立刻反映到字段登记表）
    fields = client.get("/api/machining-dfm/tools/fields").json()["fields"]
    group_field = [item for item in fields if item["key"] == "grp"][0]
    assert [item["value"] for item in group_field["choices"]] == ["hp", "dp", "hld", "acc"]
    renamed = client.patch(
        "/api/machining-dfm/tool-categories/hm", headers=headers, json={"label": "合金铣刀（改名）"}
    )
    assert renamed.status_code == 200 and renamed.json()["category"]["label"] == "合金铣刀（改名）"
    fields = client.get("/api/machining-dfm/tools/fields").json()["fields"]
    cat_field = [item for item in fields if item["key"] == "cat"][0]
    labels = {item["value"]: item["label"] for item in cat_field["choices"]}
    assert labels["hm"] == "合金铣刀（改名）"

    # 新增自定义类型并直接用于刀具
    created = client.post(
        "/api/machining-dfm/tool-categories",
        headers=headers,
        json={"code": "x1", "label": "自定义成型刀", "scope": "cut"},
    )
    assert created.status_code == 200
    tool = client.post(
        "/api/machining-dfm/tools", headers=headers, json={"grp": "hp", "tp": "成型刀", "cat": "x1"}
    )
    assert tool.status_code == 200 and tool.json()["tool"]["cat"] == "x1"
    # 被刀具引用时不能删除；清掉引用后才能删（内置项永远不能删）
    assert client.delete("/api/machining-dfm/tool-categories/x1", headers=headers).status_code == 409
    client.delete(f"/api/machining-dfm/tools/{tool.json()['tool']['id']}", headers=headers)
    assert client.delete("/api/machining-dfm/tool-categories/x1", headers=headers).status_code == 200
    assert client.delete("/api/machining-dfm/tool-categories/hm", headers=headers).status_code == 409
    assert client.delete("/api/machining-dfm/tool-groups/hp", headers=headers).status_code == 409
    assert client.post(
        "/api/machining-dfm/tool-categories", headers=headers, json={"code": "hm", "label": "重复"}
    ).status_code == 409
    assert client.post(
        "/api/machining-dfm/tool-categories", headers=headers, json={"code": "x2", "label": "坏归属", "scope": "xx"}
    ).status_code == 422


def test_tool_dict_choices_reject_unknown_and_wrong_scope(store):
    with pytest.raises(HTTPException) as unknown_group:
        store.tools.create({"grp": "nope", "tp": "越界刀具", "cat": "hm"})
    assert unknown_group.value.status_code == 422 and "库分类" in unknown_group.value.detail
    with pytest.raises(HTTPException) as unknown_category:
        store.tools.create({"grp": "hp", "tp": "越界刀具", "cat": "milling"})
    assert unknown_category.value.status_code == 422 and "类型" in unknown_category.value.detail
    # 类型归属要与库分类一致：国内/进口 只能用于刀柄与配件
    with pytest.raises(HTTPException) as wrong_scope:
        store.tools.create({"grp": "hp", "tp": "错归属", "cat": "cn"})
    assert wrong_scope.value.status_code == 422 and "只用于" in wrong_scope.value.detail
    with pytest.raises(HTTPException) as wrong_scope_back:
        store.tools.create({"grp": "hld", "tp": "错归属", "cat": "hm"})
    assert wrong_scope_back.value.status_code == 422
    # 切换库分类时必须同时给出合规类型（页面就是这么提交的）
    tool = store.tools.create({"grp": "hp", "tp": "切换试验", "cat": "hm"})["id"]
    with pytest.raises(HTTPException):
        store.tools.update(tool, {"grp": "hld"})
    updated = store.tools.update(tool, {"grp": "hld", "cat": "cn"})
    assert updated["grp"] == "hld" and updated["cat"] == "cn"
    usage = store.tools.reference_counts()
    assert usage["groups"]["hld"] == 1 and usage["categories"]["cn"] == 1


V2_TOOLS_SCHEMA = """
CREATE TABLE tools(
    id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL DEFAULT 0,
    tool_group TEXT NOT NULL DEFAULT 'hp', name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'other', diameter REAL NOT NULL DEFAULT 0.0,
    length REAL NOT NULL DEFAULT 0.0, spindle_rpm REAL NOT NULL DEFAULT 0.0,
    feed_rate REAL NOT NULL DEFAULT 0.0, life_minutes REAL NOT NULL DEFAULT 0.0,
    price REAL NOT NULL DEFAULT 0.0, photo_id TEXT REFERENCES assets(id),
    created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE INDEX idx_machining_dfm_tools_order ON tools(sort_order, id);
CREATE INDEX idx_machining_dfm_tools_group ON tools(tool_group);
CREATE INDEX idx_machining_dfm_tools_category ON tools(category);
"""


def test_v2_tools_table_is_rebuilt_with_foreign_keys(tmp_path, seed_dir):
    """已经是"类型化但无外键"的库（上一版形态）要能原地升级到字典表 + 外键。"""
    root = tmp_path / "data" / "machining_dfm"
    store = MachiningDFMStore(root, seed_dir)
    store.tools.insert_rows([
        {"grp": "hp", "tp": "旧刀具A", "cat": "hm", "d": 10, "price": 100},
        {"grp": "hld", "tp": "旧刀柄", "cat": "cn", "price": 800},
    ])
    raw = sqlite3.connect(root / "machining_dfm.sqlite3")
    raw.executescript(
        "PRAGMA foreign_keys=OFF;"
        "DROP TABLE tools;"
        "DROP TABLE tool_groups;"
        "DROP TABLE tool_categories;"
    )
    raw.executescript(V2_TOOLS_SCHEMA)
    now = "2026-01-02T00:00:00+00:00"
    raw.execute(
        "INSERT INTO tools(id,sort_order,tool_group,name,category,diameter,price,created,updated) "
        "VALUES('t1',0,'hp','旧刀具A','hm',10,100,?,?)",
        (now, now),
    )
    raw.execute(
        "INSERT INTO tools(id,sort_order,tool_group,name,category,diameter,price,created,updated) "
        "VALUES('t2',1,'hld','旧刀柄','cn',0,800,?,?)",
        (now, now),
    )
    raw.execute("UPDATE app_settings SET value_json='2' WHERE key='tool_library_schema_version'")
    raw.commit()
    raw.close()

    upgraded = MachiningDFMStore(root, seed_dir)
    assert [row["id"] for row in upgraded.tools.list_typed()] == ["t1", "t2"]
    assert [row["tp"] for row in upgraded.tools.list_typed()] == ["旧刀具A", "旧刀柄"]
    assert upgraded.tools.find("t1")["price"] == 100.0
    with upgraded.connect() as db:
        # 旧表本来就有指向 assets 的图片外键，这里要看的是新增的两条字典外键
        targets = {(row[2], row[3]) for row in db.execute("PRAGMA foreign_key_list(tools)")}
        assert ("tool_groups", "tool_group") in targets and ("tool_categories", "category") in targets
        assert db.execute("SELECT COUNT(*) FROM tool_groups").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM tool_categories").fetchone()[0] == 49
        indexes = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='tools'"
        )}
        assert {"idx_machining_dfm_tools_order", "idx_machining_dfm_tools_group",
                "idx_machining_dfm_tools_category"} <= indexes
        assert json.loads(db.execute(
            "SELECT value_json FROM app_settings WHERE key='tool_library_schema_version'"
        ).fetchone()[0]) == 3
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='tools_pre_foreign_keys'").fetchone()[0] == 0
    assert (root / "backups" / "pre-tool-dictionaries.sqlite3").is_file()

    # 升级后再启动不会重复重建，数据与字典都稳定
    again = MachiningDFMStore(root, seed_dir)
    assert [row["id"] for row in again.tools.list_typed()] == ["t1", "t2"]
    assert again.tools.count() == 2
    assert len(again.tool_dict.categories()) == 49


# ---------------------------------------------------------------- 夹具库 / 检具库

FIXTURE_PAGE_HEADERS = ["模具中心", "图片", "名称", "价格 ¥", "制造周期 天", "备注"]
GAUGE_PAGE_HEADERS = [
    "检具类别", "图片", "检具名称", "检具图号", "产品尺寸 mm", "检具尺寸 mm",
    "价格 万¥", "设计周期 天", "制造周期 天",
]
FIXTURE_LEGACY_KEYS = {"center", "img", "mc", "name", "price", "rmk"}
GAUGE_LEGACY_KEYS = {"type", "img", "dc", "drw", "inspSize", "mc", "name", "prdSize", "price"}


def test_fixture_gauge_registry_matches_page(store):
    """字段登记表要覆盖页面表头：键、列名、单位都对得上。"""
    fields = {item["key"]: item for item in store.fixture_fields()["fields"]}
    assert [item["label"] + (f" {item['unit']}" if item["unit"] else "")
            for item in store.fixture_fields()["fields"]] == [
        "模具中心", "名称", "价格 ¥", "制造周期 天", "备注",
    ]
    assert fields["center"]["references"] == "fixture_centers"
    assert fields["mc"]["column"] == "process_days" and fields["mc"]["type"] == "int"
    assert [item["value"] for item in fields["center"]["choices"]] == [
        "1025减震模具中心", "1059轻合金模具中心", "1929底盘模具中心", "8107结构件模具中心",
    ]
    assert store.fixtures.field_columns == ("center", "name", "price", "process_days", "remark")

    gauge_fields = {item["key"]: item for item in store.gauge_fields()["fields"]}
    assert [item["label"] + (f" {item['unit']}" if item["unit"] else "")
            for item in store.gauge_fields()["fields"]] == [
        "检具类别", "检具名称", "检具图号", "产品尺寸 mm", "检具尺寸 mm", "价格 万¥",
        "设计周期 天", "制造周期 天",
    ]
    assert gauge_fields["type"]["references"] == "gauge_categories"
    assert gauge_fields["type"]["column"] == "category"
    assert gauge_fields["prdSize"]["column"] == "product_size"
    assert gauge_fields["inspSize"]["column"] == "inspection_size"
    assert gauge_fields["price"]["unit"] == "万¥"
    assert gauge_fields["mc"]["column"] == "process_days"
    assert gauge_fields["dc"]["column"] == "design_days"
    assert [item["value"] for item in gauge_fields["type"]["choices"]] == [
        "毛坯检具", "成品机械检具", "成品总成检具", "成品电子检具", "测量支架",
    ]
    assert store.gauges.field_columns == (
        "category", "name", "drawing", "product_size", "inspection_size", "price",
        "design_days", "process_days",
    )


def test_fixture_gauge_tables_have_dictionary_foreign_keys(store):
    with store.connect() as db:
        for table, column, target in (
            ("fixtures", "center", "fixture_centers"),
            ("gauges", "category", "gauge_categories"),
        ):
            foreign_keys = {(row[2], row[3], row[4]) for row in db.execute(f"PRAGMA foreign_key_list({table})")}
            assert (target, column, "name") in foreign_keys
            assert ("assets", "photo_id", "id") in foreign_keys
        # 外键生效：写字典外的类别会被数据库拒绝
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO fixtures(id,sort_order,center,name,created,updated) "
                "VALUES('x',0,'不存在的中心','夹具','t','t')"
            )
    assert [item["name"] for item in store.fixture_centers.names()] == [
        "1025减震模具中心", "1059轻合金模具中心", "1929底盘模具中心", "8107结构件模具中心",
    ]
    assert len(store.gauge_categories.names()) == 5


def test_legacy_fixture_and_gauge_payloads_are_migrated(legacy_root, seed_dir):
    store = MachiningDFMStore(legacy_root, seed_dir)
    fixtures = store.fixtures.list_typed()
    assert [row["name"] for row in fixtures] == ["四轴机加夹具", "五轴机加夹具", "试验夹具"]
    assert fixtures[0]["center"] == "1025减震模具中心" and fixtures[0]["mc"] == 30
    assert fixtures[1]["price"] == 35000.0 and fixtures[1]["rmk"] == "含外购件"
    gauges = store.gauges.list_typed()
    assert gauges[0]["type"] == "毛坯检具" and gauges[0]["prdSize"] == "1138*700*461"
    assert gauges[0]["price"] == 12.5 and gauges[0]["dc"] == 15 and gauges[0]["mc"] == 40
    assert gauges[2]["type"] == "试验检具类别"

    # 旧短键视图原样保留（渲染器与导出不用改）
    assert set(store.fixtures.list_legacy()[0]) == FIXTURE_LEGACY_KEYS | {"id"}
    assert set(store.gauges.list_legacy()[0]) == GAUGE_LEGACY_KEYS | {"id"}
    # 图片搬到磁盘，行里只剩外键与 URL
    assert fixtures[1]["photo_url"].startswith("/api/machining-dfm/assets/")
    assert store.fixtures.list_legacy()[1]["img"] == fixtures[1]["photo_url"]
    files = list((legacy_root / "assets" / "fixture_photo").rglob("*.png"))
    assert len(files) == 1 and files[0].read_bytes() == PHOTO_BYTES

    # 数据里出现、字典里没有的类别自动补录，标注来源 legacy
    centers = {item["name"]: item for item in store.fixture_centers.names()}
    assert centers["9999试验模具中心"]["source"] == "legacy"
    assert centers["9999试验模具中心"]["builtin"] is False
    categories = {item["name"]: item for item in store.gauge_categories.names()}
    assert categories["试验检具类别"]["source"] == "legacy"

    with store.connect() as db:
        versions = {row[0]: json.loads(row[1]) for row in db.execute(
            "SELECT key,value_json FROM app_settings WHERE key LIKE '%schema_version'"
        )}
        assert versions["fixture_library_schema_version"] == 2
        assert versions["gauge_library_schema_version"] == 2
        assert db.execute("SELECT COUNT(*) FROM fixtures_legacy_v1").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM gauges_legacy_v1").fetchone()[0] == 3
    assert (legacy_root / "backups" / "pre-typed-fixtures.sqlite3").is_file()
    assert (legacy_root / "backups" / "pre-typed-gauges.sqlite3").is_file()

    # 幂等：再启动一次数据不重复、id 不变
    again = MachiningDFMStore(legacy_root, seed_dir)
    assert [row["id"] for row in again.fixtures.list_typed()] == [row["id"] for row in fixtures]
    assert again.fixtures.count() == 3 and again.gauges.count() == 3
    assert len(again.fixture_centers.names()) == 5 and len(again.gauge_categories.names()) == 6


def test_fixture_gauge_row_level_api(store, tmp_path):
    client = make_client(store, tmp_path)
    headers = admin_headers(client)

    listing = client.get("/api/machining-dfm/fixtures").json()
    assert listing["count"] == 0 and listing["fields"]["fields"][0]["key"] == "center"

    created = client.post(
        "/api/machining-dfm/fixtures",
        headers=headers,
        json={"center": "1025减震模具中心", "name": "四轴机加夹具", "price": 12000, "mc": 30},
    )
    assert created.status_code == 200
    fixture = created.json()["fixture"]
    assert fixture["mc"] == 30 and fixture["rmk"] == "" and fixture["photo_url"] is None

    patched = client.patch(
        f"/api/machining-dfm/fixtures/{fixture['id']}", headers=headers, json={"price": 13500}
    )
    assert patched.status_code == 200 and patched.json()["fixture"]["price"] == 13500.0
    assert patched.json()["fixture"]["name"] == "四轴机加夹具"
    # 未知类别 422；负数与超限 422
    assert client.patch(
        f"/api/machining-dfm/fixtures/{fixture['id']}", headers=headers, json={"center": "无此中心"}
    ).status_code == 422
    assert client.post(
        "/api/machining-dfm/fixtures", headers=headers,
        json={"center": "1025减震模具中心", "name": "负数", "price": -1},
    ).status_code == 422

    gauge = client.post(
        "/api/machining-dfm/gauges",
        headers=headers,
        json={"type": "毛坯检具", "name": "左后纵梁毛坯检具", "drw": "9020045309-01",
              "prdSize": "1138*700*461", "inspSize": "1200*1000*1400", "price": 12.5,
              "dc": 15, "mc": 40},
    ).json()["gauge"]
    assert gauge["type"] == "毛坯检具" and gauge["dc"] == 15
    assert client.post(
        "/api/machining-dfm/gauges", headers=headers,
        json={"type": "无此类别", "name": "越界检具"},
    ).status_code == 422

    # 图片上传/删除（夹具、检具各一套）
    for name, key, row_id in (("fixtures", "fixture", fixture["id"]), ("gauges", "gauge", gauge["id"])):
        uploaded = client.put(
            f"/api/machining-dfm/{name}/{row_id}/photo",
            headers={**headers, "Content-Type": "image/png"},
            content=PHOTO_BYTES,
        )
        assert uploaded.status_code == 200
        url = uploaded.json()[key]["photo_url"]
        assert url.startswith("/api/machining-dfm/assets/")
        assert client.get(url).content == PHOTO_BYTES
        cleared = client.delete(f"/api/machining-dfm/{name}/{row_id}/photo", headers=headers)
        assert cleared.status_code == 200
        assert cleared.json()[key]["photo_url"] is None
        assert client.put(
            f"/api/machining-dfm/{name}/{row_id}/photo",
            headers={**headers, "Content-Type": "application/zip"},
            content=b"pk",
        ).status_code == 415

    # 排序必须提交全量 id
    assert client.post(
        "/api/machining-dfm/gauges/reorder", headers=headers, json={"ids": []}
    ).status_code == 422
    reordered = client.post(
        "/api/machining-dfm/gauges/reorder", headers=headers, json={"ids": [gauge["id"]]}
    )
    assert reordered.status_code == 200

    # 删除不阻塞：只回报引用它的项目
    assert client.delete(f"/api/machining-dfm/fixtures/{fixture['id']}", headers=headers).status_code == 200
    assert client.get("/api/machining-dfm/fixtures").json()["count"] == 0
    assert client.get("/api/machining-dfm/gauges").json()["count"] == 1
    # 未登录不能写
    assert client.post(
        "/api/machining-dfm/gauges", json={"type": "毛坯检具", "name": "越权"}
    ).status_code == 401


def test_named_dictionary_crud_and_cascade_delete(store, tmp_path):
    client = make_client(store, tmp_path)
    headers = admin_headers(client)

    state = client.get("/api/machining-dfm/library-dictionaries").json()
    assert [item["name"] for item in state["centers"]] == [
        "1025减震模具中心", "1059轻合金模具中心", "1929底盘模具中心", "8107结构件模具中心",
    ]
    assert state["usage"] == {"centers": {}, "categories": {}}

    # 新增自定义模具中心 → 直接可用于夹具
    created = client.post(
        "/api/machining-dfm/fixture-centers", headers=headers, json={"name": "1999试验模具中心"}
    )
    assert created.status_code == 200 and created.json()["row"]["builtin"] is False
    assert client.post(
        "/api/machining-dfm/fixture-centers", headers=headers, json={"name": "1999试验模具中心"}
    ).status_code == 409
    fixture = client.post(
        "/api/machining-dfm/fixtures", headers=headers,
        json={"center": "1999试验模具中心", "name": "试验夹具", "price": 500},
    ).json()["fixture"]

    # 有数据时不能直接删；内置类别永远不能删；改名会被拒（外键是中文名）
    assert client.delete("/api/machining-dfm/fixture-centers/1999试验模具中心", headers=headers).status_code == 409
    assert client.delete("/api/machining-dfm/fixture-centers/1025减震模具中心", headers=headers).status_code == 409
    assert client.patch(
        "/api/machining-dfm/fixture-centers/1999试验模具中心", headers=headers, json={"name": "改名"}
    ).status_code == 422
    moved = client.patch(
        "/api/machining-dfm/fixture-centers/1999试验模具中心", headers=headers, json={"sort_order": 9}
    )
    assert moved.status_code == 200 and moved.json()["row"]["sort_order"] == 9

    # 带 cascade=1 才能连同数据一起删
    cascade = client.delete(
        "/api/machining-dfm/fixture-centers/1999试验模具中心?cascade=1", headers=headers
    )
    assert cascade.status_code == 200 and cascade.json()["removed"]["removed_rows"] == 1
    assert client.get("/api/machining-dfm/fixtures").json()["count"] == 0
    assert client.get("/api/machining-dfm/fixture-centers").json()["usage"] == {}

    # 检具类别同样：自定义可加可删，内置不可删
    assert client.post(
        "/api/machining-dfm/gauge-categories", headers=headers, json={"name": "试验检具类别"}
    ).status_code == 200
    assert client.delete("/api/machining-dfm/gauge-categories/试验检具类别", headers=headers).status_code == 200
    assert client.delete("/api/machining-dfm/gauge-categories/测量支架", headers=headers).status_code == 409
    assert client.post(
        "/api/machining-dfm/gauge-categories", headers=headers, json={"name": ""}
    ).status_code == 422
    assert fixture["center"] == "1999试验模具中心"


def test_library_compat_endpoints_keep_old_clients_working(store, tmp_path):
    client = make_client(store, tmp_path)
    headers = admin_headers(client)

    client.post(
        "/api/machining-dfm/fixtures", headers=headers,
        json={"center": "1025减震模具中心", "name": "四轴机加夹具", "price": 12000, "mc": 30},
    )
    client.post(
        "/api/machining-dfm/gauges", headers=headers,
        json={"type": "毛坯检具", "name": "毛坯检具A", "drw": "D-1", "price": 5},
    )

    libraries = client.get("/api/machining-dfm/libraries").json()
    assert set(libraries["counts"]) == {"mdb", "tdb", "fdb", "idb"}
    assert libraries["counts"]["fdb"] == 1 and libraries["counts"]["idb"] == 1
    assert libraries["libraries"]["fcnX"][0] == "1025减震模具中心"
    assert libraries["libraries"]["icnX"][0] == "毛坯检具"
    # 引导数据仍然把类别列表放在旧键上，页面 fixClasses()/inspClasses() 照旧可用
    assert store.compose({"G": {}})["G"]["fcnX"][0] == "1025减震模具中心"

    # 旧客户端的整库保存：按 (类别, 名称) / (类别, 名称, 图号) 匹配更新，不再整表覆盖成 payload
    saved = client.put(
        "/api/machining-dfm/libraries",
        headers=headers,
        json={
            "fdb": [{"center": "1025减震模具中心", "name": "四轴机加夹具", "price": 13000,
                     "mc": 35, "rmk": "改价", "img": ""},
                    {"center": "1059轻合金模具中心", "name": "新增夹具", "price": 900}],
            "idb": [{"type": "毛坯检具", "name": "毛坯检具A", "drw": "D-1", "price": 6}],
            "icnX": ["毛坯检具", "自定义类别"],
            "fcnX": ["1025减震模具中心"],
        },
    )
    assert saved.status_code == 200
    counts = saved.json()["counts"]
    assert counts["fdb"]["count"] == 2 and counts["fdb"]["inserted"] == 1
    assert counts["idb"]["count"] == 1 and counts["idb"]["updated"] == 1
    rows = {row["name"]: row for row in client.get("/api/machining-dfm/fixtures").json()["fixtures"]}
    assert rows["四轴机加夹具"]["price"] == 13000.0 and rows["四轴机加夹具"]["mc"] == 35
    assert rows["四轴机加夹具"]["rmk"] == "改价"
    assert "新增夹具" in rows
    # 类别只补录、不整表覆盖（内置类别不会因为旧客户端没提交而消失）
    assert "自定义类别" in [item["name"] for item in store.gauge_categories.names()]
    assert "测量支架" in [item["name"] for item in store.gauge_categories.names()]


def test_legacy_bulk_save_never_deletes_rows(store, tmp_path):
    """旧接口的整体保存只增改不删：部分提交（甚至空数组）不能删掉库里其余数据。

    回归用例：这条接口曾经沿用"提交里没有就删"的整表覆盖语义，
    一次只带一行的提交把真实库里的 177 条夹具与 437 条检具全删了。
    """
    client = make_client(store, tmp_path)
    headers = admin_headers(client)
    for name in ("夹具一", "夹具二", "夹具三"):
        client.post("/api/machining-dfm/fixtures", headers=headers,
                    json={"center": "1025减震模具中心", "name": name, "price": 100})
    for index in range(2):
        client.post("/api/machining-dfm/gauges", headers=headers,
                    json={"type": "毛坯检具", "name": f"检具{index}", "drw": f"D-{index}"})

    saved = client.put(
        "/api/machining-dfm/libraries",
        headers=headers,
        json={"fdb": [{"center": "1025减震模具中心", "name": "夹具一", "price": 999}],
              "idb": [], "icnX": [], "fcnX": []},
    )
    assert saved.status_code == 200
    assert saved.json()["counts"]["fdb"]["updated"] == 1
    assert saved.json()["counts"]["fdb"]["removed"] == []
    assert saved.json()["counts"]["idb"]["removed"] == []

    rows = {row["name"]: row for row in client.get("/api/machining-dfm/fixtures").json()["fixtures"]}
    assert set(rows) == {"夹具一", "夹具二", "夹具三"}
    assert rows["夹具一"]["price"] == 999.0
    assert client.get("/api/machining-dfm/gauges").json()["count"] == 2

    # 空提交同样不动任何数据
    empty = client.put("/api/machining-dfm/libraries", headers=headers,
                       json={"fdb": [], "idb": [], "icnX": [], "fcnX": []})
    assert empty.status_code == 200
    assert client.get("/api/machining-dfm/fixtures").json()["count"] == 3
    assert client.get("/api/machining-dfm/gauges").json()["count"] == 2
    # 删除只能走行级接口
    target = rows["夹具二"]["id"]
    assert client.delete(f"/api/machining-dfm/fixtures/{target}", headers=headers).status_code == 200
    assert client.get("/api/machining-dfm/fixtures").json()["count"] == 2


# ------------------------------------------------------- 项目信息（project_settings）


def project_info_state(part="P-INFO"):
    """带项目图片（data URL）与建模外键（lang/_vSnap）的项目信息。"""
    return {
        "mdb": [{"brand": "A", "model": "M1"}],
        "tdb": [], "fdb": [], "idb": [],
        "pr": [{"nm": "OP10", "tl": []}],
        "is": [],
        "vh": [{"dt": "2026-01-01", "ver": "V1.0", "ds": "初版", "by": "张三"}],
        "G": {
            "cust": "赛力斯 SERES", "part": part, "prj": "dp", "custVer": "V2.1",
            "dfmDate": "2026-09-17", "hpd": 20, "sft": 2, "dpm": 26, "avl": 0.9,
            "len": 120, "wid": 80, "hgt": 40, "wgt": 3.5, "showFlow": 0,
            "bInspType": "通用游标卡尺", "bInspPrice": 1200, "fInspType": "三坐标测量机",
            "fInspPrice": 8000, "msInspPrice": 500,
            "pI": photo_data_url(), "pf": None, "bInspImg": None, "fInspImg": None,
            "lang": "zh", "_vSnap": {"_pr": 1},
        },
    }


def test_project_settings_are_row_level_and_read_model_is_unchanged(store):
    """项目信息落表：一行一列；旧读模型 G 逐键还原（图片 inline 后逐字相同）。"""
    created = store.create("项目信息用例", project_info_state())
    project_id = created["id"]

    with store.connect() as db:
        row = db.execute("SELECT * FROM project_settings WHERE project_id=?", (project_id,)).fetchone()
        raw = json.loads(db.execute("SELECT state_json FROM projects WHERE id=?", (project_id,)).fetchone()[0])

    assert row["customer"] == "赛力斯 SERES"
    assert row["part"] == "P-INFO"
    assert row["project_type"] == "dp"
    assert row["hours_per_day"] == 20.0 and row["availability"] == 0.9
    assert row["length"] == 120.0 and row["weight"] == 3.5
    assert row["blank_insp_price"] == 1200.0 and row["final_insp_price"] == 8000.0
    assert row["product_photo_id"]  # 产品图片已进附件库
    assert row["blank_insp_photo_id"] is None and row["final_insp_photo_id"] is None
    # 建模之外的键整份兜底，一个都不丢
    assert json.loads(row["extra_json"]) == {"lang": "zh", "_vSnap": {"_pr": 1}}
    # projects.state_json 只剩业务数组
    assert set(raw) == {"pr", "is", "vh"}
    assert raw["vh"][0]["ver"] == "V1.0"

    general = store.get(project_id)["state"]["G"]
    assert general["pI"].startswith("/api/machining-dfm/assets/")
    assert general["lang"] == "zh" and general["_vSnap"] == {"_pr": 1}
    assert general["icnX"] is not None and general["fcnX"] is not None  # 旧键仍在
    inlined = store.get(project_id, inline_assets=True)["state"]["G"]
    assert inlined["pI"] == photo_data_url()  # 导出/PPT 拿回原样的 data URL
    fields = {key: value for key, value in general.items() if key not in ("pI", "icnX", "fcnX")}
    assert fields == {
        "cust": "赛力斯 SERES", "part": "P-INFO", "prj": "dp", "custVer": "V2.1",
        "dfmDate": "2026-09-17", "hpd": 20.0, "sft": 2.0, "dpm": 26.0, "avl": 0.9,
        "len": 120.0, "wid": 80.0, "hgt": 40.0, "wgt": 3.5, "showFlow": 0,
        "bInspType": "通用游标卡尺", "bInspPrice": 1200.0, "fInspType": "三坐标测量机",
        "fInspPrice": 8000.0, "msInspPrice": 500.0, "pf": None, "bInspImg": None,
        "fInspImg": None, "lang": "zh", "_vSnap": {"_pr": 1},
    }


def test_project_settings_patch_keeps_version_and_leaves_other_fields(store):
    project_id = store.create("行级保存", project_info_state())["id"]
    before = store.get(project_id)

    saved = store.save_project_settings(project_id, {"cust": "赛力斯（改）"}, partial=True)
    assert saved["revision"] == before["revision"] + 1
    general = saved["state"]["G"]
    assert general["cust"] == "赛力斯（改）"
    assert general["part"] == "P-INFO" and general["hpd"] == 20.0  # 其它字段没被清掉
    assert general["lang"] == "zh"  # 兜底键也没被清掉

    # 每次保存都留版本（口径），并且快照里是保存后的项目信息
    versions = store.versions(project_id)
    assert versions[0]["revision"] == saved["revision"]
    snapshot = store.get(project_id, saved["revision"])
    assert snapshot["state"]["G"]["cust"] == "赛力斯（改）"
    assert store.get(project_id, before["revision"])["state"]["G"]["cust"] == "赛力斯 SERES"


def test_project_settings_validation_rejects_bad_values(store):
    project_id = store.create("校验", project_info_state())["id"]
    for payload in ({"hpd": 99}, {"prj": "xx"}, {"hpd": "abc"}, {"hpd": -1}, {"avl": 5}):
        with pytest.raises(HTTPException) as invalid:
            store.save_project_settings(project_id, payload, partial=True)
        assert invalid.value.status_code == 422
    # 整份保存（PUT 语义）没给的字段回默认值
    replaced = store.save_project_settings(project_id, {"cust": "只剩客户"}, partial=False)
    assert replaced["state"]["G"]["cust"] == "只剩客户"
    assert replaced["state"]["G"]["hpd"] == 0.0
    assert replaced["state"]["G"]["pI"] is None


def test_project_photo_upload_and_clear_releases_asset(store):
    project_id = store.create("图片", project_info_state())["id"]
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        typed = store.settings.typed(project_id)
    assert typed["blank_insp_id"] is None

    uploaded = store.set_project_photo(project_id, "blank_insp", PHOTO_BYTES, "image/png")
    url = uploaded["state"]["G"]["bInspImg"]
    assert url.startswith("/api/machining-dfm/assets/")
    assert store.settings.typed(project_id)["blank_insp_url"] == url
    assert uploaded["revision"] > 1  # 传图也算一次保存，照样留版本

    cleared = store.clear_project_photo(project_id, "blank_insp")
    assert cleared["state"]["G"]["bInspImg"] is None
    assert store.settings.typed(project_id)["blank_insp_id"] is None
    with store.connect() as db:
        after = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    assert after == before  # 没人引用的附件被回收，没留下垃圾


def test_two_photo_slots_sharing_one_image_do_not_break_clearing(store, tmp_path):
    """同一个项目两个图片槽位用同一张图（内容去重 → 同一个 assets 行）。

    清掉其中一个槽位时，另一个槽位还指着这一行：回收判断必须把**同一行其它附件列**
    也算进去，否则删完附件行立刻撞外键（HTTP 500 / IntegrityError）。
    `product` 与 `product2` 同属 `project_photo` 一类，所以这两格必然共用一行。
    """
    client = make_client(store, tmp_path)
    api = "/api/machining-dfm"
    project_id = store.create("共用图片", project_info_state())["id"]

    for slot in ("product", "product2"):
        uploaded = client.put(f"{api}/projects/{project_id}/photos/{slot}",
                              content=PHOTO_BYTES, headers={"Content-Type": "image/png"})
        assert uploaded.status_code == 200

    typed = store.settings.typed(project_id)
    assert typed["product_id"] == typed["product2_id"]      # 内容去重：同一行
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]

    # 清掉其中一个槽位：另一个槽位还在用，附件行必须留着，且不能报 500
    cleared = client.delete(f"{api}/projects/{project_id}/photos/product2")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["project"]["state"]["G"]["pf"] is None

    typed = store.settings.typed(project_id)
    assert typed["product2_id"] is None
    assert typed["product_id"]                                     # 兄弟槽位没被连坐
    with store.connect() as db:
        after = db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        still = db.execute("SELECT product_photo_id FROM project_settings WHERE project_id=?",
                           (project_id,)).fetchone()[0]
    assert after == before                                          # 还被用着 → 不回收
    assert still == typed["product_id"]

    # 两个槽位都清空后才允许回收
    assert client.delete(f"{api}/projects/{project_id}/photos/product").status_code == 200
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == before - 1


def test_whole_state_save_sharing_one_image_between_slots(store):
    """整份保存（旧前端路径）同样不能把兄弟槽位还指着的附件行删掉。"""
    project_id = store.create("整份保存共用图", project_info_state())["id"]
    first = store.set_project_photo(project_id, "blank_insp", PHOTO_BYTES, "image/png")
    url = first["state"]["G"]["bInspImg"]
    asset_id = store.settings.typed(project_id)["blank_insp_id"]
    store.set_project_photo(project_id, "final_insp", PHOTO_BYTES, "image/png")
    assert store.settings.typed(project_id)["final_insp_id"] == asset_id   # 同图 → 同一行

    # 整份保存：final_insp 清空、blank_insp 仍是这张图（其余槽位按整份语义回默认清空）
    saved = store.save_project_settings(
        project_id, {"bInspImg": url, "fInspImg": None}, partial=False)

    assert saved["state"]["G"]["bInspImg"] == url
    assert saved["state"]["G"]["fInspImg"] is None
    typed = store.settings.typed(project_id)
    assert typed["final_insp_id"] is None and typed["blank_insp_id"] == asset_id
    with store.connect() as db:
        alive = db.execute("SELECT COUNT(*) FROM assets WHERE id=?", (asset_id,)).fetchone()[0]
    assert alive == 1                   # 还被 blank_insp 指着，不许回收


def test_choice_error_lists_values_without_repeating_them(store):
    """枚举报错要能照着改：显示名和取值一样时不许再套一层括号。"""
    project_id = store.create("报错文案", project_info_state())["id"]
    with pytest.raises(HTTPException) as status_error:
        store.issues.create(project_id, {"tp": "尺寸", "st": "已关闭"})
    assert status_error.value.status_code == 422
    assert status_error.value.detail == "状态只能是：进行中、已完成"


def test_stale_sort_index_is_cleaned_on_open(store):
    """老版本留下的 ``..._sort`` 索引要在开库时清掉：同一个 (sort_order, id) 两条索引纯属浪费。"""
    with store.connect() as db:
        db.execute("CREATE INDEX IF NOT EXISTS idx_machining_dfm_machines_sort "
                   "ON machines(sort_order, id)")
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
                          "AND name='idx_machining_dfm_machines_sort'").fetchone()[0] == 1

    reopened = MachiningDFMStore(store.root, store.seed_file)
    with reopened.connect() as db:
        names = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='machines'")}
    assert "idx_machining_dfm_machines_sort" not in names
    assert "idx_machining_dfm_machines_order" in names


def test_log_endpoints_can_be_guarded(tmp_path, monkeypatch):
    """``install`` 支持给日志接口挂鉴权：机加服务的日志里有项目名与全部请求路径。"""
    from fastapi import FastAPI, HTTPException as FastAPIHTTPException

    from app.services import observability

    monkeypatch.setattr(observability, "DATA_DIR", tmp_path)

    def guard(authorization: str | None) -> None:
        if authorization != "Bearer admin-token":
            raise FastAPIHTTPException(401, "请先登录后台")

    app = FastAPI()
    observability.install(app, "guarded_service", guard)
    client = TestClient(app)

    assert client.get("/api/logs/tail").status_code == 401
    assert client.get("/api/logs/download").status_code == 401
    allowed = client.get("/api/logs/tail", headers={"Authorization": "Bearer admin-token"})
    assert allowed.status_code == 200
    assert allowed.json()["file"].endswith("server.log")

    # 不传 guard 的服务维持原样（别的分支还在用）
    plain = FastAPI()
    observability.install(plain, "plain_service")
    assert TestClient(plain).get("/api/logs/tail").status_code == 200


def test_legacy_whole_state_save_writes_settings_row(store):
    """旧前端仍然可以整份保存：内部拆成"项目信息进表 + 数组进 JSON"。"""
    project_id = store.list()[0]["id"]
    state = project_info_state("P-LEGACY")
    saved = store.update(project_id, "旧前端整份保存", state, 1)

    with store.connect() as db:
        row = db.execute("SELECT * FROM project_settings WHERE project_id=?", (project_id,)).fetchone()
        raw = json.loads(db.execute("SELECT state_json FROM projects WHERE id=?", (project_id,)).fetchone()[0])

    assert row["customer"] == "赛力斯 SERES" and row["part"] == "P-LEGACY"
    assert row["project_type"] == "dp" and row["availability"] == 0.9
    assert row["product_photo_id"]
    assert set(raw) == {"pr", "is", "vh"} and raw["vh"][0]["ds"] == "初版"
    assert saved["state"]["G"]["pI"] == store.get(project_id)["state"]["G"]["pI"]
    assert saved["state"]["G"]["lang"] == "zh"
    # 项目列表摘要（客户/零件）也能从表里读出来
    assert store.list()[0]["customer"] == "赛力斯 SERES"
    assert store.list()[0]["part"] == "P-LEGACY"


def test_project_settings_api_roundtrip(store, tmp_path):
    client = make_client(store, tmp_path)
    project_id = store.create("接口用例", project_info_state())["id"]

    fields = client.get("/api/machining-dfm/project-settings/fields").json()
    assert [item["key"] for item in fields["fields"]][:4] == ["cust", "part", "prj", "custVer"]
    assert [item["slot"] for item in fields["attachments"]] == [
        "product", "product2", "blank_insp", "final_insp"
    ]

    loaded = client.get(f"/api/machining-dfm/projects/{project_id}/settings").json()
    assert loaded["settings"]["cust"] == "赛力斯 SERES"
    assert loaded["settings"]["product_url"].startswith("/api/machining-dfm/assets/")

    patched = client.patch(
        f"/api/machining-dfm/projects/{project_id}/settings", json={"dpm": 30, "prj": "hp"}
    )
    assert patched.status_code == 200
    state = patched.json()["project"]["state"]["G"]
    assert state["dpm"] == 30.0 and state["prj"] == "hp" and state["cust"] == "赛力斯 SERES"

    assert client.patch(
        f"/api/machining-dfm/projects/{project_id}/settings", json={"prj": "nope"}
    ).status_code == 422

    uploaded = client.put(
        f"/api/machining-dfm/projects/{project_id}/photos/product",
        content=PHOTO_BYTES, headers={"content-type": "image/png"},
    )
    assert uploaded.status_code == 200
    url = uploaded.json()["project"]["state"]["G"]["pI"]
    assert url.startswith("/api/machining-dfm/assets/")
    assert client.get(url).content == PHOTO_BYTES  # 附件接口能取回同一张图
    cleared = client.delete(f"/api/machining-dfm/projects/{project_id}/photos/product")
    assert cleared.status_code == 200
    assert cleared.json()["project"]["state"]["G"]["pI"] is None
    assert client.delete(
        f"/api/machining-dfm/projects/{project_id}/photos/nope"
    ).status_code == 422

    whole = client.put(
        f"/api/machining-dfm/projects/{project_id}/settings",
        json={"cust": "整份保存", "part": "P-PUT", "hpd": 12},
    )
    assert whole.status_code == 200
    general = whole.json()["project"]["state"]["G"]
    assert general["cust"] == "整份保存" and general["part"] == "P-PUT" and general["hpd"] == 12.0
    assert general["len"] == 0.0  # 整份语义：没给的字段回默认


def test_project_settings_migration_is_idempotent(store):
    """迁移幂等：真旧库（state_json 里还带 G）启动即迁，重启不再重复迁、也不覆盖新值。"""
    project_id = store.list()[0]["id"]
    legacy_state = json.dumps(
        {"G": {"cust": "旧库客户", "part": "P-OLD", "lang": "th"}, "pr": [{"nm": "OP10", "tl": []}],
         "is": [], "vh": []},
        ensure_ascii=False,
    )
    with store.connect() as db:
        db.execute("UPDATE projects SET state_json=? WHERE id=?", (legacy_state, project_id))
        db.execute("DELETE FROM project_settings WHERE project_id=?", (project_id,))
        db.execute("DELETE FROM app_settings WHERE key='project_schema_version'")

    # 旧库真实形态：项目信息还在 state_json 里 → 启动时迁移
    migrated = MachiningDFMStore(store.root, store.seed_file)
    general = migrated.get(project_id)["state"]["G"]
    assert general["cust"] == "旧库客户" and general["part"] == "P-OLD"
    assert general["lang"] == "th"  # 建模外的键进 extra_json 兜底
    with migrated.connect() as db:
        version = db.execute("SELECT value_json FROM app_settings WHERE key='project_schema_version'").fetchone()
        archived = db.execute(
            "SELECT state_json FROM projects_legacy_v1 WHERE id=?", (project_id,)
        ).fetchone()
        raw = json.loads(db.execute("SELECT state_json FROM projects WHERE id=?", (project_id,)).fetchone()[0])
        rows = db.execute("SELECT COUNT(*) FROM project_settings").fetchone()[0]
    assert version is not None and json.loads(version[0]) == 1
    assert json.loads(archived[0])["G"]["cust"] == "旧库客户"  # 迁移前状态归档，可回滚
    assert set(raw) == {"pr", "is", "vh"}

    migrated.save_project_settings(project_id, {"cust": "迁移后改过"}, partial=True)
    restarted = MachiningDFMStore(store.root, store.seed_file)
    with restarted.connect() as db:
        again = db.execute("SELECT COUNT(*) FROM project_settings").fetchone()[0]
        customer = db.execute(
            "SELECT customer FROM project_settings WHERE project_id=?", (project_id,)
        ).fetchone()[0]
    assert again == rows  # 没多出一行
    assert customer == "迁移后改过"
    assert restarted.get(project_id)["state"]["G"]["cust"] == "迁移后改过"


def test_defaults_still_render_seed_project_info(store):
    """``/defaults`` 仍按种子项目信息组合（新项目从这份数据起步）。"""
    defaults = store.defaults()
    assert defaults["G"]["part"] == "P-001"
    assert defaults["mdb"] and defaults["pr"][0]["mid"] == "m-beta"
    assert "icnX" in defaults["G"] and "fcnX" in defaults["G"]




