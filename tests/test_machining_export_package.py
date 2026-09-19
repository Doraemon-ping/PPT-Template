"""阶段 5 · 口径 §7.0：``GET /api/machining-dfm/projects/{pid}/export.zip``（导出文件包）。

包结构（定死、不自创）：``project.json``（与读模型同一份形状，附件字段换成包内相对路径）
+ ``assets/<id>.<ext>``（本项目真引用到的附件原始字节）+ ``README.txt``。

这里逐条钉住四件事：
1. 包内**正好**是那三个部分：project.json、README.txt、以及读模型里引用到的每个附件；
2. 包内附件字节与磁盘**逐字节一致**，且读模型里的附件字段逐个都能在包里找到；
3. 不引用别的项目 / 没被引用的附件；
4. 接口**只读**：导出前后读模型逐字节不变、库与 data/ 目录一个字节没动。
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.machining_dfm import MachiningDFMStore, router_for

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"pixel" * 40
PNG_BYTES_2 = b"\x89PNG\r\n\x1a\n" + b"other-pixel" * 60
PNG_BYTES_3 = b"\x89PNG\r\n\x1a\n" + b"third-pixel" * 80
DOC_BYTES = b"%PDF-1.4 package test document"

API = "/api/machining-dfm"
ASSET_PREFIX = "/api/machining-dfm/assets/"


# ---------------------------------------------------------------- 夹具


def write_seed_dir(root: Path) -> Path:
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


@pytest.fixture()
def client(store, tmp_path):
    static = tmp_path / "static" / "machining_dfm"
    static.mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<h1>machining</h1>", encoding="utf-8")
    app = FastAPI()
    app.include_router(router_for(lambda: store, tmp_path / "static"))
    return TestClient(app)


@pytest.fixture()
def admin(client) -> dict:
    token = client.post(f"{API}/auth/login",
                        json={"role": "admin", "password": "TP23456"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- 小工具


def blank_state(part="P-EXP") -> dict:
    return {"mdb": [], "tdb": [], "pr": [], "is": [], "fdb": [], "idb": [], "vh": [],
            "G": {"cust": "导出客户", "part": part}}


def new_project(client, name="导出测试项目", state=None) -> str:
    response = client.post(f"{API}/projects", json={"name": name, "state": state or blank_state()})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def put_photo(client, url, data=PNG_BYTES, mime="image/png", extra=None):
    response = client.put(url, content=data, headers={"content-type": mime, **(extra or {})})
    assert response.status_code == 200, response.text
    return response.json()


def read_model(client, project_id: str, **params) -> dict:
    response = client.get(f"{API}/projects/{project_id}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def collect_asset_values(node, prefix="") -> list[tuple[str, str]]:
    """读模型里所有指向附件的字段值（路径 + 值），路径相对 ``state``。"""
    found: list[tuple[str, str]] = []
    if isinstance(node, str):
        if node.startswith(ASSET_PREFIX):
            found.append((prefix, node))
        return found
    if isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(collect_asset_values(item, f"{prefix}[{index}]"))
        return found
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(collect_asset_values(value, f"{prefix}.{key}" if prefix else key))
    return found


def collect_relative_values(node, prefix="") -> list[tuple[str, str]]:
    """``project.json`` 里所有包内相对路径（``assets/<id>.<ext>``）。"""
    found: list[tuple[str, str]] = []
    if isinstance(node, str):
        if node.startswith("assets/"):
            found.append((prefix, node))
        return found
    if isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(collect_relative_values(item, f"{prefix}[{index}]"))
        return found
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(collect_relative_values(value, f"{prefix}.{key}" if prefix else key))
    return found


def asset_id_of(value: str) -> str:
    """``/api/machining-dfm/assets/<id>?download=1`` → ``<id>``。"""
    return value.split("?", 1)[0].split("#", 1)[0].rsplit("/", 1)[-1]


def open_package(response) -> tuple[zipfile.ZipFile, dict]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/zip"), \
        response.headers["content-type"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    return archive, json.loads(archive.read("project.json").decode("utf-8"))


def snapshot_tree(root: Path) -> dict:
    """data/ 目录里每个文件的大小 + sha256（导出前后必须一模一样）。"""
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            result[path.relative_to(root).as_posix()] = (
                path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()
            )
    return result


def snapshot_assets_table(db_path: Path) -> list[tuple]:
    connection = sqlite3.connect(db_path)
    try:
        return [tuple(row) for row in connection.execute(
            "SELECT id,kind,mime,name,size,sha256,path,created FROM assets ORDER BY id")]
    finally:
        connection.close()


def package_setup(client, admin) -> tuple[str, dict]:
    """造一个"有图可导"的项目：项目产品图 + 项目检具图 + 一台设备图 + 一份设备资料。

    返回 ``(project_id, 读模型)``。
    """
    project_id = new_project(client, "DFM 导出/非法:名*? 项目")
    put_photo(client, f"{API}/projects/{project_id}/photos/product", PNG_BYTES)
    put_photo(client, f"{API}/projects/{project_id}/photos/final_insp", PNG_BYTES_2)
    put_photo(client, f"{API}/machines/m-alpha/photo", PNG_BYTES, "image/png", admin)
    doc = client.put(f"{API}/machines/m-alpha/doc", content=DOC_BYTES,
                     headers={"content-type": "application/pdf", **admin})
    assert doc.status_code == 200, doc.text
    model = read_model(client, project_id)
    assert len(collect_asset_values(model["state"])) == 4, collect_asset_values(model["state"])
    return project_id, model


# ---------------------------------------------------------------- 1 包结构


def test_package_holds_exactly_read_model_named_assets_and_readme(store, client, admin):
    project_id, model = package_setup(client, admin)
    response = client.get(f"{API}/projects/{project_id}/export.zip")
    archive, _ = open_package(response)

    referenced = [asset_id_of(value) for _, value in collect_asset_values(model["state"])]
    expected = {"project.json", "README.txt"} | {
        f"assets/{asset_id}{Path(store.assets.record(asset_id)['path']).suffix}"
        for asset_id in referenced
    }
    assert len(expected) == 6, sorted(expected)      # 两份说明 + 4 个附件
    assert set(archive.namelist()) == expected, sorted(archive.namelist())
    # 不写空条目：每条 assets/ 都是真文件
    assert all(archive.getinfo(name).file_size > 0 for name in archive.namelist()), archive.namelist()


def test_package_asset_bytes_match_disk_and_paths_resolve(store, client, admin):
    project_id, _ = package_setup(client, admin)
    response = client.get(f"{API}/projects/{project_id}/export.zip")
    archive, payload = open_package(response)

    # project.json 里每个附件字段都是包内相对路径，且在包里逐个找得到
    relative = collect_relative_values(payload["state"])
    assert relative, "读模型里应当有附件引用"
    assert all(value.startswith("assets/") for _, value in relative), relative
    assert not any(ASSET_PREFIX in value for _, value in relative)
    assert all(value in set(archive.namelist()) for _, value in relative), relative

    # 字节与磁盘逐字节一致
    for name in archive.namelist():
        if not name.startswith("assets/"):
            continue
        asset_id = Path(name).stem
        record = store.assets.record(asset_id)
        assert record is not None, name
        assert name == f"assets/{asset_id}{Path(record['path']).suffix}"
        assert archive.read(name) == store.assets.file_path(record).read_bytes()
        assert archive.read(name) == store.assets.read_bytes(asset_id)
        assert len(archive.read(name)) == int(record["size"])

    # 读模型里引用了几处，project.json 里就换了几处（一处都不能漏）
    model = read_model(client, project_id)
    assert len(collect_asset_values(model["state"])) == len(relative)


def test_package_json_keeps_read_model_shape_and_export_block(store, client, admin):
    project_id, model = package_setup(client, admin)
    response = client.get(f"{API}/projects/{project_id}/export.zip")
    _, payload = open_package(response)

    assert set(payload) == set(model) | {"_export"}
    for key in model:
        if key != "state":
            assert payload[key] == model[key], key
    assert set(payload["state"]) == set(model["state"])
    for key in model["state"]:
        if not collect_asset_values(model["state"][key]):
            assert payload["state"][key] == model["state"][key], key

    block = payload["_export"]
    assert set(block) == {"format", "version", "project_id", "revision", "exported", "assets"}
    assert block["format"] == "machining-dfm-package"
    assert block["version"] == 1
    assert block["project_id"] == project_id
    assert block["revision"] == model["revision"]
    assert block["exported"].startswith("20")


def test_export_block_counts_the_assets_actually_packaged(store, client, admin):
    project_id, _ = package_setup(client, admin)
    response = client.get(f"{API}/projects/{project_id}/export.zip")
    archive, payload = open_package(response)
    packed = [name for name in archive.namelist() if name.startswith("assets/")]
    assert payload["_export"]["assets"] == len(packed) == 4, (payload["_export"], packed)


def test_readme_is_utf8_and_explains_the_package(store, client, admin):
    project_id, _ = package_setup(client, admin)
    response = client.get(f"{API}/projects/{project_id}/export.zip")
    archive, _ = open_package(response)
    text = archive.read("README.txt").decode("utf-8")
    assert "assets/" in text
    assert "project.json" in text
    assert "machining-dfm-package" in text
    assert "机加 DFM 项目工作台" in text            # 由哪个服务导出
    assert 3 <= len([line for line in text.splitlines() if line.strip()]) <= 6, text


# ---------------------------------------------------------------- 2 只打包本项目引用到的附件


def test_package_skips_assets_of_other_projects(store, client, admin):
    project_a, _ = package_setup(client, admin)
    other = new_project(client, "另一个项目")
    put_photo(client, f"{API}/projects/{other}/photos/product", PNG_BYTES_3)
    other_asset = None
    for _, value in collect_asset_values(read_model(client, other)["state"]):
        other_asset = asset_id_of(value)
    assert other_asset

    response = client.get(f"{API}/projects/{project_a}/export.zip")
    archive, payload = open_package(response)
    names = set(archive.namelist())
    assert not any(other_asset in name for name in names), names
    # 只被 B 项目引用的附件字节也不该出现在 A 的包里
    assert store.assets.read_bytes(other_asset) not in [archive.read(name) for name in names]
    assert payload["_export"]["project_id"] == project_a


def test_unreferenced_asset_is_not_packaged(store, client, admin):
    """库里躺着但没有任何项目引用的附件（内容寻址不回收）：不打包。"""
    project_id, model = package_setup(client, admin)
    orphan = store.assets.put("project_photo", PNG_BYTES_3, "image/png", "orphan.png")
    assert orphan is not None and orphan["id"] not in json.dumps(model)

    response = client.get(f"{API}/projects/{project_id}/export.zip")
    archive, _ = open_package(response)
    assert f"assets/{orphan['id']}.png" not in archive.namelist()
    assert store.assets.read_bytes(orphan["id"]) not in [archive.read(name)
                                                         for name in archive.namelist()]


def test_project_without_assets_still_ships_a_package(store, client):
    project_id = new_project(client, "没有图的项目")
    response = client.get(f"{API}/projects/{project_id}/export.zip")
    archive, payload = open_package(response)
    assert set(archive.namelist()) == {"project.json", "README.txt"}
    assert payload["_export"]["assets"] == 0
    assert collect_asset_values(payload["state"]) == []
    assert not any(name.startswith("assets/") for name in archive.namelist())


# ---------------------------------------------------------------- 3 边界


def test_unknown_project_is_404_with_chinese_detail(store, client):
    response = client.get(f"{API}/projects/deadbeef/export.zip")
    assert response.status_code == 404
    assert response.json()["detail"] == "机加 DFM 项目不存在"


def test_archived_project_still_exports(store, client, admin):
    project_id, _ = package_setup(client, admin)
    deleted = client.delete(f"{API}/projects/{project_id}?reason=导出测试", headers=admin)
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"{API}/projects/{project_id}").status_code == 410   # 读接口：已删项目 410
    assert client.get(f"{API}/projects/{project_id}",
                      params={"allow_archived": "true"}).status_code == 200

    response = client.get(f"{API}/projects/{project_id}/export.zip")
    archive, payload = open_package(response)
    assert payload["archived"] is True
    assert any(name.startswith("assets/") for name in archive.namelist())


def test_download_filename_is_safe_and_keeps_the_project_name(store, client, admin):
    project_id, _ = package_setup(client, admin)   # 项目名里带 / 与 :*? 这些非法字符
    response = client.get(f"{API}/projects/{project_id}/export.zip")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment; ")
    assert 'filename="' in disposition and "filename*=UTF-8''" in disposition
    ascii_name = disposition.split('filename="', 1)[1].split('"', 1)[0]
    assert ascii_name.startswith("DFM_") and ascii_name.endswith(".zip")
    assert all(character.isascii() for character in ascii_name)
    assert not any(character in ascii_name for character in '\\/:*?"<>|')
    disposition.encode("latin-1")      # 响应头整体必须能 latin-1 编码（中文只能走 filename*）

    from urllib.parse import unquote
    utf8_name = unquote(disposition.split("filename*=UTF-8''", 1)[1])
    assert utf8_name.startswith("DFM_") and utf8_name.endswith(".zip")
    assert "导出" in utf8_name and "项目" in utf8_name
    assert not any(character in utf8_name for character in '\\/:*?"<>|')
    assert "\n" not in utf8_name and "\r" not in utf8_name


def test_empty_project_name_still_gives_a_filename(store, client):
    project_id = client.get(f"{API}/projects").json()["projects"][0]["id"]
    with store.connect() as db:
        db.execute("UPDATE projects SET name='' WHERE id=?", (project_id,))
    response = client.get(f"{API}/projects/{project_id}/export.zip")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="DFM_project.zip"'), disposition
    assert disposition.endswith("filename*=UTF-8''DFM_project.zip"), disposition


# ---------------------------------------------------------------- 4 只读


def test_export_is_read_only(store, client, admin):
    project_id, _ = package_setup(client, admin)
    before_tree = snapshot_tree(store.root)
    before_rows = snapshot_assets_table(store.db_path)
    before_model = client.get(f"{API}/projects/{project_id}").content
    before_model_archived = client.get(
        f"{API}/projects/{project_id}", params={"allow_archived": "true"}).content
    before_projects = client.get(f"{API}/projects").content

    response = client.get(f"{API}/projects/{project_id}/export.zip")
    assert response.status_code == 200
    assert response.content[:2] == b"PK"

    # 读模型逐字节不变
    assert client.get(f"{API}/projects/{project_id}").content == before_model
    assert client.get(f"{API}/projects/{project_id}",
                      params={"allow_archived": "true"}).content == before_model_archived
    assert client.get(f"{API}/projects").content == before_projects
    # assets 表与 data/ 目录里的文件一个字节没变
    assert snapshot_assets_table(store.db_path) == before_rows
    assert snapshot_tree(store.root) == before_tree


def test_export_repeats_identically(store, client, admin):
    """两次导出：包内容（除导出时间戳）完全一致 —— 纯按需生成，不攒状态。"""
    project_id, _ = package_setup(client, admin)
    first = client.get(f"{API}/projects/{project_id}/export.zip")
    second = client.get(f"{API}/projects/{project_id}/export.zip")
    assert first.content != second.content      # zip 条目时间戳会变
    archive_a, payload_a = open_package(first)
    archive_b, payload_b = open_package(second)
    assert set(archive_a.namelist()) == set(archive_b.namelist())
    for name in archive_a.namelist():
        if name in {"project.json", "README.txt"}:
            continue
        assert archive_a.read(name) == archive_b.read(name), name

    def strip_timestamp(text: str) -> str:
        return "\n".join(line for line in text.splitlines() if not line.startswith("导出时间："))

    assert strip_timestamp(archive_a.read("README.txt").decode("utf-8")) \
        == strip_timestamp(archive_b.read("README.txt").decode("utf-8"))
    payload_a["_export"].pop("exported")
    payload_b["_export"].pop("exported")
    assert payload_a == payload_b
