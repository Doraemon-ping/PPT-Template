"""阶段 2a：问题清单 ``project_issues`` 落表的单元测试。

覆盖：
1. 开关是**递增的能力级别**：版本 1 只开工序表（问题清单仍然 409），版本 2 才开问题清单；
2. 行级 CRUD / 排序 / 逻辑删除 + 回收站恢复（口径 2）；
3. **外键口径**：``process_id`` → ``project_processes(id)``、图片列 → ``assets(id)``、
   ``project_id`` → ``projects(id)``，全在 DDL 里，且 DB 层真的会拦（不是"心里有数"）；
4. 旧结构缺陷修掉：``pr`` 存名字 → 改成外键，读模型里的 ``pr`` 现算当前工序名，
   工序改名/删除都不会让这条问题"指向不存在"；
5. **读模型逐字节一致**：把旧 ``is[]`` 拆进表再 compose 出来，键顺序与字节完全相同；
6. 每次保存都留版本，且快照里的 ``is[]`` 来自表。
"""

import json

import pytest
from fastapi import HTTPException

from app.machining_dfm import MachiningDFMStore
from app.domains.issue import (
    ISSUE_ATTACHMENTS,
    ISSUE_TABLE,
    apply_issue_split,
    legacy_issues,
    split_issues,
)

#: 旧 is[] 的一行（键顺序与线上 state_json 完全一致，逐字节比对用）
LEGACY_ISSUE = {
    "tp": "尺寸",
    "pr": "机加工序-OP10",
    "ds": "",
    "fx": "",
    "cr": "",
    "st": "进行中",
    "bI": None,
    "aI": None,
}


@pytest.fixture()
def seed_dir(tmp_path):
    root = tmp_path / "seed"
    root.mkdir(parents=True, exist_ok=True)
    (root / "machines.json").write_text(json.dumps({"machines": [
        {"id": "m-alpha", "brand": "Alpha", "model": "A1", "rapid": 40, "tc": 1.5,
         "spm": 10000, "atc": 24},
        {"id": "m-beta", "brand": "Beta", "model": "B2", "rapid": 30, "tc": 2,
         "spm": 8000, "atc": 20},
    ]}, ensure_ascii=False), encoding="utf-8")
    (root / "project.json").write_text(json.dumps({
        "G": {"cust": "客户 A", "part": "P-001"},
        "pr": [{"nm": "机加工序-OP10", "tl": [], "mid": "m-beta"}],
        "is": [dict(LEGACY_ISSUE)],
        "vh": [],
    }, ensure_ascii=False), encoding="utf-8")
    for name in ("tools", "fixtures", "gauges"):
        (root / f"{name}.json").write_text("[]", encoding="utf-8")
    (root / "categories.json").write_text(json.dumps({"icnX": [], "fcnX": []}), encoding="utf-8")
    return root


def make_store(tmp_path, seed_dir, monkeypatch, version):
    monkeypatch.setenv("MACHINING_PROJECT_BUSINESS", str(version))
    return MachiningDFMStore(tmp_path / f"data-v{version}" / "machining_dfm", seed_dir)


@pytest.fixture()
def store_v2(tmp_path, seed_dir, monkeypatch):
    return make_store(tmp_path, seed_dir, monkeypatch, 2)


def pid_of(store) -> str:
    return store.list()[0]["id"]


def seed_processes(store, state=None) -> str:
    """先把工序落表（问题清单的外键指向它），返回项目 id。"""
    from app.domains.process import apply_split

    pid = pid_of(store)
    state = state or store.get(pid)["state"]
    apply_split(store.processes, store.process_tools, pid, state, machines=state.get("mdb") or [])
    return pid


# ---------------- 1. 开关是递增的能力级别 ----------------

def test_version_one_opens_processes_only(tmp_path, seed_dir, monkeypatch):
    store = make_store(tmp_path, seed_dir, monkeypatch, 1)
    assert store.business_version == 1
    assert store.project_business is True
    assert store.project_issues_enabled is False
    # 问题清单表根本没建
    with pytest.raises(Exception):
        store.issues.rows(pid_of(store))
    record = store.get(pid_of(store))
    assert record["process_table"] is True and record["issue_table"] is False
    # 读模型照旧用 state_json 里的 is[]
    assert record["state"]["is"] == [LEGACY_ISSUE]


def test_version_two_opens_issues(store_v2):
    assert store_v2.project_issues_enabled is True
    pid = pid_of(store_v2)
    assert store_v2.issues.rows(pid) == []          # 表建好了但还没数据
    record = store_v2.get(pid)
    assert record["issue_table"] is True and record["business_version"] == 2
    assert record["state"]["is"] == [LEGACY_ISSUE]  # 还没迁移 → 仍读 state_json


def test_gate_closed_route_returns_409(tmp_path, seed_dir, monkeypatch):
    store = make_store(tmp_path, seed_dir, monkeypatch, 0)
    assert store.project_issues_enabled is False
    with pytest.raises(HTTPException) as error:
        store.project_issues(pid_of(store))
    assert error.value.status_code == 409


# ---------------- 2. 表结构：外键必须真在 DDL 里 ----------------

def test_schema_has_real_foreign_keys(store_v2):
    pid = seed_processes(store_v2)
    with store_v2.connect() as db:
        ddl = db.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (ISSUE_TABLE,)
        ).fetchone()[0]
        fks = {row["from"]: (row["table"], row["to"]) for row in
               db.execute(f"PRAGMA foreign_key_list({ISSUE_TABLE})")}
        indexes = [row["name"] for row in db.execute(
            f"PRAGMA index_list({ISSUE_TABLE})")]
        indexed: set[str] = set()
        for name in indexes:
            indexed.update(info["name"] for info in db.execute(f"PRAGMA index_info({name})"))

    assert "REFERENCES projects(id)" in ddl
    assert "REFERENCES project_processes(id)" in ddl
    assert ddl.count("REFERENCES assets(id)") == 2      # 优化前 / 优化后两张图
    assert fks["process_id"] == ("project_processes", "id")
    assert fks["project_id"] == ("projects", "id")
    assert fks["before_photo_id"] == ("assets", "id")
    assert fks["after_photo_id"] == ("assets", "id")
    # 按工序查问题要走索引（外键列没索引，删工序时就是全表扫）
    assert "process_id" in indexed and "sort_order" in indexed


def test_database_rejects_dangling_foreign_key(store_v2):
    """绕过 API 直接写库：外键也必须拦住（证明约束真在库里，不只是代码里判断）。"""
    import sqlite3

    pid = seed_processes(store_v2)
    with pytest.raises(sqlite3.IntegrityError):
        with store_v2.connect() as db:
            db.execute(
                f"INSERT INTO {ISSUE_TABLE}(id,project_id,process_id,sort_order,issue_type,"
                "description,fix_plan,customer_reply,status,process_name_snapshot,extra_json,"
                "created,updated) VALUES('x',?,'不存在的工序',0,'尺寸','','','','进行中','','{}',"
                "'2026-01-01','2026-01-01')",
                (pid,),
            )


# ---------------- 3. 行级 CRUD / 逻辑删除 ----------------

def test_create_patch_reorder_and_soft_delete(store_v2):
    pid = seed_processes(store_v2)
    process = store_v2.processes.list_typed(pid)[0]

    created = store_v2.issues.create(pid, {
        "tp": "外观", "ds": "有毛刺", "process_id": process["id"], "st": "进行中",
    })
    assert created["process_id"] == process["id"]
    assert created["tp"] == "外观" and created["st"] == "进行中"

    # 行级：只改提交的字段
    patched = store_v2.issues.update(created["id"], {"st": "已完成"})
    assert patched["st"] == "已完成" and patched["ds"] == "有毛刺"

    second = store_v2.issues.create(pid, {"tp": "尺寸", "ds": "孔位偏"})
    assert second["process_id"] is None              # 项目级问题：不挂工序
    store_v2.issues.reorder(pid, [second["id"], created["id"]])
    assert [row["tp"] for row in store_v2.issues.list_typed(pid)] == ["尺寸", "外观"]

    store_v2.issues.soft_delete(created["id"], by="tester", reason="点错了")
    assert [row["tp"] for row in store_v2.issues.list_typed(pid)] == ["尺寸"]
    assert len(store_v2.issues.recycle_bin(pid)) == 1
    assert store_v2.issues.count(pid, include_deleted=True) == 2   # 物理行还在
    store_v2.issues.restore(created["id"])
    assert len(store_v2.issues.list_typed(pid)) == 2


def test_foreign_key_errors_are_friendly(store_v2):
    pid = seed_processes(store_v2)
    with pytest.raises(HTTPException) as missing:
        store_v2.issues.create(pid, {"tp": "尺寸", "process_id": "不存在"})
    assert missing.value.status_code == 422 and "不存在" in missing.value.detail

    process = store_v2.processes.list_typed(pid)[0]
    store_v2.processes.soft_delete(process["id"], by="t", reason="测试")
    with pytest.raises(HTTPException) as deleted:
        store_v2.issues.create(pid, {"tp": "尺寸", "process_id": process["id"]})
    assert deleted.value.status_code == 422 and "已被删除" in deleted.value.detail


def test_issue_belongs_to_one_project(store_v2):
    pid = seed_processes(store_v2)
    issue = store_v2.issues.create(pid, {"tp": "尺寸"})
    other = store_v2.create("另一个项目", store_v2.get(pid)["state"])["id"]
    with pytest.raises(HTTPException) as error:
        store_v2.issues.require_in_project(other, issue["id"])
    assert error.value.status_code == 404


# ---------------- 4. 修掉"按名字引用工序"的缺陷 ----------------

def test_pr_follows_process_rename(store_v2):
    pid = seed_processes(store_v2)
    process = store_v2.processes.list_typed(pid)[0]
    store_v2.create_project_issue(pid, {"tp": "尺寸", "process_id": process["id"]})

    listing = store_v2.project_issues(pid)
    row = listing["issues"][0]
    assert row["process_name"] == "机加工序-OP10"
    assert row["prName"] == "机加工序-OP10"          # 迁移/新建时记下的名字快照
    assert row["process_missing"] is False

    # 工序改名 → 问题清单里的 pr 跟着走（旧结构在这里就断了）
    store_v2.update_project_process(pid, process["id"], {"nm": "机加工序-OP10 改名"})
    assert store_v2.get(pid)["state"]["is"][0]["pr"] == "机加工序-OP10 改名"
    assert store_v2.project_issues(pid)["issues"][0]["process_missing"] is False

    # 工序被逻辑删除：外键还在，显示回退到名字快照，历史照样说得清
    store_v2.delete_project_process(pid, process["id"])
    assert store_v2.get(pid)["state"]["is"][0]["pr"] == "机加工序-OP10 改名"


def test_pr_falls_back_to_snapshot_when_unlinked(store_v2):
    pid = seed_processes(store_v2)
    store_v2.create_project_issue(pid, {"tp": "尺寸", "prName": "手工填的工序"})
    assert store_v2.get(pid)["state"]["is"][0]["pr"] == "手工填的工序"


# ---------------- 4b. 逻辑删除的行不进读模型（与 1b 同一口径） ----------------

def test_deleted_issue_leaves_read_model_but_stays_in_bin(store_v2):
    pid = seed_processes(store_v2)
    store_v2.create_project_issue(pid, {"tp": "尺寸", "ds": "第一条"})
    store_v2.create_project_issue(pid, {"tp": "外观", "ds": "第二条"})
    # 新增的问题按提交顺序追加（sort_order 递增，不按下标乱排）
    assert [row["ds"] for row in store_v2.get(pid)["state"]["is"]] == ["第一条", "第二条"]

    first_id = store_v2.project_issues(pid)["issues"][0]["id"]
    store_v2.delete_project_issue(pid, first_id)
    assert [row["ds"] for row in store_v2.get(pid)["state"]["is"]] == ["第二条"], \
        "逻辑删除的问题清单还在读模型里"
    bin_rows = store_v2.project_issues(pid)["deleted_issues"]
    assert len(bin_rows) == 1 and bin_rows[0]["deleted_at"]

    store_v2.restore_project_issue(pid, bin_rows[0]["id"])
    assert [row["ds"] for row in store_v2.get(pid)["state"]["is"]] == ["第一条", "第二条"]


def test_read_model_is_empty_when_every_issue_is_deleted(store_v2):
    """全删光时读模型应该是空数组——**不能**回退到 state_json.is 把删掉的又显示出来。"""
    pid = seed_processes(store_v2, {"pr": [{"nm": "机加工序-OP10", "tl": [], "mid": "m-beta"}],
                                    "is": [dict(LEGACY_ISSUE)], "mdb": [], "G": {}})
    processes = store_v2.processes.list_typed(pid, include_deleted=True)
    apply_issue_split(store_v2.issues, pid, {"is": [LEGACY_ISSUE]}, process_rows=processes)
    assert len(store_v2.get(pid)["state"]["is"]) == 1

    issue_id = store_v2.issues.list_typed(pid)[0]["id"]
    store_v2.delete_project_issue(pid, issue_id)
    record = store_v2.get(pid)
    assert record["state"]["is"] == []
    # state_json 里那份影子副本原样留着（回滚用），但读模型不听它的
    with store_v2.connect() as db:
        shadow = json.loads(db.execute("SELECT state_json FROM projects WHERE id=?", (pid,)).fetchone()[0])
    assert len(shadow["is"]) == 1


def test_sort_order_is_per_project_when_no_process_is_bound(store_v2):
    """不挂工序（process_id 为 NULL）的问题，也必须按提交顺序排——

    曾经踩过：排序范围用父行列去算，`WHERE process_id='<项目 id>'` 匹配不到任何行，
    每次都返回 0，于是新增的两条问题 sort_order 都是 0，显示顺序随 uuid 变。
    """
    pid = seed_processes(store_v2)
    for label in ("甲", "乙", "丙", "丁"):
        store_v2.create_project_issue(pid, {"tp": "尺寸", "ds": label})
    rows = store_v2.issues.list_typed(pid)
    assert [row["sort_order"] for row in rows] == [0, 1, 2, 3]
    assert [row["ds"] for row in store_v2.get(pid)["state"]["is"]] == ["甲", "乙", "丙", "丁"]

    # 挂工序的那些行也照旧按提交顺序（同一项目内统一排序）
    process = store_v2.processes.list_typed(pid)[0]
    store_v2.create_project_issue(pid, {"tp": "外观", "ds": "戊", "process_id": process["id"]})
    assert [row["ds"] for row in store_v2.get(pid)["state"]["is"]] == ["甲", "乙", "丙", "丁", "戊"]


# ---------------- 5. 读模型逐字节一致 ----------------

def test_split_then_compose_is_byte_identical(store_v2):
    state = {"pr": [{"nm": "机加工序-OP10", "tl": [], "mid": "m-beta"}],
             "is": [dict(LEGACY_ISSUE), {**LEGACY_ISSUE, "ds": "第二行"}], "G": {}}
    pid = seed_processes(store_v2, {**state, "mdb": [], "G": {}})
    processes = store_v2.processes.list_typed(pid, include_deleted=True)

    report = apply_issue_split(store_v2.issues, pid, state, process_rows=processes)
    assert report["issues"] == 2 and report["linked"] == 2
    assert report["missing"] == 0 and report["ambiguous"] == 0

    rebuilt = legacy_issues(store_v2.issues, pid, process_rows=processes,
                            asset_store=store_v2.assets)
    assert json.dumps(rebuilt, ensure_ascii=False) == json.dumps(state["is"], ensure_ascii=False)
    assert list(rebuilt[0]) == list(LEGACY_ISSUE)     # 键顺序也一致


def test_split_reports_names_it_cannot_match(store_v2):
    pid = seed_processes(store_v2)
    processes = store_v2.processes.list_typed(pid, include_deleted=True)
    state = {"is": [{"tp": "尺寸", "pr": "早就删掉的 OP99", "ds": "", "fx": "", "cr": "",
                     "st": "进行中", "bI": None, "aI": None}]}
    payloads, report = split_issues(state, process_rows=processes)
    assert report["missing"] == 1 and report["missing_names"] == ["早就删掉的 OP99"]
    assert payloads[0]["process_id"] == ""            # 不猜，留空
    assert payloads[0]["payload"]["prName"] == "早就删掉的 OP99"


def test_apply_issue_split_is_idempotent(store_v2):
    pid = seed_processes(store_v2)
    processes = store_v2.processes.list_typed(pid, include_deleted=True)
    state = {"is": [dict(LEGACY_ISSUE)]}
    first = apply_issue_split(store_v2.issues, pid, state, process_rows=processes)
    second = apply_issue_split(store_v2.issues, pid, state, process_rows=processes)
    assert first["skipped"] is False and second["skipped"] is True
    assert store_v2.issues.count(pid, include_deleted=True) == 1


def test_sparse_issue_row_keeps_original_keys(store_v2):
    """旧数据只有 tp/pr 两键：拆完再 compose 不能凭空多出键。"""
    sparse = {"tp": "尺寸", "pr": "机加工序-OP10"}
    pid = seed_processes(store_v2, {"pr": [{"nm": "机加工序-OP10", "tl": [], "mid": "m-beta"}],
                                    "is": [sparse], "mdb": [], "G": {}})
    processes = store_v2.processes.list_typed(pid, include_deleted=True)
    apply_issue_split(store_v2.issues, pid, {"is": [sparse]}, process_rows=processes)
    rebuilt = legacy_issues(store_v2.issues, pid, process_rows=processes)
    assert set(rebuilt[0]) - set(sparse) == {"ds", "fx", "cr", "st", "bI", "aI"}
    assert rebuilt[0]["tp"] == "尺寸" and rebuilt[0]["pr"] == "机加工序-OP10"


# ---------------- 6. 版本快照 ----------------

def test_every_issue_save_leaves_a_version(store_v2):
    pid = seed_processes(store_v2)
    process = store_v2.processes.list_typed(pid)[0]
    store_v2.create_project_issue(pid, {"tp": "尺寸", "ds": "第一版",
                                        "process_id": process["id"]})
    issue = store_v2.project_issues(pid)["issues"][0]

    before = len(store_v2.versions(pid))
    store_v2.update_project_issue(pid, issue["id"], {"ds": "第二版"})
    after = store_v2.versions(pid)
    assert len(after) == before + 1

    snapshot = store_v2.get(pid, revision=after[0]["revision"])["state"]
    assert snapshot["is"][0]["ds"] == "第二版"
    assert snapshot["is"][0]["pr"] == "机加工序-OP10"
