import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.machining_dfm import MachiningDFMStore, router_for


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


@pytest.fixture()
def store(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(sample_state(), ensure_ascii=False), encoding="utf-8")
    return MachiningDFMStore(tmp_path / "data" / "machining_dfm", seed)


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
        auth = db.execute("SELECT password_hash FROM auth_settings WHERE role='admin'").fetchone()[0]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert set(raw) == {"G", "pr", "is", "vh"}
    assert {"equipment", "tools", "fixtures", "gauges", "auth_settings", "app_settings"} <= tables
    assert store.get(project_id)["state"]["mdb"] == [{"brand": "A", "model": "M1"}]
    assert "TP23456" not in auth


def test_empty_shared_library_stays_empty_after_restart(store):
    libraries = store.libraries()
    libraries["mdb"] = []
    store.replace_libraries({**libraries, "icnX": [], "fcnX": []})

    restarted = MachiningDFMStore(store.root, store.seed_file)
    assert restarted.libraries()["mdb"] == []


def test_router_crud_uses_dedicated_store(store, tmp_path):
    static = tmp_path / "static" / "machining_dfm"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<h1>machining</h1>", encoding="utf-8")
    app = FastAPI()
    app.include_router(router_for(lambda: store, tmp_path / "static"))
    client = TestClient(app)

    boot = client.get("/api/machining-dfm/bootstrap")
    assert boot.status_code == 200
    project = boot.json()["project"]
    assert project["state"]["G"]["part"] == "P-001"
    assert str(store.root) == boot.json()["data_dir"]
    assert client.get("/api/machining-dfm/defaults").json()["G"]["part"] == "P-001"

    assert client.put("/api/machining-dfm/libraries", json={}).status_code == 422
    assert client.put("/api/machining-dfm/libraries", json={"mdb": [], "tdb": [], "fdb": [], "idb": []}).status_code == 401
    process = client.post(
        "/api/machining-dfm/auth/login", json={"role": "process", "password": "TP123456"}
    ).json()["token"]
    assert client.put(
        "/api/machining-dfm/libraries",
        headers={"Authorization": f"Bearer {process}"},
        json={"mdb": [], "tdb": [], "fdb": [], "idb": []},
    ).status_code == 403
    admin = client.post(
        "/api/machining-dfm/auth/login", json={"role": "admin", "password": "TP23456"}
    ).json()["token"]
    changed = client.put(
        "/api/machining-dfm/config",
        headers={"Authorization": f"Bearer {admin}"},
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
        f"/api/machining-dfm/projects/{created.json()['id']}/archive?archived=true", json={}
    )
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert client.get("/api/machining-dfm/projects?archived=true").json()["projects"][0]["id"] == created.json()["id"]
    assert client.get("/machining-dfm").text == "<h1>machining</h1>"


def test_invalid_state_is_rejected(store):
    with pytest.raises(HTTPException) as error:
        store.create("坏数据", {"G": []})
    assert error.value.status_code == 422
