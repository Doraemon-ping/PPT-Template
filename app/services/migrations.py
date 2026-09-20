# -*- coding: utf-8 -*-
"""建表与幂等迁移：把老库一步步抬到当前结构。

**为什么单独一个模块**：迁移和"平时读写"是两件不同的事 —— 迁移只在开库时跑一遍、
可能重建表、可能改数据，还要能重复跑一万遍结果一样；而项目编排（``app/services/store.py``）
只关心当前结构。分开放，读代码的人一眼能分清"这是历史包袱"还是"这是现在的规则"。

**为什么在 services 层**：迁移要驱动每一个业务域的建表与数据搬迁，天然位于 ``app/domains/``
之上，所以不能放 ``app/db/``（那会让底座层反向依赖业务层）。

**调用方式**：``MachiningDFMStore.__init__`` 在末尾按固定顺序调一遍；每个迁移函数都收 ``store``
（要用它的连接、附件库与各域引擎）。store 侧保留同名薄转发方法，所以调用点一行都不用改。

**幂等性靠什么**：不靠"看数据长什么样"，靠 ``app_settings`` 里的**结构版本号**
（``tool_schema_version`` / ``fixture_schema_version`` / …）与"表在不在"。
版本号到位的库，函数体直接返回，不碰任何数据。

**为什么要备份**：凡是"重建表"的迁移，动手前先整库备份到 ``backups/``
（见 :func:`backup_before_decoupling`）。
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..core.security import DEFAULT_PASSWORDS, PASSWORD_ITERATIONS, password_digest
from ..core.utils import compact_json, stamp
from ..db.schema import (
    FIXTURE_SCHEMA_VERSION,
    GAUGE_SCHEMA_VERSION,
    LEGACY_LIBRARY_TABLES,
    LIBRARY_KEYS,
    MACHINE_SCHEMA_VERSION,
    PROJECT_ARRAYS,
    PROJECT_SCHEMA_VERSION,
    TOOL_SCHEMA_VERSION,
)
from ..domains.fixtures import FIXTURE_CENTER_SEED
from ..domains.gauges import GAUGE_CATEGORY_SEED
from ..domains.machines import resolve_machine_ref


def initialize_shared_data(store) -> None:
    categories = store.bundle.categories()
    with store.connect() as db:
        now = stamp()
        initialized = db.execute(
            "SELECT value_json FROM app_settings WHERE key='libraries_initialized'"
        ).fetchone()
        if initialized is None:
            legacy = db.execute("SELECT state_json FROM projects ORDER BY updated DESC LIMIT 1").fetchone()
            legacy_state = json.loads(legacy["state_json"]) if legacy else {}
            for key, table in LEGACY_LIBRARY_TABLES.items():
                rows = legacy_state.get(key) if isinstance(legacy_state.get(key), list) else store.bundle.legacy_library(key)
                # 夹具/检具已类型化：首次数据写进迁移用的归档表，由迁移搬进新表
                store._replace_library(db, f"{table}_legacy_v1", rows)
            db.execute(
                "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?)",
                ("libraries_initialized", "true", now),
            )
        for role, password in DEFAULT_PASSWORDS.items():
            if db.execute("SELECT 1 FROM auth_settings WHERE role=?", (role,)).fetchone():
                continue
            salt = secrets.token_bytes(16)
            db.execute(
                "INSERT INTO auth_settings(role,salt,password_hash,iterations,updated) VALUES(?,?,?,?,?)",
                (role, salt.hex(), password_digest(password, salt), PASSWORD_ITERATIONS, now),
            )
        defaults = {
            "site_title": "机加 DFM 项目工作台",
            "autosave_ms": 1200,
            "token_secret": secrets.token_hex(32),
            "inspection_categories": categories["icnX"],
            "fixture_categories": categories["fcnX"],
        }
        for key, value in defaults.items():
            db.execute(
                "INSERT OR IGNORE INTO app_settings(key,value_json,updated) VALUES(?,?,?)",
                (key, compact_json(value), now),
            )
        category_version = db.execute(
            "SELECT value_json FROM app_settings WHERE key='category_schema_version'"
        ).fetchone()
        if category_version is None:
            for key, seed_key in {
                "inspection_categories": "icnX",
                "fixture_categories": "fcnX",
            }.items():
                current = db.execute("SELECT value_json FROM app_settings WHERE key=?", (key,)).fetchone()
                existing = json.loads(current["value_json"]) if current else []
                merged = list(dict.fromkeys([*categories[seed_key], *existing]))
                db.execute(
                    "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
                    (key, compact_json(merged), now),
                )
            db.execute(
                "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?)",
                ("category_schema_version", "1", now),
            )

def backup_before_decoupling(store) -> None:
    with store.connect() as db:
        row = db.execute("SELECT state_json FROM projects LIMIT 1").fetchone()
    if not row or not any(key in json.loads(row["state_json"]) for key in LIBRARY_KEYS):
        return
    store._backup("pre-library-decoupling.sqlite3")

def prepare_tool_table(store, db) -> None:
    """建刀具三张表：先字典表（外键目标），再把旧 ``payload_json`` 表改名归档，最后建本体表。

    ``tools.tool_group`` / ``category`` 是指向 ``tool_groups`` / ``tool_categories``
    的文本码外键，所以两张字典表必须先存在并灌好内置项。这一层只处理"表壳"，
    数据搬运与时序在同目录的 ``_migrate_tool_library()``。
    """
    store.tool_dict.schema(db)
    store.tool_dict.seed(db)
    legacy = False
    if store._table_exists(db, "tools"):
        columns = {row[1] for row in db.execute("PRAGMA table_info(tools)")}
        legacy = "payload_json" in columns
    if legacy:
        if store._table_exists(db, "tools_legacy_v1"):
            # 上一轮已经归档过同名旧表：现在这个只是同一份数据的旧壳。
            db.execute("DROP TABLE tools")
        else:
            with store._rename_compat(db):
                db.execute("ALTER TABLE tools RENAME TO tools_legacy_v1")
    store.tools.schema(db)

def migrate_tool_library(store) -> None:
    """把刀具库从 ``tools.payload_json`` 搬进类型化列，并把分类/类型拆到字典表。

    幂等：看 ``app_settings.tool_library_schema_version``；能跑到的三种库形态：
    旧 payload 表（v1）、已类型化但无外键（v2）、当前形态（v3）。
    """
    with store.connect() as db:
        version_row = db.execute(
            "SELECT value_json FROM app_settings WHERE key='tool_library_schema_version'"
        ).fetchone()
        version = int(json.loads(version_row["value_json"])) if version_row else 1
        installed = int(db.execute("SELECT COUNT(*) FROM tools").fetchone()[0])
        has_fk = store._tools_has_dictionary_foreign_keys(db)
        legacy_rows = []
        if store._table_exists(db, "tools_legacy_v1"):
            legacy_rows = db.execute(
                "SELECT payload_json FROM tools_legacy_v1 ORDER BY sort_order,id"
            ).fetchall()
    if version >= TOOL_SCHEMA_VERSION:
        return
    with store.connect() as db:
        store.tool_dict.seed(db)  # 补上版本升级带来的新内置字典项
    if not installed:
        rows: list[dict[str, Any]] = []
        if legacy_rows:
            store._backup("pre-typed-tools.sqlite3")
            for row in legacy_rows:
                try:
                    payload = json.loads(row["payload_json"])
                except (TypeError, ValueError):
                    payload = None
                if isinstance(payload, dict):
                    rows.append(payload)
        else:
            rows = store.bundle.tools()
        if rows:
            store.tools.insert_rows(rows)  # 旧分类码在此归一化，未知码补录进类型字典
    if not has_fk:
        store._backup("pre-tool-dictionaries.sqlite3")
        with store.connect() as db:
            # 先归一化表里已有的旧码并补录未知码，否则外键搬数据时会失败
            store.tools.normalize_row_categories(db=db)
            for row in db.execute("SELECT DISTINCT tool_group FROM tools").fetchall():
                store.tool_dict.register_groups({row[0]: row[0]}, db=db)
            store._rebuild_tools_with_foreign_keys(db)
    with store.connect() as db:
        now = stamp()
        db.execute(
            "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
            ("tool_library_schema_version", compact_json(TOOL_SCHEMA_VERSION), now),
        )

def prepare_named_library(store, db, table: str, library, dictionaries) -> None:
    """建"类别字典表 + 本体表"两件套：旧 ``payload_json`` 表改名归档，本体表带类别外键。"""
    dictionaries.schema(db)
    legacy = False
    if store._table_exists(db, table):
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        legacy = "payload_json" in columns
    if legacy:
        archive = f"{table}_legacy_v1"
        if store._table_exists(db, archive):
            db.execute(f"DROP TABLE {table}")
        else:
            with store._rename_compat(db):
                db.execute(f"ALTER TABLE {table} RENAME TO {archive}")
    library.schema(db)

def prepare_fixture_table(store, db) -> None:
    store._prepare_named_library(db, "fixtures", store.fixtures, store.fixture_centers)

def prepare_gauge_table(store, db) -> None:
    store._prepare_named_library(db, "gauges", store.gauges, store.gauge_categories)

def migrate_named_library(
    store,
    *,
    table: str,
    library,
    dictionaries,
    version_key: str,
    version: int,
    seed_key: str,
    seed_defaults: tuple[str, ...],
    backup_name: str,
    bundle_key: str,
    label: str,
) -> None:
    """把"类别 + 行"从 ``payload_json`` 搬进两张表（夹具体/检具体 + 类别字典）。

    幂等：看 ``app_settings.<version_key>``；归档表是本体的旧壳，类别从
    ``app_settings.<seed_key>``（即页面上一直在用的类别列表）灌种，保持现有显示顺序，
    数据里出现、列表里没有的类别自动补录（``source='legacy'``）。
    """
    with store.connect() as db:
        version_row = db.execute(
            "SELECT value_json FROM app_settings WHERE key=?", (version_key,)
        ).fetchone()
        current = int(json.loads(version_row["value_json"])) if version_row else 1
        installed = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        legacy_rows: list[dict[str, Any]] = []
        if store._table_exists(db, f"{table}_legacy_v1"):
            for row in db.execute(
                f"SELECT payload_json FROM {table}_legacy_v1 ORDER BY sort_order,id"
            ):
                try:
                    payload = json.loads(row["payload_json"])
                except (TypeError, ValueError):
                    payload = None
                if isinstance(payload, dict):
                    legacy_rows.append(payload)
    if current >= version:
        return
    seed_names = store._setting(seed_key) or list(seed_defaults)
    with store.connect() as db:
        dictionaries.seed_rows(db, seed_names)
    if not installed:
        rows = legacy_rows or store.bundle.legacy_library(bundle_key)
        if legacy_rows:
            store._backup(backup_name)
        if rows:
            library.insert_rows(rows)  # 类别在此补录，未知类别不会挡住外键
    with store.connect() as db:
        db.execute(
            "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
            (version_key, compact_json(version), stamp()),
        )

def migrate_fixture_library(store) -> None:
    store._migrate_named_library(
        table="fixtures",
        library=store.fixtures,
        dictionaries=store.fixture_centers,
        version_key="fixture_library_schema_version",
        version=FIXTURE_SCHEMA_VERSION,
        seed_key="fixture_categories",
        seed_defaults=FIXTURE_CENTER_SEED,
        backup_name="pre-typed-fixtures.sqlite3",
        bundle_key="fdb",
        label="夹具",
    )

def migrate_gauge_library(store) -> None:
    store._migrate_named_library(
        table="gauges",
        library=store.gauges,
        dictionaries=store.gauge_categories,
        version_key="gauge_library_schema_version",
        version=GAUGE_SCHEMA_VERSION,
        seed_key="inspection_categories",
        seed_defaults=GAUGE_CATEGORY_SEED,
        backup_name="pre-typed-gauges.sqlite3",
        bundle_key="idb",
        label="检具",
    )

def migrate_machine_library(store) -> None:
    """Move the machine library out of ``equipment.payload_json`` into typed columns.

    Idempotent: drives off ``app_settings.library_schema_version`` and only fills
    an empty ``machines`` table.  Also rewrites project ``pr[].mi`` indexes into
    stable ``pr[].mid`` references so deleting a machine can never re-point an
    existing process.
    """
    with store.connect() as db:
        version_row = db.execute(
            "SELECT value_json FROM app_settings WHERE key='library_schema_version'"
        ).fetchone()
        version = int(json.loads(version_row["value_json"])) if version_row else 1
        installed = int(db.execute("SELECT COUNT(*) FROM machines").fetchone()[0])
        # 老库才有这张旧壳表；已经清过的库没有它（那种库本来也没什么可搬的）
        legacy = db.execute(
            "SELECT id,sort_order,payload_json FROM equipment ORDER BY sort_order,id"
        ).fetchall() if store._table_exists(db, "equipment") else []
    if version >= MACHINE_SCHEMA_VERSION:
        # 已迁移过：空库是用户的真实状态，不能再用初始数据把它填回来。
        return
    if not installed:
        rows: list[dict[str, Any]] = []
        if legacy:
            store._backup("pre-typed-machines.sqlite3")
            for row in legacy:
                try:
                    payload = json.loads(row["payload_json"])
                except (TypeError, ValueError):
                    payload = None
                if isinstance(payload, dict):
                    rows.append(payload)
        else:
            rows = store.bundle.machines()
        if rows:
            store.machines.insert_rows(rows)
    store._rewrite_process_machine_refs()
    with store.connect() as db:
        now = stamp()
        if legacy:
            db.execute("CREATE TABLE IF NOT EXISTS equipment_legacy_v1 AS SELECT * FROM equipment")
        db.execute(
            "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
            ("library_schema_version", compact_json(MACHINE_SCHEMA_VERSION), now),
        )

def rewrite_process_machine_refs(store) -> int:
    ids, fallback = store._machine_refs()
    if not ids:
        return 0
    changed = 0
    with store.connect() as db:
        # 影子副本停写之后 ``revisions`` 可能整张表都不在（口径 6）：有就一起改，没有就跳过
        targets = [("projects", ("id",))]
        if store._table_exists(db, "revisions"):
            targets.append(("revisions", ("project_id", "revision")))
        for table, key_columns in targets:
            for row in db.execute(f"SELECT * FROM {table}").fetchall():
                state = json.loads(row["state_json"])
                processes = state.get("pr")
                if not isinstance(processes, list):
                    continue
                touched = False
                for index, process in enumerate(processes):
                    if not isinstance(process, dict):
                        continue
                    reference = str(process.get("mid") or "").strip()
                    if reference in ids:
                        if "mi" in process:
                            process.pop("mi", None)
                            touched = True
                        continue
                    reference = resolve_machine_ref(process.get("mi"), ids, fallback)
                    if reference:
                        process["mid"] = reference
                        process.pop("mi", None)
                        touched = True
                if not touched:
                    continue
                where = " AND ".join(f"{column}=?" for column in key_columns)
                db.execute(
                    f"UPDATE {table} SET state_json=? WHERE {where}",
                    (compact_json(state), *[row[column] for column in key_columns]),
                )
                changed += 1
    return changed

def migrate_project_snapshots(store) -> None:
    with store.connect() as db:
        rows = db.execute("SELECT id,state_json FROM projects").fetchall()
        for row in rows:
            state = json.loads(row["state_json"])
            if any(key in state for key in LIBRARY_KEYS):
                db.execute("UPDATE projects SET state_json=? WHERE id=?", (store._encode(state), row["id"]))
        if not store._table_exists(db, "revisions"):
            return  # 影子副本已停写（口径 6）：没有这张表就没有要清的库副本
        rows = db.execute("SELECT project_id,revision,state_json FROM revisions").fetchall()
        for row in rows:
            state = json.loads(row["state_json"])
            if any(key in state for key in LIBRARY_KEYS):
                db.execute(
                    "UPDATE revisions SET state_json=? WHERE project_id=? AND revision=?",
                    (store._encode(state), row["project_id"], row["revision"]),
                )

def migrate_project_settings(store) -> None:
    """把 ``projects.state_json`` 里的 ``G`` 拆进 ``project_settings``（幂等）。

    迁移前先备份整库，并把原始 state 归档进 ``projects_legacy_v1``（万一要回滚）。
    项目图片（``pI``/``pf``/``bInspImg``/``fInspImg``）从 data URL 搬进附件库，
    ``G`` 里建模之外的键（``lang`` / ``_vSnap`` / 将来新增的键）进 ``extra_json`` 兜底，
    老读模型 ``G`` 由 ``legacy_g()`` 精确还原，一个键都不变。

    历史版本（``revisions``）的快照**保持原样**：它们是不可变历史，读路径仍按 JSON 还原；
    版本管理重构那一阶段再统一收进 ``project_versions``。
    """
    with store.connect() as db:
        rows = db.execute("SELECT id,name,state_json FROM projects").fetchall()
    pending: list[tuple[Any, dict[str, Any]]] = []
    for row in rows:
        if store.settings.exists(row["id"]):
            continue
        try:
            state = json.loads(row["state_json"])
        except (TypeError, ValueError):
            continue
        if isinstance(state, dict):
            pending.append((row, state))
    if not pending:
        return
    store._backup("pre-project-settings.sqlite3")
    with store.connect() as db:
        # 归档表**只在真有东西要归档时才建**：没旧数据可搬的库（比如已经迁完、
        # 影子副本也清掉了的库）不该因为"迁移程序跑过一遍"就多出一张空表。
        db.execute(
            "CREATE TABLE IF NOT EXISTS projects_legacy_v1("
            "id TEXT PRIMARY KEY,name TEXT NOT NULL DEFAULT '',"
            "state_json TEXT NOT NULL,archived_at TEXT NOT NULL)"
        )
        for row, state in pending:
            db.execute(
                "INSERT OR REPLACE INTO projects_legacy_v1(id,name,state_json,archived_at) VALUES(?,?,?,?)",
                (row["id"], row["name"], row["state_json"], stamp()),
            )
            arrays = {key: state.get(key, []) for key in PROJECT_ARRAYS}
            db.execute("UPDATE projects SET state_json=? WHERE id=?", (compact_json(arrays), row["id"]))
    for row, state in pending:
        general = state.get("G") if isinstance(state.get("G"), dict) else {}
        general = {key: value for key, value in general.items() if key not in LIBRARY_KEYS}
        general.pop("icnX", None)
        general.pop("fcnX", None)
        # lenient：旧数据里超范围/非数字的取值不阻断迁移，原值进 extra_json 兜底
        store.settings.apply_state(row["id"], {"G": general}, lenient=True)
    with store.connect() as db:
        db.execute(
            "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
            ("project_schema_version", compact_json(PROJECT_SCHEMA_VERSION), stamp()),
        )

def ensure_seed_project(store) -> None:
    with store.connect() as db:
        if db.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
            return
    state = store.bundle.project()
    part = str(state.get("G", {}).get("part") or "原文件数据").strip()
    store.create(f"原文件集成 · {part}", state)
