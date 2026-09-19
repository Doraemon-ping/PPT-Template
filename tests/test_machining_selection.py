"""阶段 2b：选型报价 ``project_selections`` 落表的单元测试。

覆盖：

1. 能力级别 ≥3 才启用（≥1 工序、≥2 问题清单、≥3 选型报价），没启用时接口 409；
2. **外键全部是真的**：``fixture_center`` → ``fixture_centers(name)``、
   ``gauge_category`` → ``gauge_categories(name)``、``fixture_id`` → ``fixtures(id)``、
   ``gauge_id`` → ``gauges(id)``、``project_id`` → ``projects(id)``；DB 层真的拦得住；
3. 表级 CHECK：夹具行不许挂检具列（反之亦然）、``quoted`` 只能是 0/1；
4. 旧结构两个缺陷修掉：元素里存的是拼出来的字符串（库里改名后指向不存在）→
   读模型现算当前库值；下标即关系（字典插一条就串位）→ 按**类别名**定位；
5. 库行被删（物理删除）→ ``ON DELETE SET NULL`` + 快照列继续算价（口径 4）；
6. **读模型逐字节一致**：旧四个数组拆进表再 compose 出来完全相同；
7. 每个格子一行（含未选型的格子），否则"是否报价"的勾选会丢；
8. 每次保存都留版本（口径 1）。
"""

import json

import pytest
from fastapi import HTTPException

from app.machining_dfm import MachiningDFMStore
from app.machining_selection import (
    FIXTURE_TABLE,
    GAUGE_TABLE,
    KIND_FIXTURE,
    KIND_GAUGE,
    ProjectSelections,
    apply_selection_split,
    compose_selection_arrays,
    legacy_selection_arrays,
    selection_payload,
    split_selections,
)

FIXTURE_KEY = "1025减震模具中心|两点式拉杆四轴机加夹具"
GAUGE_KEY = "成品总成检具|控制器壳体总成检具|9081000615-01"


@pytest.fixture()
def seed_dir(tmp_path):
    root = tmp_path / "seed"
    root.mkdir(parents=True, exist_ok=True)
    (root / "machines.json").write_text(json.dumps({"machines": [
        {"id": "m-alpha", "brand": "Alpha", "model": "A1", "rapid": 40, "tc": 1.5,
         "spm": 10000, "atc": 24},
    ]}, ensure_ascii=False), encoding="utf-8")
    # 字典与两本库都用真数据的样子：中心/类别是字典表主键（名字）。
    # 注意数组元素与它所在格子必须是同一个类别（真实数据就是这样）：
    # fcnX[0]=1025 中心 → fixQ[0] 是 1025 的夹具；icnX[1]=成品总成检具 → insp[1] 是成品总成检具。
    (root / "project.json").write_text(json.dumps({
        "G": {
            "cust": "客户 A", "part": "P-001",
            "fixQ": [FIXTURE_KEY, "", ""], "fixQC": [1, 0, 1],
            "insp": ["", GAUGE_KEY, ""], "inspQ": [1, 0, 1],
        },
        "pr": [{"nm": "机加工序-OP10", "tl": [], "mid": "m-alpha"}],
        "is": [],
        "vh": [],
    }, ensure_ascii=False), encoding="utf-8")
    (root / "fixtures.json").write_text(json.dumps([
        {"id": "fx-1", "center": "1025减震模具中心", "name": "两点式拉杆四轴机加夹具",
         "price": 16000, "mc": 12, "rmk": ""},
        {"id": "fx-2", "center": "1059轻合金模具中心", "name": "轻合金夹具",
         "price": 8000, "mc": 8, "rmk": ""},
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


def make_store(tmp_path, seed_dir, monkeypatch, version):
    monkeypatch.setenv("MACHINING_PROJECT_BUSINESS", str(version))
    return MachiningDFMStore(tmp_path / f"data-v{version}" / "machining_dfm", seed_dir)


@pytest.fixture()
def store(tmp_path, seed_dir, monkeypatch):
    return make_store(tmp_path, seed_dir, monkeypatch, 3)


def pid_of(store) -> str:
    return store.list()[0]["id"]


def general_of(store, pid) -> dict:
    return store.settings.legacy_g(pid)


def migrate(store, pid) -> dict:
    """像迁移工具那样把旧的四个数组拆进表。"""
    return apply_selection_split(
        store.selections, pid, general_of(store, pid),
        categories=store._selection_categories(),
        library=store._selection_library(),
    )


def arrays(state_or_general) -> dict:
    return {key: state_or_general[key] for key in ("fixQ", "fixQC", "insp", "inspQ")}


# ---------------- 1. 能力级别 ----------------

def test_version_two_does_not_open_selections(tmp_path, seed_dir, monkeypatch):
    store = make_store(tmp_path, seed_dir, monkeypatch, 2)
    assert store.business_version == 2
    assert store.selections_enabled is False
    assert store.get(pid_of(store))["selection_table"] is False
    with pytest.raises(Exception):  # 表根本没建
        store.selections.rows(pid_of(store))


def test_version_three_opens_selections(store):
    pid = pid_of(store)
    record = store.get(pid)
    assert store.selections_enabled is True
    assert record["selection_table"] is True and record["business_version"] == 3
    assert store.selections.rows(pid) == []
    # 还没迁移 → 读模型仍旧读 extra_json 里那四个数组
    assert arrays(record["state"]["G"])["fixQ"][0] == FIXTURE_KEY


def test_gate_closed_route_returns_409(tmp_path, seed_dir, monkeypatch):
    store = make_store(tmp_path, seed_dir, monkeypatch, 0)
    with pytest.raises(HTTPException) as error:
        store.project_selections(pid_of(store))
    assert error.value.status_code == 409


# ---------------- 2. 表结构：外键与 CHECK 必须真在 DDL 里 ----------------

def test_schema_is_two_project_level_tables(store):
    """夹具/检具各一张项目级表：各自只放自己的列，**没有 kind 多态列**。"""
    with store.connect() as db:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {table: {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                   for table in (FIXTURE_TABLE, GAUGE_TABLE)}
    assert {FIXTURE_TABLE, GAUGE_TABLE} <= tables
    assert "kind" not in columns[FIXTURE_TABLE] and "kind" not in columns[GAUGE_TABLE]
    # 夹具表不该有检具的列（反之亦然）——"这是夹具表"由表名说清楚
    assert "gauge_category" not in columns[FIXTURE_TABLE]
    assert "gauge_id" not in columns[FIXTURE_TABLE]
    assert "fixture_center" not in columns[GAUGE_TABLE]
    assert "fixture_id" not in columns[GAUGE_TABLE]
    # 每张表都有项目外键与排序（页面上的格子下标）
    for table in (FIXTURE_TABLE, GAUGE_TABLE):
        assert {"project_id", "sort_order", "quoted", "legacy_key"} <= columns[table]


def test_schema_has_real_foreign_keys(store):
    with store.connect() as db:
        fks = {
            table: {row["from"]: (row["table"], row["to"], row["on_delete"]) for row in
                    db.execute(f"PRAGMA foreign_key_list({table})")}
            for table in (FIXTURE_TABLE, GAUGE_TABLE)
        }
        ddl = {table: db.execute("SELECT sql FROM sqlite_master WHERE name=?",
                                 (table,)).fetchone()[0]
               for table in (FIXTURE_TABLE, GAUGE_TABLE)}
    assert fks[FIXTURE_TABLE]["project_id"] == ("projects", "id", "NO ACTION")
    assert fks[FIXTURE_TABLE]["fixture_center"] == ("fixture_centers", "name", "SET NULL")
    assert fks[FIXTURE_TABLE]["fixture_id"] == ("fixtures", "id", "SET NULL")
    assert fks[GAUGE_TABLE]["gauge_category"] == ("gauge_categories", "name", "SET NULL")
    assert fks[GAUGE_TABLE]["gauge_id"] == ("gauges", "id", "SET NULL")
    # 跨类 CHECK 没有了（列都不在同一张表，没必要）；"是否报价"仍旧只能是 0/1
    for table in (FIXTURE_TABLE, GAUGE_TABLE):
        assert "CHECK (quoted IN (0,1))" in ddl[table]
        assert "kind IN" not in ddl[table]


def test_database_rejects_dangling_foreign_key(store):
    """绕开接口直接写库也得被 SQLite 拦住（外键不是摆设）。"""
    import sqlite3

    pid = pid_of(store)
    with pytest.raises(sqlite3.IntegrityError):
        with store.connect() as db:
            db.execute(
                f"INSERT INTO {FIXTURE_TABLE}(id,project_id,sort_order,legacy_key,"
                "fixture_center,created,updated) VALUES('x',?,0,'','不存在中心','t','t')",
                (pid,),
            )


def test_fixture_queries_are_indexed(store):
    with store.connect() as db:
        indexed: dict[str, set[str]] = {}
        for table in (FIXTURE_TABLE, GAUGE_TABLE):
            names: set[str] = set()
            for index in db.execute(f"PRAGMA index_list({table})"):
                for info in db.execute(f"PRAGMA index_info({index['name']})"):
                    names.add(info["name"])
            indexed[table] = names
    assert {"project_id", "sort_order"} <= indexed[FIXTURE_TABLE]
    assert {"project_id", "sort_order"} <= indexed[GAUGE_TABLE]
    assert "fixture_center" in indexed[FIXTURE_TABLE] and "fixture_id" in indexed[FIXTURE_TABLE]
    assert "gauge_category" in indexed[GAUGE_TABLE] and "gauge_id" in indexed[GAUGE_TABLE]


# ---------------- 3. 拆分与读模型逐字节一致 ----------------

def test_split_then_compose_is_byte_identical(store):
    pid = pid_of(store)
    before = arrays(general_of(store, pid))
    report = migrate(store, pid)
    assert report["rows"] == 6 and report["bound"] == 2      # 3 格夹具 + 3 格检具
    assert report["missing"] == 0 and report["ambiguous"] == 0
    after = arrays(store.get(pid)["state"]["G"])
    assert json.dumps(after, ensure_ascii=False) == json.dumps(before, ensure_ascii=False)


def test_every_slot_gets_a_row_even_when_empty(store):
    """未选型的格子也要有行，否则"是否报价"的勾选（fixQC/inspQ）会丢。"""
    pid = pid_of(store)
    migrate(store, pid)
    rows = store.selections.list_typed(pid)
    assert len(rows) == 6
    assert len([row for row in rows if not row["legacy_key"]]) == 4
    for kind, expected in ((KIND_FIXTURE, [1, 0, 1]), (KIND_GAUGE, [1, 0, 1])):
        quoted = [row["quoted"] for row in rows if row["kind"] == kind]
        assert quoted == expected


def test_split_is_idempotent(store):
    pid = pid_of(store)
    migrate(store, pid)
    again = migrate(store, pid)
    assert again["skipped"] is True
    assert len(store.selections.list_typed(pid)) == 6


def test_binding_fills_snapshots(store):
    pid = pid_of(store)
    migrate(store, pid)
    row = [item for item in store.selections.list_typed(pid)
           if item["kind"] == KIND_FIXTURE and item["sort_order"] == 0][0]
    assert row["fixture_id"] == "fx-1"
    assert row["fixture_center"] == "1025减震模具中心"
    assert row["price_snapshot"] == 16000.0 and row["days_snapshot"] == 12.0
    gauge = [item for item in store.selections.list_typed(pid)
             if item["kind"] == KIND_GAUGE and item["sort_order"] == 1][0]
    assert gauge["gauge_id"] == "gg-1" and gauge["drawing_snapshot"] == "9081000615-01"
    assert gauge["design_days_snapshot"] == 3.0 and gauge["price_snapshot"] == 9.0


def test_compose_uses_current_library_values(store):
    """库里改名后，读模型跟着走——旧结构里那串字符串是不会跟着变的（这就是要修的缺陷）。"""
    pid = pid_of(store)
    migrate(store, pid)
    store.fixtures.update("fx-1", {"name": "两点式拉杆四轴机加夹具·改名后"})
    assert store.get(pid)["state"]["G"]["fixQ"][0] == \
        "1025减震模具中心|两点式拉杆四轴机加夹具·改名后"


def test_library_delete_keeps_snapshot(store):
    """库行被删（物理删除）→ 外键置空，快照继续显示（口径 4：源库删后按快照价）。"""
    pid = pid_of(store)
    migrate(store, pid)
    with store.connect() as db:
        db.execute("DELETE FROM fixtures WHERE id='fx-1'")
    row = [item for item in store.selections.list_typed(pid)
           if item["kind"] == KIND_FIXTURE and item["sort_order"] == 0][0]
    assert row["fixture_id"] is None and row["price_snapshot"] == 16000.0
    assert store.get(pid)["state"]["G"]["fixQ"][0] == \
        "1025减震模具中心|两点式拉杆四轴机加夹具"


def test_category_is_deleted_from_dictionary(store):
    """字典里删掉一个（自定义）中心（**逻辑删除**）：引用与行都留着，这一格从可见字典里消失。

    口径 2：类别行、它下面的夹具、以及项目里指向它们的列一律不动（附件也保留），
    所以恢复类别 + 恢复夹具之后，这一格原样接回来 —— 没有"删了就回不去"的情况。
    """
    pid = pid_of(store)
    migrate(store, pid)
    with store.connect() as db:
        db.execute(
            "INSERT INTO fixture_centers(name,sort_order,builtin,source,created,updated)"
            " VALUES('自定义中心',9,0,'user','t','t')"
        )
        db.execute(
            "INSERT INTO fixtures(id,sort_order,center,name,price,process_days,remark,created,updated)"
            " VALUES('fx-自定义',9,'自定义中心','自定义夹具',5000,3,'','t','t')"
        )
    store.save_project_selection(pid, KIND_FIXTURE, 3, {"fixture_id": "fx-自定义"})
    assert store.get(pid)["state"]["G"]["fixQ"][3] == "自定义中心|自定义夹具"

    store.fixture_centers.delete("自定义中心", cascade=True)   # 连带把这个中心的夹具一起逻辑删除
    row = [item for item in store.selections.list_typed(pid)
           if item["kind"] == KIND_FIXTURE and item["sort_order"] == 3][0]
    # 引用列不动（不是 SET NULL）：历史关系留着，好恢复
    assert row["fixture_center"] == "自定义中心" and row["fixture_id"] == "fx-自定义"
    assert row["name_snapshot"] == "自定义夹具"        # 快照还在，没丢数据
    general = store.get(pid)["state"]["G"]
    assert general["fixQ"] == [FIXTURE_KEY, "", ""]     # 长度跟着**可见**字典变，这一格消失
    assert len(store.selections.list_typed(pid)) == 7   # 行一行都没少（含那一格）
    # 回收站里两样都在
    assert [item["name"] for item in store.fixture_centers.trash()] == ["自定义中心"]
    assert [item["name"] for item in store.fixtures.trash()] == ["自定义夹具"]

    # 恢复之后：这一格原样回来，选择键与服务端读模型逐字节一致
    store.fixture_centers.restore("自定义中心")
    store.fixtures.restore("fx-自定义")
    assert store.get(pid)["state"]["G"]["fixQ"][3] == "自定义中心|自定义夹具"
    assert store.fixture_centers.trash() == [] and store.fixtures.trash() == []


def test_row_survives_dictionary_reorder(store):
    """字典里插一条 → 下标整体后移，但**按类别名定位**，选型不会串位。"""
    pid = pid_of(store)
    migrate(store, pid)
    with store.connect() as db:
        db.execute(
            "INSERT INTO fixture_centers(name,sort_order,builtin,source,created,updated)"
            " VALUES('新中心',-1,0,'user','t','t')"
        )
    general = store.get(pid)["state"]["G"]
    assert general["fixQ"][0] == ""                                   # 新插进来的那一格是空的
    assert general["fixQ"][1] == FIXTURE_KEY                          # 原来的选型还在原来的中心上
    assert general["fixQC"] == [1, 1, 0, 1]                           # 勾选跟着中心走


# ---------------- 4. 行级写入（接口层） ----------------

def test_save_selection_creates_row_with_price_snapshot(store):
    pid = pid_of(store)
    store.save_project_selection(pid, KIND_FIXTURE, 1, {"fixture_id": "fx-2"})
    row = [item for item in store.selections.list_typed(pid)
           if item["kind"] == KIND_FIXTURE and item["sort_order"] == 1][0]
    assert row["fixture_id"] == "fx-2" and row["price_snapshot"] == 8000.0
    assert store.get(pid)["state"]["G"]["fixQ"][1] == "1059轻合金模具中心|轻合金夹具"


def test_save_selection_by_legacy_key_binds_unique_row(store):
    pid = pid_of(store)
    # 旧串只有两段（没有图号），库里唯一匹配 → 绑定并补上图号
    store.save_project_selection(pid, KIND_GAUGE, 1,
                                 {"legacy_key": "成品总成检具|控制器壳体总成检具"})
    row = [item for item in store.selections.list_typed(pid)
           if item["kind"] == KIND_GAUGE and item["sort_order"] == 1][0]
    assert row["gauge_id"] == "gg-1" and row["drawing_snapshot"] == "9081000615-01"
    assert store.get(pid)["state"]["G"]["insp"][1] == GAUGE_KEY


def test_legacy_key_category_wins_over_slot(store):
    """旧串里的类别与格子不一致时，以串里的类别为准（读模型才能原样还原）。"""
    pid = pid_of(store)
    store.save_project_selection(pid, KIND_GAUGE, 0,
                                 {"legacy_key": "成品总成检具|控制器壳体总成检具"})
    row = [item for item in store.selections.list_typed(pid)
           if item["kind"] == KIND_GAUGE and item["sort_order"] == 0][0]
    assert row["gauge_category"] == "成品总成检具"
    general = store.get(pid)["state"]["G"]
    assert general["insp"][0] == "" and general["insp"][1] == GAUGE_KEY


def test_save_quoted_only_touches_the_flag(store):
    pid = pid_of(store)
    store.save_project_selection(pid, KIND_FIXTURE, 0, {"fixture_id": "fx-1"})
    store.save_project_selection(pid, KIND_FIXTURE, 0, {"quoted": 0})
    row = [item for item in store.selections.list_typed(pid)
           if item["kind"] == KIND_FIXTURE and item["sort_order"] == 0][0]
    assert row["quoted"] == 0 and row["fixture_id"] == "fx-1"
    assert store.get(pid)["state"]["G"]["fixQC"][0] == 0


def test_wrong_category_is_rejected(store):
    pid = pid_of(store)
    with pytest.raises(HTTPException) as error:
        # fx-2 属于 1059，不能选到 1025 那一格（第 0 格）
        store.save_project_selection(pid, KIND_FIXTURE, 0, {"fixture_id": "fx-2"})
    assert error.value.status_code == 422 and "1059" in error.value.detail


def test_unknown_library_row_is_rejected(store):
    pid = pid_of(store)
    with pytest.raises(HTTPException) as error:
        store.save_project_selection(pid, KIND_FIXTURE, 0, {"fixture_id": "没有这条"})
    assert error.value.status_code == 422 and "夹具库" in error.value.detail


def test_slot_out_of_range_is_rejected(store):
    pid = pid_of(store)
    with pytest.raises(HTTPException) as error:
        store.save_project_selection(pid, KIND_FIXTURE, 99, {"fixture_id": "fx-1"})
    assert error.value.status_code == 422 and "超范围" in error.value.detail


def test_bad_quoted_value_is_rejected(store):
    pid = pid_of(store)
    with pytest.raises(HTTPException) as error:
        store.save_project_selection(pid, KIND_FIXTURE, 0, {"quoted": 7})
    assert error.value.status_code == 422


def test_clear_slot_keeps_row_and_flag(store):
    pid = pid_of(store)
    store.save_project_selection(pid, KIND_FIXTURE, 0, {"fixture_id": "fx-1"})
    store.save_project_selection(pid, KIND_FIXTURE, 0, {"quoted": 0})
    store.clear_project_selection(pid, KIND_FIXTURE, 0)
    row = [item for item in store.selections.list_typed(pid)
           if item["kind"] == KIND_FIXTURE and item["sort_order"] == 0][0]
    assert row["legacy_key"] == "" and row["fixture_id"] is None
    assert row["quoted"] == 0                       # 清空选型不影响"要不要报价"
    assert row["price_snapshot"] == 0.0
    general = store.get(pid)["state"]["G"]
    assert general["fixQ"][0] == "" and general["fixQC"][0] == 0


def test_clearing_empty_slot_is_a_noop(store):
    """清空一个本来就空的格子：不建版本、不改数据（但懒迁移已经把老数据搬进表了）。"""
    pid = pid_of(store)
    before = store.get(pid)["revision"]
    record = store.clear_project_selection(pid, KIND_FIXTURE, 2)
    assert record["id"] == pid and record["revision"] == before
    # 第一次动选型会先把老数组整份搬进来（否则别的格子会看着空）
    rows = store.selections.list_typed(pid)
    assert len(rows) == 6
    assert [item for item in rows if item["kind"] == KIND_FIXTURE and item["sort_order"] == 2][0][
        "legacy_key"] == ""


# ---------------- 5. 列表接口与版本快照 ----------------

def test_listing_reports_slots_and_bound_state(store):
    pid = pid_of(store)
    migrate(store, pid)
    listing = store.project_selections(pid)
    assert listing["enabled"] is True
    assert listing["categories"][KIND_FIXTURE] == \
        ["1025减震模具中心", "1059轻合金模具中心", "1929底盘模具中心"]
    fixtures = listing["slots"][KIND_FIXTURE]
    assert len(fixtures) == 3
    assert fixtures[0]["value"] == FIXTURE_KEY and fixtures[0]["bound"] is True
    assert fixtures[0]["price"] == 16000.0 and fixtures[0]["quoted"] == 1
    assert fixtures[1]["bound"] is False and fixtures[1]["fixture_id"] is None
    assert fixtures[1]["value"] == "" and fixtures[1]["quoted"] == 0
    assert listing["arrays"]["inspQ"] == [1, 0, 1]


def test_every_selection_save_leaves_a_version(store):
    pid = pid_of(store)
    before = store.get(pid)["revision"]
    store.save_project_selection(pid, KIND_FIXTURE, 0, {"fixture_id": "fx-1"})
    record = store.get(pid)
    assert record["revision"] == before + 1
    with store.connect() as db:
        row = db.execute("SELECT state_json FROM revisions WHERE project_id=? ORDER BY revision DESC",
                         (pid,)).fetchone()
    snapshot = json.loads(row["state_json"])
    assert snapshot["G"]["fixQ"][0] == FIXTURE_KEY


def test_missing_selection_rows_fall_back_to_general(store):
    """表里一行都没有 → 读模型仍读旧数据（没迁移的项目行为一字不变）。"""
    pid = pid_of(store)
    assert legacy_selection_arrays(
        store.selections, pid,
        categories=store._selection_categories(), library=store._selection_library()) is None
    assert store.get(pid)["state"]["G"]["fixQ"][0] == FIXTURE_KEY


def test_split_ignores_unknown_library_value(store):
    """旧串在库里找不到：照旧存字符串、不绑库、不猜（报告里也要看得到）。"""
    pid = pid_of(store)
    general = general_of(store, pid)
    general["fixQ"] = ["1025减震模具中心|库里没有这个夹具", "", ""]
    general["insp"] = ["", "", ""]
    report = split_selections(store.selections, pid, general,
                              categories=store._selection_categories(),
                              library=store._selection_library())
    assert report["missing"] == 1 and report["bound"] == 0
    assert "找不到" in " ".join(report["details"])
    row = [item for item in store.selections.list_typed(pid)
           if item["kind"] == KIND_FIXTURE and item["sort_order"] == 0][0]
    assert row["fixture_id"] is None and row["legacy_key"] == "1025减震模具中心|库里没有这个夹具"
    # 读模型仍然逐字节还给旧值
    assert store.get(pid)["state"]["G"]["fixQ"][0] == "1025减震模具中心|库里没有这个夹具"


def test_compose_skips_rows_without_category(store):
    pid = pid_of(store)
    arrays_out = compose_selection_arrays(
        [{"kind": KIND_FIXTURE, "fixture_center": "", "legacy_key": "x|y",
          "quoted": 1, "sort_order": 0}],
        categories={KIND_FIXTURE: ["1025减震模具中心"], KIND_GAUGE: []},
    )
    assert arrays_out["fixQ"] == [""] and arrays_out["insp"] == []


# ---------------- 6. 结构（本次重构）：项目 → 工序 → 设备 / 夹具选型 / 检具选型 ----------------

def test_selection_listing_is_per_kind(store):
    """每种选型各有一个清单接口：夹具只列模具中心、检具只列检具类别，互不掺杂。"""
    pid = pid_of(store)
    migrate(store, pid)
    fixtures = store.project_selection(pid, KIND_FIXTURE)
    gauges = store.project_selection(pid, KIND_GAUGE)
    assert (fixtures["kind"], fixtures["label"], fixtures["table"]) == \
        (KIND_FIXTURE, "夹具", FIXTURE_TABLE)
    assert (gauges["kind"], gauges["label"], gauges["table"]) == \
        (KIND_GAUGE, "检具", GAUGE_TABLE)
    assert [slot["category"] for slot in fixtures["slots"]] == \
        ["1025减震模具中心", "1059轻合金模具中心", "1929底盘模具中心"]
    assert [slot["category"] for slot in gauges["slots"]] == \
        ["毛坯检具", "成品总成检具", "测量支架"]
    # 报价合计只算勾了"要报价"的格子
    assert fixtures["total"]["quoted"] == 2 and fixtures["total"]["price"] == 16000.0
    # 检具这一格（成品总成检具）勾的是"不报价"，所以合计不含它，但格子自己的价要算得出来
    assert gauges["total"]["quoted"] == 2 and gauges["total"]["price"] == 0.0
    assert gauges["slots"][1]["price"] == 9.0 and gauges["slots"][1]["quoted"] == 0


def test_process_machine_selection_is_explicit(store):
    """「工序设备选择」：每道工序单挂一个接口选/清设备，读模型里带上当前设备。"""
    from fastapi import HTTPException

    pid = pid_of(store)
    store.create_project_process(pid, {"nm": "机加工序-OP10", "mid": "m-alpha"})
    process = store.project_processes(pid)["processes"][0]
    assert process["machine"]["machine_id"] == "m-alpha"
    assert process["machine"]["brand"] == "Alpha"

    store.set_project_process_machine(pid, process["id"], {"machine_id": "m-alpha"})
    listing = store.project_processes(pid)
    assert [item["id"] for item in listing["machines"]] == ["m-alpha"]
    assert listing["default_machine_id"] == "m-alpha"

    # 不存在的设备：422（不是静默写入、也不是 500）
    with pytest.raises(HTTPException) as error:
        store.set_project_process_machine(pid, process["id"], {"machine_id": "m-nope"})
    assert error.value.status_code == 422

    # 清空 → 退回兜底机型（读模型里的 machine_id 变空、快照也清掉）
    store.clear_project_process_machine(pid, process["id"])
    cleared = store.project_processes(pid)["processes"][0]
    assert cleared["machine"]["machine_id"] == "" and cleared["machine"]["is_fallback"] is True
    assert cleared["machine"]["model"] == ""


def test_legacy_polymorphic_rows_are_copied_by_kind(store):
    """迁移：老的多态表 ``project_selections`` 的行按 kind 分进两张新表（行 id 保留）。"""
    pid = pid_of(store)
    with store.connect() as db:
        db.executescript(
            "CREATE TABLE IF NOT EXISTS project_selections("
            "id TEXT PRIMARY KEY, project_id TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,"
            "kind TEXT, fixture_center TEXT, gauge_category TEXT, fixture_id TEXT, gauge_id TEXT,"
            "legacy_key TEXT NOT NULL DEFAULT '', name_snapshot TEXT NOT NULL DEFAULT '',"
            "drawing_snapshot TEXT NOT NULL DEFAULT '', price_snapshot REAL NOT NULL DEFAULT 0,"
            "days_snapshot REAL NOT NULL DEFAULT 0, design_days_snapshot REAL NOT NULL DEFAULT 0,"
            "quoted INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, updated TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO project_selections(id,project_id,sort_order,kind,fixture_center,"
            "fixture_id,legacy_key,name_snapshot,quoted,created,updated) "
            "VALUES('old-f1',?,0,'fixture','1025减震模具中心','fx-1',?,'两点式拉杆四轴机加夹具',0,"
            "'2026-01-01','2026-01-01')", (pid, FIXTURE_KEY))
        db.execute(
            "INSERT INTO project_selections(id,project_id,sort_order,kind,gauge_category,"
            "gauge_id,legacy_key,name_snapshot,drawing_snapshot,quoted,created,updated) "
            "VALUES('old-g1',?,1,'gauge','成品总成检具','gg-1',?,'控制器壳体总成检具',"
            "'9081000615-01',1,'2026-01-01','2026-01-01')", (pid, GAUGE_KEY))
        legacy = [dict(row) for row in db.execute(
            "SELECT * FROM project_selections WHERE project_id=?", (pid,))]

    from app.machining_selection import copy_legacy_rows

    report = copy_legacy_rows(store.selections, pid, legacy)
    assert report["rows"] == 2
    assert report["tables"] == {FIXTURE_TABLE: 1, GAUGE_TABLE: 1}
    fixture = store.selections.fixtures.list_typed(pid, include_deleted=True)[0]
    gauge = store.selections.gauges.list_typed(pid, include_deleted=True)[0]
    assert (fixture["id"], fixture["sort_order"]) == ("old-f1", 0)
    assert fixture["fixture_id"] == "fx-1" and fixture["quoted"] == 0
    assert "kind" not in fixture                     # 新表没有多态列
    assert (gauge["id"], gauge["sort_order"]) == ("old-g1", 1)
    assert gauge["gauge_id"] == "gg-1" and gauge["drawing_snapshot"] == "9081000615-01"
    # 读模型逐字节还给旧数组（含被关掉报价的那一格）
    assert store.get(pid)["state"]["G"]["fixQC"][0] == 0
