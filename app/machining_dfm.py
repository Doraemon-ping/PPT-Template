"""Dedicated, data-decoupled backend for the machining DFM application."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


PROJECT_ARRAYS = ("pr", "is", "vh")
LIBRARY_TABLES = {"mdb": "equipment", "tdb": "tools", "fdb": "fixtures", "idb": "gauges"}
MAX_STATE_BYTES = 32 * 1024 * 1024
PASSWORD_ITERATIONS = 260_000
DEFAULT_PASSWORDS = {"process": "TP123456", "admin": "TP23456"}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _project_state(state: dict[str, Any]) -> dict[str, Any]:
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
    return result


def _encode_project_state(state: dict[str, Any]) -> str:
    try:
        payload = _compact(_project_state(state))
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"项目数据无法序列化：{exc}") from exc
    if len(payload.encode("utf-8")) > MAX_STATE_BYTES:
        raise HTTPException(413, "项目数据超过 32 MB，请压缩或删除过大的项目图片后再保存")
    return payload


def _password_digest(password: str, salt: bytes, iterations: int = PASSWORD_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


class ProjectWrite(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    state: dict[str, Any]
    revision: int | None = None


class LibraryWrite(BaseModel):
    mdb: list[dict[str, Any]]
    tdb: list[dict[str, Any]]
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


class SettingsWrite(BaseModel):
    site_title: str = Field(min_length=1, max_length=100)
    autosave_ms: int = Field(ge=500, le=10_000)


class MachiningDFMStore:
    """Projects, shared master data, and backend auth in one isolated SQLite DB."""

    def __init__(self, root: Path, seed_file: Path):
        self.root = Path(root)
        self.seed_file = Path(seed_file)
        self.root.mkdir(parents=True, exist_ok=True)
        self.backup_dir = self.root / "backups"
        self.db_path = self.root / "machining_dfm.sqlite3"
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL,
                    state_json TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS revisions(
                    project_id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL,
                    state_json TEXT NOT NULL, created TEXT NOT NULL,
                    PRIMARY KEY(project_id, revision),
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS equipment(
                    id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL,
                    payload_json TEXT NOT NULL, updated TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tools(
                    id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL,
                    payload_json TEXT NOT NULL, updated TEXT NOT NULL
                );
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
            )
        self._backup_before_decoupling()
        self._initialize_shared_data()
        self._migrate_project_snapshots()
        self.ensure_seed_project()

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

    def _seed(self) -> dict[str, Any]:
        if not self.seed_file.is_file():
            raise RuntimeError(f"机加 DFM 初始数据不存在：{self.seed_file}")
        return json.loads(self.seed_file.read_text(encoding="utf-8"))

    def _backup_before_decoupling(self) -> None:
        backup = self.backup_dir / "pre-library-decoupling.sqlite3"
        if not self.db_path.is_file() or backup.exists():
            return
        with self.connect() as db:
            row = db.execute("SELECT state_json FROM projects LIMIT 1").fetchone()
        if not row or not any(key in json.loads(row["state_json"]) for key in LIBRARY_TABLES):
            return
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        source, target = sqlite3.connect(self.db_path), sqlite3.connect(backup)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()

    def _initialize_shared_data(self) -> None:
        seed = self._seed()
        with self.connect() as db:
            now = _stamp()
            initialized = db.execute(
                "SELECT value_json FROM app_settings WHERE key='libraries_initialized'"
            ).fetchone()
            if initialized is None:
                legacy = db.execute("SELECT state_json FROM projects ORDER BY updated DESC LIMIT 1").fetchone()
                legacy_state = json.loads(legacy["state_json"]) if legacy else {}
                for key, table in LIBRARY_TABLES.items():
                    rows = legacy_state.get(key) if isinstance(legacy_state.get(key), list) else seed.get(key, [])
                    self._replace_library(db, table, rows)
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
                "inspection_categories": seed.get("G", {}).get("icnX", []),
                "fixture_categories": seed.get("G", {}).get("fcnX", []),
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
                    current = db.execute(
                        "SELECT value_json FROM app_settings WHERE key=?", (key,)
                    ).fetchone()
                    existing = json.loads(current["value_json"]) if current else []
                    base = seed.get("G", {}).get(seed_key, [])
                    merged = list(dict.fromkeys([*base, *existing]))
                    db.execute(
                        "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
                        (key, _compact(merged), now),
                    )
                db.execute(
                    "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?)",
                    ("category_schema_version", "1", now),
                )

    def _migrate_project_snapshots(self) -> None:
        with self.connect() as db:
            rows = db.execute("SELECT id,state_json FROM projects").fetchall()
            for row in rows:
                state = json.loads(row["state_json"])
                if any(key in state for key in LIBRARY_TABLES):
                    db.execute("UPDATE projects SET state_json=? WHERE id=?", (_encode_project_state(state), row["id"]))
            rows = db.execute("SELECT project_id,revision,state_json FROM revisions").fetchall()
            for row in rows:
                state = json.loads(row["state_json"])
                if any(key in state for key in LIBRARY_TABLES):
                    db.execute(
                        "UPDATE revisions SET state_json=? WHERE project_id=? AND revision=?",
                        (_encode_project_state(state), row["project_id"], row["revision"]),
                    )

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

    def libraries(self) -> dict[str, list[dict[str, Any]]]:
        result = {}
        with self.connect() as db:
            for key, table in LIBRARY_TABLES.items():
                rows = db.execute(f"SELECT payload_json FROM {table} ORDER BY sort_order,id").fetchall()
                result[key] = [json.loads(row["payload_json"]) for row in rows]
        return result

    def replace_libraries(self, libraries: dict[str, Any]) -> dict[str, int]:
        if not set(LIBRARY_TABLES).issubset(libraries):
            raise HTTPException(422, "必须同时提交设备、刀具、夹具和检具四类基础库")
        with self.connect() as db:
            for key, table in LIBRARY_TABLES.items():
                self._replace_library(db, table, libraries[key])
            now = _stamp()
            for key, value in {
                "inspection_categories": libraries.get("icnX", []),
                "fixture_categories": libraries.get("fcnX", []),
            }.items():
                if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                    raise HTTPException(422, "自定义基础库类别必须是文字数组")
                db.execute(
                    "INSERT INTO app_settings(key,value_json,updated) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated=excluded.updated",
                    (key, _compact(value), now),
                )
        return {key: len(libraries[key]) for key in LIBRARY_TABLES}

    def _compose(self, state: dict[str, Any]) -> dict[str, Any]:
        result = {**self.libraries(), **state}
        result["G"] = dict(result["G"])
        result["G"]["icnX"] = self._setting("inspection_categories")
        result["G"]["fcnX"] = self._setting("fixture_categories")
        return result

    def ensure_seed_project(self) -> None:
        with self.connect() as db:
            if db.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
                return
        state = self._seed()
        part = str(state.get("G", {}).get("part") or "原文件数据").strip()
        self.create(f"原文件集成 · {part}", state)

    def defaults(self) -> dict[str, Any]:
        return self._compose(_project_state(self._seed()))

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, Any]:
        state = json.loads(row["state_json"])
        project = state.get("G") if isinstance(state.get("G"), dict) else {}
        return {
            "id": row["id"], "name": row["name"], "revision": row["revision"],
            "created": row["created"], "updated": row["updated"],
            "archived": bool(row["archived"]), "customer": project.get("cust", ""),
            "part": project.get("part", ""),
        }

    def _record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {**self._summary(row), "state": self._compose(json.loads(row["state_json"]))}

    def list(self, archived: bool = False) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM projects WHERE archived=? ORDER BY updated DESC", (int(archived),)
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get(self, project_id: str, revision: int | None = None, *, allow_archived: bool = False) -> dict[str, Any]:
        with self.connect() as db:
            project = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if project is None:
                raise HTTPException(404, "机加 DFM 项目不存在")
            if project["archived"] and not allow_archived:
                raise HTTPException(410, "项目已删除，可在“已删除项目”中恢复")
            if revision is None:
                return self._record(project)
            old = db.execute(
                "SELECT project_id AS id,name,revision,state_json,created,created AS updated,0 AS archived "
                "FROM revisions WHERE project_id=? AND revision=?", (project_id, revision),
            ).fetchone()
        if old is None:
            raise HTTPException(404, "历史版本不存在")
        return self._record(old)

    def create(self, name: str, state: dict[str, Any]) -> dict[str, Any]:
        payload = _encode_project_state(state)
        now, project_id, clean_name = _stamp(), uuid.uuid4().hex, name.strip()
        if not clean_name:
            raise HTTPException(422, "项目名称不能为空")
        with self.connect() as db:
            db.execute(
                "INSERT INTO projects(id,name,revision,state_json,created,updated,archived) VALUES(?,?,?,?,?,?,0)",
                (project_id, clean_name, 1, payload, now, now),
            )
            db.execute(
                "INSERT INTO revisions(project_id,revision,name,state_json,created) VALUES(?,?,?,?,?)",
                (project_id, 1, clean_name, payload, now),
            )
        return self.get(project_id)

    def update(self, project_id: str, name: str, state: dict[str, Any], revision: int | None) -> dict[str, Any]:
        if revision is None:
            raise HTTPException(422, "保存已有项目时必须提供当前版本号")
        payload, clean_name, now = _encode_project_state(state), name.strip(), _stamp()
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
                (clean_name, next_revision, payload, now, project_id),
            )
            db.execute(
                "INSERT INTO revisions(project_id,revision,name,state_json,created) VALUES(?,?,?,?,?)",
                (project_id, next_revision, clean_name, payload, now),
            )
        return self.get(project_id)

    def archive(self, project_id: str, archived: bool) -> dict[str, Any]:
        with self.connect() as db:
            result = db.execute(
                "UPDATE projects SET archived=?,updated=? WHERE id=?", (int(archived), _stamp(), project_id)
            )
            if result.rowcount != 1:
                raise HTTPException(404, "机加 DFM 项目不存在")
        return self.get(project_id, allow_archived=True)

    def versions(self, project_id: str) -> list[dict[str, Any]]:
        self.get(project_id, allow_archived=True)
        with self.connect() as db:
            rows = db.execute(
                "SELECT revision,name,created FROM revisions WHERE project_id=? ORDER BY revision DESC", (project_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def public_settings(self) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT key,value_json FROM app_settings "
                "WHERE key NOT IN "
                "('token_secret','inspection_categories','fixture_categories','libraries_initialized',"
                "'category_schema_version')"
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
        return store_factory().create(req.name, req.state)

    @router.get("/api/machining-dfm/projects/{project_id}")
    def get_project(project_id: str, revision: int | None = None, allow_archived: bool = False):
        return store_factory().get(project_id, revision, allow_archived=allow_archived)

    @router.put("/api/machining-dfm/projects/{project_id}")
    def update_project(project_id: str, req: ProjectWrite):
        return store_factory().update(project_id, req.name, req.state, req.revision)

    @router.post("/api/machining-dfm/projects/{project_id}/archive")
    def archive_project(project_id: str, archived: bool = Query(True)):
        return store_factory().archive(project_id, archived)

    @router.get("/api/machining-dfm/projects/{project_id}/versions")
    def project_versions(project_id: str):
        return {"versions": store_factory().versions(project_id)}

    @router.get("/api/machining-dfm/libraries")
    def get_libraries():
        store = store_factory()
        libraries = store.libraries()
        libraries["icnX"] = store._setting("inspection_categories")
        libraries["fcnX"] = store._setting("fixture_categories")
        return {"libraries": libraries, "counts": {key: len(libraries[key]) for key in LIBRARY_TABLES}}

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
