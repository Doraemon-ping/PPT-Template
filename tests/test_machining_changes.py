"""阶段 3b：变更流水落表（``project_changes``）的单元测试。

覆盖：

1. 能力级别 ≥5 才启用（1 工序 / 2 问题清单 / 3 选型报价 / 4 版本履历 / **5 变更流水**），
   没启用时不建表、接口 409、行级写入照常但不记流水；
2. **外键全是真的**：``project_id``→``projects``、``version_id``/``history_row_id``→``project_versions``、
   四个业务行外键 → 工序/刀具行/问题/选型；DB 层拦得住（凭空 id 插不进去），
   删目标行时 ``ON DELETE SET NULL`` 生效且不挡住删除；
3. ``CHECK`` 把"恰好挂一个"钉死：实体与列不匹配、``settings``/``project`` 挂了行、未知实体/动作一律拒绝；
4. 每个行级写入点都留一条流水：工序/刀具行/问题/选型/履历的新增、修改、逻辑删除、恢复、排序、
   换图；每条的 ``entity``/``action``/``label``/目标行外键都对；
5. ``version_id`` 指得到"这一次保存"的那一行（``version_revision`` 与项目版本一致）；
6. 标签是给人看的一句话（字段中文名 + 旧值→新值；级联删除写"随工序删除"）；
7. 拒绝的写入不留流水（422/409 之后一条都不多）；
8. 系统自己搬数据（老履历就地补建）**不**记流水（口径 5：不无中生有）；
9. 只读：没有写接口，清单按项目隔离、按实体/动作筛选、软删列留着给阶段 4。
"""

import json
import uuid

import pytest

from app.machining_dfm import MachiningDFMStore
from app.machining_changes import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_PHOTO,
    ACTION_REORDER,
    ACTION_RESTORE,
    ACTION_SAVE,
    ACTION_UPDATE,
    CHANGES_TABLE,
    CHANGES_VERSION,
    ENTITY_HISTORY,
    ENTITY_ISSUE,
    ENTITY_PROCESS,
    ENTITY_PROJECT,
    ENTITY_SELECTION,
    ENTITY_SETTINGS,
    ENTITY_TOOL,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


def state_of(store, pid) -> dict:
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
        "vh": [],
    }, ensure_ascii=False), encoding="utf-8")
    (root / "tools.json").write_text("[]", encoding="utf-8")
    (root / "fixtures.json").write_text("[]", encoding="utf-8")
    (root / "gauges.json").write_text("[]", encoding="utf-8")
    (root / "categories.json").write_text(
        json.dumps({"fcnX": ["中心一"], "icnX": ["检具一"]}, ensure_ascii=False), encoding="utf-8")
    return root


def make_store(tmp_path, seed_dir, monkeypatch, version):
    monkeypatch.setenv("MACHINING_PROJECT_BUSINESS", str(version))
    return MachiningDFMStore(tmp_path / f"data-v{version}" / "machining_dfm", seed_dir)


@pytest.fixture()
def store(tmp_path, seed_dir, monkeypatch):
    return make_store(tmp_path, seed_dir, monkeypatch, CHANGES_VERSION)


def pid_of(store) -> str:
    return store.list()[0]["id"]


def changes(store, pid, **kwargs) -> list[dict]:
    """项目流水，按发生顺序（旧 → 新）。"""
    return list(reversed(store.project_changes(pid, **kwargs)["changes"]))


def last(store, pid, **kwargs) -> dict:
    return changes(store, pid, **kwargs)[-1]


def make_process(store, pid, name="OP10 粗铣", **payload) -> dict:
    store.create_project_process(pid, {"nm": name, **payload})
    return store.processes.list_typed(pid)[-1]


# ---------------- 1. 能力级别 ----------------

def test_version_four_does_not_open_changes(tmp_path, seed_dir, monkeypatch):
    store = make_store(tmp_path, seed_dir, monkeypatch, 4)
    pid = pid_of(store)
    assert store.business_version == 4
    assert store.changes_enabled is False
    assert store.get(pid)["changes_table"] is False
    with pytest.raises(Exception):  # 表根本没建
        store.change_table.rows(pid)
    with pytest.raises(Exception):
        store.project_changes(pid)


def test_version_five_opens_changes(store):
    pid = pid_of(store)
    record = store.get(pid)
    assert store.changes_enabled is True
    assert record["changes_table"] is True and record["business_version"] == CHANGES_VERSION
    assert store.project_changes(pid)["enabled"] is True


def test_rows_are_still_written_when_changes_disabled(tmp_path, seed_dir, monkeypatch):
    """开关没开到 5：行级写入照常，只是不记流水（代码可以先上线，数据晚点再迁）。"""
    store = make_store(tmp_path, seed_dir, monkeypatch, 4)
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")
    assert [row["nm"] for row in store.processes.list_typed(pid)] == [process["nm"]]
    assert store.get(pid)["state"]["pr"][0]["nm"] == "OP10 粗铣"  # 读模型也已经是表里的行


# ---------------- 2. 外键真的存在 ----------------

def test_ddl_foreign_keys_are_real(store):
    with store.connect() as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name=?",
                         (CHANGES_TABLE,)).fetchone()["sql"]
    for column, table in (
        ("project_id", "projects(id)"),
        ("version_id", "project_versions(id)"),
        ("process_row_id", "project_processes(id)"),
        ("tool_row_id", "project_process_tools(id)"),
        ("issue_row_id", "project_issues(id)"),
        # 选型拆表后：夹具/检具各一列（老的 selection_row_id 只剩一个可空列，不再建外键）
        ("fixture_row_id", "project_fixtures(id)"),
        ("gauge_row_id", "project_gauges(id)"),
        ("history_row_id", "project_versions(id)"),
    ):
        assert f'"{column}" TEXT' in sql or f"{column} TEXT" in sql
        assert f"REFERENCES {table}" in sql, column
    # 老列还在（历史流水行读得到当时挂的是谁），但**没有**外键了——老表在新库里根本不存在
    assert "selection_row_id TEXT" in sql
    assert "REFERENCES project_selections(id)" not in sql
    # 七个"被改的行/版本"列都是 SET NULL，只有 project_id 是 NO ACTION
    assert sql.count("ON DELETE SET NULL") == 7
    assert "project_id TEXT NOT NULL REFERENCES projects(id)" in sql


def test_foreign_key_blocks_unknown_project(store):
    with store.connect() as db:
        with pytest.raises(Exception):
            db.execute(
                f"INSERT INTO {CHANGES_TABLE}(id,project_id,sort_order,entity,action,label,"
                "extra_json,created,updated) VALUES('x','no-such-project',0,'project','save','x',"
                "'{}','t','t')")


def test_set_null_when_target_row_disappears(store):
    """物理删掉被改的那一行（真实口径里不会发生）：外键置空，流水本身留着。"""
    pid = pid_of(store)
    store.create_project_process(pid, {"nm": "OP10 粗铣"})
    process = store.processes.list_typed(pid)[-1]
    with store.connect() as db:
        before = db.execute(
            f"SELECT COUNT(*) FROM {CHANGES_TABLE} WHERE process_row_id=?", (process["id"],)
        ).fetchone()[0]
        db.execute("DELETE FROM project_processes WHERE id=?", (process["id"],))
        after = db.execute(
            f"SELECT COUNT(*), SUM(process_row_id IS NULL) FROM {CHANGES_TABLE}"
        ).fetchone()
    assert before == 1
    assert after[0] >= 1 and after[1] >= 1  # 行还在，只是外键被置空


# ---------------- 3. CHECK：恰好挂一个 ----------------

def test_check_rejects_unknown_entity_or_action(store):
    pid = pid_of(store)
    with pytest.raises(Exception):
        insert_row(store, project_id=pid, entity="mystery", action=ACTION_UPDATE, label="x")
    with pytest.raises(Exception):
        insert_row(store, project_id=pid, entity=ENTITY_PROJECT, action="explode", label="x")


def insert_row(store, **body):
    """直接往表里插一行（绕开接口，专门验 CHECK）。"""
    columns = ["id", "project_id", "sort_order", "entity", "action", "label", "extra_json",
               "created", "updated", "version_id", "process_row_id", "tool_row_id",
               "issue_row_id", "selection_row_id", "history_row_id"]
    defaults = {"sort_order": 0, "extra_json": "{}", "created": "t", "updated": "t"}
    values = [body.get(column, defaults.get(column)) for column in columns]
    values[0] = body.get("id") or "row-" + uuid.uuid4().hex[:8]
    with store.connect() as db:
        db.execute(
            f"INSERT INTO {CHANGES_TABLE}(" + ",".join(columns) + ") VALUES("
            + ",".join("?" * len(columns)) + ")", tuple(values))


def test_check_rejects_entity_and_column_mismatch(store):
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")
    tool = make_tool(store, pid, process["id"])
    # entity='process' 却挂到刀具行上 → 拒绝（挂上的列必须与实体对应）
    with pytest.raises(Exception):
        insert_row(store, project_id=pid, entity=ENTITY_PROCESS, action=ACTION_UPDATE,
                   label="错挂", tool_row_id=tool["id"])
    # settings 挂了行 → 拒绝（整项目改动不许挂行）
    with pytest.raises(Exception):
        insert_row(store, project_id=pid, entity=ENTITY_SETTINGS, action=ACTION_UPDATE,
                   label="错挂", process_row_id=process["id"])
    # 一次挂两列 → 拒绝（最多挂一个）
    with pytest.raises(Exception):
        insert_row(store, project_id=pid, entity=ENTITY_PROCESS, action=ACTION_UPDATE,
                   label="双挂", process_row_id=process["id"], tool_row_id=tool["id"])


def test_check_allows_row_to_become_null(store):
    """五列都是 ``ON DELETE SET NULL``：目标行被物理删掉后，"实体对但没挂行"必须仍然合法。

    这一条是回归点：CHECK 原来写成"必须恰好挂一列"，于是删业务行时 SET NULL 会把 CHECK
    顶掉（``IntegrityError: CHECK constraint failed``），连"删掉一行"都做不成。
    """
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")
    insert_row(store, project_id=pid, entity=ENTITY_PROCESS, action=ACTION_UPDATE, label="没挂行")
    # 排序调整也没有对应的行
    insert_row(store, project_id=pid, entity=ENTITY_TOOL, action=ACTION_REORDER, label="排序")
    items = changes(store, pid)
    assert any(item["action"] == ACTION_REORDER for item in items)
    assert any(item["entity"] == ENTITY_PROCESS and item["process_row_id"] is None
               for item in items)


# ---------------- 4. 每个写入点都留一条 ----------------

def make_tool(store, pid, process_id, code="T01", **payload) -> dict:
    store.create_project_tool(pid, process_id, {"code": code, "tp": payload.pop("tp", "D50盘铣刀"),
                                                "n": payload.pop("n", 3000), **payload})
    return store.process_tools.list_typed(pid)[-1]


def make_issue(store, pid, **payload) -> dict:
    store.create_project_issue(pid, {"tp": payload.pop("tp", "尺寸超差"),
                                     "ds": payload.pop("ds", "孔位偏 0.2"), **payload})
    return store.issues.list_typed(pid)[-1]


def test_new_project_is_recorded(store):
    pid = pid_of(store)
    item = changes(store, pid)[0]
    assert (item["entity"], item["action"]) == (ENTITY_PROJECT, ACTION_CREATE)
    assert "新建项目" in item["label"]
    assert item["version_revision"] == 1


def test_process_create_update_delete_restore(store):
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")

    store.update_project_process(pid, process["id"], {"nm": "OP10 精铣", "mc": 3})
    updated = last(store, pid)
    assert (updated["entity"], updated["action"]) == (ENTITY_PROCESS, ACTION_UPDATE)
    assert updated["process_row_id"] == process["id"]
    assert "工序名称 OP10 粗铣→OP10 精铣" in updated["label"]
    assert "设备台数 1→3" in updated["label"]

    store.delete_project_process(pid, process["id"], by="张三", reason="改方案")
    removed = last(store, pid)
    assert removed["action"] == ACTION_DELETE
    assert "改方案" in removed["label"] and removed["extra"]["by"] == "张三"

    store.restore_project_process(pid, process["id"])
    restored = last(store, pid)
    assert restored["action"] == ACTION_RESTORE
    assert restored["process_row_id"] == process["id"]


def test_tool_create_update_and_cascade(store):
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")
    tool = make_tool(store, pid, process["id"])

    assert last(store, pid)["entity"] == ENTITY_TOOL
    assert last(store, pid)["tool_row_id"] == tool["id"]

    store.update_project_tool(pid, tool["id"], {"n": 3500, "vf": 1200})
    label = last(store, pid)["label"]
    assert "转速 n 3000→3500" in label and "进给 vf 0→1200" in label

    # 删工序 → 刀具行随删（逐行留一条，写清楚是因为哪道工序）
    store.delete_project_process(pid, process["id"], by="张三", reason="改方案")
    cascade = [item for item in changes(store, pid) if item["entity"] == ENTITY_TOOL][-1]
    assert cascade["action"] == ACTION_DELETE and "随工序删除" in cascade["label"]
    assert cascade["tool_row_id"] == tool["id"]

    store.restore_project_process(pid, process["id"])
    back = [item for item in changes(store, pid) if item["entity"] == ENTITY_TOOL][-1]
    assert back["action"] == ACTION_RESTORE and "随工序恢复" in back["label"]


def test_tool_photo_and_clear(store):
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")
    tool = make_tool(store, pid, process["id"])

    store.set_tool_photo(pid, tool["id"], PNG, "image/png", "t.png")
    shot = last(store, pid)
    assert (shot["entity"], shot["action"]) == (ENTITY_TOOL, ACTION_PHOTO)
    assert "换图（刀具图）" in shot["label"] and shot["extra"]["has_asset"] is True

    store.clear_tool_photo(pid, tool["id"])
    cleared = last(store, pid)
    assert cleared["action"] == ACTION_PHOTO and cleared["extra"]["has_asset"] is False


def test_issue_create_update_delete_reorder_and_photo(store):
    pid = pid_of(store)
    issue = make_issue(store, pid)
    assert (last(store, pid)["entity"], last(store, pid)["action"]) == (ENTITY_ISSUE, ACTION_CREATE)
    assert last(store, pid)["issue_row_id"] == issue["id"]

    # 问题图片（这条以前是 500：调了附件库不存在的方法）
    store.set_issue_photo(pid, issue["id"], "before", PNG, "image/png")
    shot = last(store, pid)
    assert shot["action"] == ACTION_PHOTO and "换图（修改前）" in shot["label"]
    with store.connect() as db:
        asset_id = db.execute("SELECT before_photo_id FROM project_issues WHERE id=?",
                              (issue["id"],)).fetchone()[0]
    assert asset_id

    store.update_project_issue(pid, issue["id"], {"st": "已完成"})
    assert "状态 进行中→已完成" in last(store, pid)["label"]

    store.delete_project_issue(pid, issue["id"], reason="客户撤销")
    assert last(store, pid)["action"] == ACTION_DELETE
    store.restore_project_issue(pid, issue["id"])
    assert last(store, pid)["action"] == ACTION_RESTORE

    store.reorder_project_issues(pid, [issue["id"]])
    assert last(store, pid)["action"] == ACTION_REORDER
    assert last(store, pid)["issue_row_id"] is None  # 排序是整表操作


def test_selection_writes_are_recorded(store):
    pid = pid_of(store)
    # 第一次动这个项目的选型：先把老数组整份搬进两张新表（懒迁移），这一步**不记流水**
    # （它是系统搬数据，不是人改数据），所以下面的保存是"改已有行"而不是"建行"
    store.save_project_selection(pid, "fixture", 0, {"quoted": 0})
    created = last(store, pid)
    assert created["entity"] == ENTITY_SELECTION
    assert created["action"] == ACTION_UPDATE
    # 选型的行外键**分列**：夹具行进 fixture_row_id，检具行进 gauge_row_id
    assert created["fixture_row_id"] and created["gauge_row_id"] is None
    assert created["selection_row_id"] is None
    assert "夹具第 1 格" in created["label"]
    # 那一格真的落表了（懒迁移 + 这次保存）
    row = [item for item in store.selections.fixtures.list_typed(pid)
           if item["sort_order"] == 0][0]
    assert row["quoted"] == 0 and created["fixture_row_id"] == row["id"]

    # 再改一格 = 行级修改，标签里写清楚哪个字段变了
    store.save_project_selection(pid, "fixture", 0, {"quoted": 1})
    updated = last(store, pid)
    assert updated["action"] == ACTION_UPDATE
    assert updated["fixture_row_id"] == created["fixture_row_id"]
    assert "是否报价 0→1" in updated["label"]

    # 检具走另一列（同一实体名，靠 extra 里的 kind 决定挂哪一列）
    store.save_project_selection(pid, "gauge", 0, {"quoted": 0})
    gauge_change = last(store, pid)
    assert gauge_change["fixture_row_id"] is None
    assert gauge_change["gauge_row_id"]
    assert "检具第 1 格" in gauge_change["label"]


def test_history_writes_are_recorded(store):
    pid = pid_of(store)
    store.create_project_history(pid, {"ver": "V1.0", "dt": "2026-03-01", "ds": "初版", "by": "张三"})
    created = last(store, pid)
    assert (created["entity"], created["action"]) == (ENTITY_HISTORY, ACTION_CREATE)
    assert created["history_row_id"]
    assert "V1.0" in created["label"]

    row = store.version_table.history_rows(pid)[0]
    store.save_project_history(pid, row["id"], {"ds": "初版发布"})
    assert "变更内容 初版→初版发布" in last(store, pid)["label"]

    store.delete_project_history(pid, row["id"], reason="页面删除")
    assert last(store, pid)["action"] == ACTION_DELETE


def test_settings_and_whole_document_save_are_recorded(store):
    pid = pid_of(store)
    store.save_project_settings(pid, {"hpd": 20})
    item = last(store, pid)
    assert (item["entity"], item["action"]) == (ENTITY_SETTINGS, ACTION_UPDATE)
    assert "日可动时间" in item["label"] and "→20" in item["label"]
    assert item["process_row_id"] is None and item["issue_row_id"] is None

    record = store.get(pid)
    store.update(pid, record["name"], record["state"], record["revision"])
    saved = last(store, pid)
    assert (saved["entity"], saved["action"]) == (ENTITY_PROJECT, ACTION_SAVE)
    assert saved["version_revision"] == record["revision"] + 1


def test_machine_change_is_recorded_by_model_name(store):
    """换设备：流水里写型号（不是 uuid），并且结构化明细里带着设备列。

    顺带看着一个真缺陷：``Machines.find()`` 返回 ``sqlite3.Row``，原来 ``set_machine()``
    直接 ``machine.get(...)`` —— 真服务上"换设备"一调就是 500（打开开关才走得到，所以线上没暴露）。
    """
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")
    machine_id = store.machines.ids()[0]

    store.update_project_process(pid, process["id"], {"mid": machine_id})
    picked = last(store, pid)
    row = store.processes.list_typed(pid)[0]
    assert row["mid"] == machine_id and row["machine_snapshot"]["id"] == machine_id
    assert picked["entity"] == ENTITY_PROCESS and picked["action"] == ACTION_UPDATE
    assert row["machine_snapshot"]["model"] in picked["label"]
    assert picked["extra"]["fields"][0]["key"] == "mid"

    # 选了同一台：值没变也要说清楚（快照可能被刷新过）
    store.update_project_process(pid, process["id"], {"mid": machine_id})
    assert "型号没变" in last(store, pid)["label"]

    # 取消选择：外键置空（空串不是 NULL，会踩外键）
    store.update_project_process(pid, process["id"], {"mid": ""})
    assert store.processes.list_typed(pid)[0]["mid"] == ""
    assert "→（空）" in last(store, pid)["label"]


# ---------------- 5. version_id 指得到这一次保存 ----------------

def test_version_id_points_at_that_save(store):
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")
    item = last(store, pid)
    assert item["version_id"]
    with store.connect() as db:
        row = db.execute("SELECT kind,revision,project_id FROM project_versions WHERE id=?",
                         (item["version_id"],)).fetchone()
    assert row["kind"] == "save"
    assert row["project_id"] == pid
    assert row["revision"] == item["version_revision"] == store.get(pid)["revision"]

    # 快照里也能看到这一版（流水只是给这一版写了个"怎么了"）
    record = store.get(pid, row["revision"])
    assert any(proc["nm"] == "OP10 粗铣" for proc in record["state"]["pr"])


def test_every_write_bumps_one_save_and_one_change(store):
    pid = pid_of(store)
    before_revision = store.get(pid)["revision"]
    before = len(changes(store, pid))
    process = make_process(store, pid, "OP10 粗铣")
    store.update_project_process(pid, process["id"], {"nm": "OP10 精铣"})
    store.delete_project_process(pid, process["id"], reason="测试")
    after = changes(store, pid)
    assert len(after) == before + 3
    revision = store.get(pid)["revision"]
    assert revision == before_revision + 3
    assert [item["version_revision"] for item in after[-3:]] == [revision - 2, revision - 1, revision]


# ---------------- 6/7. 标签与"拒绝的写入不留流水" ----------------

def test_label_is_human_readable(store):
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")
    store.update_project_process(pid, process["id"], {"nm": "OP10 精铣"})
    label = last(store, pid)["label"]
    assert label.startswith("工序 OP10 精铣：")
    assert "→" in label


def test_long_text_is_truncated(store):
    pid = pid_of(store)
    process = make_process(store, pid, "工序" * 60)     # 120 字，登记表允许的上限
    label = last(store, pid)["label"]
    assert len(label) <= 400                            # 流水行的上限
    assert label.endswith("…") or "…" in label          # 标题按 60 字截断，不整段塞进来
    assert process["nm"] == "工序" * 60                  # 表里存的是原文，一个字都不改


def test_rejected_write_leaves_no_change(store):
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")
    before = len(changes(store, pid))
    with pytest.raises(Exception):  # 状态只能是"进行中/已完成"
        make_issue(store, pid, st="随便写")
    assert len(changes(store, pid)) == before

    before = len(changes(store, pid))
    with pytest.raises(Exception):  # 无关项目 → 404
        store.update_project_process(pid, "no-such-process", {"nm": "x"})
    assert len(changes(store, pid)) == before
    assert process["nm"] == "OP10 粗铣"


def test_materialized_history_is_not_recorded(store):
    """老履历就地补建是"系统搬数据"，不是用户改动（口径 5：不无中生有）。"""
    pid = pid_of(store)
    with store.connect() as db:
        state = state_of(store, pid)
        state["vh"] = [{"dt": "2026-01-05", "ver": "V0.9", "ds": "老数据", "by": "李四"}]
        db.execute("UPDATE projects SET state_json=? WHERE id=?",
                   (json.dumps(state, ensure_ascii=False, separators=(",", ":")), pid))
    before = len(changes(store, pid))
    store.create_project_history(pid, {"ver": "V1.0"})
    items = changes(store, pid)
    assert len(items) == before + 1
    assert items[-1]["entity"] == ENTITY_HISTORY and items[-1]["action"] == ACTION_CREATE
    assert "V0.9" not in items[-1]["label"]      # 补建的那两行没有流水
    assert len(store.version_table.history_rows(pid)) == 2


# ---------------- 9. 只读清单 ----------------

def test_listing_is_per_project_and_filtered(store):
    pid = pid_of(store)
    make_process(store, pid, "OP10 粗铣")
    make_issue(store, pid)
    only_issue = changes(store, pid, entity=ENTITY_ISSUE)
    assert only_issue and all(item["entity"] == ENTITY_ISSUE for item in only_issue)
    only_create = changes(store, pid, action=ACTION_CREATE)
    assert only_create and all(item["action"] == ACTION_CREATE for item in only_create)
    assert store.project_changes(pid, limit=1)["changes"].__len__() == 1

    other = store.change_table.listing("no-such-project")
    assert other["count"] == 0


def test_listing_exposes_labels_and_actions(store):
    pid = pid_of(store)
    listing = store.project_changes(pid)
    assert listing["table"] == CHANGES_TABLE
    assert ENTITY_PROCESS in listing["entities"] and ENTITY_HISTORY in listing["entities"]
    assert ACTION_SAVE in listing["actions"] and ACTION_PHOTO in listing["actions"]
    assert listing["action_labels"][ACTION_SAVE] == "保存"
    assert listing["entity_labels"][ENTITY_TOOL] == "工序刀具行"


def test_soft_delete_columns_are_empty_and_recycle_listing_works(store):
    pid = pid_of(store)
    make_process(store, pid, "OP10 粗铣")
    live = changes(store, pid)
    assert all(item["deleted_at"] is None for item in live)
    assert store.project_changes(pid, recycle=True)["count"] == 0
    # 阶段 4 的"隐藏某条"：逻辑删除后从正常清单里消失、回收站里还在（外键行照旧）
    with store.connect() as db:
        db.execute(f"UPDATE {CHANGES_TABLE} SET deleted_at='now' WHERE id=?",
                   (store.project_changes(pid)["changes"][0]["id"],))
    assert store.project_changes(pid)["count"] == len(live) - 1
    assert store.project_changes(pid, recycle=True)["count"] == 1


def test_rows_are_append_only_via_store(store):
    """流水是追加型日志：没有任何写接口（前端也没有写入点）。"""
    pid = pid_of(store)
    make_process(store, pid, "OP10 粗铣")
    assert not hasattr(store, "create_project_change")
    assert not hasattr(store, "update_project_change")
    assert not hasattr(store, "delete_project_change")


def test_snapshot_survives_and_shadow_tables_stay_empty(store):
    """记流水不影响保存版本，而且**保存版本只在表里存一份**（口径 6）。

    2026-09-18 之前是"``revisions`` 与 ``project_versions`` 两份、逐字节相同"；
    清掉旧副本之后旧表不建也不写，快照只存在 ``project_versions``，
    项目行里的 ``state_json`` 也不再重复存三份业务数组。
    """
    pid = pid_of(store)
    process = make_process(store, pid, "OP10 粗铣")
    store.update_project_process(pid, process["id"], {"nm": "OP10 精铣"})
    with store.connect() as db:
        revision = db.execute(
            "SELECT MAX(revision) AS top FROM project_versions WHERE project_id=? AND kind='save'",
            (pid,)).fetchone()["top"]
        snapshot = json.loads(db.execute(
            "SELECT state_json FROM project_versions WHERE project_id=? AND kind='save' AND revision=?",
            (pid, revision)).fetchone()["state_json"])
        shadow = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='revisions'").fetchone()
    # 快照照旧是完整的一份：项目信息 + 三份业务数组
    assert set(snapshot) == {"G", "pr", "is", "vh"}
    assert snapshot["pr"][0]["nm"] == "OP10 精铣", "快照里的数据必须是保存当时的那份"
    assert shadow is None, "开关到 4 之后不该再有 revisions 影子表"

    # 整份保存这条路才会重写项目行：表里已经有的那份就不再重复存（口径 6）
    record = store.get(pid)
    store.update(pid, record["name"], record["state"], record["revision"])
    with store.connect() as db:
        stored = json.loads(db.execute(
            "SELECT state_json FROM projects WHERE id=?", (pid,)).fetchone()["state_json"])
    assert stored == {}, "三份数组都在表里了，项目行里不该再存一份"
    assert store.get(pid)["state"]["pr"][0]["nm"] == "OP10 精铣", "清掉副本之后读模型照旧"
