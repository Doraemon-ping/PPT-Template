"""阶段 3a：版本履历落表（``project_versions``）的单元测试。

覆盖：

1. 能力级别 ≥4 才启用（1 工序 / 2 问题清单 / 3 选型报价 / **4 版本履历**），没启用时接口 409；
2. **外键是真的**：``project_id`` → ``projects(id)``，DB 层拦得住（凭空 pid 插不进去）；
3. 表级 CHECK 把语义钉死：``kind`` 只能是 save/history；save 必须 ``revision>0`` 且快照非空；
   history 必须 ``revision=0``（哨兵）——不存在"空版本"这种捏造的历史；
4. 保存版本（kind='save'）：每次保存一行、``state_json`` 与 ``revisions`` 逐字节相同（影子副本，
   回滚无损）、``/versions`` 与旧 ``revisions`` 列表完全一致、``?revision=N`` 依旧打开；
5. 版本履历（kind='history'）：读模型 ``vh[]`` 与旧 ``state_json.vh`` **逐字节相同**（含键序）；
   ``vh`` 为空但表里有行时表是权威；表里一行都没有时回退 ``state_json.vh``；
6. 行级写入：改一个格存一个格、缺键补空串、登记表以外的键进 ``extra_json`` 兜底（不丢数据）；
7. 删除 = 逻辑删除（口径 2）：行还在表里、进回收站、可恢复，恢复后读模型回到原样；
8. 迁移助手 ``apply_history_split``：幂等（重复跑不插第二遍）、非对象条目在体检阶段就拦住、不静默丢。
"""

import json

import pytest
from fastapi import HTTPException

from app.machining_dfm import MachiningDFMStore
from app.domains.history import (
    HISTORY_TABLE,
    HISTORY_VERSION,
    KIND_HISTORY,
    KIND_SAVE,
    apply_history_split,
    compose_history,
    history_listing,
    history_payload,
    history_preflight,
    legacy_history,
    split_history_rows,
    version_listing,
)

VH_ROWS = [
    {"dt": "2026-01-05", "ver": "V1.0", "ds": "初版发布", "by": "张三"},
    {"dt": "2026-02-11", "ver": "V1.1", "ds": "改结构", "by": "李四"},
]


def state_of(store, pid) -> dict:
    """项目行里的 ``state_json``（迁移工具就是从这儿取旧 vh 的）。"""
    with store.connect() as db:
        row = db.execute("SELECT state_json FROM projects WHERE id=?", (pid,)).fetchone()
    return json.loads(row["state_json"])


@pytest.fixture()
def seed_dir(tmp_path):
    root = tmp_path / "seed"
    root.mkdir(parents=True, exist_ok=True)
    (root / "machines.json").write_text(json.dumps({"machines": [
        {"id": "m-alpha", "brand": "Alpha", "model": "A1"},
    ]}, ensure_ascii=False), encoding="utf-8")
    (root / "project.json").write_text(json.dumps({
        "G": {"cust": "客户 A", "part": "P-001"},
        "pr": [{"nm": "机加工序-OP10", "tl": [], "mid": "m-alpha"}],
        "is": [],
        "vh": [dict(row) for row in VH_ROWS],
    }, ensure_ascii=False), encoding="utf-8")
    (root / "tools.json").write_text("[]", encoding="utf-8")
    (root / "fixtures.json").write_text("[]", encoding="utf-8")
    (root / "gauges.json").write_text("[]", encoding="utf-8")
    (root / "categories.json").write_text(
        json.dumps({"fcnX": [], "icnX": []}, ensure_ascii=False), encoding="utf-8")
    return root


def make_store(tmp_path, seed_dir, monkeypatch, version):
    monkeypatch.setenv("MACHINING_PROJECT_BUSINESS", str(version))
    return MachiningDFMStore(tmp_path / f"data-v{version}" / "machining_dfm", seed_dir)


@pytest.fixture()
def store(tmp_path, seed_dir, monkeypatch):
    return make_store(tmp_path, seed_dir, monkeypatch, HISTORY_VERSION)


def pid_of(store) -> str:
    return store.list()[0]["id"]


def seed_legacy_revisions(store, pid) -> None:
    """造出"3a 之前的老库"形态：旧 ``revisions`` 表 + 每一次保存的快照行。

    开关到 4 之后这张影子表就不再维护了（口径 6：哪一级落表了，那一级的影子副本停写），
    所以迁移测试要自己把"迁移前的老库"造出来 —— 迁移工具本来就是给老库用的。
    快照字节直接取 ``project_versions`` 的 save 行：当年两处存的就是同一串字节。
    """
    from app.machining_dfm import LEGACY_REVISIONS_SCHEMA

    with store.connect() as db:
        db.executescript(LEGACY_REVISIONS_SCHEMA)
        rows = db.execute(
            f"SELECT revision,name,state_json,created FROM {HISTORY_TABLE} "
            "WHERE project_id=? AND kind=? ORDER BY revision", (pid, KIND_SAVE),
        ).fetchall()
        for row in rows:
            db.execute(
                "INSERT OR REPLACE INTO revisions(project_id,revision,name,state_json,created) "
                "VALUES(?,?,?,?,?)",
                (pid, row["revision"], row["name"], row["state_json"], row["created"]),
            )


def legacy_revisions(store, pid) -> list:
    with store.connect() as db:
        return db.execute(
            "SELECT revision,name,state_json,created FROM revisions WHERE project_id=? "
            "ORDER BY revision", (pid,),
        ).fetchall()


def migrate(store, pid) -> dict:
    """像迁移工具那样：先把老库的影子表造出来，再把旧 revisions + ``state_json.vh`` 灌进表。"""
    seed_legacy_revisions(store, pid)
    return apply_history_split(
        store.version_table, pid,
        state_of(store, pid),
        revisions=legacy_revisions(store, pid),
    )


def vh_of(store, pid) -> list:
    return store.get(pid)["state"].get("vh")


# ---------------- 1. 能力级别 ----------------

def test_version_three_does_not_open_history(tmp_path, seed_dir, monkeypatch):
    store = make_store(tmp_path, seed_dir, monkeypatch, 3)
    assert store.business_version == 3
    assert store.history_enabled is False
    assert store.get(pid_of(store))["history_table"] is False
    with pytest.raises(Exception):  # 表根本没建
        store.version_table.rows(pid_of(store))


def test_version_three_still_keeps_the_shadow_copy(tmp_path, seed_dir, monkeypatch):
    """开关**还没到 4**时旧路径还是权威：``revisions`` 与 ``state_json`` 照旧维护（回滚靠它）。"""
    store = make_store(tmp_path, seed_dir, monkeypatch, 3)
    pid = pid_of(store)
    # 开关 < 4 时履历接口是 409（表还没启用），走的是老的"整份保存"路
    with pytest.raises(HTTPException):
        store.project_history(pid)
    record = store.get(pid)
    store.update(pid, record["name"], record["state"], record["revision"])
    with store.connect() as db:
        assert db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='revisions'").fetchone(), \
            "开关 < 4 时这张表必须还在（迁移工具要读它）"
        rows = db.execute("SELECT revision,state_json FROM revisions WHERE project_id=? ORDER BY revision",
                          (pid,)).fetchall()
        stored = json.loads(db.execute("SELECT state_json FROM projects WHERE id=?", (pid,)
                                       ).fetchone()["state_json"])
    assert [int(row["revision"]) for row in rows], "开关 < 4 → 影子副本必须照旧写"
    assert set(json.loads(rows[0]["state_json"])) == {"G", "pr", "is", "vh"}, "影子副本是完整快照"
    assert set(stored) == {"pr", "is", "vh"}, "开关 < 4 → 项目行里那三份数组也照旧留着"


def test_read_model_arrays_are_always_lists(store):
    """三份业务数组永远是数组：表是权威时"表里 0 行"就是"空"，不能整个键消失。"""
    pid = pid_of(store)
    with store.connect() as db:
        db.execute("UPDATE projects SET state_json='{}' WHERE id=?", (pid,))
    state = store.get(pid)["state"]
    for key in ("pr", "is", "vh"):
        assert isinstance(state[key], list), f"{key} 必须是数组（前端一直按数组用）"


def test_version_four_opens_history(store):
    pid = pid_of(store)
    record = store.get(pid)
    assert store.history_enabled is True
    assert record["history_table"] is True and record["business_version"] == HISTORY_VERSION
    # 建项目那一次就留了一个保存版本，但**履历行还没有**（要等迁移工具搬）
    assert store.version_table.has_history_rows(pid) is False
    assert len(store.version_table.save_rows(pid)) == 1
    # 还没迁移 → 读模型仍旧读 state_json.vh（与改造前一样）
    assert record["state"]["vh"] == VH_ROWS


def test_gate_closed_route_returns_409(tmp_path, seed_dir, monkeypatch):
    store = make_store(tmp_path, seed_dir, monkeypatch, 3)
    pid = pid_of(store)
    with pytest.raises(HTTPException) as error:
        store.project_history(pid)
    assert error.value.status_code == 409


# ---------------- 2. 外键 ----------------

def test_ddl_declares_project_foreign_key(store):
    with store.connect() as db:
        sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (HISTORY_TABLE,)).fetchone()[0]
    assert "REFERENCES projects(id)" in sql
    assert f"CHECK (kind IN ('{KIND_SAVE}','{KIND_HISTORY}'))" in sql
    # 关联列是真外键 → DB 层拦得住凭空的项目 id
    with pytest.raises(Exception):
        with store.connect() as db:
            db.execute(
                f"INSERT INTO {HISTORY_TABLE}(id,project_id,kind,revision,created,updated) "
                "VALUES('x','no-such-project','history',0,'t','t')",
            )


# ---------------- 3. 表级 CHECK ----------------

@pytest.mark.parametrize("payload", [
    {"kind": "save", "revision": 0},                     # 保存版本必须有版本号
    {"kind": "history", "revision": 3},                  # 履历行不许带版本号
    {"kind": "history", "revision": 0, "state": {"a": 1}},  # 履历行的快照必须是空的
])
def test_checks_reject_contradictory_rows(store, payload):
    pid = pid_of(store)
    with pytest.raises(Exception):
        store.version_table.create(pid, payload)


def test_kind_must_be_known(store):
    pid = pid_of(store)
    with pytest.raises(HTTPException):
        store.version_table.create(pid, {"kind": "whatever", "revision": 0})


# ---------------- 4. 保存版本 ----------------

def test_every_save_writes_a_save_row(store):
    pid = pid_of(store)
    assert len(store.version_table.save_rows(pid)) == 1  # 建项目那一次
    store.create_project_history(pid, {"dt": "2026-03-01", "ver": "V1.2"})
    rows = store.version_table.save_rows(pid)
    assert [int(row["revision"]) for row in rows] == [2, 1]  # 倒序，与 /versions 一致
    assert store.get(pid)["revision"] == 2


def test_shadow_copy_stops_once_history_is_in_tables(store):
    """口径 6：开关到 4 之后旧 ``revisions`` 表**不建也不写** —— 库里每种数据只有一份。

    （阶段 3a 当时是"两份都写、逐字节相同"，那时还没法回滚验证；
    2026-09-18 清理旧副本时改成"表是唯一权威"，回滚改成从备份恢复。）
    """
    pid = pid_of(store)
    store.create_project_history(pid, {"dt": "2026-03-01"})
    with store.connect() as db:
        assert db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='revisions'").fetchone() is None
        saves = db.execute(
            f"SELECT revision FROM {HISTORY_TABLE} WHERE project_id=? AND kind=? ORDER BY revision",
            (pid, KIND_SAVE),
        ).fetchall()
    # 建项目 + 加一条履历 = 两次保存，两次都在表里，一次不少
    assert [int(row["revision"]) for row in saves] == [1, 2]


def test_legacy_revisions_is_still_the_migration_source(store):
    """老库（3a 之前）的影子表还在时，迁移工具照样能把它搬进表 —— 一行都不许丢。"""
    pid = pid_of(store)
    store.create_project_history(pid, {"dt": "2026-03-01"})
    seed_legacy_revisions(store, pid)
    legacy = legacy_revisions(store, pid)
    assert [int(row["revision"]) for row in legacy] == [1, 2]

    apply_history_split(store.version_table, pid, state_of(store, pid), revisions=legacy)
    with store.connect() as db:
        pairs = db.execute(
            "SELECT r.revision AS revision, r.state_json AS old_json, v.state_json AS new_json "
            f"FROM revisions r JOIN {HISTORY_TABLE} v "
            "ON v.project_id=r.project_id AND v.revision=r.revision AND v.kind='save' "
            "WHERE r.project_id=?", (pid,),
        ).fetchall()
    assert pairs, "保存版本应该与老库 revisions 一一对应"
    for row in pairs:
        assert row["new_json"] == row["old_json"], f"第 {row['revision']} 版快照不一致"


def test_versions_listing_matches_save_rows(store):
    pid = pid_of(store)
    store.create_project_history(pid, {"dt": "2026-03-01"})
    seed_legacy_revisions(store, pid)
    with store.connect() as db:
        old = db.execute(
            "SELECT revision,name,created FROM revisions WHERE project_id=? ORDER BY revision DESC",
            (pid,),
        ).fetchall()
    assert [{key: item[key] for key in ("revision", "name", "created")} for item in
            version_listing(store.version_table, pid)] == \
        [{key: row[key] for key in ("revision", "name", "created")} for row in old]


def test_revision_endpoint_still_opens(store):
    pid = pid_of(store)
    store.create_project_history(pid, {"dt": "2026-03-01"})
    record = store.get(pid, 1)
    assert record["revision"] == 1
    assert record["state"]["pr"][0]["nm"] == "机加工序-OP10"


# ---------------- 5. 读模型 ----------------

def test_history_round_trip_is_byte_identical(store):
    pid = pid_of(store)
    before = json.dumps(vh_of(store, pid), ensure_ascii=False)
    migrate(store, pid)
    after = json.dumps(vh_of(store, pid), ensure_ascii=False)
    assert after == before
    # 键序也要一样：页面渲染与 PPT 导出都按这个顺序
    assert [list(item) for item in vh_of(store, pid)] == [list(row) for row in VH_ROWS]


def test_table_with_rows_is_authoritative(store):
    pid = pid_of(store)
    migrate(store, pid)
    # 表里删光（逻辑删除）后 vh 不该回到 state_json 的旧值——表有行就是权威
    for row in store.version_table.history_rows(pid):
        store.version_table.soft_delete(row["id"], reason="测试")
    assert vh_of(store, pid) == []
    # 只凭表还原
    assert compose_history(store.version_table.history_rows(pid)) == []


def test_empty_table_falls_back_to_state_json(store):
    pid = pid_of(store)
    assert store.version_table.has_history_rows(pid) is False
    assert legacy_history(store.version_table, pid) is None
    assert vh_of(store, pid) == VH_ROWS


def test_history_row_without_extra_keys(store):
    """旧行只认四个键：多出来的键不丢、也不改值，按原样补在后面。"""
    pid = pid_of(store)
    state = state_of(store, pid)
    state["vh"] = [{"dt": "2026-01-05", "ver": "V1.0", "ds": "初版", "by": "张三",
                    "why": "客户要求"}]
    report = apply_history_split(store.version_table, pid, state)
    assert report["history"] == 1 and report["extras"] == 1
    assert vh_of(store, pid) == [{"dt": "2026-01-05", "ver": "V1.0", "ds": "初版",
                                  "by": "张三", "why": "客户要求"}]
    # 再改一个格，兜底键不能丢
    row_id = store.version_table.history_rows(pid)[0]["id"]
    store.save_project_history(pid, row_id, {"ds": "初版（修订）"})
    assert vh_of(store, pid)[0]["why"] == "客户要求"
    assert vh_of(store, pid)[0]["ds"] == "初版（修订）"


# ---------------- 6. 行级写入 ----------------

def test_row_apis_write_one_cell_at_a_time(store):
    pid = pid_of(store)
    migrate(store, pid)
    rows = store.project_history(pid)["history"]
    assert len(rows) == len(VH_ROWS)
    record = store.save_project_history(pid, rows[1]["id"], {"ds": "改结构（第二版）"})
    assert record["state"]["vh"][1]["ds"] == "改结构（第二版）"
    assert record["state"]["vh"][1]["ver"] == "V1.1"
    # 迁移本身**不算一次用户保存**（不凭空造版本），所以行级写入才是第 2 版
    assert record["revision"] == 2


def test_create_history_fills_missing_keys(store):
    pid = pid_of(store)
    record = store.create_project_history(pid, {"dt": "2026-03-01", "ver": "V1.9"})
    row = record["state"]["vh"][-1]
    assert row == {"dt": "2026-03-01", "ver": "V1.9", "ds": "", "by": ""}


def test_history_listing_shape(store):
    pid = pid_of(store)
    migrate(store, pid)
    listing = history_listing(store.version_table, pid)
    assert listing["table"] == HISTORY_TABLE and listing["kind"] == KIND_HISTORY
    assert listing["keys"] == ["dt", "ver", "ds", "by"]
    assert listing["count"] == listing["live_count"] == 2 and listing["recycle_count"] == 0
    assert listing["history"][0]["revision"] is None   # 履历行不是保存版本
    assert listing["history"][0]["id"].endswith("-h0")


def test_index_target_uses_current_listing(store):
    pid = pid_of(store)
    migrate(store, pid)
    # 页面只给下标：下标换了目标，服务端按**当前**列表换算
    record = store.save_project_history(pid, "", {"index": 1, "ds": "按下标改"})
    assert record["state"]["vh"][1]["ds"] == "按下标改"
    with pytest.raises(HTTPException) as error:
        store.save_project_history(pid, "", {"index": 9, "ds": "越界"})
    assert error.value.status_code == 409


def test_reorder_changes_order_without_touching_save_rows(store):
    pid = pid_of(store)
    migrate(store, pid)
    rows = [row["id"] for row in store.version_table.history_rows(pid)]
    saves_before = {row["id"]: row["sort_order"]
                    for row in store.version_table.save_rows(pid, include_deleted=True)}
    store.reorder_project_history(pid, list(reversed(rows)))
    assert [item["ver"] for item in vh_of(store, pid)] == ["V1.1", "V1.0"]
    saves_after = {row["id"]: row["sort_order"]
                   for row in store.version_table.save_rows(pid, include_deleted=True)}
    # 原有的保存版本序号一个都没被重排打乱（新加的那一版不算）
    assert all(saves_after[key] == value for key, value in saves_before.items())


# ---------------- 7. 逻辑删除 ----------------

def test_delete_is_soft_and_restorable(store):
    pid = pid_of(store)
    migrate(store, pid)
    row_id = store.version_table.history_rows(pid)[0]["id"]
    store.delete_project_history(pid, row_id, by="tester", reason="点错了")
    assert [item["ver"] for item in vh_of(store, pid)] == ["V1.1"]
    assert store.version_table.has_history_rows(pid) is True          # 行还在表里
    recycle = store.project_history(pid, recycle=True)
    assert recycle["count"] == 1 and recycle["recycle_count"] == 1
    assert recycle["history"][0]["deleted_by"] == "tester"
    store.restore_project_history(pid, row_id)
    assert [item["ver"] for item in vh_of(store, pid)] == ["V1.0", "V1.1"]


def test_deleted_row_cannot_be_edited(store):
    pid = pid_of(store)
    migrate(store, pid)
    row_id = store.version_table.history_rows(pid)[0]["id"]
    store.delete_project_history(pid, row_id)
    with pytest.raises(HTTPException) as error:
        store.save_project_history(pid, row_id, {"ds": "偷偷改"})
    assert error.value.status_code == 410


def test_history_row_of_other_project_is_rejected(store, tmp_path, seed_dir):
    pid = pid_of(store)
    migrate(store, pid)
    row_id = store.version_table.history_rows(pid)[0]["id"]
    with pytest.raises(HTTPException) as error:
        store.save_project_history("no-such-project", row_id, {"ds": "x"})
    assert error.value.status_code == 404


# ---------------- 8. 迁移 ----------------

def test_apply_split_is_idempotent(store):
    pid = pid_of(store)
    first = migrate(store, pid)
    assert first["skipped"] is False and first["history"] == len(VH_ROWS)
    saves = len(store.version_table.save_rows(pid))
    second = migrate(store, pid)
    assert second["skipped"] is True
    assert len(store.version_table.save_rows(pid)) == saves
    assert len(store.version_table.history_rows(pid)) == len(VH_ROWS)
    assert second["existing_rows"] == saves + len(VH_ROWS)


def test_preflight_blocks_bad_old_data(store):
    pid = pid_of(store)
    state = state_of(store, pid)
    seed_legacy_revisions(store, pid)
    revisions = legacy_revisions(store, pid)
    problems = history_preflight([{
        "id": pid, "name": "x",
        "state_json": json.dumps({**state, "vh": [{"dt": "1"}, "裸字符串"]}, ensure_ascii=False),
        "revisions": revisions,
    }])
    assert problems and "不是对象" in problems[0]
    # 非数组的 vh 也不猜
    problems = history_preflight([{
        "id": pid, "name": "x", "state_json": json.dumps({"vh": {"dt": "1"}}), "revisions": [],
    }])
    assert problems and "不是数组" in problems[0]


def test_split_never_silently_drops(store):
    with pytest.raises(HTTPException) as error:
        split_history_rows([{"dt": "1"}, 42])
    assert "第 2 条" in error.value.detail


def test_history_payload_only_accepts_four_keys():
    values = history_payload({"dt": "2026-01-01", "ver": "V1", "ds": "d", "by": "b",
                              "id": "hack", "revision": 99, "kind": "save"})
    assert values == {"dt": "2026-01-01", "ver": "V1", "ds": "d", "by": "b"}
    # 别的键进兜底列，不丢
    assert history_payload({"dt": "1", "why": "因为"})["extra"] == {"why": "因为"}
    with pytest.raises(HTTPException):
        history_payload({"ds": "x" * 5000})


def test_legacy_keys_order_matches_page():
    """读模型键序必须是页面上 addVH() 的插入顺序（真页面的 form 同步依赖它）。"""
    assert list(compose_history([{"dt": "d", "ver": "v", "ds": "s", "by": "b"}])[0]) == \
        ["dt", "ver", "ds", "by"]


# ---------------- 9. 兜底：没赶上迁移的老项目 ----------------

def test_virtual_listing_then_first_write_materializes(store):
    """开关刚打开、迁移还没跑：页面照样能看到并能改，第一次写就把老履历补建成真行。"""
    pid = pid_of(store)
    listing = store.project_history(pid)
    assert listing["materialized"] is False
    assert listing["count"] == len(VH_ROWS)
    # 影子清单发的 id 与"就地补建"用的 id 必须一致（否则页面会被告知"这一行不在了"）
    assert [row["id"] for row in listing["history"]] == [f"{pid}-h0", f"{pid}-h1"]
    assert store.version_table.has_history_rows(pid) is False

    record = store.save_project_history(pid, f"{pid}-h1", {"ds": "改结构（落表了）"})
    assert store.version_table.has_history_rows(pid) is True
    assert [row["ver"] for row in record["state"]["vh"]] == ["V1.0", "V1.1"]
    assert record["state"]["vh"][1]["ds"] == "改结构（落表了）"
    # 补建出来的行与原数组逐字节一致（除了刚改的那一格）
    assert store.project_history(pid)["materialized"] is True


def test_new_row_materializes_old_ones_first(store):
    pid = pid_of(store)
    record = store.create_project_history(pid, {"dt": "2026-03-01", "ver": "V1.2"})
    assert [row["ver"] for row in record["state"]["vh"]] == ["V1.0", "V1.1", "V1.2"]



