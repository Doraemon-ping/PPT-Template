"""口径 7：**新建项目（含"另存为新项目"）也要落表**。

改之前：`POST /projects` 把带上来的一整份读模型写进 `projects.state_json` 就算完事，
业务表一行都没有 —— 新项目/副本项目于是天生处在"JSON 满、表空"的双存储形态里：

* 读模型走 JSON（表里没行就回退），页面**看起来**有工序、有问题；
* 但 `GET /projects/{id}/processes` 返回 0 行 → 页面上的工序行**没有行 id**
  → 行级保存（改个工序名、选设备、选刀具）全都无从下手，只能整份保存；
* 数据一边在 JSON、一边（后来改了点儿东西）在表里，两份迟早跑偏。

现在的口径：产品路径（HTTP `POST /projects`）传 `import_tables=True`，
把 state 逐域拆进 `project_settings` / `project_processes(+tools)` / `project_issues` /
`project_fixtures+project_gauges` / `project_versions(kind='history')`，
拆完 `state_json` 里**一份影子副本都不留**。这一组测试盯四件事：

1. 创建后各域表里有行、`state_json` 是 `{}`；
2. **读模型逐字节一致**：同一份 state，走"只写 JSON"（老形状）与走"拆进表"两条路，
   `store.get()` 出来的 state 必须一模一样（这是迁移工具用的同一把尺子）；
3. 拆分**幂等**：同一份 state 再 import 一次不会灌出第二份（口径 2 不做物理删除）；
4. HTTP 路由真的走了这条新路（`POST /projects` 之后工序行有 id，能行级保存）。
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.machining_dfm import MachiningDFMStore, router_for

API = "/api/machining-dfm"
FIXTURE_KEY = "1025减震模具中心|两点式拉杆四轴机加夹具"
GAUGE_KEY = "成品总成检具|控制器壳体总成检具|9081000615-01"

PROCESSES = [
    {"nm": "机加工序-OP10", "mc": 1, "mid": "m-alpha", "nc": {"cc": 2, "co": 2, "mc_": 2, "sc": 2, "ac": 1, "it": 5},
     "tl": [{"id": "T01", "tp": "D50盘铣刀", "ds": "大面开粗", "d": 50, "n": 3000, "vf": 3000,
             "ln": 1600, "ps": 1, "cn": 1, "bg": False, "td": 700, "tt": 2, "sd": 1},
            {"id": "T02", "tp": "D6.5钻铰刀", "ds": "D6.5圆孔", "d": 6.5, "n": 2000, "vf": 400,
             "ln": 10, "ps": 1, "cn": 1, "bg": False, "td": 500, "tt": 2, "sd": 1}]},
    {"nm": "机加工序-OP20", "mc": 1, "mid": "m-alpha", "nc": {"cc": 2, "co": 2, "mc_": 1, "sc": 1, "ac": 0.5, "it": 5},
     "tl": [{"id": "T01", "tp": "D5立铣刀", "ds": "腰形孔", "d": 5, "n": 5000, "vf": 1200,
             "ln": 20, "ps": 2, "cn": 1, "bg": False, "td": 500, "tt": 2, "sd": 1}]},
]

ISSUES = [
    {"tp": "尺寸", "pr": "机加工序-OP10", "ds": "孔位超差", "fx": "改夹具定位", "cr": "",
     "st": "进行中", "bI": None, "aI": None},
]

HISTORY = [
    {"dt": "2026-09-01", "ver": "V0.1", "ds": "初版", "by": "admin"},
]

GENERAL = {
    "cust": "客户 A", "part": "P-001", "hpd": 12,
    "fixQ": [FIXTURE_KEY, "", ""], "fixQC": [1, 0, 1],
    "insp": ["", GAUGE_KEY, ""], "inspQ": [1, 0, 1],
}


def write_seed_dir(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "machines.json").write_text(json.dumps({"machines": [
        {"id": "m-alpha", "brand": "Alpha", "model": "A1", "rapid": 40, "tc": 1.5,
         "spm": 10000, "atc": 24, "price": 55},
    ]}, ensure_ascii=False), encoding="utf-8")
    (root / "project.json").write_text(json.dumps(
        {"G": {"cust": "", "part": "", "fixQ": [], "fixQC": [], "insp": [], "inspQ": []},
         "pr": [], "is": [], "vh": []}, ensure_ascii=False), encoding="utf-8")
    (root / "fixtures.json").write_text(json.dumps([
        {"id": "fx-1", "center": "1025减震模具中心", "name": "两点式拉杆四轴机加夹具",
         "price": 16000, "mc": 12, "rmk": ""},
    ], ensure_ascii=False), encoding="utf-8")
    (root / "gauges.json").write_text(json.dumps([
        {"id": "gg-1", "type": "成品总成检具", "name": "控制器壳体总成检具",
         "drw": "9081000615-01", "price": 9, "dc": 3, "mc": 20},
    ], ensure_ascii=False), encoding="utf-8")
    (root / "categories.json").write_text(json.dumps({
        "fcnX": ["1025减震模具中心", "1059轻合金模具中心", "1929底盘模具中心"],
        "icnX": ["毛坯检具", "成品总成检具", "测量支架"],
    }, ensure_ascii=False), encoding="utf-8")
    return root


@pytest.fixture()
def seed_dir(tmp_path):
    return write_seed_dir(tmp_path / "seed")


@pytest.fixture()
def store(tmp_path, seed_dir, monkeypatch):
    monkeypatch.setenv("MACHINING_PROJECT_BUSINESS", "5")
    return MachiningDFMStore(tmp_path / "data" / "machining_dfm", seed_dir)


@pytest.fixture()
def client(store, tmp_path):
    static = tmp_path / "static" / "machining_dfm"
    static.mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<h1>machining</h1>", encoding="utf-8")
    app = FastAPI()
    app.include_router(router_for(lambda: store, tmp_path / "static"))
    return TestClient(app)


def full_state() -> dict:
    return {"G": dict(GENERAL), "pr": json.loads(json.dumps(PROCESSES)),
            "is": json.loads(json.dumps(ISSUES)), "vh": json.loads(json.dumps(HISTORY))}


def state_of(store, pid) -> dict:
    return store.get(pid)["state"]


def rows_of(store, pid) -> dict:
    return {
        "processes": store.processes.count(pid, include_deleted=True),
        "tools": store.process_tools.count(pid, include_deleted=True),
        "issues": store.issues.count(pid, include_deleted=True),
        "fixtures": store.selections.fixtures.count(pid, include_deleted=True),
        "gauges": store.selections.gauges.count(pid, include_deleted=True),
        "history": len(store.version_table.history_rows(pid)),
    }


def stored_state_json(store, pid) -> str:
    with store.connect() as db:
        return db.execute("SELECT state_json FROM projects WHERE id=?", (pid,)).fetchone()[0]


# ---------------- 1. 拆进表、JSON 里不留影子副本 ----------------

def test_import_tables_fills_every_domain_and_blanks_state_json(store):
    pid = store.create("新建项目", full_state(), import_tables=True)["id"]
    counts = rows_of(store, pid)
    assert counts["processes"] == 2
    assert counts["tools"] == 3                     # 2 + 1
    assert counts["issues"] == 1
    assert counts["fixtures"] == 3                  # 三个中心，一个中心一格
    assert counts["gauges"] == 3                    # 三个检具类别，一类一格
    assert counts["history"] == 1                   # kind='history' 一行一条，不重复灌
    assert stored_state_json(store, pid) == "{}"    # 一份影子副本都不留
    record = store.get(pid)
    assert record["process_table"] is True and record["issue_table"] is True
    assert record["selection_table"] is True and record["history_table"] is True


def test_created_project_rows_have_ids_for_row_level_saves(store):
    """页面靠行 id 做行级保存：新建项目的工序/刀具行都得有 id。"""
    pid = store.create("新建项目", full_state(), import_tables=True)["id"]
    listing = store.project_processes(pid)
    assert [row["nm"] for row in listing["processes"]] == ["机加工序-OP10", "机加工序-OP20"]
    assert all(row["id"] for row in listing["processes"])
    first = listing["processes"][0]
    assert [tool["code"] for tool in first["tools"]] == ["T01", "T02"]
    assert all(tool["id"] for tool in first["tools"])
    issue = store.project_issues(pid)["issues"][0]
    assert issue["id"] and issue["process_id"] == first["id"]   # 按工序名绑上了外键


def test_empty_state_creates_project_with_no_rows(store):
    pid = store.create("空项目", {"G": {}, "pr": [], "is": [], "vh": []},
                       import_tables=True)["id"]
    assert rows_of(store, pid) == {"processes": 0, "tools": 0, "issues": 0, "fixtures": 0,
                                   "gauges": 0, "history": 0}
    assert stored_state_json(store, pid) == "{}"


# ---------------- 2. 读模型逐字节一致（同一把尺子） ----------------

def test_split_keeps_every_input_value_and_only_adds_derived_defaults(store):
    """拆表**不丢值**：输入里有的字段，读模型必须原样给回来。

    反过来，读模型还会补一批**派生值/默认值**（`_ct/_vc/_vf/_fz` 是读时算的，
    `cat/hld/acc/fi` 是刀具库绑定的结果，`cI/eqP/fixP` 是工序的空槽位）——
    这些在"只写 JSON"的老路上不补（老路原样返回存进去的行）。
    真实数据（页面写出来的）本来就带派生值，所以线上迁移用"逐字节一致"这把尺子；
    这里用手写的行，尺子换成"逐字段不丢 + 只多出这一批已知键"。
    """
    legacy_pid = store.create("老形状", full_state())["id"]          # 不拆表：数据留在 JSON 里
    normalized = state_of(store, legacy_pid)
    tables_pid = store.create("新形状", normalized, import_tables=True)["id"]
    tables_state = state_of(store, tables_pid)

    derived = {"_ct", "_vc", "_vf", "_fz", "cat", "hld", "acc", "fi", "cI", "eqP", "fixP"}
    extra: set[str] = set()

    def compare(left, right, path):
        if isinstance(left, dict):
            for key, value in left.items():
                assert key in right, f"{path}.{key} 拆表后丢了"
                compare(value, right[key], f"{path}.{key}")
            extra.update(f"{path}.{key}" for key in right if key not in left)
        elif isinstance(left, list):
            assert len(left) == len(right), f"{path} 行数变了：{len(left)} → {len(right)}"
            for index, (a, b) in enumerate(zip(left, right)):
                compare(a, b, f"{path}[{index}]")
        else:
            assert left == right, f"{path} 值变了：{left!r} → {right!r}"

    compare(normalized, tables_state, "state")
    assert extra, "读模型应当补上派生/默认值（否则这条断言是空的）"
    assert all(path.rsplit(".", 1)[-1] in derived for path in extra), sorted(extra)

    # 老形状那条路：数据确实在 JSON 里（这就是要被替掉的旧行为）
    assert "机加工序-OP10" in stored_state_json(store, legacy_pid)
    # 新形状那条路：数据在表里，JSON 里一份影子副本都不留
    assert stored_state_json(store, tables_pid) == "{}"
    assert store.processes.list_typed(tables_pid)[0]["nm"] == "机加工序-OP10"


def test_machine_and_tool_bindings_survive_the_split(store):
    """拆表要把 `mid` / 刀具绑到库行上（有价就带快照），不能因为 state 里没带 mdb/tdb 就丢。"""
    pid = store.create("新建项目", full_state(), import_tables=True)["id"]
    process = store.processes.list_typed(pid)[0]
    assert process["machine_id"] == "m-alpha"          # 设备绑上了
    assert store.get(pid)["state"]["pr"][0]["mid"] == "m-alpha"


def test_import_state_twice_is_idempotent(store):
    """幂等：再 import 一次不会灌出第二份（口径 2 不做物理删除，也绝不先清空再灌）。"""
    pid = store.create("新建项目", full_state(), import_tables=True)["id"]
    before = rows_of(store, pid)
    store.import_state(pid, full_state())
    assert rows_of(store, pid) == before


def test_import_state_keeps_json_when_a_domain_is_off(store, monkeypatch):
    """某一域的能力级别没开（这里把工序关掉）→ 那一域留在 JSON 里，不硬写表。"""
    pid = store.create("新建项目", full_state())["id"]        # 老形状：全在 JSON
    store.project_business = False                            # 假装工序那一级没开
    report = store.import_state(pid, full_state())
    assert "processes" not in report["domains"]               # 工序这一域没动
    assert store.project_issues_enabled is True
    assert store.issues.count(pid, include_deleted=True) == 1  # 其它域照拆
    assert "机加工序-OP10" in stored_state_json(store, pid)    # 工序还留在 JSON 里
    assert state_of(store, pid)["pr"][0]["nm"] == "机加工序-OP10"


# ---------------- 3. HTTP 路由：产品路径真的走这条新路 ----------------

def test_route_create_splits_into_tables(client, store):
    response = client.post(f"{API}/projects", json={"name": "另存为副本", "state": full_state()})
    assert response.status_code == 200
    pid = response.json()["id"]
    assert store.processes.count(pid, include_deleted=True) == 2
    assert stored_state_json(store, pid) == "{}"

    listing = client.get(f"{API}/projects/{pid}/processes").json()
    assert len(listing["processes"]) == 2
    row_id = listing["processes"][0]["id"]

    # 页面的行级保存：改名 → 只动这一行（不再整份保存）
    patched = client.patch(f"{API}/projects/{pid}/processes/{row_id}",
                           json={"nm": "机加工序-OP10 改名"})
    assert patched.status_code == 200
    assert client.get(f"{API}/projects/{pid}/processes").json()["processes"][0]["nm"] == \
        "机加工序-OP10 改名"


# ---------------- 4. 快照引用着的附件不许被回收 ----------------

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)


def asset_rows(store) -> int:
    with store.connect() as db:
        return db.execute("SELECT COUNT(*) FROM assets").fetchone()[0]


def test_replacing_a_photo_keeps_the_asset_a_snapshot_still_points_at(client, store):
    """换项目图片时，**历史快照还指着**的旧附件不能删。

    老缺陷：判定"这张图还有没有人用"只扫声明了 `assets(id)` 外键的列，
    而快照（`project_versions.state_json`）里记的是附件 **URL**，不带外键 ——
    于是换一张图，老版本里的那张就变成死链（线上第 17/18/22/… 版就是这样坏掉的）。
    """
    pid = store.create("新建项目", full_state(), import_tables=True)["id"]
    headers = {"Authorization": "Bearer TP23456"}
    # 先用真接口存一张产品图（落一份附件 + 递增一个保存版本 → 快照里记下这张图的 URL）
    first = client.put(f"{API}/projects/{pid}/photos/product",
                       headers={**headers, "Content-Type": "image/png"}, content=PNG)
    assert first.status_code == 200, first.text
    first_asset = first.json()["project"]["state"]["G"]["pI"].rsplit("/", 1)[-1]
    assert first_asset
    with store.connect() as db:
        snapshots = [row[0] for row in db.execute(
            "SELECT state_json FROM project_versions WHERE project_id=? AND kind='save'",
            (pid,)).fetchall()]
    assert any(f"/assets/{first_asset}" in (text or "") for text in snapshots)
    before = asset_rows(store)

    # 换一张**内容不同**的图：旧附件仍被快照引用 → 行与文件都要留着
    second = client.put(f"{API}/projects/{pid}/photos/product",
                        headers={**headers, "Content-Type": "image/png"}, content=PNG + b"x")
    assert second.status_code == 200, second.text
    second_asset = second.json()["project"]["state"]["G"]["pI"].rsplit("/", 1)[-1]
    assert second_asset != first_asset
    assert asset_rows(store) == before + 1          # 只多了一张，没把旧的那张删掉
    assert client.get(f"{API}/assets/{first_asset}").status_code == 200   # 老版本里的图还取得到

    # 老版本读出来，图片地址仍然指向那张还在的附件
    revision = snapshots_index(store, pid, first_asset)
    old = client.get(f"{API}/projects/{pid}?revision={revision}").json()
    assert old["state"]["G"]["pI"].endswith(first_asset)


def snapshots_index(store, pid, asset_id) -> int:
    """哪一版快照里记着这张图 → 返回它的 revision（用来读老版本）。"""
    with store.connect() as db:
        row = db.execute(
            "SELECT revision FROM project_versions WHERE project_id=? AND state_json LIKE ? "
            "ORDER BY revision LIMIT 1", (pid, f"%/assets/{asset_id}%")).fetchone()
    assert row is not None, "快照里应该记着这张附件"
    return row[0]


def test_inline_image_in_the_submitted_state_never_reaches_the_database(client, store):
    """整份保存里带着内联图（`data:image;base64`）→ 落库前必须先变成附件。

    老缺陷：`POST/PUT /projects` 拿**请求里的原值**做版本快照，于是页面上传的那张图
    （几十 KB base64）就被永久写进第 1 版快照 —— 快照永久保留（口径 1），
    整个库扫"有没有内联图"就会命中它。线上真发生过（新建项目「11」的第 1 版）。
    """
    import base64
    png = base64.b64encode(PNG).decode("ascii")
    state = full_state()
    state["G"] = dict(state["G"], pI=f"data:image/png;base64,{png}")

    response = client.post(f"{API}/projects", json={"name": "带内联图", "state": state})
    assert response.status_code == 200, response.text
    pid = response.json()["id"]

    with store.connect() as db:
        rows = db.execute("SELECT state_json FROM project_versions WHERE project_id=?",
                          (pid,)).fetchall()
        assert rows and not any("data:image" in (row[0] or "") for row in rows)
        stored = db.execute("SELECT state_json FROM projects WHERE id=?", (pid,)).fetchone()[0]
    assert "data:image" not in stored
    # 图没丢：读模型里还是这张图，只是变成了附件引用
    photo = response.json()["state"]["G"]["pI"]
    assert photo.startswith("/api/machining-dfm/assets/")
    assert client.get(f"{API}/assets/{photo.rsplit('/', 1)[-1]}").content == PNG


def test_whole_state_save_also_converts_inline_images(client, store):
    """整份保存（`PUT /projects/{id}`）那条路同样不能把 base64 落进快照。"""
    import base64
    pid = store.create("新建项目", full_state(), import_tables=True)["id"]
    state = store.get(pid)["state"]
    state["G"] = dict(state["G"], pI="data:image/png;base64," + base64.b64encode(PNG).decode())
    response = client.put(f"{API}/projects/{pid}",
                          json={"name": "整份保存", "state": state,
                                "revision": store.get(pid)["revision"]})
    assert response.status_code == 200, response.text
    with store.connect() as db:
        rows = db.execute("SELECT state_json FROM project_versions WHERE project_id=?",
                          (pid,)).fetchall()
    assert rows and not any("data:image" in (row[0] or "") for row in rows)
    assert response.json()["state"]["G"]["pI"].startswith("/api/machining-dfm/assets/")
