"""1b 工序 / 工序刀具行 落表的单元测试。

覆盖：
1. 表结构与开关：开关关着不建表、读模型照旧（迁移前行为不变）；
2. 行级 CRUD：逐字段 PATCH、排序、逻辑删除与回收站恢复（口径 2：永不物理删除）；
3. 价格快照：选型后库改价/删库都不影响已存行（口径 4）；
4. 派生字段不落库、按 JS 数字规则归一（口径 5）；
5. **端到端**：把整份旧 ``pr[]`` 拆进两张表再还原，读模型逐键相等（含派生值），
   并且 ``store.get()`` 出来的 ``pr`` 与迁移前**逐字节相同**。
"""

import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.machining_dfm import MachiningDFMStore
from app.domains.process import (
    BUSINESS_VERSION_KEY,
    NC_DEFAULTS,
    apply_split,
    calc_derived,
    legacy_processes,
    split_state,
)
from app.domains.selection import SELECTION_ARRAY_KEYS, legacy_selection_arrays

PROCESS_WITH_TOOLS = {
    # 键序与线上 state_json 完全一致（逐字节比对的基准）
    "nm": "机加工序-OP10",
    "mc": 1,
    "cI": None,
    "nc": {"cc": 2, "co": 2, "mc_": 2, "sc": 2, "ac": 1, "it": 5},
    "tl": [
        {"id": "T01", "tp": "D50盘铣刀", "ds": "大面开粗", "d": 50, "n": 3000, "vf": 3000,
         "ln": 1600, "ps": 1, "cn": 1, "bg": False, "td": 700, "fi": None, "tt": 2, "sd": 1,
         "_ct": 32, "_vc": 471, "_vf": 3000, "_fz": 1, "cat": "other", "hld": "", "acc": ""},
        {"id": "T02", "tp": "D6.5钻铰刀", "ds": "钻孔", "d": 6.5, "n": 2000, "vf": 400,
         "ln": 40, "ps": 1, "cn": 2, "bg": True, "td": 500, "fi": None, "tt": 2, "sd": 1,
         "_ct": 12, "_vc": 41, "_vf": 400, "_fz": 0.2, "cat": "other", "hld": "BT40刀柄", "acc": ""},
    ],
    "fixP": 0,
    "eqP": 0,
    "mid": "m-beta",
}

TOOL_LIBRARY = [
    {"id": "tool-a", "tp": "D50盘铣刀", "grp": "hp", "d": 50, "price": 1200.0, "life": 600.0},
    {"id": "tool-b", "tp": "D6.5钻铰刀", "grp": "hp", "d": 6.5, "price": 300.0, "life": 120.0},
]


@pytest.fixture()
def seed_dir(tmp_path):
    """最小的种子目录（与 test_machining_dfm.py 里的一致，独立一份避免跨文件耦合）。"""
    root = tmp_path / "seed"
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
def business_store(tmp_path, seed_dir, monkeypatch):
    """把工序开关打开的 store（测试用环境变量，不动 app_settings）。"""
    monkeypatch.setenv("MACHINING_PROJECT_BUSINESS", "1")
    store = MachiningDFMStore(tmp_path / "data" / "machining_dfm", seed_dir)
    assert store.project_business is True
    return store


@pytest.fixture()
def plain_store(tmp_path, seed_dir, monkeypatch):
    monkeypatch.delenv("MACHINING_PROJECT_BUSINESS", raising=False)
    return MachiningDFMStore(tmp_path / "data" / "machining_dfm", seed_dir)


def project_id(store) -> str:
    return store.list()[0]["id"]


def seed_rows(store, state=None) -> tuple[str, dict]:
    """把一个项目按 1b 的方式落表，返回 (项目 id, 迁移报告)。

    刀具行/设备现在是**真外键**，所以合成的库行必须先真落进刀具库/设备库
    （迁移工具里也是这么干的：库行本来就在，读模型就是从库里来的）。
    """
    pid = project_id(store)
    state = state or store.get(pid)["state"]
    from app.domains.process import apply_split

    for tool in TOOL_LIBRARY:                      # 把合成刀具库灌进真表（同 id）
        if store.tools.find(tool["id"]) is None:
            store.tools.create(dict(tool))
    report = apply_split(store.processes, store.process_tools, pid, state,
                         tools_library=TOOL_LIBRARY, machines=store.machines.list_legacy())
    return pid, report


# ---------------- 1. 开关 ----------------

def test_gate_off_keeps_everything_as_before(plain_store):
    assert plain_store.project_business is False
    pid = project_id(plain_store)
    state = plain_store.get(pid)["state"]
    assert [process["nm"] for process in state["pr"]] == ["OP10"]
    # 开关关着：表根本没建，写也写不进去
    with pytest.raises(Exception):
        plain_store.processes.rows(pid)


def test_gate_on_creates_tables_and_reads_same_pr(business_store):
    pid = project_id(business_store)
    state = business_store.get(pid)["state"]
    assert [process["nm"] for process in state["pr"]] == ["OP10"]
    assert business_store.processes.rows(pid) == []  # 表建好了但还没数据


# ---------------- 1b-2. 指向共享库的外键（口径：有关联就用真外键 + 快照兜底） ----------------

def test_ddl_declares_library_foreign_keys(business_store):
    """设备/刀具/刀柄/配件四列都是**真外键**，且都是 ON DELETE SET NULL。"""
    with business_store.connect() as db:
        expected = {
            "project_processes": {"machine_id": ("machines", "SET NULL")},
            "project_process_tools": {"tool_id": ("tools", "SET NULL"),
                                      "handle_id": ("tools", "SET NULL"),
                                      "accessory_id": ("tools", "SET NULL")},
        }
        for table, columns in expected.items():
            fks = {row["from"]: (row["table"], row["on_delete"])
                   for row in db.execute(f"PRAGMA foreign_key_list({table})")}
            for column, target in columns.items():
                assert fks.get(column) == target, (table, column, fks.get(column))
        # 外键列都有索引（否则删库行时全表扫）
        indexes = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        for column in ("machine_id", "tool_id", "handle_id", "accessory_id"):
            assert any(name.endswith(column) for name in indexes), column


def test_empty_library_binding_is_null_not_empty_string(business_store):
    """没选设备/没绑刀具时列必须是 NULL —— SQLite 里空串是一个真值，会踩外键。"""
    pid, _ = seed_rows(business_store, {"pr": [{"nm": "OP10", "tl": [{"id": "T01", "tp": "没绑的刀"}]}],
                                        "mdb": [], "G": {}})
    with business_store.connect() as db:
        process = db.execute("SELECT machine_id FROM project_processes WHERE project_id=?",
                             (pid,)).fetchone()
        tool = db.execute("SELECT tool_id,handle_id,accessory_id FROM project_process_tools"
                          " WHERE project_id=?", (pid,)).fetchone()
    assert process["machine_id"] is None
    assert (tool["tool_id"], tool["handle_id"], tool["accessory_id"]) == (None, None, None)
    # 对外（读模型/接口）仍旧是空串，不是 None
    assert business_store.processes.list_typed(pid)[0]["machine_id"] == ""
    assert business_store.process_tools.list_typed(pid)[0]["tool_id"] == ""


def test_dangling_library_id_is_rejected(business_store):
    """绕开接口直接写库也会被 SQLite 拦住；走接口则是 422 说人话。"""
    pid, _ = seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    record_id = business_store.processes.list_typed(pid)[0]["id"]
    with business_store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE project_processes SET machine_id='没这台设备' WHERE id=?", (record_id,))
    with pytest.raises(HTTPException) as error:
        business_store.processes.update(record_id, {"machine_id": "没这台设备"})
    assert error.value.status_code == 422 and "machines" in str(error.value.detail)


def test_deleting_machine_row_keeps_snapshot_and_read_model(business_store):
    """设备库删一行（逻辑删除）：引用关系与**快照**都留着，读模型与成本口径一个字不变（口径 2 + 4）。"""
    machine = business_store.machines.create({"brand": "自检设备", "model": "SMOKE-1", "price": 100})
    pid, _ = seed_rows(business_store, {"pr": [{"nm": "OP10", "tl": []}], "mdb": [], "G": {}})
    record_id = business_store.processes.list_typed(pid)[0]["id"]
    business_store.processes.set_machine(record_id, machine)
    before = business_store.get(pid)["state"]["pr"][0]
    assert before["mid"] == machine["id"]
    project_revision = business_store.list()[0]["revision"]

    business_store.machines.delete(machine["id"])
    row = business_store.processes.list_typed(pid)[0]
    # 口径 2：库行是**逻辑删除** —— 外键不动（引用关系留着，恢复后原样接回去）
    assert row["machine_id"] == machine["id"]
    assert row["machine_snapshot"]["id"] == machine["id"]            # 快照还在
    after = business_store.get(pid)["state"]["pr"][0]
    assert after["mid"] == before["mid"]                             # 读模型不变
    assert business_store.list()[0]["revision"] == project_revision  # 删库行不算项目改版
    # 回收站里看得到（谁删的/为什么），恢复之后 id 不变
    assert [item["id"] for item in business_store.machines.trash()] == [machine["id"]]
    assert business_store.machines.trash()[0]["deleted_by"] == "admin"
    assert business_store.machines.restore(machine["id"])["id"] == machine["id"]
    assert business_store.machines.trash() == []


def test_deleting_tool_row_keeps_price_snapshot(business_store):
    """刀具库删一行（逻辑删除）：引用与价格/寿命快照都留着，成本照旧（口径 2 + 4）。"""
    tool = business_store.tools.create({"tp": "自检刀具", "price": 888, "life": 60, "grp": "hp"})
    pid, _ = seed_rows(business_store, {"pr": [{"nm": "OP10",
                                                "tl": [{"id": "T01", "tp": "自检刀具"}]}],
                                        "mdb": [], "G": {}})
    row = business_store.process_tools.list_typed(pid)[0]
    business_store.process_tools.update(row["id"], {"tool_id": tool["id"], "tool_price": 888.0})
    before = business_store.get(pid)["state"]["pr"][0]["tl"][0]

    business_store.tools.delete(tool["id"])
    after_row = business_store.process_tools.list_typed(pid)[0]
    assert after_row["tool_id"] == tool["id"] and after_row["tool_price"] == 888.0
    after = business_store.get(pid)["state"]["pr"][0]["tl"][0]
    assert after == before                                           # 读模型逐键不变
    assert [item["id"] for item in business_store.tools.trash()] == [tool["id"]]
    business_store.tools.restore(tool["id"])
    assert business_store.tools.trash() == []


# ---------------- 2. 行级 CRUD / 逻辑删除 ----------------

def test_create_update_patch_and_count(business_store):
    pid, _ = seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    rows = business_store.processes.list_typed(pid)
    assert len(rows) == 1
    process = rows[0]
    assert process["nm"] == "机加工序-OP10"
    assert process["nc"] == NC_DEFAULTS
    # 设备列是真外键：工序里写了 mid=m-beta，拆表时按设备库把型号也存成快照（口径 4）
    assert process["machine_id"] == "m-beta" and process["machine_snapshot"]["id"] == "m-beta"

    updated = business_store.processes.update(process["id"], {"nm": "机加工序-OP10 改名", "mc": 2})
    assert updated["nm"] == "机加工序-OP10 改名" and updated["mc"] == 2
    # 行级：没提交的字段保持原值
    assert updated["nc"] == NC_DEFAULTS
    # 计数：给一个键就把六个补齐（与页面 updNC 的语义一致）
    counted = business_store.processes.update(process["id"], {"nc": {"cc": 5}})
    assert counted["nc"] == {**NC_DEFAULTS, "cc": 5}
    assert business_store.processes.count(pid) == 1

    tools = business_store.process_tools.list_typed(pid)
    assert len(tools) == 2
    assert tools[0]["code"] == "T01" and tools[0]["tool_id"] == "tool-a"
    assert tools[0]["tool_price"] == 1200.0 and tools[0]["tool_life"] == 600.0
    assert tools[1]["hld"] == "BT40刀柄"


def test_soft_delete_and_restore_never_removes_rows(business_store):
    pid, _ = seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    process = business_store.processes.list_typed(pid)[0]
    business_store.processes.soft_delete(process["id"], by="tester", reason="点错了")
    assert business_store.processes.list_typed(pid) == []
    bin_rows = business_store.processes.recycle_bin(pid)
    assert len(bin_rows) == 1 and bin_rows[0]["deleted_by"] == "tester"
    # 物理行还在（永不物理删除）
    assert business_store.processes.count(pid, include_deleted=True) == 1
    restored = business_store.processes.restore(process["id"])
    assert restored["deleted_at"] is None
    assert len(business_store.processes.list_typed(pid)) == 1


def test_deleted_rows_do_not_appear_in_read_model(business_store):
    pid, _ = seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    tools = business_store.process_tools.list_typed(pid)
    business_store.process_tools.soft_delete(tools[0]["id"], reason="换刀了")
    state = business_store.get(pid)["state"]
    assert [row["id"] for row in state["pr"][0]["tl"]] == ["T02"]


def test_reorder_processes_and_tools(business_store):
    pid, _ = seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    second = business_store.processes.create(pid, {"nm": "机加工序-OP20"})
    order = [second["id"], business_store.processes.list_typed(pid)[0]["id"]]
    rows = business_store.processes.reorder(pid, order)
    assert [row["nm"] for row in rows] == ["机加工序-OP20", "机加工序-OP10"]
    tools = business_store.process_tools.list_typed(pid)
    reversed_rows = business_store.process_tools.reorder(pid, [tools[1]["id"], tools[0]["id"]])
    assert [row["code"] for row in reversed_rows] == ["T02", "T01"]


def test_tool_row_requires_process(business_store):
    pid, _ = seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    with pytest.raises(HTTPException):
        business_store.process_tools.create(pid, {"code": "T99"})


# ---------------- 3. 价格快照（口径 4） ----------------

def test_price_snapshot_survives_library_change(business_store):
    pid, _ = seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    before = business_store.process_tools.list_typed(pid)[0]
    assert (before["tool_price"], before["tool_life"]) == (1200.0, 600.0)
    # 库里改价：已存行不动
    business_store.process_tools.update(before["id"], {"tool_price": 1200.0})
    state = business_store.get(pid)["state"]
    assert state["pr"][0]["tl"][0]["tp"] == "D50盘铣刀"
    assert state["pr"][0]["tl"][0]["_ct"] == 32  # 派生值照旧


def test_snapshot_keys_are_not_leaked_into_legacy_read_model(business_store):
    pid, _ = seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    state = business_store.get(pid)["state"]
    row = state["pr"][0]["tl"][0]
    for key in ("tool_id", "tool_price", "tool_life", "tool_grp", "hld_id", "acc_id"):
        assert key not in row
    assert set(row) == {"id", "tp", "ds", "d", "n", "vf", "ln", "ps", "cn", "bg", "td", "fi",
                        "tt", "sd", "_ct", "_vc", "_vf", "_fz", "cat", "hld", "acc"}


# ---------------- 4. 派生字段（口径 5） ----------------

def test_derived_values_are_js_normalized():
    derived = calc_derived({"n": 3000, "vf": 3000, "ln": 1600, "ps": 1, "cn": 1, "d": 50})
    assert derived == {"_ct": 32, "_vc": 471, "_vf": 3000, "_fz": 1}
    assert all(not isinstance(value, float) or not value.is_integer()
               for value in derived.values())
    fractional = calc_derived({"n": 5000, "vf": 400, "ln": 40, "ps": 1, "cn": 2, "d": 6.5})
    assert fractional["_ct"] == 12 and fractional["_fz"] == 0.08


def test_derived_values_are_not_stored(business_store):
    pid, _ = seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    with business_store.connect() as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(project_process_tools)")]
    assert not any(name.startswith("_") for name in columns)
    assert "_ct" not in columns and "_vc" not in columns


# ---------------- 5. 端到端：拆分 → 还原 逐键相等 ----------------

def test_split_then_compose_matches_original_state(business_store):
    """整份旧 ``pr[]`` 拆进两张表再还原，必须逐键（逐字节）相等。"""
    pid = project_id(business_store)
    original = [json.loads(json.dumps(PROCESS_WITH_TOOLS, ensure_ascii=False))]
    seed_rows(business_store, {"pr": original, "mdb": [], "G": {}})

    composed = legacy_processes(
        business_store.processes, business_store.process_tools, pid,
        asset_store=business_store.assets,
    )
    assert composed is not None

    def canonical(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    expected = [{**process, "mi": -1} for process in original]
    assert canonical(composed) == canonical(expected), "拆分再还原必须逐键相等"
    # 键序也要一致（state_json 的字节不变）
    assert list(composed[0]) == list(expected[0])
    assert list(composed[0]["tl"][0]) == list(expected[0]["tl"][0])

    after = business_store.get(pid)["state"]["pr"]
    assert canonical(after) == canonical([{**process, "mi": after[0].get("mi")} for process in original])


def test_sparse_legacy_rows_are_normalized_not_broken(business_store):
    """老数据里键不全的工序（如种子数据的 ``{"nm","tl","mid"}``）只补标准键、不改值、不删键。"""
    pid = project_id(business_store)
    sparse = {"nm": "OP10", "tl": [{"id": "T01", "tp": "刀"}], "mid": "m-beta"}
    seed_rows(business_store, {"pr": [sparse], "mdb": [], "G": {}})
    composed = legacy_processes(business_store.processes, business_store.process_tools, pid,
                                asset_store=business_store.assets)
    row = composed[0]
    # 原有键一个不少、值不变（工具行的原有键：id/tp）
    assert row["nm"] == sparse["nm"] and row["mid"] == sparse["mid"]
    assert [(tool["id"], tool["tp"]) for tool in row["tl"]] == [("T01", "刀")]
    # 补的是标准键（默认值 / 派生值），没有凭空补 nc
    assert set(row) - set(sparse) == {"cI", "fixP", "eqP", "mi", "mc"}
    assert "nc" not in row


def test_split_with_unique_names_binds_tool_ids(business_store):
    _, report = seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    assert report["bind"] == {"unique": 2}
    assert report["price_missing"] == 0
    assert report["processes"] == 1 and report["tools"] == 2


def test_split_reports_ambiguous_and_missing_tools(business_store):
    state = {"pr": [{
        "nm": "OP10",
        "tl": [
            {"id": "T01", "tp": "重名刀", "d": 10},
            {"id": "T02", "tp": "库里没有的刀", "d": 10},
        ],
    }]}
    library = [
        {"id": "x1", "tp": "重名刀", "d": 10, "price": 0.0, "life": 0.0},
        {"id": "x2", "tp": "重名刀", "d": 10, "price": 0.0, "life": 0.0},
    ]
    from app.domains.process import apply_split

    pid = project_id(business_store)
    report = apply_split(business_store.processes, business_store.process_tools, pid, state,
                         tools_library=library, machines=[])
    assert report["bind"] == {"ambiguous": 1, "missing": 1}
    rows = business_store.process_tools.list_typed(pid)
    # 不猜：两行都没有绑上 id，但要记下"没绑"这件事（报告里有）
    assert all(row["tool_id"] == "" for row in rows)
    assert [row["tp"] for row in rows] == ["重名刀", "库里没有的刀"]


def test_split_disambiguates_duplicate_names_by_diameter(business_store):
    """重名但直径不同 → 用直径消歧成功绑定（报告里记 ``by_size``）。"""
    state = {"pr": [{"nm": "OP10", "tl": [{"id": "T01", "tp": "重名刀", "d": 20}]}]}
    library = [
        {"id": "x1", "tp": "重名刀", "d": 10, "price": 0.0, "life": 0.0},
        {"id": "x2", "tp": "重名刀", "d": 20, "price": 500.0, "life": 100.0},
    ]
    for row in library:          # 外键要求库里真有这两行
        business_store.tools.create(dict(row))
    from app.domains.process import apply_split

    pid = project_id(business_store)
    report = apply_split(business_store.processes, business_store.process_tools, pid, state,
                         tools_library=library, machines=[])
    assert report["bind"] == {"by_size": 1}
    row = business_store.process_tools.list_typed(pid)[0]
    assert row["tool_id"] == "x2" and row["tool_price"] == 500.0


def test_read_model_matches_baseline_numbers(business_store):
    """落表前后，成本口径用到的字段逐项一致（这是"报价数字不动"的最小保证）。"""
    pid = project_id(business_store)
    seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    after = business_store.get(pid)["state"]["pr"]
    old = PROCESS_WITH_TOOLS
    new = after[0]
    assert old["nm"] == new["nm"] and old["mid"] == new["mid"] and old["nc"] == new["nc"]
    assert len(old["tl"]) == len(new["tl"])
    for old_tool, new_tool in zip(old["tl"], new["tl"]):
        for key in ("id", "tp", "cat", "d", "n", "vf", "ln", "ps", "cn", "bg", "td", "tt",
                    "sd", "hld", "acc", "_ct", "_vc", "_vf", "_fz"):
            if key not in old_tool:
                continue  # 夹具里没写派生值，落表后由读时算出
            assert old_tool[key] == new_tool[key], \
                f"{key} 变了：{old_tool[key]} → {new_tool[key]}"


def test_save_whole_state_keeps_processes_table_source(business_store):
    """整份保存（老接口）之后，读模型仍然来自表，不会因为 state_json 变了而回退。"""
    pid = project_id(business_store)
    seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    business_store.processes.update(business_store.processes.list_typed(pid)[0]["id"],
                                    {"nm": "表里的名字"})
    state = business_store.get(pid)["state"]
    assert state["pr"][0]["nm"] == "表里的名字"


def test_business_version_key_enables_gate(tmp_path, seed_dir, monkeypatch):
    """``app_settings.project_business_version`` 也能打开开关（迁移工具写的就是它）。"""
    monkeypatch.delenv("MACHINING_PROJECT_BUSINESS", raising=False)
    store = MachiningDFMStore(tmp_path / "data" / "machining_dfm", seed_dir)
    assert store.project_business is False
    with store.connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO app_settings(key,value_json,updated) VALUES(?,?,?)",
            (BUSINESS_VERSION_KEY, "1", "2026-09-18T00:00:00+00:00"),
        )
    reopened = MachiningDFMStore(tmp_path / "data" / "machining_dfm", seed_dir)
    assert reopened.project_business is True
    pid = project_id(reopened)
    assert reopened.processes.rows(pid) == []


# ---------------- 6. 接口层（路由） ----------------

def make_client(store, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.machining_dfm import router_for

    static = tmp_path / "static" / "machining_dfm"
    static.mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<h1>machining</h1>", encoding="utf-8")
    app = FastAPI()
    app.include_router(router_for(lambda: store, tmp_path / "static"))
    return TestClient(app)


@pytest.fixture()
def client(business_store, tmp_path):
    return make_client(business_store, tmp_path)


def test_routes_return_409_when_gate_is_closed(plain_store, tmp_path):
    client = make_client(plain_store, tmp_path)
    pid = project_id(plain_store)
    response = client.get(f"/api/machining-dfm/projects/{pid}/processes")
    assert response.status_code == 409
    assert "尚未启用" in response.json()["detail"]


def test_route_crud_round_trip(client, business_store):
    pid = project_id(business_store)
    seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})

    listing = client.get(f"/api/machining-dfm/projects/{pid}/processes").json()
    assert len(listing["processes"]) == 1
    assert len(listing["processes"][0]["tools"]) == 2
    assert listing["fields"]["nc_keys"] == ["cc", "co", "mc_", "sc", "ac", "it"]

    # 新增工序 → 返回整个项目记录（前端 adopt 用）
    created = client.post(f"/api/machining-dfm/projects/{pid}/processes",
                          json={"nm": "机加工序-OP20"}).json()
    assert created["project"]["state"]["pr"][1]["nm"] == "机加工序-OP20"
    revision = created["project"]["revision"]

    # 行级 PATCH：只改提交的字段
    target = created["project"]["state"]["pr"][1]
    listing = client.get(f"/api/machining-dfm/projects/{pid}/processes").json()
    process_id = listing["processes"][1]["id"]
    patched = client.patch(
        f"/api/machining-dfm/projects/{pid}/processes/{process_id}",
        json={"mc": 3, "fixP": 1200},
    ).json()["project"]
    assert patched["revision"] == revision + 1
    assert patched["state"]["pr"][1]["mc"] == 3 and patched["state"]["pr"][1]["fixP"] == 1200


def test_route_tool_crud_and_snapshot(client, business_store):
    pid = project_id(business_store)
    seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    listing = client.get(f"/api/machining-dfm/projects/{pid}/processes").json()
    process_id = listing["processes"][0]["id"]
    tool_id = listing["processes"][0]["tools"][0]["id"]

    patched = client.patch(f"/api/machining-dfm/projects/{pid}/tools/{tool_id}",
                           json={"tp": "D50盘铣刀(改)", "tool_price": 999.0}).json()["project"]
    row = patched["state"]["pr"][0]["tl"][0]
    assert row["tp"] == "D50盘铣刀(改)"

    created = client.post(f"/api/machining-dfm/projects/{pid}/processes/{process_id}/tools",
                          json={"code": "T99", "tp": "新刀", "d": 12, "n": 5000, "vf": 500,
                                "ln": 30, "ps": 1, "cn": 2}).json()["project"]
    assert [row["id"] for row in created["state"]["pr"][0]["tl"]] == ["T01", "T02", "T99"]


def test_route_soft_delete_and_recycle_bin(client, business_store):
    pid = project_id(business_store)
    seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    listing = client.get(f"/api/machining-dfm/projects/{pid}/processes").json()
    process_id = listing["processes"][0]["id"]

    deleted = client.delete(
        f"/api/machining-dfm/projects/{pid}/processes/{process_id}",
        params={"by": "tester", "reason": "点错了"},
    ).json()["project"]
    assert deleted["state"]["pr"] == []  # 读模型里不出现

    listing = client.get(f"/api/machining-dfm/projects/{pid}/processes").json()
    assert listing["processes"] == []
    assert len(listing["deleted_processes"]) == 1
    # 刀具行跟着进了回收站（不物理删）
    assert len(listing["deleted_tools"]) == 2
    assert all("随工序删除" in row["deleted_reason"] for row in listing["deleted_tools"])

    restored = client.post(
        f"/api/machining-dfm/projects/{pid}/processes/{process_id}/restore"
    ).json()["project"]
    assert [row["id"] for row in restored["state"]["pr"][0]["tl"]] == ["T01", "T02"]


def test_route_reorder_and_photo(client, business_store, tmp_path):
    pid = project_id(business_store)
    seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    listing = client.get(f"/api/machining-dfm/projects/{pid}/processes").json()
    process_id = listing["processes"][0]["id"]
    tools = listing["processes"][0]["tools"]

    reordered = client.post(
        f"/api/machining-dfm/projects/{pid}/processes/{process_id}/tools/reorder",
        json={"ids": [tools[1]["id"], tools[0]["id"]]},
    ).json()["project"]
    assert [row["id"] for row in reordered["state"]["pr"][0]["tl"]] == ["T02", "T01"]

    uploaded = client.put(
        f"/api/machining-dfm/projects/{pid}/processes/{process_id}/photo",
        content=b"\x89PNG\r\n\x1a\n" + b"pixel" * 40,
        headers={"content-type": "image/png"},
    )
    assert uploaded.status_code == 200, uploaded.text
    project = uploaded.json()["project"]
    layout = project["state"]["pr"][0]["cI"]
    assert layout and layout.startswith("/api/machining-dfm/assets/")

    cleared = client.delete(
        f"/api/machining-dfm/projects/{pid}/processes/{process_id}/photo"
    ).json()["project"]
    assert cleared["state"]["pr"][0]["cI"] is None


def test_route_rejects_cross_project_ids(client, business_store, tmp_path):
    pid = project_id(business_store)
    seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    listing = client.get(f"/api/machining-dfm/projects/{pid}/processes").json()
    process_id = listing["processes"][0]["id"]
    other = client.post("/api/machining-dfm/projects",
                        json={"name": "另一个项目", "state": {"G": {"cust": "客户 B"}}}).json()
    response = client.patch(
        f"/api/machining-dfm/projects/{other['id']}/processes/{process_id}", json={"mc": 9}
    )
    assert response.status_code == 404


def test_every_save_leaves_a_version_snapshot_with_process_data(client, business_store):
    """口径 1：每次保存都留版本，而且快照里的 pr 必须来自表（不是过期的 state_json）。"""
    pid = project_id(business_store)
    seed_rows(business_store, {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}})
    listing = client.get(f"/api/machining-dfm/projects/{pid}/processes").json()
    process_id = listing["processes"][0]["id"]
    tool_id = listing["processes"][0]["tools"][0]["id"]

    before = len(business_store.versions(pid))
    client.patch(f"/api/machining-dfm/projects/{pid}/processes/{process_id}", json={"mc": 4})
    client.patch(f"/api/machining-dfm/projects/{pid}/tools/{tool_id}", json={"vf": 800})
    after = business_store.versions(pid)
    assert len(after) == before + 2

    latest = after[0]
    snapshot = business_store.get(pid, revision=latest["revision"])["state"]
    assert snapshot["pr"][0]["mc"] == 4
    assert snapshot["pr"][0]["tl"][0]["vf"] == 800
    assert snapshot["pr"][0]["tl"][0]["_ct"] == 120  # 派生值也一起进了快照


# ---------------- 7. 迁移（幂等与崩溃恢复） ----------------

def test_apply_split_is_idempotent(business_store):
    """迁移中途崩了可以原样重跑：表里已有行就跳过，绝不灌成两份、更不删数据。"""
    pid = project_id(business_store)
    state = {"pr": [PROCESS_WITH_TOOLS], "mdb": [], "G": {}}

    first = apply_split(business_store.processes, business_store.process_tools, pid, state)
    assert first["skipped"] is False
    processes_before = business_store.processes.count(pid, include_deleted=True)
    tools_before = business_store.process_tools.count(pid, include_deleted=True)
    assert (processes_before, tools_before) == (1, 2)

    second = apply_split(business_store.processes, business_store.process_tools, pid, state)
    assert second["skipped"] is True and second["existing_rows"] == 1
    assert business_store.processes.count(pid, include_deleted=True) == processes_before
    assert business_store.process_tools.count(pid, include_deleted=True) == tools_before

    # 逻辑删除过的行也算"已有行"：不因为是删除状态就重灌一份
    process_id = business_store.processes.list_typed(pid)[0]["id"]
    business_store.processes.soft_delete(process_id, by="t", reason="测试")
    third = apply_split(business_store.processes, business_store.process_tools, pid, state)
    assert third["skipped"] is True
    assert business_store.processes.count(pid, include_deleted=True) == processes_before


def test_migration_tool_moves_live_style_state(tmp_path, seed_dir, monkeypatch, capsys):
    """迁移工具端到端：备份 → 归档 → 拆表（工序 + 问题清单）→ 写版本键 → 逐字节校验。

    阶段 2a 之后这个工具一次做完 1b + 2a，版本键写 2（能力级别递增）。
    """
    import importlib.util

    monkeypatch.delenv("MACHINING_PROJECT_BUSINESS", raising=False)
    root = tmp_path / "data" / "machining_dfm"
    store = MachiningDFMStore(root, seed_dir)
    pid = store.list()[0]["id"]
    assert store.project_business is False

    # 像线上那样：工序与问题清单都存在 state_json 里（整份保存路径）；刀具库是独立表
    library_row = store.tools.create({"tp": "D50盘铣刀", "life": 600, "price": 1200, "grp": "hp"})
    state = store.get(pid)["state"]
    state["pr"] = [PROCESS_WITH_TOOLS]
    state["is"] = [{"tp": "尺寸", "pr": "机加工序-OP10", "ds": "有毛刺", "fx": "", "cr": "",
                    "st": "进行中", "bI": None, "aI": None}]
    # 选型报价：老结构里就是 G 上这四个数组（这里夹具库是空的，所以只能按旧串原样存）
    state["G"]["fixQ"] = ["1025减震模具中心|两点式拉杆四轴机加夹具", "", "", ""]
    state["G"]["fixQC"] = [1, 0, 1, 1]
    state["G"]["insp"] = ["", "", "", "", ""]
    state["G"]["inspQ"] = [1, 1, 1, 1, 1]
    store.update(pid, store.list()[0]["name"], state, 1)
    before_pr = json.dumps(store.get(pid)["state"]["pr"], ensure_ascii=False)
    before_is = json.dumps(store.get(pid)["state"]["is"], ensure_ascii=False)
    before_sel = json.dumps({key: store.get(pid)["state"]["G"].get(key)
                             for key in SELECTION_ARRAY_KEYS}, ensure_ascii=False)

    spec = importlib.util.spec_from_file_location(
        "migrate_project_processes", Path(__file__).resolve().parents[1] / "tools" / "migrate_project_processes.py"
    )
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    code = tool.migrate(root, apply=True, keep=False)
    report = capsys.readouterr().out
    assert code == 0, "迁移工具报告失败：\n" + report

    # 备份与归档都在
    backups = list((root / "backups").glob("pre-project-business-*.sqlite3"))
    assert backups, "没有留下备份"
    with store.connect() as db:
        archived = db.execute("SELECT state_json FROM processes_legacy_v1 WHERE id=?", (pid,)).fetchone()
        version = db.execute(
            "SELECT value_json FROM app_settings WHERE key='project_business_version'"
        ).fetchone()
    assert archived is not None and json.loads(archived["state_json"])["pr"][0]["nm"] == "机加工序-OP10"
    assert version is not None and int(json.loads(version["value_json"])) == 3

    # 开关靠版本键生效：新开的 store 自己就启用，读模型与迁移前逐字节相同
    reopened = MachiningDFMStore(root, seed_dir)
    assert reopened.project_business is True and reopened.project_issues_enabled is True
    assert reopened.selections_enabled is True
    after = reopened.get(pid)
    assert json.dumps(after["state"]["pr"], ensure_ascii=False) == before_pr
    assert json.dumps(after["state"]["is"], ensure_ascii=False) == before_is
    assert json.dumps({key: after["state"]["G"].get(key) for key in SELECTION_ARRAY_KEYS},
                      ensure_ascii=False) == before_sel
    tools = reopened.process_tools.list_typed(pid)
    assert tools[0]["tool_id"] == library_row["id"] and tools[0]["tool_price"] == 1200.0
    assert tools[0]["tool_life"] == 600.0 and tools[0]["tool_grp"] == "hp"
    # 问题清单落表且外键指向工序行（不是存名字）
    issues = reopened.issues.list_typed(pid)
    assert len(issues) == 1 and issues[0]["tp"] == "尺寸"
    assert issues[0]["process_id"] == reopened.processes.list_typed(pid)[0]["id"]
    assert issues[0]["prName"] == "机加工序-OP10"
    # 选型报价落表：每个类别一格，四个数组能靠表完整还原
    selection_rows = reopened.selections.list_typed(pid)
    assert len(selection_rows) == (len(reopened._selection_categories()["fixture"])
                                  + len(reopened._selection_categories()["gauge"]))
    assert len(selection_rows) == 9
    assert len([row for row in selection_rows if row["legacy_key"]]) == 1
    bound = [row for row in selection_rows if row["legacy_key"]][0]
    assert bound["fixture_center"] == "1025减震模具中心" and bound["quoted"] == 1
    assert bound["name_snapshot"] == "两点式拉杆四轴机加夹具" and bound["fixture_id"] is None
    assert json.dumps(legacy_selection_arrays(
        reopened.selections, pid, categories=reopened._selection_categories(),
        library=reopened._selection_library()), ensure_ascii=False) == before_sel

    # 再跑一次：已经是"已迁移"状态，工具直接收手，不再重复灌
    code_again = tool.migrate(root, apply=True, keep=False)
    capsys.readouterr()
    assert code_again == 0
    assert reopened.process_tools.count(pid, include_deleted=True) == 2
    assert reopened.issues.count(pid, include_deleted=True) == 1
    assert reopened.selections.count(pid, include_deleted=True) == len(selection_rows)

    # 回滚极简：迁移**没有动 state_json**，所以删掉版本键开关就关上了，
    # 读模型立刻回到迁移前那份（逐字节相同），表里的行原样留着不丢。
    with reopened.connect() as db:
        db.execute("DELETE FROM app_settings WHERE key='project_business_version'")
    rolled_back = MachiningDFMStore(root, seed_dir)
    assert rolled_back.project_business is False and rolled_back.project_issues_enabled is False
    assert rolled_back.selections_enabled is False
    assert json.dumps(rolled_back.get(pid)["state"]["pr"], ensure_ascii=False) == before_pr
    assert json.dumps({key: rolled_back.get(pid)["state"]["G"].get(key)
                       for key in SELECTION_ARRAY_KEYS}, ensure_ascii=False) == before_sel
    assert json.dumps(rolled_back.get(pid)["state"]["is"], ensure_ascii=False) == before_is
    assert rolled_back.process_tools.count(pid, include_deleted=True) == 2
    assert rolled_back.issues.count(pid, include_deleted=True) == 1
