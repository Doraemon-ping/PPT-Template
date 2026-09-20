"""阶段 4：逻辑删除 + 回收站（基础库/字典也进回收站）。

口径（已拍板）：**不允许永久删除、没有保留期**（口径 2）；字典/库**同名重建 = 复活原行**（口径 3）；
源库删掉后项目按快照价算（口径 4）。回收站**查看**给两个角色、**恢复**只给管理员。

这一套测试盯的是"删 → 回收站可见 → 恢复 → 回到原样"这条闭环，以及逻辑删除**不动物业数据**：
引用列不动、附件不回收、读模型逐字节不变。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.machining_dfm import CHANGES_VERSION, MachiningDFMStore
from app.domains.history import HISTORY_TABLE, KIND_SAVE

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def seed_dir(tmp_path):
    root = tmp_path / "seed"
    root.mkdir(parents=True, exist_ok=True)
    (root / "machines.json").write_text(json.dumps({"machines": [
        {"id": "m-alpha", "brand": "Alpha", "model": "A1", "price": 120},
    ]}, ensure_ascii=False), encoding="utf-8")
    (root / "project.json").write_text(json.dumps({
        "G": {"cust": "客户 A", "part": "P-001"},
        "pr": [{"nm": "机加工序-OP10", "tl": [{"id": "T01", "tp": "D12 铣刀"}], "mid": "m-alpha"}],
        "is": [{"type": "外观", "desc": "毛刺"}],
        "vh": [],
    }, ensure_ascii=False), encoding="utf-8")
    (root / "tools.json").write_text(json.dumps([
        {"id": "tool-1", "tp": "D12 铣刀", "grp": "hp", "cat": "hm", "price": 300, "life": 60},
    ], ensure_ascii=False), encoding="utf-8")
    (root / "fixtures.json").write_text("[]", encoding="utf-8")
    (root / "gauges.json").write_text("[]", encoding="utf-8")
    (root / "categories.json").write_text(
        json.dumps({"fcnX": [], "icnX": []}, ensure_ascii=False), encoding="utf-8")
    return root


@pytest.fixture()
def store(tmp_path, seed_dir, monkeypatch):
    monkeypatch.setenv("MACHINING_PROJECT_BUSINESS", str(CHANGES_VERSION))
    return MachiningDFMStore(tmp_path / "data" / "machining_dfm", seed_dir)


def pid_of(store) -> str:
    return store.list()[0]["id"]


def migrate(store) -> str:
    """把种子项目按迁移工具的方式落表（工序/刀具行/问题清单），返回项目 id。"""
    from app.domains.process import apply_split

    pid = pid_of(store)
    state = store.get(pid)["state"]
    apply_split(store.processes, store.process_tools, pid, state,
                tools_library=store.tools.list_legacy(), machines=store.machines.list_legacy())
    for issue in state.get("is") or []:
        store.issues.create(pid, dict(issue))
    return pid


# ---------------- 1. 业务行：删 → 回收站 → 恢复 ----------------


def test_business_row_round_trip_through_trash(store):
    """工序删掉（连刀具行一起）→ 项目回收站里看得到（带删除人/原因）→ 恢复 → 读模型逐字节回到原样。"""
    pid = migrate(store)
    before = json.dumps(store.get(pid)["state"], ensure_ascii=False, sort_keys=True)
    process = store.processes.list_typed(pid)[0]

    store.delete_project_process(pid, process["id"], by="admin", reason="客户要求重排工艺")
    trashed = store.project_trash(pid)
    assert trashed["enabled"] is True
    titles = {item["entity"]: item for item in trashed["items"]}
    assert set(titles) == {"process", "tool"}                      # 工序 + 它的刀具行都进来了
    assert titles["process"]["deleted_by"] == "admin"
    assert titles["process"]["deleted_reason"] == "客户要求重排工艺"
    assert titles["process"]["title"] == "机加工序-OP10"
    assert titles["process"]["references"] == 1                    # 牵连了 1 条刀具行
    assert titles["tool"]["references"] == 0
    assert store.processes.list_typed(pid) == []                   # 在用行里没有了
    assert store.library_trash()["items"] == []                    # 库里那两张表不受影响

    store.restore_project_process(pid, process["id"])
    assert store.project_trash(pid)["items"] == []
    after = json.dumps(store.get(pid)["state"], ensure_ascii=False, sort_keys=True)
    assert after == before                                         # 读模型（state）逐字节回到删除前
    assert len(store.process_tools.list_typed(pid)) == 1


def test_project_delete_and_restore_are_logical(store):
    """项目"删除" = archived（口径 2 没有彻底删除）：进"已删除项目"，恢复后照旧，两头都留流水。"""
    pid = migrate(store)
    store.delete_project(pid, by="admin", reason="归档一下")
    assert store.list() == []                                      # 默认列表里没有了
    assert [item["id"] for item in store.list(archived=True)] == [pid]

    global_trash = store.library_trash()["items"]
    project_items = [item for item in global_trash if item["entity"] == "project"]
    assert len(project_items) == 1 and project_items[0]["record_id"] == pid

    store.restore_project(pid, by="admin")
    assert [item["id"] for item in store.list()] == [pid]
    labels = [row["label"] for row in store.project_changes(pid)["changes"]]
    assert any("删除项目" in text for text in labels)
    assert any("恢复项目" in text for text in labels)


# ---------------- 2. 基础库 / 字典：逻辑删除 + 复活原行 ----------------


def test_library_row_trash_reports_referencing_projects(store):
    """设备库删一行：回收站里带"被 N 个项目引用"，恢复后 id 不变、工序引用也接着。"""
    pid = migrate(store)
    process = store.processes.list_typed(pid)[0]
    assert process["machine_id"] == "m-alpha"

    store.machines.delete("m-alpha", by="admin", reason="设备淘汰")
    items = {item["record_id"]: item for item in store.library_trash()["items"]}
    assert "m-alpha" in items
    assert items["m-alpha"]["entity"] == "machines"
    assert items["m-alpha"]["references"] == 1                      # 有 1 个项目在用
    assert items["m-alpha"]["deleted_reason"] == "设备淘汰"
    assert store.machines.rows() == []                              # 在用行里没有它了

    # 工序行还在，引用列不动（不是 SET NULL）：恢复之后原样接回去
    row = store.processes.list_typed(pid)[0]
    assert row["machine_id"] == "m-alpha"
    store.restore_trash_row("machines", "m-alpha", by="admin")
    assert store.machines.trash() == []
    assert store.get(pid)["state"]["pr"][0]["mid"] == "m-alpha"


def test_trash_restore_rejects_unknown_table(store):
    """回收站接口的表名白名单：不认识的表一律 422（不能让接口变成任意表操作入口）。"""
    for bad in ("projects", "project_changes", "sqlite_master", "assets"):
        with pytest.raises(HTTPException) as error:
            store.restore_trash_row(bad, "whatever")
        assert error.value.status_code == 422


def test_dictionary_row_revives_on_recreate(store):
    """字典同名重建 = 复活原行（口径 3）：不新建重复行，恢复后引用还在。"""
    store.fixture_centers.create({"name": "自检中心"})
    fixture = store.fixtures.create({"center": "自检中心", "name": "自检夹具",
                                     "price": 5000, "process_days": 3})
    assert fixture["id"]
    store.fixture_centers.delete("自检中心", cascade=True, by="admin", reason="清一批")
    # 字典行与它下面的夹具行都只是打标记，行都还在
    assert [item["name"] for item in store.fixture_centers.trash()] == ["自检中心"]
    assert [item["name"] for item in store.fixtures.trash()] == ["自检夹具"]
    assert store.fixture_centers.count("自检中心") == 0              # 引用计数只算在用行

    revived = store.fixture_centers.create({"name": "自检中心"})
    assert revived.get("revived") is True                          # 复活而不是新建
    assert [item["name"] for item in store.fixture_centers.trash()] == []
    with store.connect() as db:
        total = db.execute("SELECT COUNT(*) FROM fixture_centers WHERE name='自检中心'").fetchone()[0]
    assert total == 1                                              # 没有重复行
    # 夹具行还在回收站里（类别复出不代表数据行自动回来），恢复之后原样接回去
    assert [item["name"] for item in store.fixtures.trash()] == ["自检夹具"]
    store.fixtures.restore(fixture["id"])
    assert store.fixtures.trash() == []
    assert [row["name"] for row in store.fixtures.list_typed()] == ["自检夹具"]


# ---------------- 3. 老库自愈（加列是幂等的，不动数据） ----------------


def test_schema_adds_trash_columns_to_old_database(tmp_path, seed_dir, monkeypatch):
    """老库（没有三列）打开时自动补列：幂等、可空、读模型不变。"""
    monkeypatch.setenv("MACHINING_PROJECT_BUSINESS", str(CHANGES_VERSION))
    data = tmp_path / "legacy" / "machining_dfm"
    store = MachiningDFMStore(data, seed_dir)
    pid = migrate(store)
    before = json.dumps(store.get(pid), ensure_ascii=False, sort_keys=True)
    tables = ("machines", "tools", "fixtures", "gauges",
              "tool_groups", "tool_categories", "fixture_centers", "gauge_categories")
    # 把三列拆掉，造出"老库"形态（连回收站索引一起拆：SQLite 不让删被索引引用的列）
    with store.connect() as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for table in tables:
            db.execute(f"DROP INDEX IF EXISTS idx_machining_dfm_{table}_trash")
            for column in ("deleted_at", "deleted_by", "deleted_reason"):
                db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")

    reopened = MachiningDFMStore(data, seed_dir)                   # 再打开一次 = 自愈
    with reopened.connect() as db:
        for table in tables:
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            assert {"deleted_at", "deleted_by", "deleted_reason"} <= columns
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    after = json.dumps(reopened.get(pid)["state"], ensure_ascii=False, sort_keys=True)
    assert json.loads(after) == json.loads(before)["state"]        # 加列没有动任何数据
    reopened.machines.delete("m-alpha", by="admin")
    assert [item["record_id"] for item in reopened.library_trash()["items"]] == ["m-alpha"]


# ---------------- 4. 迁移工具（干跑，绝不动线上） ----------------


def test_migrate_tool_dry_run(tmp_path, seed_dir, monkeypatch):
    """:文件:`tools/migrate_library_trash.py` 干跑：副本上加列 → 读模型不变 → 回收站可用 → 删/恢复闭环。"""
    import subprocess
    import sys

    monkeypatch.setenv("MACHINING_PROJECT_BUSINESS", str(CHANGES_VERSION))
    data = tmp_path / "live" / "machining_dfm"
    MachiningDFMStore(data, seed_dir)                              # 造出一个有数据的库
    tool = ROOT / "tools" / "migrate_library_trash.py"
    if not tool.exists():
        pytest.skip("迁移工具还没落地")
    result = subprocess.run(
        [sys.executable, str(tool), "--source", str(data)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "读模型" in result.stdout
    assert "干净" in result.stdout or "ok" in result.stdout
    assert "删一行 → 回收站" in result.stdout and "回到原样" in result.stdout
