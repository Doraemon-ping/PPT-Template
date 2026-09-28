import json
import sqlite3
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, TypeVar

from ..core.exceptions import ConnectorRecordNotFound
from ..models import ApiConnection, ApiEndpoint, ApiParameter, Dataset, FieldMapping
from ..settings import DATA_DIR

T = TypeVar("T")
_MIGRATION_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str | None, default: Any) -> Any:
    return default if value is None else json.loads(value)


def _nested_record_count(value: Any) -> int:
    sizes: list[int] = []

    def visit(item: Any) -> None:
        if isinstance(item, list):
            sizes.append(len(item))
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)

    visit(value)
    return max(sizes, default=1 if value not in ({}, [], None) else 0)


class ConnectorDatabase:
    """Small sqlite repository that follows the workbench's existing storage style."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or DATA_DIR / "ppt_workbench" / "workbench.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.apply_migrations()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 20000")
        return db

    def apply_migrations(self) -> None:
        migration_dir = Path(__file__).with_name("migrations")
        with _MIGRATION_LOCK:
            db = self.connect()
            try:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS connector_schema_migrations("
                    "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
                )
                applied = {
                    row["name"]
                    for row in db.execute("SELECT name FROM connector_schema_migrations").fetchall()
                }
                for migration in sorted(migration_dir.glob("*.sql")):
                    if migration.name in applied:
                        continue
                    db.executescript(migration.read_text(encoding="utf-8"))
                    db.execute(
                        "INSERT INTO connector_schema_migrations(name, applied_at) VALUES(?, ?)",
                        (migration.name, _now()),
                    )
                    db.commit()
            finally:
                db.close()

    @staticmethod
    def _connection(row: sqlite3.Row) -> ApiConnection:
        return ApiConnection(
            id=row["id"], name=row["name"], system_name=row["system_name"],
            base_url=row["base_url"], auth_type=row["auth_type"],
            auth_config=_json_load(row["auth_config"], {}), timeout=row["timeout"],
            status=row["status"], created_at=_datetime(row["created_at"]),
            updated_at=_datetime(row["updated_at"]),
        )

    @staticmethod
    def _endpoint(row: sqlite3.Row) -> ApiEndpoint:
        return ApiEndpoint(
            id=row["id"], connection_id=row["connection_id"], name=row["name"],
            path=row["path"], method=row["method"], headers=_json_load(row["headers"], {}),
            query_params=_json_load(row["query_params"], {}),
            body_template=_json_load(row["body_template"], None),
            description=row["description"], status=row["status"],
        )

    @staticmethod
    def _parameter(row: sqlite3.Row) -> ApiParameter:
        return ApiParameter(
            id=row["id"], endpoint_id=row["endpoint_id"], name=row["name"],
            location=row["location"], source_type=row["source_type"],
            source_key=row["source_key"], default_value=_json_load(row["default_value"], None),
        )

    @staticmethod
    def _mapping(row: sqlite3.Row) -> FieldMapping:
        return FieldMapping(
            id=row["id"], endpoint_id=row["endpoint_id"], source_path=row["source_path"],
            target_field=row["target_field"], transform_type=row["transform_type"],
            transform_config=_json_load(row["transform_config"], {}),
        )

    @staticmethod
    def _dataset(row: sqlite3.Row) -> Dataset:
        keys = set(row.keys())
        return Dataset(
            id=row["id"], source=row["source"], schema_version=row["schema_version"],
            data=_json_load(row["data"], {}), created_at=_datetime(row["created_at"]),
            connection_id=row["connection_id"] if "connection_id" in keys else None,
            endpoint_id=row["endpoint_id"] if "endpoint_id" in keys else None,
            parameters=_json_load(row["parameters"], {}) if "parameters" in keys else {},
        )

    def _one(self, sql: str, values: tuple[Any, ...], convert: Callable[[sqlite3.Row], T], label: str) -> T:
        db = self.connect()
        try:
            row = db.execute(sql, values).fetchone()
        finally:
            db.close()
        if row is None:
            raise ConnectorRecordNotFound(f"{label}不存在")
        return convert(row)

    def create_connection(self, values: dict[str, Any]) -> ApiConnection:
        now = _now()
        db = self.connect()
        try:
            cursor = db.execute(
                "INSERT INTO api_connections(name,system_name,base_url,auth_type,auth_config,timeout,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (values["name"], values["system_name"], values["base_url"], values["auth_type"],
                 _json_dump(values.get("auth_config", {})), values.get("timeout", 30),
                 values.get("status", "active"), now, now),
            )
            db.commit()
            record_id = cursor.lastrowid
        finally:
            db.close()
        return self.get_connection(record_id)

    def get_connection(self, record_id: int) -> ApiConnection:
        return self._one("SELECT * FROM api_connections WHERE id=?", (record_id,), self._connection, "API连接")

    def list_connections(self) -> list[ApiConnection]:
        db = self.connect()
        try:
            return [self._connection(row) for row in db.execute("SELECT * FROM api_connections ORDER BY id").fetchall()]
        finally:
            db.close()

    def update_connection(self, record_id: int, values: dict[str, Any]) -> ApiConnection:
        allowed = {"name", "system_name", "base_url", "auth_type", "auth_config", "timeout", "status"}
        return self._update("api_connections", record_id, values, allowed, {"auth_config"}, self.get_connection)

    def delete_connection(self, record_id: int) -> None:
        self._delete("api_connections", record_id, "API连接")

    def create_endpoint(self, values: dict[str, Any]) -> ApiEndpoint:
        self.get_connection(values["connection_id"])
        now = _now()
        db = self.connect()
        try:
            cursor = db.execute(
                "INSERT INTO api_endpoints(connection_id,name,path,method,headers,query_params,body_template,description,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (values["connection_id"], values["name"], values["path"], values["method"],
                 _json_dump(values.get("headers", {})), _json_dump(values.get("query_params", {})),
                 None if values.get("body_template") is None else _json_dump(values["body_template"]),
                 values.get("description", ""), values.get("status", "active"), now, now),
            )
            db.commit()
            record_id = cursor.lastrowid
        finally:
            db.close()
        return self.get_endpoint(record_id)

    def get_endpoint(self, record_id: int) -> ApiEndpoint:
        return self._one("SELECT * FROM api_endpoints WHERE id=?", (record_id,), self._endpoint, "API接口")

    def list_endpoints(self, connection_id: int | None = None) -> list[ApiEndpoint]:
        sql, values = "SELECT * FROM api_endpoints", ()
        if connection_id is not None:
            sql, values = sql + " WHERE connection_id=?", (connection_id,)
        db = self.connect()
        try:
            return [self._endpoint(row) for row in db.execute(sql + " ORDER BY id", values).fetchall()]
        finally:
            db.close()

    def update_endpoint(self, record_id: int, values: dict[str, Any]) -> ApiEndpoint:
        allowed = {"connection_id", "name", "path", "method", "headers", "query_params", "body_template", "description", "status"}
        if "connection_id" in values:
            self.get_connection(values["connection_id"])
        return self._update(
            "api_endpoints", record_id, values, allowed,
            {"headers", "query_params", "body_template"}, self.get_endpoint,
        )

    def delete_endpoint(self, record_id: int) -> None:
        self._delete("api_endpoints", record_id, "API接口")

    def create_parameter(self, values: dict[str, Any]) -> ApiParameter:
        self.get_endpoint(values["endpoint_id"])
        now = _now()
        db = self.connect()
        try:
            cursor = db.execute(
                "INSERT INTO api_parameters(endpoint_id,name,location,source_type,source_key,default_value,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (values["endpoint_id"], values["name"], values["location"], values["source_type"],
                 values.get("source_key"), None if values.get("default_value") is None else _json_dump(values["default_value"]), now, now),
            )
            db.commit()
            record_id = cursor.lastrowid
        finally:
            db.close()
        return self.get_parameter(record_id)

    def get_parameter(self, record_id: int) -> ApiParameter:
        return self._one("SELECT * FROM api_parameters WHERE id=?", (record_id,), self._parameter, "API参数")

    def list_parameters(self, endpoint_id: int) -> list[ApiParameter]:
        db = self.connect()
        try:
            rows = db.execute("SELECT * FROM api_parameters WHERE endpoint_id=? ORDER BY id", (endpoint_id,)).fetchall()
            return [self._parameter(row) for row in rows]
        finally:
            db.close()

    def update_parameter(self, record_id: int, values: dict[str, Any]) -> ApiParameter:
        allowed = {"endpoint_id", "name", "location", "source_type", "source_key", "default_value"}
        if "endpoint_id" in values:
            self.get_endpoint(values["endpoint_id"])
        return self._update("api_parameters", record_id, values, allowed, {"default_value"}, self.get_parameter)

    def delete_parameter(self, record_id: int) -> None:
        self._delete("api_parameters", record_id, "API参数")

    def create_mapping(self, values: dict[str, Any]) -> FieldMapping:
        self.get_endpoint(values["endpoint_id"])
        now = _now()
        db = self.connect()
        try:
            cursor = db.execute(
                "INSERT INTO field_mappings(endpoint_id,source_path,target_field,transform_type,transform_config,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (values["endpoint_id"], values["source_path"], values["target_field"],
                 values.get("transform_type", "none"), _json_dump(values.get("transform_config", {})), now, now),
            )
            db.commit()
            record_id = cursor.lastrowid
        finally:
            db.close()
        return self.get_mapping(record_id)

    def import_openapi(
        self,
        connection_values: dict[str, Any],
        operations: list[dict[str, Any]],
        *,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Persist one reviewed contract import as one atomic configuration change."""
        if workspace_id is not None:
            self.get_workspace(workspace_id)
        now = _now()
        db = self.connect()
        try:
            cursor = db.execute(
                "INSERT INTO api_connections(name,system_name,base_url,auth_type,auth_config,timeout,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (connection_values["name"], connection_values["system_name"], connection_values["base_url"],
                 connection_values.get("auth_type", "none"), _json_dump(connection_values.get("auth_config", {})),
                 connection_values.get("timeout", 30), "active", now, now),
            )
            connection_id = cursor.lastrowid
            endpoint_ids: list[int] = []
            for operation in operations:
                cursor = db.execute(
                    "INSERT INTO api_endpoints(connection_id,name,path,method,headers,query_params,body_template,description,status,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (connection_id, operation["name"], operation["path"], operation["method"], "{}", "{}",
                     _json_dump({}) if operation["method"] == "POST" else None,
                     operation.get("description", ""), "active", now, now),
                )
                endpoint_id = cursor.lastrowid
                endpoint_ids.append(endpoint_id)
                for parameter in operation.get("parameters", []):
                    db.execute(
                        "INSERT INTO api_parameters(endpoint_id,name,location,source_type,source_key,default_value,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (endpoint_id, parameter["name"], parameter["location"], parameter["source_type"],
                         parameter.get("source_key"),
                         None if parameter.get("default_value") is None else _json_dump(parameter["default_value"]), now, now),
                    )
                for mapping in operation.get("mappings", []):
                    transform_config = dict(mapping.get("transform_config", {}))
                    if mapping.get("value_type") == "image":
                        transform_config.setdefault("url_base", connection_values["base_url"])
                    db.execute(
                        "INSERT INTO field_mappings(endpoint_id,source_path,target_field,transform_type,transform_config,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (endpoint_id, mapping["source_path"], mapping["target_field"],
                         mapping.get("transform_type", "none"), _json_dump(transform_config), now, now),
                    )
            if workspace_id is not None:
                db.execute(
                    "INSERT OR IGNORE INTO workspace_sources(workspace_id,connection_id,created_at) VALUES(?,?,?)",
                    (workspace_id, connection_id, now),
                )
                db.execute("UPDATE workspaces SET updated_at=? WHERE id=?", (now, workspace_id))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return {
            "connection": self.get_connection(connection_id),
            "endpoints": [self.get_endpoint(endpoint_id) for endpoint_id in endpoint_ids],
            "workspace_id": workspace_id,
        }

    def get_mapping(self, record_id: int) -> FieldMapping:
        return self._one("SELECT * FROM field_mappings WHERE id=?", (record_id,), self._mapping, "字段映射")

    def list_mappings(self, endpoint_id: int) -> list[FieldMapping]:
        db = self.connect()
        try:
            rows = db.execute("SELECT * FROM field_mappings WHERE endpoint_id=? ORDER BY id", (endpoint_id,)).fetchall()
            return [self._mapping(row) for row in rows]
        finally:
            db.close()

    def update_mapping(self, record_id: int, values: dict[str, Any]) -> FieldMapping:
        allowed = {"endpoint_id", "source_path", "target_field", "transform_type", "transform_config"}
        if "endpoint_id" in values:
            self.get_endpoint(values["endpoint_id"])
        return self._update("field_mappings", record_id, values, allowed, {"transform_config"}, self.get_mapping)

    def delete_mapping(self, record_id: int) -> None:
        self._delete("field_mappings", record_id, "字段映射")

    def create_dataset(self, dataset: Dataset) -> Dataset:
        db = self.connect()
        try:
            db.execute(
                "INSERT INTO datasets(id,source,schema_version,data,created_at,connection_id,endpoint_id,parameters) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (dataset.id, dataset.source, dataset.schema_version, _json_dump(dataset.data),
                 dataset.created_at.isoformat().replace("+00:00", "Z"), dataset.connection_id,
                 dataset.endpoint_id, _json_dump(dataset.parameters or {})),
            )
            db.commit()
        finally:
            db.close()
        return self.get_dataset(dataset.id)

    def get_dataset(self, record_id: str) -> Dataset:
        return self._one("SELECT * FROM datasets WHERE id=?", (record_id,), self._dataset, "Dataset")

    def list_datasets(self, source: str | None = None, limit: int = 100) -> list[Dataset]:
        sql, values = "SELECT * FROM datasets", ()
        if source:
            sql, values = sql + " WHERE source=?", (source,)
        db = self.connect()
        try:
            rows = db.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*values, limit)).fetchall()
            return [self._dataset(row) for row in rows]
        finally:
            db.close()

    def latest_endpoint_dataset(self, endpoint_id: int) -> Dataset | None:
        db = self.connect()
        try:
            row = db.execute(
                "SELECT * FROM datasets WHERE endpoint_id=? ORDER BY created_at DESC LIMIT 1",
                (endpoint_id,),
            ).fetchone()
            return self._dataset(row) if row else None
        finally:
            db.close()

    def create_workspace(self, values: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        db = self.connect()
        try:
            cursor = db.execute(
                "INSERT INTO workspaces(name,description,created_at,updated_at) VALUES(?,?,?,?)",
                (values["name"], values.get("description", ""), now, now),
            )
            db.commit()
            workspace_id = cursor.lastrowid
        finally:
            db.close()
        return self.get_workspace(workspace_id)

    def list_workspaces(self) -> list[dict[str, Any]]:
        db = self.connect()
        try:
            rows = db.execute(
                "SELECT w.*," 
                "(SELECT COUNT(*) FROM workspace_sources ws WHERE ws.workspace_id=w.id) AS source_count," 
                "(SELECT COUNT(*) FROM workspace_sources ws JOIN connector_source_status s "
                " ON s.connection_id=ws.connection_id WHERE ws.workspace_id=w.id AND s.status='normal') AS healthy_source_count," 
                "COALESCE((SELECT SUM(s.record_count) FROM workspace_sources ws JOIN connector_source_status s "
                " ON s.connection_id=ws.connection_id WHERE ws.workspace_id=w.id),0) AS record_count," 
                "(SELECT COUNT(*) FROM workspace_templates wt WHERE wt.workspace_id=w.id) AS template_count," 
                "(SELECT COUNT(*) FROM workspace_templates wt WHERE wt.workspace_id=w.id "
                " AND (wt.placeholder_count > 0 OR wt.binding_target_count > 0 OR EXISTS ("
                " SELECT 1 FROM workspace_template_bindings wtb WHERE wtb.workspace_id=wt.workspace_id"
                " AND wtb.template_id=wt.template_id AND wtb.binding_count > 0))) AS bindable_template_count," 
                "(SELECT MAX(COALESCE(s.last_used_at,c.updated_at)) FROM workspace_sources ws "
                " JOIN api_connections c ON c.id=ws.connection_id LEFT JOIN connector_source_status s "
                " ON s.connection_id=ws.connection_id WHERE ws.workspace_id=w.id) AS last_used_at "
                "FROM workspaces w ORDER BY COALESCE(last_used_at,w.updated_at) DESC"
            ).fetchall()
            items = []
            for row in rows:
                healthy = row["source_count"] > 0 and row["healthy_source_count"] == row["source_count"]
                bindable = row["bindable_template_count"] > 0
                if row["source_count"] == 0:
                    setup_status = "needs_source"
                elif not healthy:
                    setup_status = "source_error"
                elif row["template_count"] == 0:
                    setup_status = "needs_template"
                elif not bindable:
                    setup_status = "needs_binding"
                else:
                    setup_status = "ready"
                items.append({
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "source_count": row["source_count"],
                    "healthy_source_count": row["healthy_source_count"],
                    "record_count": row["record_count"],
                    "template_count": row["template_count"],
                    "bindable_template_count": row["bindable_template_count"],
                    "last_used_at": row["last_used_at"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "setup_status": setup_status,
                    "ready": setup_status == "ready",
                })
            return items
        finally:
            db.close()

    def get_workspace(self, workspace_id: int) -> dict[str, Any]:
        for workspace in self.list_workspaces():
            if workspace["id"] == workspace_id:
                workspace["sources"] = self.list_source_summaries(workspace_id)
                workspace["templates"] = self.list_workspace_templates(workspace_id)
                return workspace
        raise ConnectorRecordNotFound("工作空间不存在")

    def attach_workspace_source(self, workspace_id: int, connection_id: int) -> dict[str, Any]:
        self.get_workspace(workspace_id)
        self.get_connection(connection_id)
        now = _now()
        db = self.connect()
        try:
            db.execute(
                "INSERT OR IGNORE INTO workspace_sources(workspace_id,connection_id,created_at) VALUES(?,?,?)",
                (workspace_id, connection_id, now),
            )
            db.execute("UPDATE workspaces SET updated_at=? WHERE id=?", (now, workspace_id))
            db.commit()
        finally:
            db.close()
        return self.get_workspace(workspace_id)

    def attach_workspace_template(self, workspace_id: int, values: dict[str, Any]) -> dict[str, Any]:
        self.get_workspace(workspace_id)
        now = _now()
        db = self.connect()
        try:
            db.execute(
                "INSERT INTO workspace_templates(workspace_id,template_id,source_name,slide_count,size," 
                "placeholder_count,binding_target_count,created_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(workspace_id,template_id) DO UPDATE SET "
                "source_name=excluded.source_name,slide_count=excluded.slide_count,size=excluded.size," 
                "placeholder_count=excluded.placeholder_count,binding_target_count=excluded.binding_target_count",
                (workspace_id, values["template_id"], values.get("source_name", ""),
                 values.get("slide_count", 0), values.get("size", 0),
                 values.get("placeholder_count", 0), values.get("binding_target_count", 0), now),
            )
            db.execute("UPDATE workspaces SET updated_at=? WHERE id=?", (now, workspace_id))
            db.commit()
        finally:
            db.close()
        return self.get_workspace(workspace_id)

    def list_workspace_templates(self, workspace_id: int) -> list[dict[str, Any]]:
        db = self.connect()
        try:
            rows = db.execute(
                "SELECT wt.template_id,wt.source_name,wt.slide_count,wt.size,wt.placeholder_count,"
                "wt.binding_target_count,wt.created_at,COALESCE(wtb.binding_count,0) AS configured_binding_count "
                "FROM workspace_templates wt LEFT JOIN workspace_template_bindings wtb "
                "ON wtb.workspace_id=wt.workspace_id AND wtb.template_id=wt.template_id "
                "WHERE wt.workspace_id=? ORDER BY wt.created_at DESC",
                (workspace_id,),
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["bindable"] = (
                    item["placeholder_count"] > 0
                    or item["binding_target_count"] > 0
                    or item["configured_binding_count"] > 0
                )
                items.append(item)
            return items
        finally:
            db.close()

    def get_workspace_template_binding(self, workspace_id: int, template_id: str) -> dict[str, Any]:
        self.get_workspace(workspace_id)
        db = self.connect()
        try:
            template = db.execute(
                "SELECT 1 FROM workspace_templates WHERE workspace_id=? AND template_id=?",
                (workspace_id, template_id),
            ).fetchone()
            if not template:
                raise ConnectorRecordNotFound("工作空间中的 PPT 模板不存在")
            row = db.execute(
                "SELECT revision,payload,binding_count,created_at,updated_at "
                "FROM workspace_template_bindings WHERE workspace_id=? AND template_id=?",
                (workspace_id, template_id),
            ).fetchone()
            if not row:
                return {
                    "workspace_id": workspace_id,
                    "template_id": template_id,
                    "revision": 0,
                    "payload": None,
                    "binding_count": 0,
                    "created_at": None,
                    "updated_at": None,
                }
            return {
                "workspace_id": workspace_id,
                "template_id": template_id,
                "revision": row["revision"],
                "payload": _json_load(row["payload"], {}),
                "binding_count": row["binding_count"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            db.close()

    def save_workspace_template_binding(
        self,
        workspace_id: int,
        template_id: str,
        *,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        current = self.get_workspace_template_binding(workspace_id, template_id)
        if current["revision"] != expected_revision:
            return None
        slides = payload.get("deck") or []
        binding_count = sum(
            len(slide.get("bindings") or {})
            for slide in slides
            if isinstance(slide, dict)
        )
        now = _now()
        next_revision = expected_revision + 1
        db = self.connect()
        try:
            db.execute(
                "INSERT INTO workspace_template_bindings("
                "workspace_id,template_id,revision,payload,binding_count,created_at,updated_at"
                ") VALUES(?,?,?,?,?,?,?) ON CONFLICT(workspace_id,template_id) DO UPDATE SET "
                "revision=excluded.revision,payload=excluded.payload,binding_count=excluded.binding_count,"
                "updated_at=excluded.updated_at",
                (workspace_id, template_id, next_revision, _json_dump(payload), binding_count, now, now),
            )
            db.execute("UPDATE workspaces SET updated_at=? WHERE id=?", (now, workspace_id))
            db.commit()
        finally:
            db.close()
        return self.get_workspace_template_binding(workspace_id, template_id)

    def get_workspace_binding_dataset(self, workspace_id: int) -> tuple[Dataset, list[FieldMapping]]:
        workspace = self.get_workspace(workspace_id)
        if not workspace["sources"]:
            raise ConnectorRecordNotFound("工作空间尚未接入数据来源")
        db = self.connect()
        try:
            row = db.execute(
                "SELECT d.* FROM workspace_sources ws "
                "JOIN api_connections c ON c.id=ws.connection_id "
                "JOIN datasets d ON d.source=c.system_name "
                "WHERE ws.workspace_id=? ORDER BY d.created_at DESC LIMIT 1",
                (workspace_id,),
            ).fetchone()
            if not row:
                raise ConnectorRecordNotFound("工作空间尚无可用于绑定的 Dataset")
            mapping_rows = db.execute(
                "SELECT fm.* FROM workspace_sources ws "
                "JOIN api_endpoints e ON e.connection_id=ws.connection_id "
                "JOIN field_mappings fm ON fm.endpoint_id=e.id "
                "WHERE ws.workspace_id=? ORDER BY fm.id",
                (workspace_id,),
            ).fetchall()
            return self._dataset(row), [self._mapping(item) for item in mapping_rows]
        finally:
            db.close()

    def get_workspace_binding_sources(self, workspace_id: int) -> list[dict[str, Any]]:
        """Return the latest Dataset for every attached system endpoint.

        Older workspaces created before Dataset provenance was recorded still
        contribute one connection-level Dataset with all mappings. New data is
        associated with its exact endpoint, so mappings from another endpoint
        can never be applied to the wrong response.
        """
        workspace = self.get_workspace(workspace_id)
        if not workspace["sources"]:
            raise ConnectorRecordNotFound("工作空间尚未接入数据来源")
        db = self.connect()
        try:
            connections = db.execute(
                "SELECT c.id,c.name,c.system_name,ws.created_at FROM workspace_sources ws "
                "JOIN api_connections c ON c.id=ws.connection_id "
                "WHERE ws.workspace_id=? ORDER BY ws.created_at,c.id",
                (workspace_id,),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for connection in connections:
                modern = db.execute(
                    "SELECT d.*,e.name AS endpoint_name FROM api_endpoints e "
                    "JOIN datasets d ON d.id=(SELECT d2.id FROM datasets d2 "
                    " WHERE d2.endpoint_id=e.id ORDER BY d2.created_at DESC LIMIT 1) "
                    "WHERE e.connection_id=? AND e.status='active' ORDER BY e.id",
                    (connection["id"],),
                ).fetchall()
                rows = modern
                if not rows:
                    legacy = db.execute(
                        "SELECT d.*,NULL AS endpoint_name FROM datasets d "
                        "WHERE (d.connection_id=? OR (d.connection_id IS NULL AND d.source=?)) "
                        "ORDER BY d.created_at DESC LIMIT 1",
                        (connection["id"], connection["system_name"]),
                    ).fetchall()
                    rows = legacy
                for row in rows:
                    endpoint_id = row["endpoint_id"]
                    if endpoint_id is None:
                        mapping_rows = db.execute(
                            "SELECT fm.* FROM api_endpoints e JOIN field_mappings fm ON fm.endpoint_id=e.id "
                            "WHERE e.connection_id=? ORDER BY fm.id",
                            (connection["id"],),
                        ).fetchall()
                    else:
                        mapping_rows = db.execute(
                            "SELECT * FROM field_mappings WHERE endpoint_id=? ORDER BY id",
                            (endpoint_id,),
                        ).fetchall()
                    result.append({
                        "connection_id": connection["id"],
                        "connection_name": connection["name"],
                        "system_name": connection["system_name"],
                        "endpoint_id": endpoint_id,
                        "endpoint_name": row["endpoint_name"],
                        "dataset": self._dataset(row),
                        "mappings": [self._mapping(item) for item in mapping_rows],
                    })
            if not result:
                raise ConnectorRecordNotFound("工作空间尚无可用于绑定的 Dataset")
            counts: dict[int, int] = {}
            for item in result:
                counts[item["connection_id"]] = counts.get(item["connection_id"], 0) + 1
            for item in result:
                key = f"source_{item['connection_id']}"
                if counts[item["connection_id"]] > 1 and item["endpoint_id"] is not None:
                    key += f"_endpoint_{item['endpoint_id']}"
                item["source_key"] = key
                item["display_name"] = item["connection_name"] + (
                    " · " + item["endpoint_name"] if item["endpoint_name"] else ""
                )
            return result
        finally:
            db.close()

    def record_source_status(
        self,
        connection_id: int,
        *,
        status: str,
        reason_code: str | None = None,
        reason_message: str | None = None,
        record_count: int = 0,
    ) -> None:
        now = _now()
        success_at = now if status == "normal" else None
        db = self.connect()
        try:
            db.execute(
                "INSERT INTO connector_source_status("
                "connection_id,status,reason_code,reason_message,last_checked_at,last_success_at,last_used_at,record_count"
                ") VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(connection_id) DO UPDATE SET "
                "status=excluded.status,reason_code=excluded.reason_code,reason_message=excluded.reason_message,"
                "last_checked_at=excluded.last_checked_at,"
                "last_success_at=COALESCE(excluded.last_success_at,connector_source_status.last_success_at),"
                "last_used_at=excluded.last_used_at,record_count=excluded.record_count",
                (connection_id, status, reason_code, reason_message, now, success_at, now, record_count),
            )
            db.commit()
        finally:
            db.close()

    def list_source_summaries(self, workspace_id: int | None = None) -> list[dict[str, Any]]:
        db = self.connect()
        try:
            workspace_join = "JOIN workspace_sources ws ON ws.connection_id=c.id " if workspace_id else ""
            workspace_where = "WHERE ws.workspace_id=? " if workspace_id else ""
            values = (workspace_id,) if workspace_id else ()
            rows = db.execute(
                "SELECT c.*,COUNT(DISTINCT CASE WHEN e.status='active' THEN e.id END) AS endpoint_count,"
                "COALESCE(s.status,'not_tested') AS sync_status,s.reason_code,s.reason_message,"
                "s.last_checked_at,s.last_success_at,s.last_used_at,COALESCE(s.record_count,0) AS record_count "
                "FROM api_connections c "
                + workspace_join +
                "LEFT JOIN api_endpoints e ON e.connection_id=c.id "
                "LEFT JOIN connector_source_status s ON s.connection_id=c.id "
                + workspace_where +
                "GROUP BY c.id ORDER BY COALESCE(s.last_used_at,c.updated_at) DESC",
                values,
            ).fetchall()
            items = []
            for row in rows:
                labels = {}
                mapping_rows = db.execute(
                    "SELECT fm.target_field,fm.transform_config FROM api_endpoints e "
                    "JOIN field_mappings fm ON fm.endpoint_id=e.id "
                    "WHERE e.connection_id=? AND e.status='active' ORDER BY fm.id",
                    (row["id"],),
                ).fetchall()
                for mapping in mapping_rows:
                    config = _json_load(mapping["transform_config"], {})
                    label = config.get("display_name") if isinstance(config, dict) else None
                    if label:
                        labels[mapping["target_field"]] = str(label)
                latest_datasets = db.execute(
                    "SELECT d.data FROM api_endpoints e JOIN datasets d ON d.id=("
                    " SELECT d2.id FROM datasets d2 WHERE d2.endpoint_id=e.id"
                    " ORDER BY d2.created_at DESC LIMIT 1) WHERE e.connection_id=? AND e.status='active'",
                    (row["id"],),
                ).fetchall()
                if not latest_datasets:
                    latest_datasets = db.execute(
                        "SELECT data FROM datasets WHERE source=? ORDER BY created_at DESC LIMIT 1",
                        (row["system_name"],),
                    ).fetchall()
                record_count = row["record_count"]
                if latest_datasets:
                    record_count = sum(
                        _nested_record_count(_json_load(item["data"], {}))
                        for item in latest_datasets
                    )
                endpoint_names = [
                    item["name"] for item in db.execute(
                        "SELECT name FROM api_endpoints WHERE connection_id=? AND status='active' ORDER BY id",
                        (row["id"],),
                    ).fetchall()
                ]
                items.append({
                    "id": row["id"],
                    "name": row["name"],
                    "system_name": row["system_name"],
                    "base_url": row["base_url"],
                    "auth_type": row["auth_type"],
                    "status": row["sync_status"],
                    "reason_code": row["reason_code"],
                    "reason": row["reason_message"],
                    "last_checked_at": row["last_checked_at"],
                    "last_success_at": row["last_success_at"],
                    "last_used_at": row["last_used_at"],
                    "record_count": record_count,
                    "endpoint_count": row["endpoint_count"],
                    "dataset_count": len(latest_datasets),
                    "endpoint_names": endpoint_names,
                    "display_labels": labels,
                })
            return items
        finally:
            db.close()

    def _update(
        self, table: str, record_id: int, values: dict[str, Any], allowed: set[str],
        json_fields: set[str], getter: Callable[[int], T],
    ) -> T:
        getter(record_id)
        changes = {key: value for key, value in values.items() if key in allowed}
        if not changes:
            return getter(record_id)
        for key in json_fields & changes.keys():
            changes[key] = None if changes[key] is None and key == "body_template" else _json_dump(changes[key])
        changes["updated_at"] = _now()
        assignments = ",".join(f"{key}=?" for key in changes)
        db = self.connect()
        try:
            db.execute(f"UPDATE {table} SET {assignments} WHERE id=?", (*changes.values(), record_id))
            db.commit()
        finally:
            db.close()
        return getter(record_id)

    def _delete(self, table: str, record_id: int, label: str) -> None:
        db = self.connect()
        try:
            cursor = db.execute(f"DELETE FROM {table} WHERE id=?", (record_id,))
            db.commit()
        finally:
            db.close()
        if cursor.rowcount == 0:
            raise ConnectorRecordNotFound(f"{label}不存在")


@lru_cache(maxsize=1)
def get_connector_database() -> ConnectorDatabase:
    return ConnectorDatabase()
