"""Dedicated, data-decoupled backend for the machining DFM application.

Storage layout (one SQLite file + an asset directory):

* ``projects`` / ``revisions`` — project owned data (``G`` / ``pr`` / ``is`` / ``vh``)
* ``machines`` — the machine library, one typed column per page field
* ``tools`` / ``fixtures`` / ``gauges`` — libraries still stored as JSON payloads
  (next refactor targets, see ``docs/MACHINING_LIBRARY_REFACTOR.md``)
* ``assets`` — metadata of photos/documents whose bytes live on disk

Processes reference machines through ``pr[].mid`` (a stable id).  The legacy
``pr[].mi`` index and the legacy short-key machine rows are still produced on the
read path so the original renderer and the PPT data-source contract keep working.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .machining_assets import DOCUMENT_MIMES, IMAGE_MIMES, AssetStore
from .machining_fixtures import (
    FIXTURE_CENTER_SEED,
    FixtureCenters,
    FixtureLibrary,
    field_headers as fixture_field_headers,
)
from .machining_gauges import (
    GAUGE_CATEGORY_SEED,
    GaugeCategories,
    GaugeLibrary,
    field_headers as gauge_field_headers,
)
from .machining_library import quote_identifier
from .machining_issue import (
    ISSUE_FIELDS,
    ISSUE_STATUSES,
    ISSUE_TABLE,
    ISSUE_TYPES,
    ISSUE_VERSION,
    ProjectIssues,
    apply_issue_split,
    legacy_issues,
)
from .machining_machines import MachineLibrary, field_headers
from .machining_project import ProjectSettings, SETTINGS_FIELDS
from .machining_changes import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_PHOTO,
    ACTION_SAVE,
    ACTION_UPDATE,
    CHANGES_TABLE,
    CHANGES_VERSION,
    ENTITY_PROJECT,
    ENTITY_SETTINGS,
    ProjectChanges,
)
from .machining_history import (
    HISTORY_TABLE,
    HISTORY_VERSION,
    KIND_HISTORY,
    LEGACY_HISTORY_KEYS,
    ProjectVersions,
    history_listing,
    history_payload,
    insert_save_row,
    json_text,
    legacy_history,
    light_view,
    new_history_values,
    save_row_id,
    save_row_values,
    split_history_rows,
    version_listing,
    virtual_history_listing,
)
from .machining_selection import (
    FIXTURE_TABLE,
    GAUGE_TABLE,
    KIND_FIXTURE,
    KIND_GAUGE,
    LEGACY_SELECTION_TABLE,
    SELECTION_ARRAY_KEYS,
    SELECTION_KINDS,
    SELECTION_TABLE_NAMES,
    SELECTION_VERSION,
    KIND_SPECS,
    ProjectSelections,
    apply_selection_split,
    copy_legacy_rows,
    legacy_selection_arrays,
    selection_listing,
    selection_payload,
    selections_listing,
    spec_for,
    split_selections,
)
from .machining_process import (
    BUSINESS_VERSION,
    BUSINESS_VERSION_KEY,
    NC_DEFAULTS,
    NC_KEYS,
    PROCESS_FIELDS,
    SNAPSHOT_KEYS,
    TOOL_FIELDS,
    ProjectProcesses,
    ProjectProcessTools,
    apply_split,
    js_number,
    legacy_processes,
)
from .machining_seed import SeedBundle
from .machining_tools import ToolDictionary, ToolLibrary, tool_derived_headers, tool_field_headers

PROJECT_ARRAYS = ("pr", "is", "vh")
# 旧载荷表：只在首次建库/迁移时作为数据来源，迁完就归档成 *_legacy_v1。
LEGACY_LIBRARY_TABLES = {"fdb": "fixtures", "idb": "gauges"}
# 组合视图里对外暴露的基础库键，四个库都已独立成表。
LIBRARY_KEYS = ("mdb", "tdb", "fdb", "idb")
MACHINE_SCHEMA_VERSION = 2
TOOL_SCHEMA_VERSION = 3
FIXTURE_SCHEMA_VERSION = 2
GAUGE_SCHEMA_VERSION = 2
# 项目业务数据：项目信息（G 的建模字段）已搬进 project_settings 表。
PROJECT_SCHEMA_VERSION = 1
MAX_STATE_BYTES = 32 * 1024 * 1024
PASSWORD_ITERATIONS = 260_000
DEFAULT_PASSWORDS = {"process": "TP123456", "admin": "TP23456"}

#: 项目信息各字段的中文名（变更流水写"日可动时间 22→20"用）
SETTINGS_FIELD_LABELS = {field.key: field.label for field in SETTINGS_FIELDS}


def _display_value(value: Any) -> str:
    """变更流水里怎么展示一个值（数与 JS 同口径、空说人话、文本截断）。"""
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None or value == "":
        return "（空）"
    if isinstance(value, (int, float)):
        return str(js_number(value))
    text = str(value).replace("\n", " ").strip()
    return text[:60] + "…" if len(text) > 60 else text

#: 旧 ``revisions`` 表（整份快照一版一行）。**只在"版本履历还没落表"时才建**：
#: 阶段 3a 之后保存版本进了 ``project_versions``，``revisions`` 就只剩"影子副本"这一个作用，
#: 而影子副本只在还能回滚到旧路径（开关 < 4）时才有意义。开关到 4 之后表不建、行不写，
#: 库里每种数据只有一份（口径 6：哪一级落表了，那一级的影子副本就停写）。
LEGACY_REVISIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS revisions(
    project_id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL,
    state_json TEXT NOT NULL, created TEXT NOT NULL,
    PRIMARY KEY(project_id, revision),
    FOREIGN KEY(project_id) REFERENCES projects(id)
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(
    id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL,
    state_json TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0
);
-- 设备库的旧壳 ``equipment``（id/sort_order/payload_json/updated）**不再创建**：
-- 设备已经类型化进 ``machines``，那张表只剩 288 KB 没人读的重复数据（含内联图片），
-- 2026-09-18 已随旧副本一起清掉。老库（``library_schema_version`` 还没到 2）里如果还有它，
-- ``_migrate_machine_library()`` 照旧会读它当搬迁来源（见那里的 ``_table_exists`` 判断）。
CREATE TABLE IF NOT EXISTS fixtures(
    id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL,
    payload_json TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gauges(
    id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL,
    payload_json TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_settings(
    role TEXT PRIMARY KEY, salt TEXT NOT NULL, password_hash TEXT NOT NULL,
    iterations INTEGER NOT NULL, updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings(
    key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_machining_dfm_projects_archived_updated
    ON projects(archived, updated DESC);
"""


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _resolve_machine_ref(index: Any, machine_ids: list[str], fallback: str) -> str:
    """Legacy ``pr[].mi`` index → stable machine id (fallback machine when unknown)."""
    try:
        position = int(index)
    except (TypeError, ValueError):
        position = -1
    if 0 <= position < len(machine_ids):
        return machine_ids[position]
    return fallback


def _project_process(row: Any, machine_ids: list[str], fallback: str) -> Any:
    """Normalise one process row: keep ``mid``, convert a legacy ``mi`` when possible."""
    if not isinstance(row, dict):
        return row
    process = dict(row)
    reference = str(process.get("mid") or "").strip()[:64]
    if not reference:
        reference = _resolve_machine_ref(process.get("mi"), machine_ids, fallback)
    if reference:
        process["mid"] = reference
        process.pop("mi", None)
    return process


def _project_state(state: dict[str, Any], machine_ids: list[str] | None = None, fallback: str = "") -> dict[str, Any]:
    """Validate and return only project-owned data, excluding shared libraries."""
    if not isinstance(state, dict):
        raise HTTPException(422, "项目数据必须是 JSON 对象")
    if not isinstance(state.get("G"), dict):
        raise HTTPException(422, "项目数据缺少 G 项目信息")
    project_globals = dict(state["G"])
    project_globals.pop("icnX", None)
    project_globals.pop("fcnX", None)
    result = {"G": project_globals}
    for key in PROJECT_ARRAYS:
        value = state.get(key, [])
        if not isinstance(value, list):
            raise HTTPException(422, f"项目数据中的 {key} 必须是数组")
        result[key] = value
    ids = list(machine_ids or [])
    result["pr"] = [_project_process(row, ids, fallback) for row in result["pr"]]
    return result


def _encode_project_state(state: dict[str, Any], machine_ids: list[str] | None = None, fallback: str = "") -> str:
    try:
        payload = _compact(_project_state(state, machine_ids, fallback))
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"项目数据无法序列化：{exc}") from exc
    if len(payload.encode("utf-8")) > MAX_STATE_BYTES:
        raise HTTPException(413, "项目数据超过 32 MB，请压缩或删除过大的项目图片后再保存")
    return payload


def _split_project_state(
    state: dict[str, Any], machine_ids: list[str] | None = None, fallback: str = ""
) -> tuple[dict[str, Any], dict[str, Any]]:
    """把整份 ``state`` 拆成 ``(项目信息 G, 只剩业务数组的 state)``。

    项目信息（客户/零件/产能/尺寸/检具报价/项目图片）从此归 ``project_settings`` 表，
    ``projects.state_json`` 只留 ``pr`` / ``is`` / ``vh`` 三份业务数组。
    """
    validated = _project_state(state, machine_ids, fallback)
    general = validated.pop("G")
    return general, validated


def _password_digest(password: str, salt: bytes, iterations: int = PASSWORD_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


class _InlineImage:
    """整份保存里碰到的内联图片占位（先认出来，落成附件之后再换回附件地址）。"""

    __slots__ = ("kind", "value", "url")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value
        self.url: str | None = None


#: 内联图片按它所在的键决定存成哪一类附件（只影响附件目录分类与显示名）。
INLINE_IMAGE_KINDS = {
    "pI": "project_photo", "pf": "project_photo",
    "bInspImg": "inspection_photo", "fInspImg": "inspection_photo",
    "cI": "process_photo", "fi": "tool_photo", "img": "tool_photo",
    "bI": "issue_photo", "aI": "issue_photo",
}
DEFAULT_INLINE_KIND = "project_photo"


def _collect_inline_images(node: Any, holders: list["_InlineImage"], key: str = "") -> Any:
    """把树里所有内联图片换成占位对象（原地留位置），占位收集进 ``holders``。"""
    if isinstance(node, dict):
        return {name: _collect_inline_images(value, holders, name)
                for name, value in node.items()}
    if isinstance(node, list):
        return [_collect_inline_images(value, holders, key) for value in node]
    if isinstance(node, str) and node.startswith("data:image/"):
        holder = _InlineImage(INLINE_IMAGE_KINDS.get(key, DEFAULT_INLINE_KIND), node)
        holders.append(holder)
        return holder
    return node


def _resolve_inline_images(node: Any) -> Any:
    """占位对象换回附件地址（附件在上面那一步已经落好了）。"""
    if isinstance(node, _InlineImage):
        return node.url or ""
    if isinstance(node, dict):
        return {name: _resolve_inline_images(value) for name, value in node.items()}
    if isinstance(node, list):
        return [_resolve_inline_images(value) for value in node]
    return node


class ProjectWrite(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    state: dict[str, Any]
    revision: int | None = None


class LibraryWrite(BaseModel):
    # ``mdb`` / ``tdb`` 已独立成表：仍然接受旧页面的整体保存，映射到类型化表。
    mdb: list[dict[str, Any]] | None = None
    tdb: list[dict[str, Any]] | None = None
    fdb: list[dict[str, Any]]
    idb: list[dict[str, Any]]
    icnX: list[str] = Field(default_factory=list)
    fcnX: list[str] = Field(default_factory=list)


class LoginRequest(BaseModel):
    role: str
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    role: str
    password: str = Field(min_length=6, max_length=256)


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    """回收站每条记一句人话标题：按候选键取第一个非空值。"""
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value[:60]
    return ""


class SettingsWrite(BaseModel):
    site_title: str = Field(min_length=1, max_length=100)
    autosave_ms: int = Field(ge=500, le=10_000)


# ---------------- 导出文件包（阶段 5 · 口径 §7.0） ----------------
# 读模型里"指向附件的字段"全是 ``/api/machining-dfm/assets/<id>`` 相对地址（库里 0 行 base64）。
# 出包时把它们换成**包内相对路径** ``assets/<id>.<ext>``，并把真引用到的附件原始字节一起打进去：
# 这份包脱离服务也能看懂、能存档、能转发（便携单文件 HTML 已按 §7.0 退休）。

#: 包格式标识与版本（写进 ``project.json`` 的顶层 ``_export`` 块）
PACKAGE_FORMAT = "machining-dfm-package"
PACKAGE_VERSION = 1
#: README.txt 里写明"这份包由哪个服务哪个版本导出"
PACKAGE_SERVICE = "机加 DFM 项目工作台（app/services/machining.py · FastAPI · 契约 1.0）"
#: 只在**整个字段值**就是一个附件地址时才算引用（形状由 check_export_assets.mjs 钉住）
ASSET_URL_PATTERN = re.compile(r"^/api/machining-dfm/assets/([A-Za-z0-9]+)(?:[?#].*)?$")
#: 文件名里不能出现的字符（Windows 更严：\/:*?"<>| 与控制字符）
FILENAME_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _package_extension(record: dict[str, Any]) -> str:
    """``assets/<id>.<ext>`` 的后缀：先看 ``assets.path``，取不到就用 ``mime`` 推。"""
    suffix = Path(str(record.get("path") or "")).suffix
    if suffix and re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix):
        return suffix.lower()
    mime = str(record.get("mime") or "").split(";", 1)[0].strip().lower()
    for table in (IMAGE_MIMES, DOCUMENT_MIMES):
        if mime in table:
            return table[mime]
    return ".bin"


def _package_filename(name: str) -> str:
    """``DFM_<项目名>.zip``：清掉非法字符、空白折成 ``_``、限长（空名兜底 ``project``）。"""
    cleaned = FILENAME_ILLEGAL.sub("_", str(name or ""))
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    cleaned = cleaned.strip("._") or "project"
    return f"DFM_{cleaned[:60]}.zip"


def _content_disposition(filename: str) -> str:
    """RFC 6266：ASCII 兜底 ``filename`` + UTF-8 的 ``filename*``（响应头不能直接放中文）。"""
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.encode("ascii", "replace").decode("ascii"))
    fallback = re.sub(r"_{2,}", "_", fallback).strip("_") or "DFM_project.zip"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _iter_asset_ids(node: Any) -> list[str]:
    """读模型里所有附件引用（按出现顺序去重），路径不限层级。"""
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            hit = ASSET_URL_PATTERN.match(value)
            if hit and hit.group(1) not in found:
                found.append(hit.group(1))
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(node)
    return found


def _rewrite_package_assets(node: Any, mapping: dict[str, str]) -> Any:
    """深拷贝读模型，把附件地址就地换成包内相对路径（``mapping`` 里没有的原样留着）。"""
    if isinstance(node, str):
        hit = ASSET_URL_PATTERN.match(node)
        return mapping[hit.group(1)] if hit and hit.group(1) in mapping else node
    if isinstance(node, list):
        return [_rewrite_package_assets(item, mapping) for item in node]
    if isinstance(node, dict):
        return {key: _rewrite_package_assets(value, mapping) for key, value in node.items()}
    return node


class MachiningDFMStore:
    """Projects, shared master data, and backend auth in one isolated SQLite DB."""

    def __init__(self, root: Path, seed: Path):
        self.root = Path(root)
        self.seed_file = Path(seed)
        self.bundle = SeedBundle(self.seed_file)
        self.root.mkdir(parents=True, exist_ok=True)
        self.backup_dir = self.root / "backups"
        self.db_path = self.root / "machining_dfm.sqlite3"
        self.assets = AssetStore(self.root, self.connect)
        self.settings = ProjectSettings(self.connect, self.assets)
        self.processes = ProjectProcesses(self.connect, self.assets)
        self.process_tools = ProjectProcessTools(self.connect, self.assets)
        self.issues = ProjectIssues(self.connect, self.assets)
        self.selections = ProjectSelections(self.connect, self.assets)
        # 名字带 _table：`versions()` 是方法名，不能重名（与 project_issues_enabled 同一个坑）
        self.version_table = ProjectVersions(self.connect, self.assets)
        # 变更流水（3b）：名字同样带 _table，`project_changes()` 是方法名
        self.change_table = ProjectChanges(self.connect, self.assets)
        self.machines = MachineLibrary(self.connect, self.assets)
        self.tool_dict = ToolDictionary(self.connect)
        self.tools = ToolLibrary(self.connect, self.assets, self.tool_dict)
        self.fixture_centers = FixtureCenters(self.connect)
        self.fixtures = FixtureLibrary(self.connect, self.assets, self.fixture_centers)
        self.gauge_categories = GaugeCategories(self.connect)
        self.gauges = GaugeLibrary(self.connect, self.assets, self.gauge_categories)
        # 删类别时连带删数据（并回收附件），由字典表调用回本体库
        self.fixture_centers.cascade = self.fixtures.delete_by_center
        self.gauge_categories.cascade = self.gauges.delete_by_category
        with self.connect() as db:
            db.executescript(SCHEMA)
            self.assets.schema(db)
            self.settings.schema(db)
            self.machines.schema(db)
            self._prepare_tool_table(db)
            self._prepare_fixture_table(db)
            self._prepare_gauge_table(db)
        # 工序落表是**显式开关**（``app_settings.project_business_version`` 或
        # ``MACHINING_PROJECT_BUSINESS=2``）：没打开就不建表、读模型照旧走 state_json，
        # 代码可以先上线，数据迁移由 tools/migrate_project_processes.py 单独执行。
        # 版本号是**递增的能力级别**：≥1 工序落表，≥2 再加问题清单（2a）……
        self.business_version = self._business_version()
        self.project_business = self.business_version >= BUSINESS_VERSION
        # 名字带上 _enabled：project_issues() 是方法名，不能重名
        self.project_issues_enabled = self.business_version >= ISSUE_VERSION
        # 选型报价（2b）：外键指向夹具/检具库与类别字典，所以它一定晚于这两张字典表存在
        self.selections_enabled = self.business_version >= SELECTION_VERSION
        # 版本履历（3a）：保存版本（原 revisions）+ 页面版本履历（原 state_json.vh）合成一张表
        self.history_enabled = self.business_version >= HISTORY_VERSION
        # 变更流水（3b）：记"这一次改动到底改了什么"（外键指向上面几张业务表的行）
        self.changes_enabled = self.business_version >= CHANGES_VERSION
        #: **影子副本开关**（口径 6）：版本履历落表之后，旧 ``revisions`` 表与
        #: ``projects.state_json`` 里的三份业务数组都不再需要——它们在表里已经有权威一份。
        #: 还在用旧路径（开关 < 4）时照旧维护，回滚只需要改版本键。
        self.legacy_shadow = not self.history_enabled
        if self.legacy_shadow:
            with self.connect() as db:
                # 老库上这张表本来就有；新库（开关还没到 4）也得建出来，迁移工具要读它
                db.executescript(LEGACY_REVISIONS_SCHEMA)
        #: 本次改动攒下来的流水草稿：在 ``_bump_project`` 那个事务里统一落库（挂上版本行 id）
        self._pending_changes: list[dict[str, Any]] = []
        if self.project_business:
            with self.connect() as db:
                self.processes.schema(db)
                self.process_tools.schema(db)
        if self.project_issues_enabled:
            # 问题清单有指向工序的外键，所以它一定晚于工序表存在
            with self.connect() as db:
                self.issues.schema(db)
        if self.selections_enabled:
            with self.connect() as db:
                self.selections.schema(db)
        if self.history_enabled:
            # 版本履历表只外键指向 projects，没有别的依赖
            with self.connect() as db:
                self.version_table.schema(db)
        if self.changes_enabled:
            # 变更流水外键指向工序/刀具行/问题/选型/版本行，所以它一定晚于上面这些表
            with self.connect() as db:
                self.change_table.schema(db)
        # 行级写入的出口：引擎只管交草稿，落库统一在 _bump_project 的事务里（见 machining_changes）
        for table in (self.processes, self.process_tools, self.issues,
                      self.selections.fixtures, self.selections.gauges, self.version_table):
            table.change_sink = self._note_change
        self._backup_before_decoupling()
        self._initialize_shared_data()
        self._migrate_machine_library()
        self._migrate_tool_library()
        self._migrate_fixture_library()
        self._migrate_gauge_library()
        self._migrate_project_snapshots()
        self._migrate_project_settings()
        self.ensure_seed_project()
        self.assets.prune_orphans()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def _rename_compat(self, db):
        """重建/归档某张表时，别让 SQLite 顺手改写**别的表**里指向它的外键。

        基础库的迁移都是"改成同名新表"（改名 → 建新表 → 搬数据 → 删旧表）。
        现在项目侧的表会真外键指向 ``tools``/``fixtures``/``gauges``/``machines``，
        改名那一步默认会把子表里的 ``REFERENCES tools(id)`` 一起改写成
        ``REFERENCES tools_pre_foreign_keys(id)``，删掉旧表后子表的外键就指到不存在的表。
        ``legacy_alter_table=ON`` 关掉这个改写（改名只改名）。
        """
        previous = int(db.execute("PRAGMA legacy_alter_table").fetchone()[0])
        db.execute("PRAGMA legacy_alter_table=ON")
        try:
            yield
        finally:
            db.execute(f"PRAGMA legacy_alter_table={1 if previous else 0}")

    def _business_version(self) -> int:
        """项目业务数据落到表里的**能力级别**（口径：显式开关，默认 0 = 全关）。

        打开方式二选一：

        * ``app_settings.project_business_version``：≥1 工序落表、≥2 再加问题清单……
          （由 ``tools/migrate_*.py --apply`` 写入）；
        * 环境变量 ``MACHINING_PROJECT_BUSINESS``：给整数就用整数（测试/演练传 2），
          给 ``true``/``yes``/``on`` 当 1。

        每个请求都会新造 store，所以迁移完**不用重启服务**，下一个请求就切过来。
        """
        raw = str(os.environ.get("MACHINING_PROJECT_BUSINESS") or "").strip().lower()
        if raw:
            try:
                return int(raw)
            except ValueError:
                if raw in {"true", "yes", "on"}:
                    return BUSINESS_VERSION
        try:
            with self.connect() as db:
                row = db.execute(
                    "SELECT value_json FROM app_settings WHERE key=?", (BUSINESS_VERSION_KEY,)
                ).fetchone()
        except sqlite3.Error:
            return 0
        if row is None:
            return 0
        try:
            return int(json.loads(row["value_json"]))
        except (TypeError, ValueError):
            return 0

    def _backup(self, name: str) -> Path | None:
        backup = self.backup_dir / name
        if not self.db_path.is_file() or backup.exists():
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        source, target = sqlite3.connect(self.db_path), sqlite3.connect(backup)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return backup

    def _backup_before_decoupling(self) -> None:
        with self.connect() as db:
            row = db.execute("SELECT state_json FROM projects LIMIT 1").fetchone()
        if not row or not any(key in json.loads(row["state_json"]) for key in LIBRARY_KEYS):
            return
        self._backup("pre-library-decoupling.sqlite3")

    # ---------------- first run / migration ----------------

    def _initialize_shared_data(self) -> None:
        categories = self.bundle.categories()
        with self.connect() as db:
            now = _stamp()
            initialized = db.execute(
                "SELECT value_json FROM app_settings WHERE key='libraries_initialized'"
            ).fetchone()
            if initialized is None:
                legacy = db.execute("SELECT state_json FROM projects ORDER BY updated DESC LIMIT 1").fetchone()
                legacy_state = json.loads(legacy["state_json"]) if legacy else {}
                for key, table in LEGACY_LIBRARY_TABLES.items():
                    rows = legacy_state.get(key) if isinstance(legacy_state.get(key), list) else self.bundle.legacy_library(key)
                    # 夹具/检具已类型化：首次数据写进迁移用的归档表，由迁移搬进新表
                    self._replace_library(db, f"{table}_legacy_v1", rows)
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
                    (role, salt.hex(), _password_digest(password, salt), PASSWORD_ITERATIONS, now),
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
                    (key, _compact(value), now),
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
                        (key, _compact(merged), now),
                    )
                db.execute(
                    "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?)",
                    ("category_schema_version", "1", now),
                )

    def _machine_refs(self) -> tuple[list[str], str]:
        ids = self.machines.ids()
        fallback = self.machines.default_ref() or (ids[-1] if ids else "")
        return ids, fallback

    # ---------------- 刀具库：旧表换壳 + 迁移 ----------------

    @staticmethod
    def _table_exists(db, name: str) -> bool:
        return db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    def _prepare_tool_table(self, db) -> None:
        """建刀具三张表：先字典表（外键目标），再把旧 ``payload_json`` 表改名归档，最后建本体表。

        ``tools.tool_group`` / ``category`` 是指向 ``tool_groups`` / ``tool_categories``
        的文本码外键，所以两张字典表必须先存在并灌好内置项。这一层只处理"表壳"，
        数据搬运与时序在同目录的 ``_migrate_tool_library()``。
        """
        self.tool_dict.schema(db)
        self.tool_dict.seed(db)
        legacy = False
        if self._table_exists(db, "tools"):
            columns = {row[1] for row in db.execute("PRAGMA table_info(tools)")}
            legacy = "payload_json" in columns
        if legacy:
            if self._table_exists(db, "tools_legacy_v1"):
                # 上一轮已经归档过同名旧表：现在这个只是同一份数据的旧壳。
                db.execute("DROP TABLE tools")
            else:
                with self._rename_compat(db):
                    db.execute("ALTER TABLE tools RENAME TO tools_legacy_v1")
        self.tools.schema(db)

    def _tools_has_dictionary_foreign_keys(self, db) -> bool:
        """只看指向两张字典表的外键 —— 旧表本来就有指向 assets 的图片外键，不能作为判据。"""
        targets = {(row[2], row[3]) for row in db.execute("PRAGMA foreign_key_list(tools)")}
        return ("tool_groups", "tool_group") in targets and ("tool_categories", "category") in targets

    def _rebuild_tools_with_foreign_keys(self, db) -> None:
        """把没有外键的 ``tools`` 表重建为带外键的版本（SQLite 不能 ALTER 加外键）。

        步骤：改名 → 建新表 → 搬数据 → 删旧表（连带旧索引）→ 重建索引。
        """
        index_names = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='tools' AND sql IS NOT NULL"
        )]
        with self._rename_compat(db):
            db.execute("ALTER TABLE tools RENAME TO tools_pre_foreign_keys")
        for name in index_names:  # 索引名被旧表占着，先删掉，搬完数据再按新表重建
            db.execute(f"DROP INDEX IF EXISTS {quote_identifier(name)}")
        db.executescript(self.tools.ddl())
        columns = ",".join(f'"{column}"' for column in self.tools.insert_columns)
        db.execute(
            f"INSERT INTO tools({columns}) SELECT {columns} FROM tools_pre_foreign_keys"
        )
        db.execute("DROP TABLE tools_pre_foreign_keys")
        self.tools.create_indexes(db)

    def _migrate_tool_library(self) -> None:
        """把刀具库从 ``tools.payload_json`` 搬进类型化列，并把分类/类型拆到字典表。

        幂等：看 ``app_settings.tool_library_schema_version``；能跑到的三种库形态：
        旧 payload 表（v1）、已类型化但无外键（v2）、当前形态（v3）。
        """
        with self.connect() as db:
            version_row = db.execute(
                "SELECT value_json FROM app_settings WHERE key='tool_library_schema_version'"
            ).fetchone()
            version = int(json.loads(version_row["value_json"])) if version_row else 1
            installed = int(db.execute("SELECT COUNT(*) FROM tools").fetchone()[0])
            has_fk = self._tools_has_dictionary_foreign_keys(db)
            legacy_rows = []
            if self._table_exists(db, "tools_legacy_v1"):
                legacy_rows = db.execute(
                    "SELECT payload_json FROM tools_legacy_v1 ORDER BY sort_order,id"
                ).fetchall()
        if version >= TOOL_SCHEMA_VERSION:
            return
        with self.connect() as db:
            self.tool_dict.seed(db)  # 补上版本升级带来的新内置字典项
        if not installed:
            rows: list[dict[str, Any]] = []
            if legacy_rows:
                self._backup("pre-typed-tools.sqlite3")
                for row in legacy_rows:
                    try:
                        payload = json.loads(row["payload_json"])
                    except (TypeError, ValueError):
                        payload = None
                    if isinstance(payload, dict):
                        rows.append(payload)
            else:
                rows = self.bundle.tools()
            if rows:
                self.tools.insert_rows(rows)  # 旧分类码在此归一化，未知码补录进类型字典
        if not has_fk:
            self._backup("pre-tool-dictionaries.sqlite3")
            with self.connect() as db:
                # 先归一化表里已有的旧码并补录未知码，否则外键搬数据时会失败
                self.tools.normalize_row_categories(db=db)
                for row in db.execute("SELECT DISTINCT tool_group FROM tools").fetchall():
                    self.tool_dict.register_groups({row[0]: row[0]}, db=db)
                self._rebuild_tools_with_foreign_keys(db)
        with self.connect() as db:
            now = _stamp()
            db.execute(
                "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
                ("tool_library_schema_version", _compact(TOOL_SCHEMA_VERSION), now),
            )

    def _prepare_named_library(self, db, table: str, library, dictionaries) -> None:
        """建"类别字典表 + 本体表"两件套：旧 ``payload_json`` 表改名归档，本体表带类别外键。"""
        dictionaries.schema(db)
        legacy = False
        if self._table_exists(db, table):
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            legacy = "payload_json" in columns
        if legacy:
            archive = f"{table}_legacy_v1"
            if self._table_exists(db, archive):
                db.execute(f"DROP TABLE {table}")
            else:
                with self._rename_compat(db):
                    db.execute(f"ALTER TABLE {table} RENAME TO {archive}")
        library.schema(db)

    def _prepare_fixture_table(self, db) -> None:
        self._prepare_named_library(db, "fixtures", self.fixtures, self.fixture_centers)

    def _prepare_gauge_table(self, db) -> None:
        self._prepare_named_library(db, "gauges", self.gauges, self.gauge_categories)

    def _migrate_named_library(
        self,
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
        with self.connect() as db:
            version_row = db.execute(
                "SELECT value_json FROM app_settings WHERE key=?", (version_key,)
            ).fetchone()
            current = int(json.loads(version_row["value_json"])) if version_row else 1
            installed = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            legacy_rows: list[dict[str, Any]] = []
            if self._table_exists(db, f"{table}_legacy_v1"):
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
        seed_names = self._setting(seed_key) or list(seed_defaults)
        with self.connect() as db:
            dictionaries.seed_rows(db, seed_names)
        if not installed:
            rows = legacy_rows or self.bundle.legacy_library(bundle_key)
            if legacy_rows:
                self._backup(backup_name)
            if rows:
                library.insert_rows(rows)  # 类别在此补录，未知类别不会挡住外键
        with self.connect() as db:
            db.execute(
                "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
                (version_key, _compact(version), _stamp()),
            )

    def _migrate_fixture_library(self) -> None:
        self._migrate_named_library(
            table="fixtures",
            library=self.fixtures,
            dictionaries=self.fixture_centers,
            version_key="fixture_library_schema_version",
            version=FIXTURE_SCHEMA_VERSION,
            seed_key="fixture_categories",
            seed_defaults=FIXTURE_CENTER_SEED,
            backup_name="pre-typed-fixtures.sqlite3",
            bundle_key="fdb",
            label="夹具",
        )

    def _migrate_gauge_library(self) -> None:
        self._migrate_named_library(
            table="gauges",
            library=self.gauges,
            dictionaries=self.gauge_categories,
            version_key="gauge_library_schema_version",
            version=GAUGE_SCHEMA_VERSION,
            seed_key="inspection_categories",
            seed_defaults=GAUGE_CATEGORY_SEED,
            backup_name="pre-typed-gauges.sqlite3",
            bundle_key="idb",
            label="检具",
        )

    def _migrate_machine_library(self) -> None:
        """Move the machine library out of ``equipment.payload_json`` into typed columns.

        Idempotent: drives off ``app_settings.library_schema_version`` and only fills
        an empty ``machines`` table.  Also rewrites project ``pr[].mi`` indexes into
        stable ``pr[].mid`` references so deleting a machine can never re-point an
        existing process.
        """
        with self.connect() as db:
            version_row = db.execute(
                "SELECT value_json FROM app_settings WHERE key='library_schema_version'"
            ).fetchone()
            version = int(json.loads(version_row["value_json"])) if version_row else 1
            installed = int(db.execute("SELECT COUNT(*) FROM machines").fetchone()[0])
            # 老库才有这张旧壳表；已经清过的库没有它（那种库本来也没什么可搬的）
            legacy = db.execute(
                "SELECT id,sort_order,payload_json FROM equipment ORDER BY sort_order,id"
            ).fetchall() if self._table_exists(db, "equipment") else []
        if version >= MACHINE_SCHEMA_VERSION:
            # 已迁移过：空库是用户的真实状态，不能再用初始数据把它填回来。
            return
        if not installed:
            rows: list[dict[str, Any]] = []
            if legacy:
                self._backup("pre-typed-machines.sqlite3")
                for row in legacy:
                    try:
                        payload = json.loads(row["payload_json"])
                    except (TypeError, ValueError):
                        payload = None
                    if isinstance(payload, dict):
                        rows.append(payload)
            else:
                rows = self.bundle.machines()
            if rows:
                self.machines.insert_rows(rows)
        self._rewrite_process_machine_refs()
        with self.connect() as db:
            now = _stamp()
            if legacy:
                db.execute("CREATE TABLE IF NOT EXISTS equipment_legacy_v1 AS SELECT * FROM equipment")
            db.execute(
                "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
                ("library_schema_version", _compact(MACHINE_SCHEMA_VERSION), now),
            )

    def _rewrite_process_machine_refs(self) -> int:
        ids, fallback = self._machine_refs()
        if not ids:
            return 0
        changed = 0
        with self.connect() as db:
            # 影子副本停写之后 ``revisions`` 可能整张表都不在（口径 6）：有就一起改，没有就跳过
            targets = [("projects", ("id",))]
            if self._table_exists(db, "revisions"):
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
                        reference = _resolve_machine_ref(process.get("mi"), ids, fallback)
                        if reference:
                            process["mid"] = reference
                            process.pop("mi", None)
                            touched = True
                    if not touched:
                        continue
                    where = " AND ".join(f"{column}=?" for column in key_columns)
                    db.execute(
                        f"UPDATE {table} SET state_json=? WHERE {where}",
                        (_compact(state), *[row[column] for column in key_columns]),
                    )
                    changed += 1
        return changed

    def _migrate_project_snapshots(self) -> None:
        with self.connect() as db:
            rows = db.execute("SELECT id,state_json FROM projects").fetchall()
            for row in rows:
                state = json.loads(row["state_json"])
                if any(key in state for key in LIBRARY_KEYS):
                    db.execute("UPDATE projects SET state_json=? WHERE id=?", (self._encode(state), row["id"]))
            if not self._table_exists(db, "revisions"):
                return  # 影子副本已停写（口径 6）：没有这张表就没有要清的库副本
            rows = db.execute("SELECT project_id,revision,state_json FROM revisions").fetchall()
            for row in rows:
                state = json.loads(row["state_json"])
                if any(key in state for key in LIBRARY_KEYS):
                    db.execute(
                        "UPDATE revisions SET state_json=? WHERE project_id=? AND revision=?",
                        (self._encode(state), row["project_id"], row["revision"]),
                    )

    def _encode(self, state: dict[str, Any]) -> str:
        ids, fallback = self._machine_refs()
        return _encode_project_state(state, ids, fallback)

    # ---------------- 项目信息迁移 / 读写 ----------------

    def _migrate_project_settings(self) -> None:
        """把 ``projects.state_json`` 里的 ``G`` 拆进 ``project_settings``（幂等）。

        迁移前先备份整库，并把原始 state 归档进 ``projects_legacy_v1``（万一要回滚）。
        项目图片（``pI``/``pf``/``bInspImg``/``fInspImg``）从 data URL 搬进附件库，
        ``G`` 里建模之外的键（``lang`` / ``_vSnap`` / 将来新增的键）进 ``extra_json`` 兜底，
        老读模型 ``G`` 由 ``legacy_g()`` 精确还原，一个键都不变。

        历史版本（``revisions``）的快照**保持原样**：它们是不可变历史，读路径仍按 JSON 还原；
        版本管理重构那一阶段再统一收进 ``project_versions``。
        """
        with self.connect() as db:
            rows = db.execute("SELECT id,name,state_json FROM projects").fetchall()
        pending: list[tuple[Any, dict[str, Any]]] = []
        for row in rows:
            if self.settings.exists(row["id"]):
                continue
            try:
                state = json.loads(row["state_json"])
            except (TypeError, ValueError):
                continue
            if isinstance(state, dict):
                pending.append((row, state))
        if not pending:
            return
        self._backup("pre-project-settings.sqlite3")
        with self.connect() as db:
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
                    (row["id"], row["name"], row["state_json"], _stamp()),
                )
                arrays = {key: state.get(key, []) for key in PROJECT_ARRAYS}
                db.execute("UPDATE projects SET state_json=? WHERE id=?", (_compact(arrays), row["id"]))
        for row, state in pending:
            general = state.get("G") if isinstance(state.get("G"), dict) else {}
            general = {key: value for key, value in general.items() if key not in LIBRARY_KEYS}
            general.pop("icnX", None)
            general.pop("fcnX", None)
            # lenient：旧数据里超范围/非数字的取值不阻断迁移，原值进 extra_json 兜底
            self.settings.apply_state(row["id"], {"G": general}, lenient=True)
        with self.connect() as db:
            db.execute(
                "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
                ("project_schema_version", _compact(PROJECT_SCHEMA_VERSION), _stamp()),
            )

    def project_settings_fields(self) -> dict[str, Any]:
        return self.settings.fields_spec()

    def project_settings(self, project_id: str) -> dict[str, Any]:
        self.get(project_id, allow_archived=True)
        return {"settings": self.settings.typed(project_id), **self.settings.fields_spec()}

    def _project_general(self, project_id: str) -> dict[str, Any]:
        row = self.settings.ensure(project_id)
        return self.settings.legacy_g(row=row, selections=self._selection_arrays(project_id))

    def _selection_categories(self) -> dict[str, list[str]]:
        """四类选型的**格子顺序**：就是页面 `fixClasses()` / `inspClasses()` 读的那份列表。"""
        return {
            KIND_FIXTURE: [item["name"] for item in self.fixture_centers.names()],
            KIND_GAUGE: [item["name"] for item in self.gauge_categories.names()],
        }

    def _selection_library(self) -> dict[str, dict[str, dict[str, Any]]]:
        """两本库按 id 建索引（读模型要用**当前**库值还原旧字符串）。"""
        return {
            KIND_FIXTURE: {str(row["id"]): row for row in self.fixtures.list_legacy()},
            KIND_GAUGE: {str(row["id"]): row for row in self.gauges.list_legacy()},
        }

    def _selection_arrays(self, project_id: str) -> dict[str, list[Any]] | None:
        """读模型里 ``G.fixQ/fixQC/insp/inspQ``：开关关着或表里没有行 → ``None``（回退旧数据）。"""
        if not self.selections_enabled:
            return None
        return legacy_selection_arrays(
            self.selections, project_id,
            categories=self._selection_categories(),
            library=self._selection_library(),
        )

    def _history_arrays(self, project_id: str) -> list[dict[str, Any]] | None:
        """读模型里 ``vh[]``：开关关着或表里没有行 → ``None``（回退 ``state_json.vh``）。"""
        if not self.history_enabled:
            return None
        return legacy_history(self.version_table, project_id)

    def _snapshot_arrays(self, project_id: str) -> dict[str, Any]:
        """版本快照里的业务数组：``pr``/``is``/``vh`` 在落表启用后**必须从表里读**——
        否则版本历史会记下过期的业务数据（表是唯一权威）。

        注意：**必须在打开写入事务之前调用**。SQLite 的写事务会拿锁，
        在事务里再开一条连接去读表既慢又可能等锁超时。
        """
        with self.connect() as db:
            row = db.execute("SELECT state_json FROM projects WHERE id=?", (project_id,)).fetchone()
        arrays = json.loads(row["state_json"]) if row is not None else {}
        result = {key: arrays.get(key, []) for key in PROJECT_ARRAYS}
        if self.project_business:
            processes = legacy_processes(
                self.processes, self.process_tools, project_id, asset_store=self.assets
            )
            if processes is not None:
                result["pr"] = processes
        if self.project_issues_enabled:
            issues = legacy_issues(
                self.issues, project_id,
                process_rows=self.processes.list_typed(project_id, include_deleted=True),
                asset_store=self.assets,
            )
            if issues is not None:
                result["is"] = issues
        history = self._history_arrays(project_id)
        if history is not None:
            result["vh"] = history
        return result

    def _write_snapshot(self, db, project_id: str, name: str, revision: int, *,
                        general: dict[str, Any], arrays: dict[str, Any]) -> None:
        """在已有写入事务里落一个版本快照（口径：每次保存都留版本、全部保留）。

        阶段 3a 起，快照写进 ``project_versions``（``kind='save'``）。
        旧 ``revisions`` 表只在 ``legacy_shadow``（开关还没到 4）时继续写，当影子副本；
        开关到 4 之后一个字节都不再往它写 —— 表是唯一权威，回滚改成从备份恢复（口径 6）。
        """
        snapshot = {"G": general, **arrays}
        stamp = _stamp()
        payload = _compact(snapshot)
        if self.legacy_shadow:
            db.execute(
                "INSERT INTO revisions(project_id,revision,name,state_json,created) VALUES(?,?,?,?,?)",
                (project_id, revision, name, payload, stamp),
            )
        if self.history_enabled:
            insert_save_row(db, project_id, revision, name, payload, stamp)

    def _snapshot(self, db, project_id: str, name: str, revision: int, *, general: dict[str, Any]) -> None:
        """兼容旧调用：在写入事务里现读现写（新代码请用 ``_snapshot_arrays`` 预先读好）。"""
        self._write_snapshot(db, project_id, name, revision,
                             general=general, arrays=self._snapshot_arrays(project_id))

    # ---------------- 变更流水（3b） ----------------

    def _note_change(self, draft: dict[str, Any]) -> None:
        """行级写入引擎交上来的流水草稿（这里只攒着，落库在 ``_bump_project``）。"""
        if not self.changes_enabled:
            return
        self._pending_changes.append(dict(draft))

    @contextmanager
    def _quiet_changes(self):
        """临时关掉流水记录：**系统自己搬数据**（老履历就地补建、迁移）不算"改动"。

        口径 5（不无中生有）：补建是"把本来就有的东西落到表里"，不是用户改了什么，
        要是也记一笔，流水里就会冒出一堆"新增版本履历"，反倒看不出人干了什么。
        """
        tables = (self.processes, self.process_tools, self.issues,
                  self.selections.fixtures, self.selections.gauges, self.version_table)
        saved = [table.change_sink for table in tables]
        for table in tables:
            table.change_sink = None
        try:
            yield
        finally:
            for table, sink in zip(tables, saved):
                table.change_sink = sink

    def _flush_changes(self, db, project_id: str, revision: int, *, created: str | None = None) -> int:
        """把攒下来的草稿写进 ``project_changes``（**必须在写事务里**，与保存版本同一次提交）。

        ``version_id`` 用保存版本的稳定 id（``<项目 id>-v<版本号>``）—— 一次改动一定指得到
        那一次的保存版本；没开版本履历（级别 4 以下）就没有版本行可指，置空。
        """
        drafts, self._pending_changes = self._pending_changes, []
        if not drafts or not self.changes_enabled:
            return 0
        version_id = save_row_id(project_id, revision) if self.history_enabled else None
        return len(self.change_table.insert_drafts(
            db, project_id, drafts, version_id=version_id, created=created,
        ))

    def _business_guard(self) -> None:
        """工序落表没启用时，相关接口给一个明确答复而不是 500。"""
        if not self.project_business:
            raise HTTPException(409, "工序落表尚未启用（请先运行迁移工具打开开关）")

    def _bump_project(self, project_id: str, *, expect_revision: int | None = None) -> dict[str, Any]:
        """写业务表之后的统一收尾：递增项目版本 + 留一个版本快照 + 返回整个项目记录。

        ``expect_revision`` 给了就做乐观锁（与整份保存的 409 语义一致）。
        快照数据在开写事务**之前**读好，避免写事务里再开连接读表。
        """
        general = self.settings.legacy_g(project_id, selections=self._selection_arrays(project_id))
        arrays = self._snapshot_arrays(project_id)
        with self.connect() as db:
            current = db.execute(
                "SELECT name,revision,archived FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if current is None:
                raise HTTPException(404, "机加 DFM 项目不存在")
            if current["archived"]:
                raise HTTPException(410, "已删除项目不能保存，请先恢复")
            if expect_revision is not None and int(current["revision"]) != int(expect_revision):
                raise HTTPException(409, f"项目已被他人保存（当前版本 {current['revision']}），请刷新后重试")
            revision = int(current["revision"]) + 1
            db.execute("UPDATE projects SET revision=?,updated=? WHERE id=?",
                       (revision, _stamp(), project_id))
            stamp = _stamp()
            self._write_snapshot(db, project_id, current["name"], revision,
                                 general=general, arrays=arrays)
            # 变更流水与保存版本同一次提交：流水行的 version_id 指的就是这一版
            self._flush_changes(db, project_id, revision, created=stamp)
        return self.get(project_id)

    def save_project_settings(
        self, project_id: str, payload: dict[str, Any], *, partial: bool = True
    ) -> dict[str, Any]:
        """行级保存项目信息：写表 + 递增项目版本 + 留一个版本快照。"""
        with self.connect() as db:
            current = db.execute("SELECT name,revision,archived FROM projects WHERE id=?", (project_id,)).fetchone()
        if current is None:
            raise HTTPException(404, "机加 DFM 项目不存在")
        if current["archived"]:
            raise HTTPException(410, "已删除项目不能保存，请先恢复")
        self.settings.ensure(project_id)
        before = self.settings.legacy_g(project_id, selections=self._selection_arrays(project_id))
        self.settings.save(project_id, payload, partial=partial)
        general = self.settings.legacy_g(project_id, selections=self._selection_arrays(project_id))
        arrays = self._snapshot_arrays(project_id)  # 写事务之前读好快照数据
        self._note_settings_change(before, general, payload)
        revision = int(current["revision"]) + 1
        now = _stamp()
        with self.connect() as db:
            db.execute(
                "UPDATE projects SET revision=?,updated=? WHERE id=?", (revision, now, project_id)
            )
            self._write_snapshot(db, project_id, current["name"], revision,
                                 general=general, arrays=arrays)
            self._flush_changes(db, project_id, revision, created=now)
        return self.get(project_id)

    def _note_settings_change(self, before: dict[str, Any], after: dict[str, Any],
                              payload: dict[str, Any]) -> None:
        """项目信息是按字段保存的，流水里写清楚"哪几个字段、从什么变成什么"。"""
        if not self.changes_enabled:
            return
        labels = SETTINGS_FIELD_LABELS
        parts: list[str] = []
        for key in payload:
            if key in ("img", "img2", "img3") or key.startswith("img"):
                continue
            if before.get(key) == after.get(key):
                continue
            name = labels.get(key, key)
            parts.append(f"{name} {_display_value(before.get(key))}→{_display_value(after.get(key))}")
        photos = [key for key in payload if key.startswith("img")]
        if photos:
            parts.append("项目图片：" + "、".join(sorted(photos)))
        label = "项目信息：" + ("；".join(parts[:6]) if parts else "保存（值没变）")
        self._note_change({
            "entity": ENTITY_SETTINGS,
            "action": ACTION_PHOTO if photos and not parts else ACTION_UPDATE,
            "label": label,
            "record_id": None,
            "extra": {"fields": sorted(parts and [item.split(" ")[0] for item in parts] or []),
                      "photos": photos},
        })

    def set_project_photo(
        self, project_id: str, slot: str, data: bytes, mime: str | None, name: str = ""
    ) -> dict[str, Any]:
        self.get(project_id, allow_archived=True)
        self.settings.set_photo(project_id, slot, data, mime, name)
        return self.save_project_settings(project_id, {}, partial=True)

    def clear_project_photo(self, project_id: str, slot: str) -> dict[str, Any]:
        self.get(project_id, allow_archived=True)
        self.settings.clear_photo(project_id, slot)
        return self.save_project_settings(project_id, {}, partial=True)

    # ---------------- 工序 / 工序刀具行（1b） ----------------
    # 与项目信息同一套规矩：写表 → 递增项目版本 → 留一个版本快照 → 返回整个项目记录。
    # 区别是这些是"项目级多行表"：行级 PATCH、排序、逻辑删除（永不物理删除）。

    def project_processes(self, project_id: str, *, include_deleted: bool = False) -> dict[str, Any]:
        """工序列表（含刀具行、**每道工序选定的设备**、含回收站计数），给前端工序页用。"""
        self._business_guard()
        self.get(project_id, allow_archived=True)
        processes = self.processes.list_typed(project_id, include_deleted=include_deleted)
        tools = self.process_tools.list_typed(project_id, include_deleted=include_deleted)
        by_process: dict[str, list[dict[str, Any]]] = {}
        for tool in tools:
            by_process.setdefault(str(tool["process_id"]), []).append(tool)
        for process in processes:
            process["tools"] = by_process.get(str(process["id"]), [])
            # 「工序设备选择」：设备是每道工序自己的一格，列表里直接把当前设备现算出来，
            # 页面上那一列（下拉框）就不用再为每道工序单独打一次接口。
            process["machine"] = self._process_machine_view(process)
        default_machine = self.machines.default_ref()
        return {
            "processes": processes,
            "default_machine_id": default_machine,
            "machines": [
                {"id": row["id"], "brand": row.get("brand") or "", "model": row.get("model") or "",
                 "price": row.get("price") or 0, "photo_url": row.get("photo_url") or "",
                 "is_fallback": bool(row.get("is_fallback"))}
                for row in self.machines.list_typed()
            ],
            "deleted_processes": self.processes.recycle_bin(project_id),
            "deleted_tools": self.process_tools.recycle_bin(project_id),
            "fields": {
                "process": [field.describe() for field in PROCESS_FIELDS],
                "tool": [field.describe() for field in TOOL_FIELDS],
                "snapshot_keys": list(SNAPSHOT_KEYS),
                "nc_keys": list(NC_KEYS),
                "nc_defaults": dict(NC_DEFAULTS),
            },
        }

    def _process_machine_view(self, process: dict[str, Any]) -> dict[str, Any]:
        """这道工序当前用的是哪台设备：``machine_id`` 优先，没有就退回兜底机型。

        快照（``machine_snapshot``）留着是为了"库里的设备后来改了/删了"时读得到当时的型号，
        所以这里同时给"当前库行"和"当时快照"两份，页面按需要显示。
        """
        machine_id = str(process.get("mid") or "").strip()
        snapshot = process.get("machine_snapshot") or {}
        fallback_id = self.machines.default_ref()
        # ``find`` 返回的是 ``sqlite3.Row``（没有 .get）——"换设备"那条路踩过这个坑，这里先统一成 dict
        found = self.machines.find(machine_id) if machine_id else None
        hit = dict(found) if found is not None else {}
        return {
            "machine_id": machine_id,
            "is_fallback": not machine_id,
            "fallback_id": fallback_id,
            "missing": bool(machine_id) and found is None,
            "brand": str(hit.get("brand") or snapshot.get("brand") or ""),
            "model": str(hit.get("model") or snapshot.get("model") or ""),
            "price": float(hit.get("price") or snapshot.get("price") or 0),
            "photo_url": str(hit.get("photo_url") or ""),
            "snapshot": dict(snapshot),
        }

    def set_project_process_machine(
        self, project_id: str, process_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """**工序设备选择**：把这道工序挂到设备库里的某一台上。

        收 ``{"machine_id": "..."}``（也认老的 ``{"mid": "..."}``）。设备 id 必须真在库里；
        空串 = 清空选择（读模型退回兜底机型）。换设备时 id 与快照一起换（口径 4）。
        """
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.processes.require_in_project(project_id, process_id)
        raw = payload.get("machine_id", payload.get("mid"))
        machine_id = "" if raw is None else str(raw).strip()
        if not machine_id:
            return self.clear_project_process_machine(project_id, process_id)
        hit = self.machines.find(machine_id)
        if hit is None:
            raise HTTPException(422, f"设备库里没有这条记录：{machine_id}")
        machine = dict(hit)
        self.processes.set_machine(process_id, machine)
        # 设备库填了价 → 顺手同步这道工序的设备费（与旧页面"换设备"时的手工同步一致）
        price = float(machine.get("price") or 0)
        if price > 0:
            self.processes.update(process_id, {"eqP": price})
        return self._bump_project(project_id)

    def clear_project_process_machine(self, project_id: str, process_id: str) -> dict[str, Any]:
        """清空工序设备选择（退回兜底机型）；行里的历史快照一并清掉，避免显示成"还挂着设备"。"""
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.processes.require_in_project(project_id, process_id)
        self.processes.set_machine(process_id, None)
        return self._bump_project(project_id)

    # ---------------- 问题清单（阶段 2a，行级读写） ----------------

    def _issue_guard(self) -> None:
        """问题清单没启用时给明确答复，而不是 500。"""
        if not self.project_issues_enabled:
            raise HTTPException(409, "问题清单落表尚未启用（请先运行迁移工具打开开关）")

    def _issue_process_names(self, project_id: str) -> dict[str, str]:
        """外键 → 工序当前名字（问题清单读模型里的 ``pr`` 由它现算）。"""
        return {
            str(row["id"]): str(row.get("nm") or "")
            for row in self.processes.list_typed(project_id, include_deleted=True)
        }

    def project_issues(self, project_id: str, *, include_deleted: bool = False) -> dict[str, Any]:
        self._issue_guard()
        self.get(project_id, allow_archived=True)
        names = self._issue_process_names(project_id)
        rows = self.issues.list_typed(project_id, include_deleted=include_deleted)
        for row in rows:
            row["process_name"] = names.get(str(row.get("process_id") or ""), "")
            row["process_missing"] = not row["process_name"]
        return {
            "issues": rows,
            "deleted_issues": self.issues.recycle_bin(project_id),
            "processes": [
                {"id": row["id"], "name": row.get("nm") or "", "sort_order": row["sort_order"]}
                for row in self.processes.list_typed(project_id)
            ],
            "fields": {
                "issue": [field.describe() for field in ISSUE_FIELDS],
                "statuses": list(ISSUE_STATUSES),
                "types": list(ISSUE_TYPES),
            },
        }

    def create_project_issue(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._issue_guard()
        self.get(project_id, allow_archived=True)
        row = self.issues.create(project_id, payload)
        # 记下当时的工序名：工序以后改名/被删除，这行历史照样说得清（外键仍是权威）
        if row.get("process_id") and not row.get("prName"):
            names = self._issue_process_names(project_id)
            name = names.get(str(row["process_id"]), "")
            if name:
                self.issues.update(row["id"], {"prName": name})
        return self._bump_project(project_id)

    def update_project_issue(self, project_id: str, issue_id: str,
                             payload: dict[str, Any]) -> dict[str, Any]:
        self._issue_guard()
        self.get(project_id, allow_archived=True)
        self.issues.require_in_project(project_id, issue_id)
        if "process_id" in payload and not payload.get("prName"):
            names = self._issue_process_names(project_id)
            name = names.get(str(payload.get("process_id") or ""), "")
            payload = {**payload, "prName": name}
        self.issues.update(issue_id, payload)
        return self._bump_project(project_id)

    def delete_project_issue(self, project_id: str, issue_id: str, *, by: str = "",
                             reason: str = "") -> dict[str, Any]:
        self._issue_guard()
        self.get(project_id, allow_archived=True)
        self.issues.require_in_project(project_id, issue_id)
        self.issues.soft_delete(issue_id, by=by, reason=reason)
        return self._bump_project(project_id)

    def restore_project_issue(self, project_id: str, issue_id: str) -> dict[str, Any]:
        self._issue_guard()
        self.get(project_id, allow_archived=True)
        self.issues.require_in_project(project_id, issue_id, allow_deleted=True)
        self.issues.restore(issue_id)
        return self._bump_project(project_id)

    def reorder_project_issues(self, project_id: str, issue_ids: list[str]) -> dict[str, Any]:
        self._issue_guard()
        self.get(project_id, allow_archived=True)
        self.issues.reorder(project_id, issue_ids)
        return self._bump_project(project_id)

    def set_issue_photo(self, project_id: str, issue_id: str, slot: str, data: bytes,
                        content_type: str | None = None) -> dict[str, Any]:
        """问题清单的图片槽（``before`` = 修改前、``after`` = 修改后）。

        **修过的坑**：这里原来写的 ``self.assets.store(...)`` —— 附件库根本没有这个方法
        （正确入口是 ``AssetStore.put(kind, data, mime, name, db=...)``），
        所以"问题清单上传图片"这条路一调就是 500。与工序/刀具行图片（``_set_row_photo``）
        现在完全同一套写法，并且空内容直接 422。
        """
        self._issue_guard()
        self.get(project_id, allow_archived=True)
        self.issues.require_in_project(project_id, issue_id)
        if not data:
            raise HTTPException(422, "图片内容为空")
        spec = self.issues.attachment(slot)
        with self.assets.session() as db:
            record = self.assets.put(spec.kind, data, content_type, "", db=db)
        self.issues.set_attachment_value(issue_id, slot, record["id"])
        return self._bump_project(project_id)

    def clear_issue_photo(self, project_id: str, issue_id: str, slot: str) -> dict[str, Any]:
        self._issue_guard()
        self.get(project_id, allow_archived=True)
        self.issues.require_in_project(project_id, issue_id)
        self.issues.set_attachment_value(issue_id, slot, None)
        return self._bump_project(project_id)

    # ---------------- 选型（阶段 2b，按"格子"读写） ----------------
    # 层级：项目 → 工序（每道工序一台设备）→ 夹具选型 → 检具选型。
    # 夹具选型、检具选型都是**项目级**资源，各一张表（project_fixtures / project_gauges），
    # 页面只有"第几格"这个概念（格子顺序 = 类别字典顺序），没有行 id，
    # 所以这里一律用 (类别, 格子下标) 定位，接口也只暴露这个坐标。

    def _selection_guard(self) -> None:
        """选型没启用时给明确答复，而不是 500。"""
        if not self.selections_enabled:
            raise HTTPException(409, "选型落表尚未启用（请先运行迁移工具打开开关）")

    def _selection_slot_row(self, project_id: str, kind: str, slot: int, *, db=None):
        return self.selections.slot_row(project_id, kind, slot, db=db)

    def project_selection(self, project_id: str, kind: str) -> dict[str, Any]:
        """**一类**选型的清单（``GET /projects/{id}/fixtures`` 或 ``/gauges``）。"""
        self._selection_guard()
        self.get(project_id, allow_archived=True)
        return selection_listing(
            self.selections, project_id, kind,
            categories=self._selection_categories(),
            library=self._selection_library(),
            enabled=self.selections_enabled,
        )

    def project_selections(self, project_id: str) -> dict[str, Any]:
        """两类选型一起给（老接口；页面上现在是两个独立页签，各走 project_selection）。"""
        self._selection_guard()
        self.get(project_id, allow_archived=True)
        return selections_listing(
            self.selections, project_id,
            categories=self._selection_categories(),
            library=self._selection_library(),
            enabled=self.selections_enabled,
        )

    def save_project_selection(
        self, project_id: str, kind: str, slot: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """保存一个格子：选型（给库行 id 或旧串）或只改"是否报价"。

        行不存在就现建（下标 = 格子位置），存在就改——页面不用先查有没有行。
        """
        self._selection_guard()
        self.get(project_id, allow_archived=True)
        self._seed_selections(project_id)
        self.selections.save_slot(
            project_id, kind, int(slot), payload,
            categories=self._selection_categories(),
            library=self._selection_library(),
        )
        return self._bump_project(project_id)

    def clear_project_selection(self, project_id: str, kind: str, slot: int) -> dict[str, Any]:
        """清空一个格子：解绑 + 旧值清掉（行保留，"是否报价"的勾选也留着）。

        不做物理删除（口径 2）：清空前的值仍在版本快照里可查、可比。
        """
        self._selection_guard()
        self.get(project_id, allow_archived=True)
        self._seed_selections(project_id)
        row = self.selections.clear_slot(project_id, kind, int(slot),
                                         categories=self._selection_categories())
        if row is None:
            # 本来就没选过：什么都不用写，但仍要给出当前项目记录（前端统一 adopt）
            return self.get(project_id)
        return self._bump_project(project_id)

    def _seed_selections(self, project_id: str) -> dict[str, Any] | None:
        """**懒迁移**：第一次动这个项目的选型之前，先把老数据整份搬进两张新表。

        为什么非做不可：读模型是"表里只要有行就以表为准"。如果不先补齐，
        用户在新页面上点第一格时只会建那一行，别的格子瞬间看起来全空了
        （数据没丢，但页面上等于"选型丢了"，没人敢用）。
        来源按优先级：老的多态表 ``project_selections``（表落过数据的权威）→
        项目 ``extra_json`` 里的 ``fixQ/fixQC/insp/inspQ`` 四个数组。
        已经搬过（表里有行）就直接返回，不重复搬。
        搬家过程**静音**（口径 5）：这是系统把本来就有的数据落到表里，不是人改了什么。
        """
        if not self.selections_enabled:
            return None
        if self.selections.count(project_id, include_deleted=True):
            return None
        legacy: list[dict[str, Any]] = []
        with self.connect() as db:
            if self._table_exists(db, LEGACY_SELECTION_TABLE):
                legacy = [dict(row) for row in db.execute(
                    f"SELECT * FROM {LEGACY_SELECTION_TABLE} WHERE project_id=?",
                    (project_id,))]
        if legacy:
            with self._quiet_changes():
                report = copy_legacy_rows(self.selections, project_id, legacy)
            report["source"] = "legacy_table"
            return report
        with self._quiet_changes():
            report = split_selections(
                self.selections, project_id, self.settings.legacy_g(project_id),
                categories=self._selection_categories(),
                library=self._selection_library(),
            )
        report["source"] = "legacy_arrays"
        return report

    @staticmethod
    def _table_exists(db: Any, table: str) -> bool:
        return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                          (table,)).fetchone() is not None

    # ---------------- 版本履历（阶段 3a，按"行"读写） ----------------
    # 页面上的"版本履历"表：一行四个格子（日期/版本号/变更内容/变更人）。
    # 页面对一行只有下标，所以三个接口都同时收 id 与下标（下标在服务端换算成 id）。

    def _history_guard(self) -> None:
        """版本履历没启用时给明确答复，而不是 500。"""
        if not self.history_enabled:
            raise HTTPException(409, "版本履历落表尚未启用（请先运行迁移工具打开开关）")

    # ---------------- 变更流水（阶段 3b，只读） ----------------
    # 写流水是服务端在每个行级写入点自动记的（与保存版本同一次提交），
    # 所以这一段只有读接口：流水是追加型日志，前端没有写入点。

    def _changes_guard(self) -> None:
        if not self.changes_enabled:
            raise HTTPException(409, "变更流水尚未启用（请先运行 tools/migrate_project_changes.py）")

    def project_changes(self, project_id: str, *, limit: int = 200, entity: str = "",
                        action: str = "", recycle: bool = False) -> dict[str, Any]:
        """项目变更流水（只读，新的在前）。"""
        self._changes_guard()
        self.get(project_id, allow_archived=True)
        listing = self.change_table.listing(project_id, limit=limit, entity=entity,
                                            action=action, recycle=recycle)
        listing["enabled"] = self.changes_enabled
        return listing

    def _state_vh(self, project_id: str) -> list[dict[str, Any]]:
        """``projects.state_json.vh``（老项目还没落表时的履历就在这儿）。"""
        with self.connect() as db:
            row = db.execute("SELECT state_json FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            return []
        rows = (json.loads(row["state_json"]) or {}).get("vh")
        return rows if isinstance(rows, list) else []

    def _ensure_history_rows(self, project_id: str) -> int:
        """表里还没有履历行时，把 ``state_json.vh`` **就地补建**成行（只补一次，返回补了几行）。

        迁移工具会一次性搬完；这条是"没赶上迁移"的兜底：整份保存/导入带进来的 vh、
        或者开关刚打开还没跑迁移的老项目，页面第一次改履历就把它补上，
        所以页面永远不用等迁移、也不会出现"刚看到就说这一行不在了"。
        行 id 与影子清单发的 ``<项目 id>-h<下标>`` 一致。
        """
        if self.version_table.has_history_rows(project_id):
            return 0
        added = 0
        # 补建不是"用户改了什么"（口径 5：不无中生有），所以这一段不记变更流水
        with self._quiet_changes():
            for values in split_history_rows(self._state_vh(project_id), project_id=project_id):
                order = int(values.pop("order"))
                record_id = str(values.pop("id"))
                if self.version_table.find(record_id) is not None:
                    continue  # 并发/重复调用：行已经在（或刚被删过），不重复插
                self.version_table.create(project_id, values, order=order, record_id=record_id)
                added += 1
        return added

    def _history_row(self, project_id: str, record_id: str, *, allow_deleted: bool = False):
        """按 id 取履历行（必须属于这个项目、必须是 ``kind='history'``）。"""
        for row in self.version_table.history_rows(project_id):
            if row["id"] != record_id:
                continue
            if row["deleted_at"] and not allow_deleted:
                raise HTTPException(410, "这条版本履历已删除，可在回收站恢复")
            return row
        raise HTTPException(404, "版本履历记录不存在，可能已被删除")

    def _history_target(self, project_id: str, payload: dict[str, Any], *, allow_deleted: bool = False):
        """兼容"只给下标"的老式调用：``{index: 2}`` → 第 2 行的 id。"""
        if isinstance(payload, dict) and payload.get("index") is not None \
                and not str(payload.get("id") or "").strip():
            rows = self.version_table.history_rows(project_id)
            index = int(payload["index"])
            if index < 0 or index >= len(rows):
                raise HTTPException(409, f"第 {index + 1} 行已经不在了（列表变过），请刷新后重试")
            return str(rows[index]["id"])
        return str(payload.get("id") or "").strip() if isinstance(payload, dict) else str(payload)

    def project_history(self, project_id: str, *, recycle: bool = False) -> dict[str, Any]:
        self._history_guard()
        self.get(project_id, allow_archived=True)
        if self.version_table.has_history_rows(project_id):
            return history_listing(self.version_table, project_id,
                                   enabled=self.history_enabled, recycle=recycle)
        # 还没落表：给一份只读的影子清单（读模型仍在读 state_json.vh），第一次写就补建
        return virtual_history_listing({"vh": self._state_vh(project_id)}, project_id,
                                       enabled=self.history_enabled, recycle=recycle)

    def create_project_history(self, project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """新增一行履历：四个键缺的补空串（与页面 ``addVH()`` 的默认值一致）。"""
        self._history_guard()
        self.get(project_id, allow_archived=True)
        self._ensure_history_rows(project_id)   # 老履历先在，新增的行才排得对
        values = new_history_values(payload or {})
        values["kind"] = KIND_HISTORY
        values["revision"] = 0
        self.version_table.create(project_id, values)
        return self._bump_project(project_id)

    def save_project_history(self, project_id: str, record_id: str,
                             payload: dict[str, Any]) -> dict[str, Any]:
        """行级保存：只改提交上来的格子（``dt``/``ver``/``ds``/``by`` 任意子集）。"""
        self._history_guard()
        self.get(project_id, allow_archived=True)
        self._ensure_history_rows(project_id)
        row = self._history_row(project_id, self._history_target(
            project_id, {"id": record_id, **(payload or {})}
        ))
        # 兜底列要**合并**而不是覆盖：登记表没覆盖的旧键一个都不能丢
        values = history_payload(payload or {}, current={"extra": light_view(row).get("extra") or {}})
        if values:
            self.version_table.update(row["id"], values)
        return self._bump_project(project_id)

    def delete_project_history(self, project_id: str, record_id: str, *,
                               by: str = "", reason: str = "") -> dict[str, Any]:
        """逻辑删除一行（口径 2：行还在表里，回收站可恢复，永不物理删除）。"""
        self._history_guard()
        self.get(project_id, allow_archived=True)
        self._ensure_history_rows(project_id)
        row = self._history_row(project_id, record_id)
        self.version_table.soft_delete(row["id"], by=by, reason=reason or "页面删除")
        return self._bump_project(project_id)

    def restore_project_history(self, project_id: str, record_id: str) -> dict[str, Any]:
        self._history_guard()
        self.get(project_id, allow_archived=True)
        self._ensure_history_rows(project_id)
        row = self._history_row(project_id, record_id, allow_deleted=True)
        self.version_table.restore(row["id"])
        return self._bump_project(project_id)

    def reorder_project_history(self, project_id: str, ids: list[str]) -> dict[str, Any]:
        """重排履历行（页面上的顺序就是显示顺序）。"""
        self._history_guard()
        self.get(project_id, allow_archived=True)
        self._ensure_history_rows(project_id)
        self.version_table.reorder_history(project_id, [str(item) for item in (ids or [])])
        return self._bump_project(project_id)

    def create_project_process(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        row = self.processes.create(project_id, payload)
        machine = str(row.get("mid") or "")
        if machine and not row.get("machine_snapshot"):
            hit = self.machines.find(machine)
            if hit is not None:
                self.processes.set_machine(row["id"], hit)
        return self._bump_project(project_id)

    def update_project_process(self, project_id: str, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.processes.require_in_project(project_id, process_id)
        if "mid" in payload:
            # 换设备：id 与快照一起换（口径 4 的同理，源库改了也读得到当时的型号）
            hit = self.machines.find(str(payload.get("mid") or ""))
            self.processes.set_machine(process_id, hit)
        self.processes.update(process_id, {key: value for key, value in payload.items() if key != "mid"})
        return self._bump_project(project_id)

    def delete_project_process(self, project_id: str, process_id: str, *, by: str = "",
                               reason: str = "") -> dict[str, Any]:
        """逻辑删除工序：它的刀具行一并逻辑删除（永不物理删除，回收站可恢复）。"""
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.processes.require_in_project(project_id, process_id)
        self.process_tools.soft_delete_by_process(process_id, by=by)
        self.processes.soft_delete(process_id, by=by, reason=reason)
        return self._bump_project(project_id)

    def restore_project_process(self, project_id: str, process_id: str, *, revision: int | None = None) -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.processes.require_in_project(project_id, process_id, allow_deleted=True)
        self.processes.restore(process_id)
        self.process_tools.restore_by_process(process_id)
        return self._bump_project(project_id, expect_revision=revision)

    def reorder_project_processes(self, project_id: str, ids: list[str]) -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.processes.reorder(project_id, ids)
        return self._bump_project(project_id)

    def create_project_tool(self, project_id: str, process_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.processes.require_in_project(project_id, process_id)
        self.process_tools.create(project_id, {**payload, "process_id": process_id})
        return self._bump_project(project_id)

    def update_project_tool(self, project_id: str, tool_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.process_tools.require_in_project(project_id, tool_id)
        self.process_tools.update(tool_id, payload)
        return self._bump_project(project_id)

    def delete_project_tool(self, project_id: str, tool_id: str, *, by: str = "",
                            reason: str = "") -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.process_tools.require_in_project(project_id, tool_id)
        self.process_tools.soft_delete(tool_id, by=by, reason=reason)
        return self._bump_project(project_id)

    def restore_project_tool(self, project_id: str, tool_id: str) -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.process_tools.require_in_project(project_id, tool_id, allow_deleted=True)
        self.process_tools.restore(tool_id)
        return self._bump_project(project_id)

    def reorder_project_tools(self, project_id: str, process_id: str, ids: list[str]) -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        self.processes.require_in_project(project_id, process_id)
        self.process_tools.reorder_in_process(process_id, ids)
        return self._bump_project(project_id)

    def set_process_photo(self, project_id: str, process_id: str, slot: str, data: bytes,
                          mime: str | None, name: str = "") -> dict[str, Any]:
        return self._set_row_photo(self.processes, project_id, process_id, slot, data, mime, name)

    def clear_process_photo(self, project_id: str, process_id: str, slot: str = "layout") -> dict[str, Any]:
        return self._clear_row_photo(self.processes, project_id, process_id, slot)

    def set_tool_photo(self, project_id: str, tool_id: str, data: bytes, mime: str | None,
                       name: str = "") -> dict[str, Any]:
        return self._set_row_photo(self.process_tools, project_id, tool_id, "photo", data, mime, name)

    def clear_tool_photo(self, project_id: str, tool_id: str) -> dict[str, Any]:
        return self._clear_row_photo(self.process_tools, project_id, tool_id, "photo")

    def _set_row_photo(self, table, project_id: str, record_id: str, slot: str, data: bytes,
                       mime: str | None, name: str) -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        table.require_in_project(project_id, record_id)
        if not data:
            raise HTTPException(422, "图片内容为空")
        with self.assets.session() as db:
            record = self.assets.put(table.attachment(slot).kind, data, mime, name, db=db)
        table.set_attachment_value(record_id, slot, record["id"])
        return self._bump_project(project_id)

    def _clear_row_photo(self, table, project_id: str, record_id: str, slot: str) -> dict[str, Any]:
        self._business_guard()
        self.get(project_id, allow_archived=True)
        table.require_in_project(project_id, record_id)
        table.set_attachment_value(record_id, slot, None)
        return self._bump_project(project_id)

    # ---------------- libraries ----------------

    @staticmethod
    def _replace_library(db: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise HTTPException(422, f"{table} 基础库必须是对象数组")
        if len(rows) > 20_000:
            raise HTTPException(422, f"{table} 基础库超过 20000 条")
        now = _stamp()
        db.execute(f"DELETE FROM {table}")
        db.executemany(
            f"INSERT INTO {table}(id,sort_order,payload_json,updated) VALUES(?,?,?,?)",
            [(uuid.uuid4().hex, index, _compact(row), now) for index, row in enumerate(rows)],
        )

    def libraries(self, *, inline_assets: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "mdb": self.machines.list_legacy(inline=inline_assets),
            "tdb": self.tools.list_legacy(inline=inline_assets),
            "fdb": self.fixtures.list_legacy(inline=inline_assets),
            "idb": self.gauges.list_legacy(inline=inline_assets),
        }
        # 类别字典：页面仍按 `G.icnX` / `G.fcnX` 读这两份列表
        result["icnX"] = [item["name"] for item in self.gauge_categories.names()]
        result["fcnX"] = [item["name"] for item in self.fixture_centers.names()]
        return result

    def replace_libraries(self, libraries: dict[str, Any]) -> dict[str, Any]:
        """兼容旧前端的整库保存：四个库都按自然键逐行 upsert，**只增改不删**。

        新前端不再走这条路（每行单独 PATCH、类别走字典接口），这里只为缓存了旧 JS 的
        页面保留可用性。注意不能沿用"提交里没有就删"的整表覆盖语义：旧页面提交的是
        它内存里的数组，一旦只带了一部分（筛选后、或新模块就地同步过），整表覆盖会把
        库里其余数据静默删光（实测一次清空 177 条夹具 + 437 条检具）。删除只走
        ``DELETE /{库}/{id}``。
        """
        missing = sorted(set(LEGACY_LIBRARY_TABLES) - set(libraries))
        if missing:
            raise HTTPException(422, "必须同时提交夹具和检具两类基础库")
        counts: dict[str, Any] = {}
        counts["mdb"] = (
            self.machines.count()
            if libraries.get("mdb") is None
            else self.machines.replace_legacy(libraries["mdb"])
        )
        counts["tdb"] = (
            self.tools.count()
            if libraries.get("tdb") is None
            else self.tools.replace_legacy(libraries["tdb"])
        )
        counts["fdb"] = self.fixtures.replace_legacy(libraries["fdb"])
        counts["idb"] = self.gauges.replace_legacy(libraries["idb"])
        # 类别列表已改为字典表维护：旧客户端提交的 icnX/fcnX 只做补录，不再整表覆盖
        with self.connect() as db:
            self.fixture_centers.register(libraries.get("fcnX") or [], db=db)
            self.gauge_categories.register(libraries.get("icnX") or [], db=db)
        return counts

    def compose(
        self,
        state: dict[str, Any],
        *,
        settings: dict[str, Any] | None = None,
        inline_assets: bool = False,
        processes: list[dict[str, Any]] | None = None,
        issues: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """组合读模型：共享库 + 项目数据。

        ``settings`` 给了就用它当 ``G``（项目信息表里的行）；没给就用 ``state`` 自带的 ``G``
        （历史版本快照、默认数据仍然走这条路）。

        ``processes`` 给了就用它当 ``pr[]``（工序表里的行，已由 :func:`legacy_processes`
        还原成旧结构）；没给就用 ``state`` 自带的 ``pr``（迁移前、历史快照走这条路）。

        ``issues`` 同理，给了就用它当 ``is[]``（问题清单表里的行）。
        ``history`` 同理，给了就用它当 ``vh[]``（版本履历表里的行）。
        """
        result = {**self.libraries(inline_assets=inline_assets), **state}
        general = dict(settings) if settings is not None else dict(result.get("G") or {})
        general["icnX"] = result["icnX"]  # 兼容旧键：类别列表现在由字典表读出
        general["fcnX"] = result["fcnX"]
        result["G"] = general
        positions = {machine_id: index for index, machine_id in enumerate(self.machines.ids())}
        source = processes if processes is not None else result.get("pr", [])
        result["pr"] = [
            {**process, "mi": positions.get(str(process.get("mid") or ""), -1)}
            if isinstance(process, dict) else process
            for process in source
        ]
        if issues is not None:
            result["is"] = issues
        if history is not None:
            result["vh"] = history
        # 三份业务数组**永远是数组**：表是权威时"表里 0 行"就是"空"，不能因为
        # ``state_json`` 里没有这个键就整个键消失（前端一直按数组用）。
        for key in PROJECT_ARRAYS:
            if not isinstance(result.get(key), list):
                result[key] = []
        return result

    # 兼容旧调用名（老代码/测试使用 _compose）。
    _compose = compose

    # ---------------- machine library helpers ----------------

    def machine_fields(self) -> list[dict[str, Any]]:
        return field_headers()

    def machine_usage(self, machine_id: str) -> list[dict[str, str]]:
        """Projects whose processes reference this machine (delete guard)."""
        used: list[dict[str, str]] = []
        with self.connect() as db:
            for row in db.execute("SELECT id,name,state_json FROM projects ORDER BY updated DESC"):
                state = json.loads(row["state_json"])
                for process in state.get("pr") or []:
                    if isinstance(process, dict) and str(process.get("mid") or "") == machine_id:
                        used.append(
                            {
                                "project_id": row["id"],
                                "project": row["name"],
                                "process": str(process.get("nm") or ""),
                            }
                        )
                        break
        return used

    def tool_fields(self) -> dict[str, Any]:
        """刀具库字段登记表：存储列（枚举取值来自字典表）+ 页面自动列。"""
        return {
            "fields": tool_field_headers(self.tool_dict),
            "derived": tool_derived_headers(),
        }

    def tool_dictionaries(self) -> dict[str, Any]:
        """两张字典表 + 各自被刀具引用的次数（删除前提示用）。"""
        return {
            "groups": self.tool_dict.groups(),
            "categories": self.tool_dict.categories(),
            "usage": self.tools.reference_counts(),
        }

    def fixture_fields(self) -> dict[str, Any]:
        """夹具库字段登记表：模具中心下拉来自字典表。"""
        return {"fields": fixture_field_headers(self.fixture_centers)}

    def gauge_fields(self) -> dict[str, Any]:
        """检具库字段登记表：检具类别下拉来自字典表。"""
        return {"fields": gauge_field_headers(self.gauge_categories)}

    def library_dictionaries(self) -> dict[str, Any]:
        """夹具/检具的类别字典 + 各自被引用的条数。"""
        return {
            "centers": self.fixture_centers.names(),
            "categories": self.gauge_categories.names(),
            "usage": {
                "centers": self.fixture_centers.usage(),
                "categories": self.gauge_categories.usage(),
            },
        }

    def fixture_usage(self, center: str, name: str) -> list[dict[str, str]]:
        """哪些项目在「夹具报价选型」里按 ``模具中心|名称`` 引用过这件夹具。"""
        return self._library_usage(f"{center}|{name}", "fixQ")

    def gauge_usage(self, category: str, name: str, drawing: str) -> list[dict[str, str]]:
        """哪些项目在检具选型里按 ``类别|名称|图号`` 引用过这件检具。"""
        return self._library_usage(f"{category}|{name}|{drawing}", "insp")

    def _library_usage(self, key: str, field: str) -> list[dict[str, str]]:
        used: list[dict[str, str]] = []
        with self.connect() as db:
            for row in db.execute("SELECT id,name,state_json FROM projects ORDER BY updated DESC"):
                state = json.loads(row["state_json"])
                general = state.get("G") or {}
                selected = general.get(field) or []
                if isinstance(selected, list) and key in [str(item) for item in selected]:
                    used.append({"project_id": row["id"], "project": row["name"]})
        return used

    def tool_usage(self, tool_name: str, group: str = "") -> list[dict[str, str]]:
        """按名称引用该刀具的项目工序（成本表按 price/life 查表，不阻塞删除）。"""
        name = str(tool_name or "").strip()
        if not name:
            return []
        used: list[dict[str, str]] = []
        with self.connect() as db:
            for row in db.execute("SELECT id,name,state_json FROM projects ORDER BY updated DESC"):
                state = json.loads(row["state_json"])
                for process in state.get("pr") or []:
                    if not isinstance(process, dict):
                        continue
                    hit = False
                    for tool in process.get("tl") or []:
                        if not isinstance(tool, dict):
                            continue
                        if group == "hld" and str(tool.get("hld") or "") == name:
                            hit = True
                        elif group == "acc" and str(tool.get("acc") or "") == name:
                            hit = True
                        elif str(tool.get("tp") or "") == name:
                            hit = True
                        if hit:
                            break
                    if hit:
                        used.append(
                            {
                                "project_id": row["id"],
                                "project": row["name"],
                                "process": str(process.get("nm") or ""),
                            }
                        )
                        break
        return used

    def asset(self, asset_id: str) -> tuple[dict[str, Any], Path]:
        record = self.assets.record(asset_id)
        if record is None:
            raise HTTPException(404, "附件不存在")
        path = self.assets.file_path(record)
        if not path.is_file():
            raise HTTPException(410, "附件文件缺失，请重新上传")
        return record, path

    # ---------------- 导出文件包（阶段 5 · 口径 §7.0） ----------------

    def export_package(self, project_id: str) -> tuple[str, bytes]:
        """导出文件包：``(建议文件名, zip 字节)``。

        包结构（口径 §7.0 定死，不自创）：

        * ``project.json`` —— 与 ``GET /projects/{pid}`` **同一份形状**的读模型，只是每个
          指向附件的字段值从 ``/api/machining-dfm/assets/<id>`` 换成包内相对路径
          ``assets/<id>.<ext>``（``ext`` 取 ``assets.path`` 后缀，取不到用 ``mime`` 推），
          并多一个顶层 ``_export`` 说明块；
        * ``assets/<id>.<ext>`` —— 读模型里**真引用到**的附件原始文件（字节与磁盘一致）；
          没被引用的不打包，一个都取不到时也不写空条目；
        * ``README.txt`` —— 怎么用这份包的几行说明（UTF-8）。

        **只读**：不落库、不写 ``data/``、不改任何既有路由的行为。项目不存在 → 404
        （沿用读接口的中文 detail）；项目已删除（``archived``）也能出包 —— 与
        ``GET /projects/{pid}?allow_archived=true`` 同一口径：数据还在，就给。
        """
        record = self.get(project_id, allow_archived=True)
        mapping: dict[str, str] = {}
        files: list[tuple[str, bytes]] = []
        for asset_id in _iter_asset_ids(record.get("state")):
            meta = self.assets.record(asset_id)
            if meta is None:
                continue
            data = self.assets.read_bytes(asset_id)
            if data is None:
                continue
            entry = f"assets/{asset_id}{_package_extension(meta)}"
            mapping[asset_id] = entry
            files.append((entry, data))
        payload = _rewrite_package_assets(record, mapping)
        exported = _stamp()
        payload["_export"] = {
            "format": PACKAGE_FORMAT,
            "version": PACKAGE_VERSION,
            "project_id": project_id,
            "revision": int(record.get("revision") or 0),
            "exported": exported,
            "assets": len(files),
        }
        readme = "\n".join((
            "机加 DFM 项目文件包（%s v%d）· 项目：%s（版本 %d）" % (
                PACKAGE_FORMAT, PACKAGE_VERSION,
                record.get("name") or project_id, int(record.get("revision") or 0)),
            "导出时间：%s · 导出服务：%s" % (exported, PACKAGE_SERVICE),
            "project.json 是这个项目的完整读模型（与 GET /api/machining-dfm/projects/{id} 同一份形状）；"
            "里面指向图片的字段是包内相对路径 assets/<附件 id>.<后缀>，对着包根打开就能看到图。",
            "assets/ 里是原图（字节与服务端一致）；本项目没引用到的附件不在包里。",
            "本包由服务端按需生成：导出只读，不改动服务端任何数据。",
        )) + "\n"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("project.json", json.dumps(payload, ensure_ascii=False, indent=2))
            for entry, data in files:
                archive.writestr(entry, data)
            archive.writestr("README.txt", readme)
        return _package_filename(str(record.get("name") or "")), buffer.getvalue()

    # ---------------- projects ----------------

    def ensure_seed_project(self) -> None:
        with self.connect() as db:
            if db.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
                return
        state = self.bundle.project()
        part = str(state.get("G", {}).get("part") or "原文件数据").strip()
        self.create(f"原文件集成 · {part}", state)

    def defaults(self, *, inline_assets: bool = False) -> dict[str, Any]:
        ids, fallback = self._machine_refs()
        state = _project_state(self.bundle.project(), ids, fallback)
        return self.compose(state, inline_assets=inline_assets)

    @staticmethod
    def _summary(row: sqlite3.Row, settings_row: sqlite3.Row | None = None) -> dict[str, Any]:
        state = json.loads(row["state_json"])
        project = state.get("G") if isinstance(state.get("G"), dict) else {}
        if settings_row is not None:
            keys = settings_row.keys()
            customer = settings_row["customer"] if "customer" in keys else ""
            part = settings_row["part"] if "part" in keys else ""
        else:
            customer, part = project.get("cust", ""), project.get("part", "")
        return {
            "id": row["id"], "name": row["name"], "revision": row["revision"],
            "created": row["created"], "updated": row["updated"],
            "archived": bool(row["archived"]), "customer": customer, "part": part,
        }

    def _record(
        self,
        row: sqlite3.Row,
        *,
        inline_assets: bool = False,
        settings_row: sqlite3.Row | None = None,
        historical: bool = False,
    ) -> dict[str, Any]:
        """组装一条对外记录。

        ``historical=True``：这是 ``?revision=N`` 的历史版本。历史版本的 ``vh[]`` **必须**
        用它自己那份快照里的，不能拿"现在这张履历表"去覆盖——否则拿旧版本去对比/恢复时，
        看到的会是今天的履历（3a 之前没有履历表，历史路径本来就是读快照的，
        这里是把它原样保住）。``pr``/``is`` 维持 1b/2a 已经上线的口径（表是权威），不在本阶段改。
        """
        state = json.loads(row["state_json"])
        if settings_row is None and "G" not in state:
            # 迁移后 projects.state_json 只剩业务数组，项目信息从表里取
            settings_row = self.settings.find(row["id"])
        general = (
            self.settings.legacy_g(row=settings_row, inline=inline_assets,
                                   selections=self._selection_arrays(row["id"]))
            if settings_row is not None else None
        )
        processes = (
            legacy_processes(
                self.processes,
                self.process_tools,
                row["id"],
                inline_assets=inline_assets,
                asset_store=self.assets,
            )
            if self.project_business else None
        )
        issues = (
            legacy_issues(
                self.issues,
                row["id"],
                process_rows=self.processes.list_typed(row["id"], include_deleted=True),
                asset_store=self.assets,
                inline_assets=inline_assets,
            )
            if self.project_issues_enabled else None
        )
        return {
            **self._summary(row, settings_row),
            # 行级保存开关：前端据此决定"行级保存"还是老的内存 + 整份保存
            "process_table": self.project_business,
            "issue_table": self.project_issues_enabled,
            "selection_table": self.selections_enabled,
            "history_table": self.history_enabled,
            "changes_table": self.changes_enabled,
            "business_version": self.business_version,
            "state": self.compose(
                state, settings=general, inline_assets=inline_assets, processes=processes,
                issues=issues,
                history=None if historical else self._history_arrays(row["id"]),
            ),
        }

    def list(self, archived: bool = False) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM projects WHERE archived=? ORDER BY updated DESC", (int(archived),)
            ).fetchall()
            settings_rows = {
                item["project_id"]: item
                for item in db.execute("SELECT * FROM project_settings").fetchall()
            }
        return [self._summary(row, settings_rows.get(row["id"])) for row in rows]

    def get(
        self,
        project_id: str,
        revision: int | None = None,
        *,
        allow_archived: bool = False,
        inline_assets: bool = False,
    ) -> dict[str, Any]:
        with self.connect() as db:
            project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if project is None:
                raise HTTPException(404, "机加 DFM 项目不存在")
            if project["archived"] and not allow_archived:
                raise HTTPException(410, "项目已删除，可在“已删除项目”中恢复")
            if revision is None:
                return self._record(
                    project,
                    inline_assets=inline_assets,
                    settings_row=self.settings.find(project_id, db=db),
                )
            if self.history_enabled:
                # 3a 之后保存版本在 project_versions（只取这一行，不把 60 份快照全捞出来）
                saved = self.version_table.find_save(project_id, revision, db=db)
                old = None if saved is None else {
                    "id": project_id, "name": saved["name"], "revision": saved["revision"],
                    "state_json": saved["state_json"], "created": saved["created"],
                    "updated": saved["created"], "archived": 0,
                }
            else:
                old = db.execute(
                    "SELECT project_id AS id,name,revision,state_json,created,created AS updated,0 AS archived "
                    "FROM revisions WHERE project_id=? AND revision=?", (project_id, revision),
                ).fetchone()
        if old is None:
            raise HTTPException(404, "历史版本不存在")
        # 历史版本快照自带 G，按 JSON 还原（不可变历史）；vh[] 也用它自己快照里的
        return self._record(old, inline_assets=inline_assets, historical=True)

    def _encode_arrays(self, arrays: dict[str, Any]) -> str:
        """``projects.state_json`` 现在只存业务数组（项目信息在表里）。"""
        payload = _compact(arrays)
        if len(payload.encode("utf-8")) > MAX_STATE_BYTES:
            raise HTTPException(413, "项目数据超过 32 MB，请压缩或删除过大的项目图片后再保存")
        return payload

    def _stored_arrays(self, db, project_id: str, arrays: dict[str, Any], payload: str) -> str:
        """真正写进 ``projects.state_json`` 的字节：**表里已经有的那一份就不再存第二份**。

        口径 6（影子副本停写）：版本履历落表之后，项目行里那三份数组就是纯冗余 ——
        同一份数据两条路走，迟早会跑偏（改一处忘一处）。

        但清空是**逐键判断**的：只有"这张表能还原出这一份"时才丢。
        ``pr``/``is``/``vh`` 各自的表里一行都没有、而这次要写的是**非空数组**时照旧留着 ——
        那说明这一级其实还没迁完（比如开关被人手动调到 4、表却是空的），
        清掉就等于把老数据删了。空数组本来就没什么可丢的，直接清。

        ``payload`` 仍然照常算（大小上限照旧卡、版本快照照旧带全量数据），
        只是不再往项目行里重复存一份。
        """
        if self.legacy_shadow:
            return payload
        kept = {
            key: value for key, value in arrays.items()
            if isinstance(value, list) and value and not self._array_in_table(db, project_id, key)
        }
        return _compact(kept)

    def _array_in_table(self, db, project_id: str, key: str) -> bool:
        """这一份业务数组是不是已经在表里了（表是权威：行数算上回收站里的行）。"""
        if key == "pr":
            if not self.project_business:
                return False
            table, where = "project_processes", "project_id=?"
        elif key == "is":
            if not self.project_issues_enabled:
                return False
            table, where = "project_issues", "project_id=?"
        else:
            if not self.history_enabled:
                return False
            table, where = "project_versions", "project_id=? AND kind='history'"
        if not self._table_exists(db, table):
            return False
        return bool(db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", (project_id,)).fetchone()[0])

    def _materialise_inline_images(self, state: dict[str, Any]) -> dict[str, Any]:
        """整份 ``state`` 里任何内联图片（``data:image/...;base64,``）先落成附件，值换成附件地址。

        为什么必须在**做快照之前**做：快照是永久保留的（口径 1：每次保存都留版本、回滚靠它），
        直接拿请求里的原值做快照，几十 KB base64 就永久躺在库里了 —— 而"库里只存引用"是硬口径。
        线上真发生过：新建项目时页面上传的那张产品图（60 KB base64）被写进第 1 版快照，
        整个库扫内联图就会命中它（`tools/check_export_assets.mjs` 第 4 组）。
        """
        holders: list[_InlineImage] = []
        staged = _collect_inline_images(state, holders)
        if not holders:
            return state
        with self.assets.session() as db:
            for holder in holders:
                record = self.assets.put_data_url(holder.kind, holder.value, db=db)
                holder.url = self.assets.url(record["id"]) if record else ""
        return _resolve_inline_images(staged)

    def create(self, name: str, state: dict[str, Any], *,
               import_tables: bool = False) -> dict[str, Any]:
        """新建项目。

        ``import_tables``：**产品路径（HTTP `POST /projects`）传 True** —— 带过来的整份读模型
        直接拆进各域的表（见 ``import_state``），项目行里不再堆一份 JSON 影子副本。
        默认 False 是给测试与迁移工具用的"老形状"入口（只写 JSON、表留空），
        它们要靠这种形状来验"从 JSON 拆进表"这段逻辑。
        """
        ids, fallback = self._machine_refs()
        # 内联图片（页面上传的 data URL）先落成附件：快照与表里都只留引用
        state = self._materialise_inline_images(state)
        general, arrays = _split_project_state(state, ids, fallback)
        payload = self._encode_arrays(arrays)
        snapshot = _compact({"G": general, **arrays})
        now, project_id, clean_name = _stamp(), uuid.uuid4().hex, name.strip()
        if not clean_name:
            raise HTTPException(422, "项目名称不能为空")
        with self.connect() as db:
            db.execute(
                "INSERT INTO projects(id,name,revision,state_json,created,updated,archived) VALUES(?,?,?,?,?,?,0)",
                (project_id, clean_name, 1,
                 self._stored_arrays(db, project_id, arrays, payload), now, now),
            )
            if self.legacy_shadow:
                db.execute(
                    "INSERT INTO revisions(project_id,revision,name,state_json,created) VALUES(?,?,?,?,?)",
                    (project_id, 1, clean_name, snapshot, now),
                )
            if self.history_enabled:
                insert_save_row(db, project_id, 1, clean_name, snapshot, now)
            self._note_change({
                "entity": ENTITY_PROJECT, "action": ACTION_CREATE,
                "label": f"新建项目：{clean_name}", "record_id": None,
                "extra": {"name": clean_name},
            })
            self._flush_changes(db, project_id, 1, created=now)
        # 项目信息落成自己的一行（项目图片进附件库）
        self.settings.apply_state(project_id, {"G": general})
        # 口径 7（**新建项目也要落表**）：`POST /projects` 可以带一整份读模型过来
        # （页面上的「另存为新项目」就是这么干的）。以前这份 state 只会写进
        # `projects.state_json`，业务表一行都没有 —— 于是新项目/副本项目永远处在
        # "JSON 满、表空"的双存储状态：读模型走 JSON，页面上那几行**没有行 id**，
        # 行级保存根本无从下手（改一道工序都被迫整份保存）。
        # 现在：能力级别开着就直接拆进各域的表，项目一行也不往 JSON 里堆。
        if import_tables:
            self.import_state(project_id, {"G": general, **arrays})
        return self.get(project_id)

    def import_state(self, project_id: str, state: dict[str, Any]) -> dict[str, Any]:
        """把一整份读模型 ``state`` 拆进各域的表（口径：**表是最小单元**）。

        用在两个地方：新建/另存为项目（`create` 末尾）与老项目的补迁
        （`tools/catchup_project_tables.py`）。逐域**幂等**：某张表已经有行就跳过那一域
        （永不"先清空再灌"——口径 2 不做物理删除）。

        逐域兜底：某一域拆失败（比如外键指向的库行不存在）就把那一域**这次新建的行**删掉、
        让这一域继续留在 ``state_json`` 里（= 老行为），绝不出现"表里一半、JSON 里一半"。
        """
        report: dict[str, Any] = {"project_id": project_id, "domains": {}, "problems": []}
        general = state.get("G") or {}
        arrays = {key: state.get(key) or [] for key in ("pr", "is", "vh")}

        if arrays["pr"] and self.project_business \
                and not self.processes.count(project_id, include_deleted=True):
            report["domains"]["processes"] = self._import_processes(project_id, state)

        if arrays["is"] and self.project_issues_enabled \
                and not self.issues.count(project_id, include_deleted=True):
            report["domains"]["issues"] = self._import_issues(project_id, state)

        if self.selections_enabled and not self.selections.count(project_id, include_deleted=True) \
                and any(str(value or "").strip() for key in SELECTION_ARRAY_KEYS
                        for value in (general.get(key) or [])):
            report["domains"]["selections"] = self._import_selections(project_id, general)

        if arrays["vh"] and self.history_enabled \
                and not self._has_table_rows(project_id, "project_versions",
                                             "project_id=? AND kind='history'"):
            # 先把 ``vh`` 从 JSON 里摘掉再逐行落表：读模型有一条"表里没有的就从
            # state_json.vh 就地补建"的老逻辑，JSON 里还留着这一份的话，
            # 建一行会被补建逻辑看出"还缺"，于是灌成两份。
            with self.connect() as db:
                db.execute("UPDATE projects SET state_json=? WHERE id=?",
                           (self._encode_arrays({**arrays, "vh": []}), project_id))
            report["domains"]["history"] = self._import_history(project_id, arrays["vh"])

        # 落到 JSON 里的只剩"表里还没有的那几份"：正常情况下这里会变成 {}
        with self.connect() as db:
            db.execute("UPDATE projects SET state_json=? WHERE id=?",
                       (self._stored_arrays(db, project_id, arrays,
                                            self._encode_arrays(arrays)), project_id))
        return report

    def _import_processes(self, project_id: str, state: dict[str, Any]) -> dict[str, Any]:
        # 库从**服务端自己的库表**取，不依赖带过来的 state 里有没有 mdb/tdb：
        # 页面的整份读模型里有这两份（顺手用），别的调用方（补迁工具）没有也能绑上。
        machines = state.get("mdb") or [dict(row) for row in self.machines.list_legacy()]
        tools_library = state.get("tdb") or [dict(row) for row in self.tools.list_legacy()]
        try:
            return apply_split(self.processes, self.process_tools, project_id, state,
                               tools_library=tools_library, machines=machines)
        except Exception as error:  # noqa: BLE001 - 拆不动就整域回退（行删干净，数据仍在 JSON 里）
            self._drop_table_rows(project_id, ("project_processes", "project_process_tools"))
            raise HTTPException(422, f"把工序拆进表失败，已回退到 JSON：{error}") from error

    def _import_issues(self, project_id: str, state: dict[str, Any]) -> dict[str, Any]:
        try:
            return apply_issue_split(
                self.issues, project_id, state,
                process_rows=self.processes.list_typed(project_id, include_deleted=True),
            )
        except Exception as error:  # noqa: BLE001
            self._drop_table_rows(project_id, ("project_issues",))
            raise HTTPException(422, f"把问题清单拆进表失败，已回退到 JSON：{error}") from error

    def _import_selections(self, project_id: str, general: dict[str, Any]) -> dict[str, Any]:
        try:
            return split_selections(
                self.selections, project_id, general,
                categories=self._selection_categories(),
                library=self._selection_library(),
            )
        except Exception as error:  # noqa: BLE001
            self._drop_table_rows(project_id, (FIXTURE_TABLE, GAUGE_TABLE))
            raise HTTPException(422, f"把选型拆进表失败，已回退到 JSON：{error}") from error

    def _import_history(self, project_id: str, rows: list[Any]) -> dict[str, Any]:
        written = 0
        try:
            for row in rows:
                payload = row if isinstance(row, dict) else {}
                with self._quiet_changes():
                    self.create_project_history(project_id, dict(payload))
                written += 1
            return {"rows": written}
        except Exception as error:  # noqa: BLE001
            self._drop_table_rows(project_id, ("project_versions",), kind="history")
            raise HTTPException(422, f"把版本履历拆进表失败，已回退到 JSON：{error}") from error

    def _has_table_rows(self, project_id: str, table: str, where: str) -> bool:
        with self.connect() as db:
            if not self._table_exists(db, table):
                return False
            return bool(db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}",
                                   (project_id,)).fetchone()[0])

    def _drop_table_rows(self, project_id: str, tables: tuple[str, ...], *,
                         kind: str = "") -> None:
        """兜底：把**这次新建的**行物理删掉（只用在"刚拆失败、数据还在 JSON 里"的场合）。

        正常业务路径永不物理删除（口径 2）；这里删的是同一秒里刚建出来、还没被任何人
        看见的行，目的只是让这一域干净地回到"只在 JSON 里"的老行为。
        """
        with self.connect() as db:
            for table in tables:
                if not self._table_exists(db, table):
                    continue
                if table == "project_versions" and kind:
                    db.execute(f"DELETE FROM {table} WHERE project_id=? AND kind=?",
                               (project_id, kind))
                else:
                    db.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))

    def update(self, project_id: str, name: str, state: dict[str, Any], revision: int | None) -> dict[str, Any]:
        if revision is None:
            raise HTTPException(422, "保存已有项目时必须提供当前版本号")
        ids, fallback = self._machine_refs()
        # 同上：内联图片先落成附件，别让它进快照（快照永久保留）
        state = self._materialise_inline_images(state)
        general, arrays = _split_project_state(state, ids, fallback)
        payload, clean_name, now = self._encode_arrays(arrays), name.strip(), _stamp()
        snapshot = _compact({"G": general, **arrays})
        if not clean_name:
            raise HTTPException(422, "项目名称不能为空")
        with self.connect() as db:
            current = db.execute("SELECT revision,archived FROM projects WHERE id=?", (project_id,)).fetchone()
            if current is None:
                raise HTTPException(404, "机加 DFM 项目不存在")
            if current["archived"]:
                raise HTTPException(410, "已删除项目不能保存，请先恢复")
            if current["revision"] != revision:
                raise HTTPException(409, f"项目已被更新，服务器当前版本为 {current['revision']}，请重新载入")
            next_revision = revision + 1
            db.execute(
                "UPDATE projects SET name=?,revision=?,state_json=?,updated=? WHERE id=?",
                (clean_name, next_revision,
                 self._stored_arrays(db, project_id, arrays, payload), now, project_id),
            )
            if self.legacy_shadow:
                db.execute(
                    "INSERT INTO revisions(project_id,revision,name,state_json,created) VALUES(?,?,?,?,?)",
                    (project_id, next_revision, clean_name, snapshot, now),
                )
            if self.history_enabled:
                insert_save_row(db, project_id, next_revision, clean_name, snapshot, now)
            self._note_change({
                "entity": ENTITY_PROJECT, "action": ACTION_SAVE,
                "label": f"整份保存：{clean_name}（第 {next_revision} 版）", "record_id": None,
                "extra": {"name": clean_name, "revision": next_revision},
            })
            self._flush_changes(db, project_id, next_revision, created=now)
        self.settings.apply_state(project_id, {"G": general})
        return self.get(project_id)

    def archive(self, project_id: str, archived: bool) -> dict[str, Any]:
        with self.connect() as db:
            result = db.execute(
                "UPDATE projects SET archived=?,updated=? WHERE id=?", (int(archived), _stamp(), project_id)
            )
            if result.rowcount != 1:
                raise HTTPException(404, "机加 DFM 项目不存在")
        return self.get(project_id, allow_archived=True)

    # ---------------- 回收站（阶段 4：逻辑删除 + 恢复，永不物理删除） ----------------

    #: 回收站里允许恢复的基础库/字典表（接口层白名单：表名不在这里一律拒绝）
    TRASH_TABLES: dict[str, str] = {
        "machines": "设备库",
        "tools": "刀具库",
        "fixtures": "夹具库",
        "gauges": "检具库",
        "tool_groups": "刀具库分类",
        "tool_categories": "刀具类型",
        "fixture_centers": "模具中心",
        "gauge_categories": "检具类别",
    }

    def _referencing_projects(self, column: str, table: str, record_id: str) -> int:
        """有**几个项目**在引用这条库行（回收站里显示"被 N 个项目引用"）。"""
        with self.connect() as db:
            if not self._table_exists(db, table):
                return 0
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            if "deleted_at" in columns:
                sql = (f"SELECT COUNT(DISTINCT project_id) FROM {table} "
                       f"WHERE {column}=? AND deleted_at IS NULL")
            else:
                sql = f"SELECT COUNT(DISTINCT project_id) FROM {table} WHERE {column}=?"
            return int(db.execute(sql, (record_id,)).fetchone()[0])

    def _library_trash_items(self) -> list[dict[str, Any]]:
        """四个本体库 + 四张字典表的已删行（每条带引用数；现算，不落库）。"""
        items: list[dict[str, Any]] = []
        for table, label, subject, title_keys, refs in (
            ("machines", "设备库", self.machines, ("brand", "model", "id"),
             (("project_processes", "machine_id"),)),
            ("tools", "刀具库", self.tools, ("name", "tp", "id"),
             (("project_process_tools", "tool_id"), ("project_process_tools", "handle_id"),
              ("project_process_tools", "accessory_id"))),
            ("fixtures", "夹具库", self.fixtures, ("name", "id"),
             ((FIXTURE_TABLE, "fixture_id"),)),
            ("gauges", "检具库", self.gauges, ("name", "id"),
             ((GAUGE_TABLE, "gauge_id"),)),
        ):
            for row in subject.trash():
                references = max(
                    (self._referencing_projects(column, ref_table, row["id"])
                     for ref_table, column in refs),
                    default=0,
                )
                items.append({
                    "group": "基础库",
                    "entity": table,
                    "entity_label": label,
                    "table": table,
                    "record_id": row["id"],
                    "title": _first_text(row, title_keys),
                    "deleted_at": row.get("deleted_at") or "",
                    "deleted_by": row.get("deleted_by") or "",
                    "deleted_reason": row.get("deleted_reason") or "",
                    "references": references,
                })
        # 刀具库的两张字典（code 主键）与夹具/检具的两张字典（中文名主键）
        label_of = {"tool_groups": "刀具库分类", "tool_categories": "刀具类型"}
        for row in self.tool_dict.trash():
            table = str(row.get("table") or "")
            items.append({
                "group": "字典",
                "entity": table,
                "entity_label": label_of.get(table, "刀具字典"),
                "table": table,
                "record_id": row["code"],
                "title": f"{row['code']} {row['label']}".strip(),
                "deleted_at": row.get("deleted_at") or "",
                "deleted_by": row.get("deleted_by") or "",
                "deleted_reason": row.get("deleted_reason") or "",
                "references": self._referencing_projects(
                    "category" if table == "tool_categories" else "tool_group", "tools", row["code"]),
            })
        for table, label, subject, ref_table, ref_column in (
            ("fixture_centers", "模具中心", self.fixture_centers, "fixtures", "center"),
            ("gauge_categories", "检具类别", self.gauge_categories, "gauges", "category"),
        ):
            for row in subject.trash():
                items.append({
                    "group": "字典",
                    "entity": table,
                    "entity_label": label,
                    "table": table,
                    "record_id": row["name"],
                    "title": row["name"],
                    "deleted_at": row.get("deleted_at") or "",
                    "deleted_by": row.get("deleted_by") or "",
                    "deleted_reason": row.get("deleted_reason") or "",
                    "references": self._referencing_projects(ref_column, ref_table, row["name"]),
                })
        items.sort(key=lambda item: item["deleted_at"], reverse=True)
        return items

    def library_trash(self) -> dict[str, Any]:
        """全局回收站：已删项目 + 基础库/字典的已删行（查看给两个角色）。"""
        items = self._library_trash_items()
        with self.connect() as db:
            projects = db.execute(
                "SELECT id,name,updated FROM projects WHERE archived=1 ORDER BY updated DESC"
            ).fetchall()
        for row in projects:
            items.append({
                "group": "项目",
                "entity": "project",
                "entity_label": "项目",
                "table": "projects",
                "record_id": row["id"],
                "title": row["name"],
                "deleted_at": row["updated"],
                "deleted_by": "",
                "deleted_reason": "已删除项目（archived=1）",
                "references": 0,
            })
        return {"enabled": True, "items": items}

    def project_trash(self, project_id: str) -> dict[str, Any]:
        """本项目回收站：业务行按实体分组，每条带删除人/原因/牵连行数。"""
        self.get(project_id, allow_archived=True)
        items: list[dict[str, Any]] = []
        tool_rows = self.process_tools.recycle_bin(project_id)
        tools_of: dict[str, int] = {}
        for row in tool_rows:
            key = str(row.get("process_id") or "")
            tools_of[key] = tools_of.get(key, 0) + 1
        for entity, label, subject, title_keys in (
            ("process", "工序", self.processes, ("nm", "id")),
            ("tool", "工序刀具行", self.process_tools, ("tp", "id")),
            ("issue", "问题清单", self.issues, ("desc", "type", "id")),
            ("fixture_selection", "夹具选型", self.selections.fixtures, ("name_snapshot", "id")),
            ("gauge_selection", "检具选型", self.selections.gauges, ("name_snapshot", "id")),
            ("history", "版本履历", self.version_table, ("name", "content", "id")),
        ):
            for row in subject.recycle_bin(project_id):
                references = tools_of.get(str(row.get("id") or ""), 0) if entity == "process" else 0
                items.append({
                    "group": label,
                    "entity": entity,
                    "entity_label": label,
                    "table": subject.table,
                    "record_id": row.get("id") or "",
                    "title": _first_text(row, title_keys),
                    "deleted_at": row.get("deleted_at") or "",
                    "deleted_by": row.get("deleted_by") or "",
                    "deleted_reason": row.get("deleted_reason") or "",
                    "references": references,
                })
        items.sort(key=lambda item: item["deleted_at"], reverse=True)
        return {"enabled": True, "project_id": project_id, "items": items}

    def restore_trash_row(self, table: str, record_id: str, *, by: str = "") -> dict[str, Any]:
        """从回收站恢复一条库行/字典行（表名白名单；恢复**只给管理员**）。"""
        if table not in self.TRASH_TABLES:
            raise HTTPException(422, f"回收站不支持这张表：{table}")
        if table in ("machines", "tools", "fixtures", "gauges"):
            subject = getattr(self, table)
            return {"table": table, "record": subject.restore(record_id, by=by)}
        if table == "tool_groups":
            return {"table": table, "record": self.tool_dict.restore_group(record_id, by=by)}
        if table == "tool_categories":
            return {"table": table, "record": self.tool_dict.restore_category(record_id, by=by)}
        if table == "fixture_centers":
            return {"table": table, "record": self.fixture_centers.restore(record_id, by=by)}
        return {"table": table, "record": self.gauge_categories.restore(record_id, by=by)}

    def delete_project(self, project_id: str, *, by: str = "", reason: str = "") -> dict[str, Any]:
        """项目"删除" = 逻辑删除：``archived=1``（口径 2 没有彻底删除）+ 记一条变更流水。

        项目级动作**不递增项目版本**（没有数据改动，也不该造一个版本快照），
        所以流水直接写在当前版本上。
        """
        self.get(project_id, allow_archived=True)
        result = self.archive(project_id, True)
        name = str(result.get("name") or "")
        self._note_project_action(
            project_id, "delete",
            f"删除项目：{name}（进「已删除项目」，随时可恢复）",
            {"by": by, "reason": reason, "archived": True},
        )
        return result

    def restore_project(self, project_id: str, *, by: str = "") -> dict[str, Any]:
        """恢复已删除项目：``archived=0`` + 记一条变更流水（同样不递增版本）。"""
        self.get(project_id, allow_archived=True)
        result = self.archive(project_id, False)
        name = str(result.get("name") or "")
        self._note_project_action(project_id, "restore", f"恢复项目：{name}",
                                  {"by": by, "archived": False})
        return result

    def _note_project_action(self, project_id: str, action: str, label: str,
                             extra: dict[str, Any]) -> None:
        """项目级事件（删除/恢复）直接落一条流水：不递增版本、也不造快照。"""
        if not self.changes_enabled:
            return
        with self.connect() as db:
            row = db.execute("SELECT revision FROM projects WHERE id=?", (project_id,)).fetchone()
            revision = int(row["revision"]) if row else 0
            version_id = save_row_id(project_id, revision) if self.history_enabled else None
            self.change_table.insert_drafts(
                db, project_id,
                [{"entity": "project", "action": action, "label": label, "extra": extra}],
                version_id=version_id,
            )

    def versions(self, project_id: str) -> list[dict[str, Any]]:
        """保存版本列表。3a 之后读 ``project_versions``（``revisions`` 继续当影子副本）。"""
        self.get(project_id, allow_archived=True)
        if self.history_enabled:
            return version_listing(self.version_table, project_id)
        with self.connect() as db:
            rows = db.execute(
                "SELECT revision,name,created FROM revisions WHERE project_id=? ORDER BY revision DESC", (project_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------- settings / auth ----------------

    def public_settings(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT key,value_json FROM app_settings "
                "WHERE key NOT IN "
                "('token_secret','inspection_categories','fixture_categories','libraries_initialized',"
                "'category_schema_version','library_schema_version','tool_library_schema_version',"
                "'fixture_library_schema_version','gauge_library_schema_version')"
            ).fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def update_settings(self, site_title: str, autosave_ms: int) -> dict[str, Any]:
        now = _stamp()
        with self.connect() as db:
            for key, value in {"site_title": site_title.strip(), "autosave_ms": autosave_ms}.items():
                db.execute(
                    "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
                    (key, _compact(value), now),
                )
        return self.public_settings()

    def _setting(self, key: str) -> Any:
        with self.connect() as db:
            row = db.execute("SELECT value_json FROM app_settings WHERE key=?", (key,)).fetchone()
        if row is None:
            raise RuntimeError(f"后台配置缺少 {key}")
        return json.loads(row["value_json"])

    def login(self, role: str, password: str) -> dict[str, Any]:
        if role not in DEFAULT_PASSWORDS:
            raise HTTPException(422, "登录角色无效")
        with self.connect() as db:
            row = db.execute("SELECT * FROM auth_settings WHERE role=?", (role,)).fetchone()
        digest = _password_digest(password, bytes.fromhex(row["salt"]), row["iterations"])
        if not hmac.compare_digest(digest, row["password_hash"]):
            raise HTTPException(401, "密码错误")
        expires = int(time.time()) + 8 * 60 * 60
        payload = _compact({"role": role, "exp": expires, "nonce": secrets.token_hex(8)}).encode()
        encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        signature = hmac.new(bytes.fromhex(self._setting("token_secret")), encoded.encode(), hashlib.sha256).hexdigest()
        return {"token": f"{encoded}.{signature}", "role": role, "expires_at": expires}

    def authorize(self, token: str | None, required: str = "admin") -> str:
        if not token:
            raise HTTPException(401, "请先登录后台")
        try:
            encoded, signature = token.split(".", 1)
            expected = hmac.new(
                bytes.fromhex(self._setting("token_secret")), encoded.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            if int(payload["exp"]) < int(time.time()):
                raise HTTPException(401, "后台登录已过期，请重新登录")
            role = payload["role"]
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(401, "后台登录凭证无效") from exc
        if required == "admin" and role != "admin":
            raise HTTPException(403, "需要管理员权限")
        if required == "process" and role not in {"process", "admin"}:
            raise HTTPException(403, "需要工艺设置权限")
        return role

    def change_password(self, role: str, password: str) -> None:
        if role not in DEFAULT_PASSWORDS:
            raise HTTPException(422, "密码角色无效")
        salt, now = secrets.token_bytes(16), _stamp()
        with self.connect() as db:
            db.execute(
                "UPDATE auth_settings SET salt=?,password_hash=?,iterations=?,updated=? WHERE role=?",
                (salt.hex(), _password_digest(password, salt), PASSWORD_ITERATIONS, now, role),
            )


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value if scheme.lower() == "bearer" and value else None


def router_for(store_factory, static_dir: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/machining-dfm")
    def machining_dfm_page():
        return FileResponse(Path(static_dir) / "machining_dfm" / "index.html")

    @router.get("/api/machining-dfm/bootstrap")
    def bootstrap(project_id: str | None = None):
        store = store_factory()
        active = store.list(False)
        if not active:
            raise HTTPException(409, "没有可打开的项目，请先恢复一个已删除项目")
        selected = project_id or active[0]["id"]
        return {
            "project": store.get(selected), "projects": active,
            "config": store.public_settings(), "data_dir": str(store.root),
        }

    @router.get("/api/machining-dfm/projects")
    def list_projects(archived: bool = Query(False)):
        return {"projects": store_factory().list(archived)}

    @router.get("/api/machining-dfm/defaults")
    def project_defaults():
        return store_factory().defaults()

    @router.post("/api/machining-dfm/projects")
    def create_project(req: ProjectWrite):
        # 产品路径：新建/另存为带上来的整份读模型**直接拆进各域的表**（口径 7），
        # 新项目从第一秒起就是"表是最小单元"，页面上每行都有行 id、能行级保存
        return store_factory().create(req.name, req.state, import_tables=True)

    @router.get("/api/machining-dfm/projects/{project_id}")
    def get_project(project_id: str, revision: int | None = None, allow_archived: bool = False):
        return store_factory().get(project_id, revision, allow_archived=allow_archived)

    @router.put("/api/machining-dfm/projects/{project_id}")
    def update_project(project_id: str, req: ProjectWrite):
        return store_factory().update(project_id, req.name, req.state, req.revision)

    @router.post("/api/machining-dfm/projects/{project_id}/archive")
    def archive_project(project_id: str, archived: bool = Query(True),
                        authorization: str | None = Header(None)):
        """旧版归档/取消归档入口（页面已改用 ``DELETE /projects/{id}`` + ``/restore``）。

        留着只为兼容老调用方，但**权限口径与新入口一致**：归档等于把项目从列表里拿掉，
        不能让没登录的人干这事。
        """
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return store.archive(project_id, archived)

    # ---------------- 回收站（阶段 4：逻辑删除，永不物理删除） ----------------
    # 查看给两个角色（admin / process 都能看），**恢复只给管理员**。

    @router.get("/api/machining-dfm/projects/{project_id}/trash")
    def project_trash(project_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "process")
        return store.project_trash(project_id)

    @router.get("/api/machining-dfm/trash")
    def library_trash(authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "process")
        return store.library_trash()

    @router.post("/api/machining-dfm/trash/{table}/{record_id}/restore")
    def restore_trash_row(table: str, record_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        return {"restored": store.restore_trash_row(table, record_id, by=role)}

    @router.delete("/api/machining-dfm/projects/{project_id}")
    def delete_project(project_id: str, by: str = Query(""), reason: str = Query(""),
                       authorization: str | None = Header(None)):
        """项目"删除" = 逻辑删除（``archived=1``）：进"已删除项目"，随时可恢复。"""
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        return {"project": store.delete_project(project_id, by=by or role, reason=reason)}

    @router.post("/api/machining-dfm/projects/{project_id}/restore")
    def restore_project(project_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        return {"project": store.restore_project(project_id, by=role)}

    @router.get("/api/machining-dfm/projects/{project_id}/versions")
    def project_versions(project_id: str):
        return {"versions": store_factory().versions(project_id)}

    # ---------------- 导出文件包（阶段 5 · 口径 §7.0） ----------------
    # 便携单文件 HTML 已退休：导出改成两条能兑现的路 —— 前端「导出 JSON」（单文件、图内联）
    # 与这条「导出文件包」（zip：project.json + 本项目引用到的附件原图 + README.txt）。
    # **只读**：GET、不落库、不写 data/；项目已删除也能出包（与读同一口径）。

    @router.get("/api/machining-dfm/projects/{project_id}/export.zip")
    def export_project_package(project_id: str):
        """导出该项目为 zip 文件包（`project.json` + `assets/<id>.<ext>` + `README.txt`）。

        包内 ``project.json`` 与 ``GET /projects/{pid}`` 同一份形状，附件字段换成包内相对路径。
        """
        filename, payload = store_factory().export_package(project_id)
        return Response(
            content=payload,
            media_type="application/zip",
            headers={
                "content-disposition": _content_disposition(filename),
                "cache-control": "no-store",
            },
        )

    # ---------------- 项目信息 / Project settings ----------------
    # 项目信息（G 的建模字段）已独立成表：逐字段读写在 project_settings 一行里，
    # 项目图片走 assets；旧键 G 由 compose 精确还原，老页面与 PPT 契约不变。

    @router.get("/api/machining-dfm/project-settings/fields")
    def project_settings_fields():
        return store_factory().project_settings_fields()

    @router.get("/api/machining-dfm/projects/{project_id}/settings")
    def get_project_settings(project_id: str):
        return store_factory().project_settings(project_id)

    @router.patch("/api/machining-dfm/projects/{project_id}/settings")
    def patch_project_settings(project_id: str, payload: dict[str, Any]):
        """改一个格存一个格：项目信息行级保存（同时递增项目版本并留快照）。"""
        return {"project": store_factory().save_project_settings(project_id, payload, partial=True)}

    @router.put("/api/machining-dfm/projects/{project_id}/settings")
    def put_project_settings(project_id: str, payload: dict[str, Any]):
        """整份项目信息保存（旧页面／批量导入用）。"""
        return {"project": store_factory().save_project_settings(project_id, payload, partial=False)}

    @router.put("/api/machining-dfm/projects/{project_id}/photos/{slot}")
    async def upload_project_photo(project_id: str, slot: str, request: Request):
        data = await request.body()
        return {
            "project": store_factory().set_project_photo(
                project_id, slot, data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/projects/{project_id}/photos/{slot}")
    def delete_project_photo(project_id: str, slot: str):
        return {"project": store_factory().clear_project_photo(project_id, slot)}

    # ---------------- 工序 / 工序刀具行（1b） ----------------
    # 与项目信息同一套写法：行级 PATCH、排序、逻辑删除（回收站可恢复），
    # 每次写都递增项目版本并留一个版本快照；返回整个项目记录给前端 adopt。

    # ---------------- 问题清单（阶段 2a） ----------------
    # 与工序同一套写法：行级 PATCH、排序、逻辑删除（回收站可恢复）、图片走附件库；
    # 每次写都递增项目版本并留一个版本快照。外键：process_id → project_processes。

    @router.get("/api/machining-dfm/projects/{project_id}/issues")
    def list_project_issues(project_id: str, include_deleted: bool = Query(False)):
        return store_factory().project_issues(project_id, include_deleted=include_deleted)

    @router.post("/api/machining-dfm/projects/{project_id}/issues")
    def create_project_issue(project_id: str, payload: dict[str, Any]):
        return {"project": store_factory().create_project_issue(project_id, payload)}

    @router.patch("/api/machining-dfm/projects/{project_id}/issues/{issue_id}")
    def patch_project_issue(project_id: str, issue_id: str, payload: dict[str, Any]):
        """改一个格存一个格：问题清单行级保存。"""
        return {"project": store_factory().update_project_issue(project_id, issue_id, payload)}

    @router.delete("/api/machining-dfm/projects/{project_id}/issues/{issue_id}")
    def delete_project_issue(project_id: str, issue_id: str, by: str = Query(""),
                             reason: str = Query("")):
        """逻辑删除（永不物理删除）：进回收站，可恢复。"""
        return {"project": store_factory().delete_project_issue(project_id, issue_id,
                                                                by=by, reason=reason)}

    @router.post("/api/machining-dfm/projects/{project_id}/issues/{issue_id}/restore")
    def restore_project_issue(project_id: str, issue_id: str):
        return {"project": store_factory().restore_project_issue(project_id, issue_id)}

    @router.post("/api/machining-dfm/projects/{project_id}/issues/reorder")
    def reorder_project_issues(project_id: str, payload: dict[str, Any]):
        return {"project": store_factory().reorder_project_issues(
            project_id, payload.get("ids") or [])}

    @router.put("/api/machining-dfm/projects/{project_id}/issues/{issue_id}/photo/{slot}")
    async def upload_issue_photo(project_id: str, issue_id: str, slot: str, request: Request):
        data = await request.body()
        return {
            "project": store_factory().set_issue_photo(
                project_id, issue_id, slot, data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/projects/{project_id}/issues/{issue_id}/photo/{slot}")
    def delete_issue_photo(project_id: str, issue_id: str, slot: str):
        return {"project": store_factory().clear_issue_photo(project_id, issue_id, slot)}

    # ---- 夹具选型 / 检具选型（项目级，各自一张表、各自一套接口） ----
    # 坐标是 (格子下标)，格子顺序 = 类别字典顺序（夹具按模具中心、检具按检具类别）。
    # 两条路径完全同构，所以下面用同一段生成逻辑挂两遍，不再有 kind 参数满天飞。

    def _selection_routes(kind: str, path: str, label: str, id_key: str) -> None:
        @router.get(f"/api/machining-dfm/projects/{{project_id}}/{path}")
        def list_selection(project_id: str, _kind: str = kind):
            return store_factory().project_selection(project_id, _kind)

        @router.put(f"/api/machining-dfm/projects/{{project_id}}/{path}/{{slot}}")
        def put_selection(project_id: str, slot: int, payload: dict[str, Any], _kind: str = kind):
            """选一格：``{id_key: …}``（库行 id）或 ``{"legacy_key": "类别|名称"}``。"""
            return {"project": store_factory().save_project_selection(
                project_id, _kind, slot, payload)}

        # 兼容语义：有的前端习惯用 PATCH 表达"改这一格的某一个字段"（例如只改"是否报价"）
        @router.patch(f"/api/machining-dfm/projects/{{project_id}}/{path}/{{slot}}")
        def patch_selection(project_id: str, slot: int, payload: dict[str, Any], _kind: str = kind):
            return {"project": store_factory().save_project_selection(
                project_id, _kind, slot, payload)}

        @router.delete(f"/api/machining-dfm/projects/{{project_id}}/{path}/{{slot}}")
        def delete_selection(project_id: str, slot: int, _kind: str = kind):
            """清空一格（行保留，"是否报价"的勾选也留着，历史在版本里可查）。"""
            return {"project": store_factory().clear_project_selection(project_id, _kind, slot)}

    _selection_routes(KIND_FIXTURE, "fixtures", "夹具选型", "fixture_id")
    _selection_routes(KIND_GAUGE, "gauges", "检具选型", "gauge_id")

    # 老接口：两类一起给（``slots`` 按 kind 分组），页面已改成两个页签各打各的
    @router.get("/api/machining-dfm/projects/{project_id}/selections")
    def list_project_selections(project_id: str):
        return store_factory().project_selections(project_id)

    # ---- 版本履历（3a）：一行 = 页面上那四个格子（日期/版本号/变更内容/变更人） ----

    @router.get("/api/machining-dfm/projects/{project_id}/history")
    def list_project_history(project_id: str, recycle: bool = Query(False)):
        """在用的履历行；``recycle=true`` 给回收站（逻辑删除的行）。"""
        return store_factory().project_history(project_id, recycle=recycle)

    @router.post("/api/machining-dfm/projects/{project_id}/history")
    def create_project_history(project_id: str, payload: dict[str, Any] | None = None):
        return {"project": store_factory().create_project_history(project_id, payload)}

    @router.patch("/api/machining-dfm/projects/{project_id}/history/{record_id}")
    def patch_project_history(project_id: str, record_id: str, payload: dict[str, Any]):
        """改一个格存一个格：``{"dt": "2026-09-18"}`` / ``{"ds": "改了什么"}``。"""
        return {"project": store_factory().save_project_history(project_id, record_id, payload)}

    @router.delete("/api/machining-dfm/projects/{project_id}/history/{record_id}")
    def delete_project_history(project_id: str, record_id: str, by: str = Query(""),
                               reason: str = Query("")):
        """逻辑删除（永不物理删除）：进回收站，可恢复。"""
        return {"project": store_factory().delete_project_history(project_id, record_id,
                                                                 by=by, reason=reason)}

    @router.post("/api/machining-dfm/projects/{project_id}/history/{record_id}/restore")
    def restore_project_history(project_id: str, record_id: str):
        return {"project": store_factory().restore_project_history(project_id, record_id)}

    @router.post("/api/machining-dfm/projects/{project_id}/history/reorder")
    def reorder_project_history(project_id: str, payload: dict[str, Any]):
        return {"project": store_factory().reorder_project_history(
            project_id, payload.get("ids") or [])}

    # ---------------- 变更流水（阶段 3b，只读） ----------------
    # 一行 = 一次改动里的一个实体；由行级写入点自动记录（不需要前端调用）。
    @router.get("/api/machining-dfm/projects/{project_id}/changes")
    def list_project_changes(project_id: str, limit: int = Query(200), entity: str = Query(""),
                             action: str = Query(""), recycle: bool = Query(False)):
        return store_factory().project_changes(project_id, limit=limit, entity=entity,
                                               action=action, recycle=recycle)

    @router.get("/api/machining-dfm/projects/{project_id}/processes")
    def list_project_processes(project_id: str, include_deleted: bool = Query(False)):
        return store_factory().project_processes(project_id, include_deleted=include_deleted)

    @router.post("/api/machining-dfm/projects/{project_id}/processes")
    def create_project_process(project_id: str, payload: dict[str, Any]):
        return {"project": store_factory().create_project_process(project_id, payload)}

    @router.patch("/api/machining-dfm/projects/{project_id}/processes/{process_id}")
    def patch_project_process(project_id: str, process_id: str, payload: dict[str, Any]):
        """改一个格存一个格：工序行级保存。"""
        return {"project": store_factory().update_project_process(project_id, process_id, payload)}

    @router.delete("/api/machining-dfm/projects/{project_id}/processes/{process_id}")
    def delete_project_process(project_id: str, process_id: str, by: str = Query(""),
                               reason: str = Query("")):
        """逻辑删除（永不物理删除）：刀具行一并进回收站，可恢复。"""
        return {"project": store_factory().delete_project_process(project_id, process_id,
                                                                 by=by, reason=reason)}

    @router.post("/api/machining-dfm/projects/{project_id}/processes/{process_id}/restore")
    def restore_project_process(project_id: str, process_id: str):
        return {"project": store_factory().restore_project_process(project_id, process_id)}

    # ---------------- 工序设备选择（项目 → 工序 → 设备） ----------------
    # 设备是**每道工序自己的一格**：单独两个接口，别混在工序行级保存里，
    # 页面上的"设备选择"下拉框就打这两个（选了 / 清空）。
    @router.put("/api/machining-dfm/projects/{project_id}/processes/{process_id}/machine")
    def set_project_process_machine(project_id: str, process_id: str, payload: dict[str, Any]):
        """选设备：``{"machine_id": "..."}``（也认老的 ``{"mid": "..."}``）。"""
        return {"project": store_factory().set_project_process_machine(
            project_id, process_id, payload)}

    @router.delete("/api/machining-dfm/projects/{project_id}/processes/{process_id}/machine")
    def clear_project_process_machine(project_id: str, process_id: str):
        """清空这道工序的设备选择（读模型退回兜底机型）。"""
        return {"project": store_factory().clear_project_process_machine(project_id, process_id)}

    @router.post("/api/machining-dfm/projects/{project_id}/processes/reorder")
    def reorder_project_processes(project_id: str, payload: dict[str, Any]):
        ids = payload.get("ids")
        if not isinstance(ids, list):
            raise HTTPException(422, "排序请求必须包含 ids 数组")
        return {"project": store_factory().reorder_project_processes(project_id, ids)}

    @router.put("/api/machining-dfm/projects/{project_id}/processes/{process_id}/photo")
    async def upload_process_photo(project_id: str, process_id: str, request: Request):
        data = await request.body()
        return {
            "project": store_factory().set_process_photo(
                project_id, process_id, "layout", data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/projects/{project_id}/processes/{process_id}/photo")
    def delete_process_photo(project_id: str, process_id: str):
        return {"project": store_factory().clear_process_photo(project_id, process_id)}

    @router.post("/api/machining-dfm/projects/{project_id}/processes/{process_id}/tools")
    def create_project_tool(project_id: str, process_id: str, payload: dict[str, Any]):
        return {"project": store_factory().create_project_tool(project_id, process_id, payload)}

    @router.post("/api/machining-dfm/projects/{project_id}/processes/{process_id}/tools/reorder")
    def reorder_project_tools(project_id: str, process_id: str, payload: dict[str, Any]):
        ids = payload.get("ids")
        if not isinstance(ids, list):
            raise HTTPException(422, "排序请求必须包含 ids 数组")
        return {"project": store_factory().reorder_project_tools(project_id, process_id, ids)}

    @router.patch("/api/machining-dfm/projects/{project_id}/tools/{tool_id}")
    def patch_project_tool(project_id: str, tool_id: str, payload: dict[str, Any]):
        """改一个格存一个格：工序刀具行级保存（含快照价）。"""
        return {"project": store_factory().update_project_tool(project_id, tool_id, payload)}

    @router.delete("/api/machining-dfm/projects/{project_id}/tools/{tool_id}")
    def delete_project_tool(project_id: str, tool_id: str, by: str = Query(""),
                            reason: str = Query("")):
        return {"project": store_factory().delete_project_tool(project_id, tool_id,
                                                              by=by, reason=reason)}

    @router.post("/api/machining-dfm/projects/{project_id}/tools/{tool_id}/restore")
    def restore_project_tool(project_id: str, tool_id: str):
        return {"project": store_factory().restore_project_tool(project_id, tool_id)}

    @router.put("/api/machining-dfm/projects/{project_id}/tools/{tool_id}/photo")
    async def upload_tool_photo(project_id: str, tool_id: str, request: Request):
        data = await request.body()
        return {
            "project": store_factory().set_tool_photo(
                project_id, tool_id, data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/projects/{project_id}/tools/{tool_id}/photo")
    def delete_tool_photo(project_id: str, tool_id: str):
        return {"project": store_factory().clear_tool_photo(project_id, tool_id)}

    # ---------------- 设备库 / Machine DB ----------------

    @router.get("/api/machining-dfm/machines/fields")
    def machine_fields():
        return {"fields": store_factory().machine_fields()}

    @router.get("/api/machining-dfm/machines")
    def list_machines():
        store = store_factory()
        return {
            "machines": store.machines.list_typed(),
            "fields": store.machine_fields(),
            "fallback_id": store.machines.default_ref(),
            "count": store.machines.count(),
        }

    @router.post("/api/machining-dfm/machines/reorder")
    def reorder_machines(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        ids = payload.get("ids")
        if not isinstance(ids, list):
            raise HTTPException(422, "排序请求必须包含 ids 数组")
        return {
            "machines": store.machines.reorder(ids),
            "fallback_id": store.machines.default_ref(),
        }

    @router.post("/api/machining-dfm/machines")
    def create_machine(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"machine": store.machines.create(payload), "count": store.machines.count()}

    @router.patch("/api/machining-dfm/machines/{machine_id}")
    def update_machine(machine_id: str, payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"machine": store.machines.update(machine_id, payload)}

    @router.delete("/api/machining-dfm/machines/{machine_id}")
    def delete_machine(
        machine_id: str,
        force: bool = Query(False),
        authorization: str | None = Header(None),
    ):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        usage = store.machine_usage(machine_id)
        if usage and not force:
            projects = "、".join(sorted({item["project"] for item in usage}))
            raise HTTPException(409, f"该设备已被项目引用（{projects}），删除后这些工序将改用默认机型。确认请加 force=true")
        # 口径 2：逻辑删除（回收站可恢复），删除人与原因记在行上
        return {"removed": store.machines.delete(machine_id, by=role), "usage": usage}

    @router.put("/api/machining-dfm/machines/{machine_id}/default")
    def set_default_machine(machine_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {
            "machines": store.machines.set_fallback(machine_id),
            "fallback_id": store.machines.default_ref(),
        }

    @router.put("/api/machining-dfm/machines/{machine_id}/photo")
    async def upload_machine_photo(
        machine_id: str,
        request: Request,
        authorization: str | None = Header(None),
    ):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        data = await request.body()
        return {
            "machine": store.machines.set_attachment(
                machine_id, "photo", data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/machines/{machine_id}/photo")
    def delete_machine_photo(machine_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"machine": store.machines.clear_attachment(machine_id, "photo")}

    @router.put("/api/machining-dfm/machines/{machine_id}/doc")
    async def upload_machine_doc(
        machine_id: str,
        request: Request,
        name: str = Query(""),
        authorization: str | None = Header(None),
    ):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        data = await request.body()
        filename = name or str(request.headers.get("x-file-name") or "")
        return {
            "machine": store.machines.set_attachment(
                machine_id, "doc", data, request.headers.get("content-type"), filename
            )
        }

    @router.delete("/api/machining-dfm/machines/{machine_id}/doc")
    def delete_machine_doc(machine_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"machine": store.machines.clear_attachment(machine_id, "doc")}

    @router.get("/api/machining-dfm/tools/fields")
    def tool_fields():
        return store_factory().tool_fields()

    @router.get("/api/machining-dfm/tools")
    def list_tools():
        store = store_factory()
        return {
            "tools": store.tools.list_typed(),
            "fields": store.tool_fields(),
            "count": store.tools.count(),
        }

    @router.post("/api/machining-dfm/tools/reorder")
    def reorder_tools(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        ids = payload.get("ids")
        if not isinstance(ids, list):
            raise HTTPException(422, "排序请求必须包含 ids 数组")
        return {"tools": store.tools.reorder(ids)}

    @router.post("/api/machining-dfm/tools")
    def create_tool(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"tool": store.tools.create(payload), "count": store.tools.count()}

    @router.patch("/api/machining-dfm/tools/{tool_id}")
    def update_tool(tool_id: str, payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"tool": store.tools.update(tool_id, payload)}

    @router.delete("/api/machining-dfm/tools/{tool_id}")
    def delete_tool(tool_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        row = store.tools.find(tool_id)
        # 项目工序行自带刀具参数，只有刀柄/配件价格按名称查库：删除不阻塞，仅提示引用。
        usage = store.tool_usage(row["name"], row["tool_group"]) if row is not None else []
        return {"removed": store.tools.delete(tool_id, by=role), "usage": usage}

    @router.put("/api/machining-dfm/tools/{tool_id}/photo")
    async def upload_tool_photo(tool_id: str, request: Request, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        data = await request.body()
        return {
            "tool": store.tools.set_attachment(
                tool_id, "photo", data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/tools/{tool_id}/photo")
    def delete_tool_photo(tool_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"tool": store.tools.clear_attachment(tool_id, "photo")}

    @router.get("/api/machining-dfm/tool-dictionaries")
    def tool_dictionaries():
        store = store_factory()
        return store.tool_dictionaries()

    @router.post("/api/machining-dfm/tool-groups")
    def create_tool_group(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"group": store.tool_dict.create_group(payload)}

    @router.patch("/api/machining-dfm/tool-groups/{code}")
    def update_tool_group(code: str, payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"group": store.tool_dict.update_group(code, payload)}

    @router.delete("/api/machining-dfm/tool-groups/{code}")
    def delete_tool_group(code: str, authorization: str | None = Header(None)):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        return {"removed": store.tool_dict.delete_group(code, by=role)}

    @router.post("/api/machining-dfm/tool-categories")
    def create_tool_category(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"category": store.tool_dict.create_category(payload)}

    @router.patch("/api/machining-dfm/tool-categories/{code}")
    def update_tool_category(code: str, payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"category": store.tool_dict.update_category(code, payload)}

    @router.delete("/api/machining-dfm/tool-categories/{code}")
    def delete_tool_category(code: str, authorization: str | None = Header(None)):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        return {"removed": store.tool_dict.delete_category(code, by=role)}

    def register_typed_library(name: str, singular: str, label: str, library_getter, fields_getter, usage_getter) -> None:
        """夹具库/检具库共用的行级接口（与设备库、刀具库同一套约定）。"""

        @router.get(f"/api/machining-dfm/{name}/fields", name=f"{name}_fields")
        def library_fields():
            return fields_getter(store_factory())

        @router.get(f"/api/machining-dfm/{name}", name=f"list_{name}")
        def library_list():
            store = store_factory()
            library = library_getter(store)
            return {
                name: library.list_typed(),
                "fields": fields_getter(store),
                "count": library.count(),
            }

        @router.post(f"/api/machining-dfm/{name}/reorder", name=f"reorder_{name}")
        def library_reorder(payload: dict[str, Any], authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            ids = payload.get("ids")
            if not isinstance(ids, list):
                raise HTTPException(422, "排序请求必须包含 ids 数组")
            return {name: library_getter(store).reorder(ids)}

        @router.post(f"/api/machining-dfm/{name}", name=f"create_{name}")
        def library_create(payload: dict[str, Any], authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            library = library_getter(store)
            return {singular: library.create(payload), "count": library.count()}

        @router.patch(f"/api/machining-dfm/{name}/{{row_id}}", name=f"update_{name}")
        def library_update(row_id: str, payload: dict[str, Any], authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            return {singular: library_getter(store).update(row_id, payload)}

        @router.delete(f"/api/machining-dfm/{name}/{{row_id}}", name=f"delete_{name}")
        def library_delete(row_id: str, authorization: str | None = Header(None)):
            store = store_factory()
            role = store.authorize(_bearer(authorization), "admin")
            library = library_getter(store)
            row = library.find(row_id)
            usage = usage_getter(store, row) if row else []
            # 项目侧按名称拼的选择键引用本库，删除不阻塞，只回报哪些项目在用
            # 口径 2：逻辑删除（回收站可恢复），谁删的记在行上
            return {"removed": library.delete(row_id, by=role), "usage": usage}

        @router.put(f"/api/machining-dfm/{name}/{{row_id}}/photo", name=f"upload_{name}_photo")
        async def library_photo(row_id: str, request: Request, authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            data = await request.body()
            return {
                singular: library_getter(store).set_attachment(
                    row_id, "photo", data, request.headers.get("content-type")
                )
            }

        @router.delete(f"/api/machining-dfm/{name}/{{row_id}}/photo", name=f"clear_{name}_photo")
        def library_photo_clear(row_id: str, authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            return {singular: library_getter(store).clear_attachment(row_id, "photo")}

    def register_named_dictionary(name: str, label: str, dictionary_getter, usage_getter) -> None:
        """类别字典接口：增、改顺序、删（默认 409，带 cascade=1 连同数据一起删）。"""

        @router.get(f"/api/machining-dfm/{name}", name=f"list_{name}")
        def dictionary_list():
            store = store_factory()
            return {"rows": dictionary_getter(store).names(), "usage": usage_getter(store)}

        @router.post(f"/api/machining-dfm/{name}", name=f"create_{name}")
        def dictionary_create(payload: dict[str, Any], authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            return {"row": dictionary_getter(store).create(payload)}

        @router.patch(f"/api/machining-dfm/{name}/{{item}}", name=f"update_{name}")
        def dictionary_update(item: str, payload: dict[str, Any], authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            return {"row": dictionary_getter(store).update(item, payload)}

        @router.delete(f"/api/machining-dfm/{name}/{{item}}", name=f"delete_{name}")
        def dictionary_delete(
            item: str, cascade: int = 0, authorization: str | None = Header(None)
        ):
            store = store_factory()
            role = store.authorize(_bearer(authorization), "admin")
            return {"removed": dictionary_getter(store).delete(
                item, cascade=bool(cascade), by=role)}

    register_typed_library(
        "fixtures",
        "fixture",
        "夹具",
        lambda store: store.fixtures,
        lambda store: store.fixture_fields(),
        lambda store, row: store.fixture_usage(row["center"], row["name"]),
    )
    register_typed_library(
        "gauges",
        "gauge",
        "检具",
        lambda store: store.gauges,
        lambda store: store.gauge_fields(),
        lambda store, row: store.gauge_usage(row["category"], row["name"], row["drawing"]),
    )
    register_named_dictionary(
        "fixture-centers", "模具中心", lambda store: store.fixture_centers,
        lambda store: store.fixture_centers.usage(),
    )
    register_named_dictionary(
        "gauge-categories", "检具类别", lambda store: store.gauge_categories,
        lambda store: store.gauge_categories.usage(),
    )

    @router.get("/api/machining-dfm/library-dictionaries")
    def library_dictionaries():
        return store_factory().library_dictionaries()

    @router.get("/api/machining-dfm/assets/{asset_id}")
    def get_asset(
        asset_id: str,
        download: bool = Query(False),
        if_none_match: str | None = Header(None),
    ):
        store = store_factory()
        record, path = store.asset(asset_id)
        etag = f'"{record["sha256"]}"'
        headers = {"cache-control": "private, max-age=86400", "etag": etag}
        # 内容寻址 + 内容 ETag：客户端带着同一个 ETag 回来即内容未变。
        if if_none_match and if_none_match.strip() in {etag, record["sha256"]}:
            return Response(status_code=304, headers=headers)
        if download:
            suffix = Path(record["path"]).suffix
            return FileResponse(
                path,
                media_type=record["mime"],
                filename=record["name"] or f"{asset_id}{suffix}",
                headers=headers,
            )
        return FileResponse(path, media_type=record["mime"], headers=headers)

    # ---------------- 兼容入口（整库保存：只为缓存了旧 JS 的页面保留） ----------------

    @router.get("/api/machining-dfm/libraries")
    def get_libraries():
        store = store_factory()
        libraries = store.libraries()
        return {
            "libraries": libraries,
            "counts": {
                "mdb": store.machines.count(),
                "tdb": store.tools.count(),
                "fdb": store.fixtures.count(),
                "idb": store.gauges.count(),
            },
        }

    @router.put("/api/machining-dfm/libraries")
    def update_libraries(req: LibraryWrite, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"ok": True, "counts": store.replace_libraries(req.model_dump())}

    @router.get("/api/machining-dfm/config")
    def get_config():
        return store_factory().public_settings()

    @router.put("/api/machining-dfm/config")
    def update_config(req: SettingsWrite, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return store.update_settings(req.site_title, req.autosave_ms)

    @router.post("/api/machining-dfm/auth/login")
    def login(req: LoginRequest):
        return store_factory().login(req.role, req.password)

    @router.put("/api/machining-dfm/auth/password")
    def change_password(req: PasswordChange, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        store.change_password(req.role, req.password)
        return {"ok": True, "role": req.role}

    return router
