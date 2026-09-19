"""通用「类型化基础库」引擎：设备 / 刀具 / 夹具 / 检具共用。

约定（管理设置里每个库都按这个模式）：

* **页面表头就是字段登记表** —— 一个 ``LibraryField`` 同时决定建表 SQL、JSON 视图、
  校验规则和旧数据迁移，加一列只改一处；
* **一行一条记录**，用稳定 ``id`` 寻址，另存 ``sort_order`` 排序，不再整库存一个
  ``payload_json``，也不再整表覆盖保存；
* **附件（图片/资料）只存元数据**：表里留 ``*_id`` 外键，文件在
  ``AssetStore`` 的磁盘目录里（``kind`` 决定子目录与类型白名单）；
* **旧短键视图**（``img`` / ``doc`` / ``tI`` …）由登记表推导，原渲染器与 PPT
  数据源契约无需改动。

子类只需要声明 ``table`` / ``fields`` / ``attachments`` 和少量钩子。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, NamedTuple

from fastapi import HTTPException

from .machining_assets import AssetStore


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


#: 逻辑删除三列（口径 2：没有保留期、没有彻底删除；回收站只是"标记 + 过滤"）
TRASH_COLUMNS = ("deleted_at", "deleted_by", "deleted_reason")


def _who(value: str | None) -> str:
    """写下"谁删的/谁恢复的"：没给角色时记 ``admin``（与业务行那边的兜底口径一致）。"""
    text = str(value or "").strip()
    return text[:40] or "admin"


class LibraryField(NamedTuple):
    """一列页面字段：JSON 键、数据库列、类型、默认值、表头文字与约束。"""

    key: str
    column: str
    kind: str  # 'text' | 'real' | 'int' | 'choice'
    default: Any
    label: str
    unit: str = ""
    limit: int = 200
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    choice_labels: tuple[tuple[str, str], ...] = ()
    references: str = ""  # 外键目标，如 'tool_groups(code)'；取值校验交给字典表

    @property
    def numeric(self) -> bool:
        return self.kind in {"real", "int"}

    @property
    def dictionary(self) -> bool:
        """枚举取值来自字典表而不是这里的静态 ``choices``。"""
        return self.kind == "choice" and not self.choices

    def header(self) -> str:
        return self.label + (f" {self.unit}" if self.unit else "")

    def choice_map(self) -> dict[str, str]:
        return dict(self.choice_labels) if self.choice_labels else {code: code for code in self.choices}

    def describe(self) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "key": self.key,
            "column": self.column,
            "type": self.kind,
            "label": self.label,
            "unit": self.unit,
            "default": self.default,
        }
        if self.choices:
            labels = self.choice_map()
            spec["choices"] = [{"value": code, "label": labels.get(code, code)} for code in self.choices]
        if self.references:
            spec["references"] = self.references.split("(")[0]
        if self.maximum is not None:
            spec["maximum"] = self.maximum
        return spec


class AttachmentSpec(NamedTuple):
    """一个附件槽位：页面键 → 资产类别 → 列 → 旧读模型键。"""

    slot: str  # 'photo' | 'doc'
    kind: str  # AssetStore kind
    column: str  # 表里的外键列
    legacy_key: str  # 旧渲染器读的键，如 'img' / 'tI'
    download: bool = False  # URL 是否带 ?download=1（资料类）
    name_column: str = ""  # 文件名列，如 'doc_name'
    name_key: str = ""  # 旧读模型里的文件名键，如 'docName'
    value_keys: tuple[str, ...] = ()  # 旧数据里可能存放附件的键（按顺序尝试）
    mime_key: str = ""  # 旧数据里的 MIME 提示键
    default_mime: str = ""  # 旧数据没带 MIME 时的兜底


def asset_in_snapshots(db, asset_id: str | None) -> bool:
    """**历史版本快照**里还引用着这张图吗？

    快照是"那一次保存时的整份读模型"（口径 1：每次保存都留版本、全部保留，回滚靠它），
    里面记的是附件 **URL**（``/api/machining-dfm/assets/<id>``），**不是外键** ——
    所以全库"按外键元数据扫"的判定根本扫不到它。只看外键的话，用户换一张产品图就会把
    老版本还要用的附件行连同文件一起删掉：回滚到第 N 版时图是死链。
    （线上真的发生过：第 17/18/22/26/30/34/38/40 版现在指着 7 个已经不存在的附件。）
    """
    if not asset_id:
        return False
    needle = f"%/assets/{asset_id}%"
    for table, column in (("project_versions", "state_json"), ("projects", "state_json")):
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            continue
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            continue
        if db.execute(
            f"SELECT 1 FROM {table} WHERE {column} LIKE ? LIMIT 1", (needle,)
        ).fetchone() is not None:
            return True
    return False


def asset_used_elsewhere(
    db, asset_id: str | None, *, skip_table: str = "", skip_key: str = "",
    skip_value: str | None = None, skip_column: str = "",
) -> bool:
    """这张图还有没有人指着？**按外键元数据全库扫**，不靠手写表格清单。

    附件按内容去重（``kind + sha256 + name``），所以同一张图可能被多行共用；
    "换图/清图"时要先确认没人再用了才能删附件行——否则外键还指着它，
    SQLite 会直接拒绝删除（第一阶段踩过）。同一张图甚至可能被**不同表**引用
    （工序示意图与刀具图同属 ``process_photo`` 一类），所以这里扫全库：
    凡是声明了指向 ``assets(id)`` 外键的列都算。

    ``skip_table``/``skip_key``/``skip_value``/``skip_column``：跳过"正在改的那个格子"。
    **必须传 ``skip_column``**（要清的那一列）：只把这一列的旧引用排除掉，同一行
    **别的附件列照常参与判定**——``project_settings`` 一行有 4 个图片槽，跳过整行会
    漏掉兄弟槽位的引用，删完附件行立刻撞外键。
    """
    if not asset_id:
        return False
    if asset_in_snapshots(db, asset_id):
        # 历史快照还指着它：**绝不删**。快照永久保留（口径 1），所以这张附件行也永久保留，
        # 代价是换图时旧图不回收 —— 这正是"回滚到任意一版图都在"必须付的代价。
        return True
    tables = [
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    scoped = bool(skip_key and skip_column and skip_value is not None)
    for table in tables:
        columns = [
            row["from"] for row in db.execute(f"PRAGMA foreign_key_list({table})")
            if row["table"] == "assets"
        ]
        if not columns:
            continue
        terms: list[str] = []
        params: list[Any] = []
        for column in columns:
            quoted = quote_identifier(column)
            if scoped and table == skip_table and column == skip_column:
                # 只有"被改的那一行的那一列"不算：别的行、本行别的列都照算
                # （不能写成 ``AND NOT (列=? AND 主键=?)``：被清空后该列是 NULL，
                #  三值逻辑下 NOT(NULL) 仍是 NULL，会把本行整个滤掉）
                terms.append(f"({quoted}=? AND {quote_identifier(skip_key)}<>?)")
                params.extend((asset_id, skip_value))
            else:
                terms.append(f"{quoted}=?")
                params.append(asset_id)
        sql = f"SELECT 1 FROM {table} WHERE (" + " OR ".join(terms) + ")"
        if db.execute(sql + " LIMIT 1", tuple(params)).fetchone() is not None:
            return True
    return False


class TypedLibrary:
    """基于一张普通 SQLite 表的行级读写引擎。"""

    table: str = ""
    table_label: str = "基础库"
    fields: tuple[LibraryField, ...] = ()
    attachments: tuple[AttachmentSpec, ...] = ()
    supports_fallback: bool = False
    display_keys: tuple[str, ...] = ()  # delete() 回显
    indexes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: 主键列名（``_asset_in_use`` 跳过"正在改的那一行"要用）
    table_key_column: str = "id"

    def __init__(self, connect: Callable[[], Any], assets: AssetStore):
        self._connect = connect
        self.assets = assets

    # ---------------- 表结构 ----------------

    @property
    def field_columns(self) -> tuple[str, ...]:
        return tuple(field.column for field in self.fields)

    @property
    def attachment_columns(self) -> tuple[str, ...]:
        columns: list[str] = []
        for spec in self.attachments:
            columns.append(spec.column)
            if spec.name_column:
                columns.append(spec.name_column)
        return tuple(columns)

    @property
    def insert_columns(self) -> tuple[str, ...]:
        columns = ["id", "sort_order"]
        if self.supports_fallback:
            columns.append("is_fallback")
        columns.extend(self.field_columns)
        columns.extend(self.attachment_columns)
        columns.extend(("created", "updated"))
        return tuple(columns)

    def ddl(self) -> str:
        lines = ["id TEXT PRIMARY KEY", "sort_order INTEGER NOT NULL DEFAULT 0"]
        if self.supports_fallback:
            lines.append("is_fallback INTEGER NOT NULL DEFAULT 0")
        ddl_types = {"text": "TEXT", "choice": "TEXT", "real": "REAL", "int": "INTEGER"}
        for field in self.fields:
            sql_type = ddl_types.get(field.kind, "TEXT")
            default = field.default
            if field.kind == "text" or field.kind == "choice":
                literal = "'" + str(default).replace("'", "''") + "'"
            else:
                literal = repr(float(default)) if field.kind == "real" else str(int(default))
            reference = f" REFERENCES {field.references}" if field.references else ""
            lines.append(
                f"{quote_identifier(field.column)} {sql_type} NOT NULL DEFAULT {literal}{reference}"
            )
        for spec in self.attachments:
            lines.append(f"{quote_identifier(spec.column)} TEXT REFERENCES assets(id)")
            if spec.name_column:
                lines.append(f"{quote_identifier(spec.name_column)} TEXT NOT NULL DEFAULT ''")
        lines.append("created TEXT NOT NULL")
        lines.append("updated TEXT NOT NULL")
        lines.extend(f"{column} TEXT" for column in TRASH_COLUMNS)   # 逻辑删除三列（口径 2）
        return f"CREATE TABLE IF NOT EXISTS {self.table}(\n    " + ",\n    ".join(lines) + "\n);\n"

    def index_ddl(self) -> str:
        script = (
            f"CREATE INDEX IF NOT EXISTS idx_machining_dfm_{self.table}_order "
            f"ON {self.table}(sort_order, id);\n"
        )
        script += (
            f"CREATE INDEX IF NOT EXISTS idx_machining_dfm_{self.table}_trash "
            f"ON {self.table}(deleted_at, sort_order);\n"
        )
        for name, columns in self.indexes:
            script += (
                f"CREATE INDEX IF NOT EXISTS idx_machining_dfm_{self.table}_{name} "
                f"ON {self.table}({', '.join(columns)});\n"
            )
        return script

    def create_indexes(self, db) -> None:
        # 早期版本这把索引叫 ``..._sort``，后来统一成 ``..._order``：老名字不清掉的话，
        # 同一个 ``(sort_order, id)`` 上会一直挂着两条一模一样的索引（线上 machines 就是这样）。
        db.execute(f"DROP INDEX IF EXISTS {quote_identifier(f'idx_machining_dfm_{self.table}_sort')}")
        db.executescript(self.index_ddl())

    def ensure_trash_columns(self, db) -> list[str]:
        """老库补上三个逻辑删除列：``ALTER TABLE ADD COLUMN`` 只加可空列，不动任何既有数据。"""
        existing = {row[1] for row in db.execute(f"PRAGMA table_info({self.table})")}
        added: list[str] = []
        for column in TRASH_COLUMNS:
            if column not in existing:
                db.execute(f"ALTER TABLE {self.table} ADD COLUMN {column} TEXT")
                added.append(column)
        return added

    def schema(self, db) -> None:
        db.executescript(self.ddl())
        self.ensure_trash_columns(db)
        self.create_indexes(db)

    # ---------------- 视图 ----------------

    def _typed(self, row: Any) -> dict[str, Any]:
        record = dict(row)
        view: dict[str, Any] = {"id": record["id"], "sort_order": int(record["sort_order"])}
        if self.supports_fallback:
            view["is_fallback"] = bool(record["is_fallback"])
        for field in self.fields:
            view[field.key] = record[field.column]
        for spec in self.attachments:
            asset_id = record[spec.column]
            view[f"{spec.slot}_id"] = asset_id
            view[f"{spec.slot}_url"] = self.assets.url(asset_id, download=spec.download)
            if spec.name_column:
                view[spec.name_column] = record[spec.name_column]
        view["created"] = record["created"]
        view["updated"] = record["updated"]
        return view

    def _legacy(self, row: Any, *, inline: bool = False) -> dict[str, Any]:
        """旧短键行：原渲染器、成本表与 PPT 契约继续读这些键。"""
        record = dict(row)
        view: dict[str, Any] = {"id": record["id"]}
        for field in self.fields:
            view[field.key] = record[field.column]
        for spec in self.attachments:
            asset_id = record[spec.column]
            if inline:
                view[spec.legacy_key] = self.assets.data_url(asset_id)
            else:
                view[spec.legacy_key] = self.assets.url(asset_id, download=spec.download)
            if spec.name_key and spec.name_column:
                view[spec.name_key] = record[spec.name_column]
        return view

    # ---------------- 读取 ----------------

    def rows(self, *, db=None, include_deleted: bool = False) -> list[Any]:
        """默认只出**在用**行（口径 2：逻辑删除的行只在回收站里）；``include_deleted`` 给回收站用。"""
        where = "" if include_deleted else " WHERE deleted_at IS NULL"
        with self.assets.session(db) as conn:
            return conn.execute(
                f"SELECT * FROM {self.table}{where} ORDER BY sort_order, id").fetchall()

    def ids(self) -> list[str]:
        return [row["id"] for row in self.rows()]

    def trash(self, *, db=None) -> list[dict[str, Any]]:
        """回收站：已逻辑删除的行，按删除时间倒序。"""
        with self.assets.session(db) as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.table} WHERE deleted_at IS NOT NULL "
                "ORDER BY deleted_at DESC, sort_order, id").fetchall()
        return [self._trash_view(row) for row in rows]

    def _trash_view(self, row: Any) -> dict[str, Any]:
        record = dict(row)
        view = self._typed(row)
        view.update({
            "deleted_at": record.get("deleted_at"),
            "deleted_by": record.get("deleted_by") or "",
            "deleted_reason": record.get("deleted_reason") or "",
        })
        return view

    def find(self, record_id: str | None, *, db=None) -> Any:
        if not record_id:
            return None
        with self.assets.session(db) as conn:
            return conn.execute(f"SELECT * FROM {self.table} WHERE id=?", (record_id,)).fetchone()

    def count(self) -> int:
        with self._connect() as db:
            return int(db.execute(
                f"SELECT COUNT(*) FROM {self.table} WHERE deleted_at IS NULL").fetchone()[0])

    def list_typed(self) -> list[dict[str, Any]]:
        return [self._typed(row) for row in self.rows()]

    def list_legacy(self, *, inline: bool = False) -> list[dict[str, Any]]:
        return [self._legacy(row, inline=inline) for row in self.rows()]

    def headers(self) -> list[dict[str, Any]]:
        return [field.describe() for field in self.fields]

    def resolve(self, record_id: str | None = None, index: int | None = None) -> dict[str, Any] | None:
        """按稳定 id 解析，取不到时回退到旧下标 / 兜底行。"""
        row = self.find(record_id)
        if row is None and index is not None:
            rows = self.rows()
            if rows and 0 <= index < len(rows):
                row = rows[index]
        if row is None and self.supports_fallback:
            fallback = self.fallback_id()
            row = self.find(fallback) if fallback else None
        if row is None:
            rows = self.rows()
            row = rows[-1] if rows else None
        return self._typed(row) if row is not None else None

    # ---------------- 兜底行（设备库专用） ----------------

    def fallback_id(self) -> str | None:
        if not self.supports_fallback:
            return None
        with self._connect() as db:
            row = db.execute(
                f"SELECT id FROM {self.table} WHERE is_fallback=1 AND deleted_at IS NULL "
                "ORDER BY sort_order, id LIMIT 1"
            ).fetchone()
        if row:
            return row["id"]
        rows = self.rows()
        return rows[-1]["id"] if rows else None

    def default_ref(self) -> str:
        return self.fallback_id() or ""

    def _ensure_fallback(self, db, preferred: str = "自定义") -> str | None:
        if not self.supports_fallback:
            return None
        row = db.execute(
            f"SELECT id FROM {self.table} WHERE is_fallback=1 AND deleted_at IS NULL "
            "ORDER BY sort_order, id LIMIT 1"
        ).fetchone()
        if row:
            return row["id"]
        first_column = self.fields[0].column if self.fields else "id"
        row = db.execute(
            f"SELECT id FROM {self.table} WHERE {first_column}=? AND deleted_at IS NULL "
            "ORDER BY sort_order, id LIMIT 1", (preferred,)
        ).fetchone()
        if row is None:
            row = db.execute(
                f"SELECT id FROM {self.table} WHERE deleted_at IS NULL "
                "ORDER BY sort_order DESC, id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        db.execute(f"UPDATE {self.table} SET is_fallback=1 WHERE id=?", (row["id"],))
        return row["id"]

    def _set_fallback(self, db, record_id: str) -> None:
        db.execute(f"UPDATE {self.table} SET is_fallback=0")
        db.execute(f"UPDATE {self.table} SET is_fallback=1 WHERE id=?", (record_id,))

    def set_fallback(self, record_id: str | None) -> list[dict[str, Any]]:
        if not self.supports_fallback:
            raise HTTPException(422, f"{self.table_label}没有兜底机型设置")
        with self._connect() as db:
            if record_id is None:
                db.execute(f"UPDATE {self.table} SET is_fallback=0")
            else:
                if self.find(record_id, db=db) is None:
                    raise HTTPException(404, f"{self.table_label}记录不存在，可能已被其他管理员删除")
                self._set_fallback(db, record_id)
        return self.list_typed()

    # ---------------- 校验 ----------------

    @classmethod
    def _number(cls, value: Any, field: LibraryField) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return field.default
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"{field.label}必须是数字") from exc
        if parsed != parsed or parsed in (float("inf"), float("-inf")):
            raise HTTPException(422, f"{field.label}不是有效数字")
        if parsed < 0:
            raise HTTPException(422, f"{field.label}不能为负数")
        if field.maximum is not None and parsed > field.maximum:
            raise HTTPException(422, f"{field.label}超过上限 {field.maximum:g}")
        return int(round(parsed)) if field.kind == "int" else float(parsed)

    @classmethod
    def _text(cls, value: Any, field: LibraryField, *, strict: bool = True) -> str:
        if value is None:
            text = ""
        elif isinstance(value, (str, int, float, bool)):
            text = str(value).strip()
        else:
            raise HTTPException(422, f"{field.label}必须是文字")
        if len(text) > field.limit:
            raise HTTPException(422, f"{field.label}超过 {field.limit} 个字符")
        if strict and field.kind == "choice" and field.choices and text not in field.choices:
            labels = field.choice_map()
            # 显示名和取值一样时不要再套一层括号（"进行中（进行中）"这种提示等于没说）
            allowed = "、".join(
                str(code) if labels.get(code, code) == code else f"{code}（{labels[code]}）"
                for code in field.choices
            )
            raise HTTPException(422, f"{field.label}只能是：{allowed}")
        return text

    @classmethod
    def clean_values(
        cls, payload: dict[str, Any], *, partial: bool = False, strict: bool = True
    ) -> dict[str, Any]:
        """把一页输入校验成 ``{column: value}``；未知键按只读字段忽略。

        ``strict=False`` 只放宽取值枚举校验（旧数据迁移用），类型与长度照旧。

        两个"没填"的写法**等同缺键**（用默认值，不报 422）：
        ``null``，以及下拉类的空串——旧数据里字段整份缺失是常态
        （例如只有 ``tp``/``pr`` 两键的问题行），迁移不能因为这种"没填"中断，
        页面上下拉没选也只是"没选"，不该变成一条错误。
        """
        if not isinstance(payload, dict):
            raise HTTPException(422, f"{cls.table_label}数据必须是 JSON 对象")
        values: dict[str, Any] = {}
        for field in cls.fields:
            raw = payload.get(field.key)
            provided = field.key in payload and raw is not None
            if provided and field.kind == "choice" and str(raw).strip() == "":
                provided = False
            if not provided:
                if not partial:
                    values[field.column] = field.default
                continue
            values[field.column] = (
                cls._text(raw, field, strict=strict)
                if field.kind in {"text", "choice"}
                else cls._number(raw, field)
            )
        return values

    # ---------------- 写入 ----------------

    def validate_values(self, values: dict[str, Any], payload: dict[str, Any]) -> None:
        """取值级校验钩子：静态枚举之外的规则（如字典表外键）由子类补充。"""

    def prepare_rows(self, db, rows: list[dict[str, Any]]) -> None:
        """批量灌数据前的钩子：把行里引用到的字典项补齐，保证外键成立。"""

    def _insert(
        self,
        db,
        record_id: str,
        sort_order: int,
        values: dict[str, Any],
        *,
        is_fallback: bool,
        attachment_ids: dict[str, Any],
        now: str,
    ) -> None:
        columns = self.insert_columns
        payload: list[Any] = [record_id, sort_order]
        if self.supports_fallback:
            payload.append(1 if is_fallback else 0)
        payload.extend(values[column] for column in self.field_columns)
        for spec in self.attachments:
            payload.append(attachment_ids.get(spec.column))
            if spec.name_column:
                payload.append(attachment_ids.get(spec.name_column, ""))
        payload.extend((now, now))
        sql = (
            f"INSERT INTO {self.table}("
            + ",".join(quote_identifier(column) for column in columns)
            + ") VALUES("
            + ",".join("?" * len(columns))
            + ")"
        )
        db.execute(sql, tuple(payload))

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = self.clean_values(payload)
        self.validate_values(values, payload)
        requested = str(payload.get("id") or "").strip()[:64]
        record_id = requested or uuid.uuid4().hex
        now = _stamp()
        with self._connect() as db:
            existing = self.find(record_id, db=db) if requested else None
            if existing is None:
                # 同名重建 = 复活原行（口径 3）：回收站里同一"自然键"的行直接复活，不新建重复行
                existing = self._find_deleted_natural(db, values)
            if existing is not None:
                if not existing["deleted_at"]:
                    raise HTTPException(409, f"{self.table_label}记录已存在")
                return self._revive(db, existing["id"], values, now=now, payload=payload)
            order = int(
                db.execute(f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {self.table}").fetchone()[0]
            )
            self._insert(
                db, record_id, order, values, is_fallback=False, attachment_ids={}, now=now
            )
            if self.supports_fallback and payload.get("is_fallback"):
                self._set_fallback(db, record_id)
        return self._typed(self.find(record_id))

    def _find_deleted_natural(self, db, values: dict[str, Any]):
        """回收站里找同一"自然键"的行（子类用 ``natural_key`` 说明怎么算同名，取值一律按列名）。"""
        key = self.natural_key(values)
        for row in db.execute(
                f"SELECT * FROM {self.table} WHERE deleted_at IS NOT NULL ORDER BY sort_order, id"):
            record = {field.column: row[field.column] for field in self.fields}
            if self.natural_key(record) == key:
                return row
        return None

    def _revive(self, db, record_id: str, values: dict[str, Any], *, now: str,
                payload: dict[str, Any]) -> dict[str, Any]:
        """复活：清空三列并把这次提交的字段写进去（行 id、排序位置、附件都不变）。"""
        assignments = ",".join(f"{quote_identifier(column)}=?" for column in values)
        prefix = f"{assignments}," if assignments else ""
        db.execute(
            f"UPDATE {self.table} SET {prefix}deleted_at=NULL,deleted_by=NULL,deleted_reason=NULL,"
            "updated=? WHERE id=?",
            (*values.values(), now, record_id),
        )
        if self.supports_fallback and payload.get("is_fallback"):
            self._set_fallback(db, record_id)
        revived = self._typed(self.find(record_id, db=db))
        revived["revived"] = True
        return revived

    def update(self, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = self.find(record_id)
        if row is None:
            raise HTTPException(404, f"{self.table_label}记录不存在，可能已被其他管理员删除")
        values = self.clean_values(payload, partial=True)
        merged = {column: row[column] for column in self.field_columns}
        merged.update(values)
        self.validate_values(merged, payload)
        with self._connect() as db:
            if values:
                assignments = ",".join(f"{quote_identifier(column)}=?" for column in values)
                db.execute(
                    f"UPDATE {self.table} SET {assignments},updated=? WHERE id=?",
                    (*values.values(), _stamp(), record_id),
                )
            if self.supports_fallback and "is_fallback" in payload:
                if payload.get("is_fallback"):
                    self._set_fallback(db, record_id)
                else:
                    db.execute(f"UPDATE {self.table} SET is_fallback=0 WHERE id=?", (record_id,))
        return self._typed(self.find(record_id))

    def _after_delete(self, db, remaining: int) -> None:
        if remaining:
            self._ensure_fallback(db)

    def delete(self, record_id: str, *, by: str = "", reason: str = "") -> dict[str, Any]:
        """**逻辑删除**（口径 2）：只写三列，行与附件文件都留着，回收站里能恢复。

        以前这里是物理 ``DELETE`` 并回收附件；现在一律不回收 —— 没有彻底删除这条路。
        """
        row = self.find(record_id)
        if row is None:
            raise HTTPException(404, f"{self.table_label}记录不存在，可能已被其他管理员删除")
        if row["deleted_at"]:
            raise HTTPException(409, f"{self.table_label}记录已经在回收站里了")
        now = _stamp()
        with self._connect() as db:
            db.execute(
                f"UPDATE {self.table} SET deleted_at=?,deleted_by=?,deleted_reason=?,updated=? "
                "WHERE id=?",
                (now, _who(by), str(reason or "")[:200], now, record_id),
            )
            remaining = int(db.execute(
                f"SELECT COUNT(*) FROM {self.table} WHERE deleted_at IS NULL").fetchone()[0])
            self._after_delete(db, remaining)
        removed = {"id": record_id, "deleted_at": now, "deleted_by": _who(by),
                   "deleted_reason": str(reason or "")[:200]}
        for key in self.display_keys:
            field = self.field(key)
            if field:
                removed[key] = row[field.column]
        removed["remaining"] = remaining
        return removed

    def restore(self, record_id: str, *, by: str = "") -> dict[str, Any]:
        """从回收站恢复：清空三列（附件一直都在，不用重建）。"""
        row = self.find(record_id)
        if row is None:
            raise HTTPException(404, f"{self.table_label}记录不存在")
        if not row["deleted_at"]:
            raise HTTPException(409, f"{self.table_label}记录本来就在用，不需要恢复")
        with self._connect() as db:
            db.execute(
                f"UPDATE {self.table} SET deleted_at=NULL,deleted_by=NULL,deleted_reason=NULL,updated=? "
                "WHERE id=?",
                (_stamp(), record_id),
            )
        restored = self._typed(self.find(record_id))
        restored["restored_by"] = _who(by)
        return restored

    def reorder(self, record_ids: Iterable[str]) -> list[dict[str, Any]]:
        ordered = [str(item) for item in record_ids]
        current = self.ids()
        if len(set(ordered)) != len(ordered):
            raise HTTPException(422, f"{self.table_label}排序列表存在重复项")
        if set(ordered) != set(current):
            raise HTTPException(422, f"{self.table_label}排序必须包含全部记录且不能新增或遗漏")
        now = _stamp()
        with self._connect() as db:
            for index, record_id in enumerate(ordered):
                db.execute(
                    f"UPDATE {self.table} SET sort_order=?,updated=? WHERE id=?", (index, now, record_id)
                )
        return self.list_typed()

    def field(self, key: str) -> LibraryField | None:
        for field in self.fields:
            if field.key == key:
                return field
        return None

    # ---------------- 附件 ----------------

    def attachment(self, slot: str) -> AttachmentSpec:
        for spec in self.attachments:
            if spec.slot == slot:
                return spec
        allowed = "、".join(spec.slot for spec in self.attachments)
        raise HTTPException(422, f"附件类别只能是 {allowed}")

    def _require(self, record_id: str) -> Any:
        row = self.find(record_id)
        if row is None:
            raise HTTPException(404, f"{self.table_label}记录不存在，可能已被其他管理员删除")
        return row

    def _asset_in_use(
        self, db, asset_id: str | None, *, skip: str | None = None, skip_column: str = ""
    ) -> bool:
        """附件按内容去重，同一张图可能被多行共用。"""
        return asset_used_elsewhere(
            db, asset_id, skip_table=self.table, skip_key=self.table_key_column,
            skip_value=skip, skip_column=skip_column,
        )

    def _release_asset(
        self, db, asset_id: str | None, *, skip: str | None = None, skip_column: str = ""
    ) -> None:
        if asset_id and not self._asset_in_use(db, asset_id, skip=skip, skip_column=skip_column):
            self.assets.delete(asset_id, db=db)

    def _other_columns_in_use(self, db, asset_id: str, *, skip: str) -> bool:
        return self._asset_in_use(db, asset_id, skip=skip)

    def set_attachment(
        self, record_id: str, slot: str, data: bytes, mime: str | None, name: str = ""
    ) -> dict[str, Any]:
        spec = self.attachment(slot)
        row = self._require(record_id)
        previous = row[spec.column]
        asset_name = name if spec.name_column else ""
        with self._connect() as db:
            record = self.assets.put(spec.kind, data, mime, asset_name, db=db)
            assignments = [f"{quote_identifier(spec.column)}=?"]
            payload: list[Any] = [record["id"]]
            if spec.name_column:
                assignments.append(f"{quote_identifier(spec.name_column)}=?")
                payload.append(record["name"])
            payload.extend((_stamp(), record_id))
            db.execute(
                f"UPDATE {self.table} SET {','.join(assignments)},updated=? WHERE id=?", tuple(payload)
            )
            if previous and previous != record["id"]:
                self._release_asset(db, previous)
        return self._typed(self.find(record_id))

    def clear_attachment(self, record_id: str, slot: str) -> dict[str, Any]:
        spec = self.attachment(slot)
        row = self._require(record_id)
        previous = row[spec.column]
        assignments = [f"{quote_identifier(spec.column)}=NULL"]
        if spec.name_column:
            assignments.append(f"{quote_identifier(spec.name_column)}=''")
        with self._connect() as db:
            db.execute(
                f"UPDATE {self.table} SET {','.join(assignments)},updated=? WHERE id=?",
                (_stamp(), record_id),
            )
            self._release_asset(db, previous)
        return self._typed(self.find(record_id))

    # ---------------- 旧数据接入 / 种子 ----------------

    def _attachment_id(
        self, db, spec: AttachmentSpec, value: Any, *, name: str = "", mime: str | None = None
    ) -> str | None:
        """接受原始字节、旧 data URL，或已经是本站附件 URL 的值。"""
        if not value:
            return None
        if isinstance(value, (bytes, bytearray)):
            record = self.assets.put(
                spec.kind, bytes(value), mime or spec.default_mime or None, name, db=db
            )
            return record["id"] if record else None
        if not isinstance(value, str):
            return None
        if value.startswith("data:"):
            record = self.assets.put_data_url(spec.kind, value, name, db=db)
            return record["id"] if record else None
        return self.assets.asset_reference(value)

    def _row_attachments(self, db, row: dict[str, Any]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for spec in self.attachments:
            name = ""
            if spec.name_column:
                name = str(row.get(spec.name_column) or (row.get(spec.name_key) if spec.name_key else "") or "")
                name = name.strip()[:160]
            value = None
            for key in spec.value_keys:
                if row.get(key):
                    value = row[key]
                    break
            asset_id = self._attachment_id(
                db,
                spec,
                value,
                name=name,
                mime=row.get(spec.mime_key) if spec.mime_key else None,
            )
            resolved[spec.column] = asset_id
            if spec.name_column:
                resolved[spec.name_column] = name
        return resolved

    def insert_rows(self, rows: list[dict[str, Any]], *, keep_ids: bool = True) -> list[str]:
        """按页面/旧格式插入一批行，返回按顺序的 id。"""
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise HTTPException(422, f"{self.table_label}必须是对象数组")
        if len(rows) > 20_000:
            raise HTTPException(422, f"{self.table_label}超过 20000 条")
        now = _stamp()
        ids: list[str] = []
        with self._connect() as db:
            self.prepare_rows(db, rows)
            for index, row in enumerate(rows):
                values = self.clean_values(row, strict=False)
                record_id = str(row.get("id") or "").strip()[:64] if keep_ids else ""
                if not record_id or self.find(record_id, db=db) is not None:
                    record_id = uuid.uuid4().hex
                attachments = self._row_attachments(db, row)
                self._insert(
                    db,
                    record_id,
                    index,
                    values,
                    is_fallback=bool(row.get("is_fallback")),
                    attachment_ids=attachments,
                    now=now,
                )
                ids.append(record_id)
            self._ensure_fallback(db)
        return ids

    def natural_key(self, values: dict[str, Any]) -> tuple:
        """旧接口整体保存时用来把提交行匹配回已有行（保持 id 稳定）。

        ``values`` 一律是**列名 → 值**（不是 JSON 短键），子类覆写时请按列名取值。
        """
        columns = [field.column for field in self.fields[:2]]
        return tuple(values.get(column, "") for column in columns)

    def replace_legacy(self, rows: list[dict[str, Any]], *, prune: bool = False) -> dict[str, Any]:
        """兼容旧页面整体保存（``PUT /libraries``）：按自然键匹配，id 尽量不变。

        ``prune`` 默认 **False**：提交里没出现的行不会被删。旧接口收到的是整库数组，
        但只要客户端只带了筛选后的一部分（或换了新页面后数组被就地同步过），整表覆盖
        就会静默删掉库里其余数据 —— 实测一次就能清空 177 条夹具、437 条检具。
        删除一律走行级 ``DELETE /{库}/{id}``，这条兼容接口只做新增/更新。
        """
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise HTTPException(422, f"{self.table_label}必须是对象数组")
        now = _stamp()
        inserted = updated = 0
        matched: set[str] = set()
        removed: list[dict[str, Any]] = []
        columns = self.field_columns
        with self._connect() as db:
            self.prepare_rows(db, rows)
            existing = db.execute(
                f"SELECT * FROM {self.table} WHERE deleted_at IS NULL ORDER BY sort_order, id"
            ).fetchall()
            pools: dict[tuple, list[Any]] = {}
            for row in existing:
                # 已有行也要按各自的 natural_key 建池，否则子类覆写的键形状对不上
                key = self.natural_key({column: row[column] for column in columns})
                pools.setdefault(key, []).append(row)
            for index, row in enumerate(rows):
                values = self.clean_values(row, strict=False)
                candidates = [
                    item for item in pools.get(self.natural_key(values), []) if item["id"] not in matched
                ]
                attachments = self._row_attachments(db, row)
                if candidates:
                    current = candidates[0]
                    matched.add(current["id"])
                    assignments = ["sort_order=?"]
                    payload: list[Any] = [index]
                    for column in columns:
                        assignments.append(f"{quote_identifier(column)}=?")
                        payload.append(values[column])
                    for spec in self.attachments:
                        assignments.append(f"{quote_identifier(spec.column)}=?")
                        payload.append(attachments.get(spec.column) or current[spec.column])
                        if spec.name_column:
                            assignments.append(f"{quote_identifier(spec.name_column)}=?")
                            payload.append(attachments.get(spec.name_column) or current[spec.name_column])
                    assignments.append("updated=?")
                    payload.extend((now, current["id"]))
                    db.execute(
                        f"UPDATE {self.table} SET " + ",".join(assignments) + " WHERE id=?",
                        tuple(payload),
                    )
                    updated += 1
                else:
                    record_id = uuid.uuid4().hex
                    self._insert(
                        db,
                        record_id,
                        index,
                        values,
                        is_fallback=bool(row.get("is_fallback")),
                        attachment_ids=attachments,
                        now=now,
                    )
                    inserted += 1
            if prune:
                for row in existing:
                    if row["id"] in matched:
                        continue
                    # 口径 2：这里也只是逻辑删除（整库覆盖不再物理删行，附件保留）
                    db.execute(
                        f"UPDATE {self.table} SET deleted_at=?,deleted_by=?,deleted_reason=?,updated=? "
                        "WHERE id=?",
                        (now, "legacy-save", "整库覆盖时提交里没有这一行", now, row["id"]),
                    )
                    entry = {"id": row["id"]}
                    for key in self.display_keys:
                        field = self.field(key)
                        if field:
                            entry[key] = row[field.column]
                    removed.append(entry)
            self._ensure_fallback(db)
        result: dict[str, Any] = {
            "inserted": inserted,
            "updated": updated,
            "removed": removed,
            "count": inserted + updated,
        }
        if self.supports_fallback:
            result["fallback"] = self.default_ref()
        return result


class NameDictionary:
    """按**名称**作主键的类别字典（模具中心 / 检具类别），外键直接用中文名。

    为什么用中文名而不是编码：项目快照里存的就是 ``"模具中心|夹具名称"``、
    ``"检具类别|名称|图号"`` 这种按名字拼的选择键（夹具/检具成本表据此回查价格），
    用名称做键可以让项目数据、成本表、导出与页面全部零改动；代价是**类别不可改名**，
    只能新增/删除（改名等于新增一个类别再搬数据）。

    子类（或使用时）给出：``table`` / ``table_label`` / ``reference_table`` /
    ``reference_column`` / ``seed``，以及可选的 ``cascade`` 回调（删类别时连带删数据）。
    """

    table = ""
    table_label = ""
    reference_table = ""
    reference_column = ""
    seed: tuple[str, ...] = ()

    def __init__(self, connect, *, seed: Iterable[str] = (), cascade: Callable[[Any, str], int] | None = None):
        self._connect = connect
        self.seed = tuple(dict.fromkeys(str(item).strip() for item in seed if str(item).strip()))
        self.cascade = cascade

    # ---------------- 建表 / 种子 ----------------

    def ddl(self) -> str:
        return (
            f"CREATE TABLE IF NOT EXISTS {self.table}(\n"
            "    name TEXT PRIMARY KEY,\n"
            "    sort_order INTEGER NOT NULL DEFAULT 0,\n"
            "    builtin INTEGER NOT NULL DEFAULT 1,\n"
            "    source TEXT NOT NULL DEFAULT 'seed',\n"
            "    created TEXT NOT NULL,\n"
            "    updated TEXT NOT NULL,\n"
            + ",\n".join(f"    {column} TEXT" for column in TRASH_COLUMNS)
            + "\n);\n"
        )

    def ensure_trash_columns(self, db) -> list[str]:
        existing = {row[1] for row in db.execute(f"PRAGMA table_info({self.table})")}
        added: list[str] = []
        for column in TRASH_COLUMNS:
            if column not in existing:
                db.execute(f"ALTER TABLE {self.table} ADD COLUMN {column} TEXT")
                added.append(column)
        return added

    def schema(self, db) -> None:
        db.executescript(self.ddl())
        self.ensure_trash_columns(db)
        db.executescript(
            f"CREATE INDEX IF NOT EXISTS idx_machining_dfm_{self.table}_trash "
            f"ON {self.table}(deleted_at, sort_order);\n"
        )

    def seed_rows(self, db, names: Iterable[str] | None = None, *, source: str = "seed") -> list[str]:
        """把类别灌进字典：``INSERT OR IGNORE``，已存在的不动（只补不改）。"""
        pending = list(dict.fromkeys(
            str(item).strip() for item in (self.seed if names is None else names) if str(item).strip()
        ))
        added: list[str] = []
        now = _stamp()
        order = int(
            db.execute(f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {self.table}").fetchone()[0]
        )
        for name in pending:
            cursor = db.execute(
                f"INSERT OR IGNORE INTO {self.table}(name,sort_order,builtin,source,created,updated) "
                "VALUES(?,?,?,?,?,?)",
                (name, order, 1 if source == "seed" else 0, source, now, now),
            )
            if cursor.rowcount:
                added.append(name)
                order += 1
        return added

    # ---------------- 读取 ----------------

    def names(self, db=None) -> list[dict[str, Any]]:
        with self._session(db) as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.table} WHERE deleted_at IS NULL ORDER BY sort_order, name"
            ).fetchall()
        return [self._view(row) for row in rows]

    def trash(self, db=None) -> list[dict[str, Any]]:
        """回收站：已逻辑删除的类别（按删除时间倒序）。"""
        with self._session(db) as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.table} WHERE deleted_at IS NOT NULL "
                "ORDER BY deleted_at DESC, sort_order, name"
            ).fetchall()
        return [self._trash_view(row) for row in rows]

    def _trash_view(self, row) -> dict[str, Any]:
        view = self._view(row)
        view.update({
            "deleted_at": row["deleted_at"],
            "deleted_by": row["deleted_by"] or "",
            "deleted_reason": row["deleted_reason"] or "",
        })
        return view

    def find_row(self, name: str, db=None):
        with self._session(db) as conn:
            return conn.execute(f"SELECT * FROM {self.table} WHERE name=?", (name,)).fetchone()

    def name_map(self, db=None) -> dict[str, dict[str, Any]]:
        return {row["value"]: row for row in self.names(db=db)}

    def count(self, name: str, db=None) -> int:
        """有多少条**在用**数据挂在这个类别下（回收站里的行不算）。"""
        with self._session(db) as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {self.reference_table} "
                f"WHERE {self.reference_column}=? AND deleted_at IS NULL",
                (name,),
            ).fetchone()
        return int(row[0])

    def usage(self, db=None) -> dict[str, int]:
        with self._session(db) as conn:
            rows = conn.execute(
                f"SELECT {self.reference_column}, COUNT(*) FROM {self.reference_table} "
                f"WHERE deleted_at IS NULL GROUP BY {self.reference_column}"
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def require(self, name: str, *, db=None) -> None:
        if str(name).strip() not in self.name_map(db=db):
            raise HTTPException(422, f"{self.table_label}「{name}」不在类别字典里，请先在管理设置里维护")

    def register(self, names: Iterable[str], *, db=None) -> list[str]:
        """旧数据里出现过、字典里还没有的类别自动补录（标注 ``source='legacy'``）。"""
        pending = [str(item).strip() for item in names if str(item).strip()]
        return self.seed_rows(db, pending, source="legacy") if pending else []

    # ---------------- 维护接口 ----------------

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _clean_name(payload.get("name") or payload.get("value"), self.table_label)
        with self._connect() as db:
            row = db.execute(f"SELECT * FROM {self.table} WHERE name=?", (name,)).fetchone()
            if row is not None and not row["deleted_at"]:
                raise HTTPException(409, f"{self.table_label}「{name}」已存在")
            if row is not None:
                # 同名重建 = 复活原行（口径 3）：回收站里那条直接复活，不新建重复行
                db.execute(
                    f"UPDATE {self.table} SET deleted_at=NULL,deleted_by=NULL,deleted_reason=NULL,"
                    "updated=? WHERE name=?",
                    (_stamp(), name),
                )
                revived = self._one(name)
                revived["revived"] = True
                return revived
            order = int(
                db.execute(f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {self.table}").fetchone()[0]
            )
            now = _stamp()
            db.execute(
                f"INSERT INTO {self.table}(name,sort_order,builtin,source,created,updated) "
                "VALUES(?,?,0,'admin',?,?)",
                (name, order, now, now),
            )
        return self._one(name)

    def update(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """只能调顺序：类别名是外键，改名会让项目里的选择键失配，因此不接受改名。"""
        requested = payload.get("name") or payload.get("value")
        if requested is not None and str(requested).strip() and str(requested).strip() != name:
            raise HTTPException(422, f"{self.table_label}不可改名：请新增一个类别再搬迁数据（旧名 {name}）")
        order = payload.get("sort_order")
        with self._connect() as db:
            if not db.execute(f"SELECT 1 FROM {self.table} WHERE name=?", (name,)).fetchone():
                raise HTTPException(404, f"{self.table_label}「{name}」不存在")
            if order is None:
                raise HTTPException(422, "只支持调整顺序（sort_order）")
            try:
                order = int(order)
            except (TypeError, ValueError):
                raise HTTPException(422, "顺序必须是整数") from None
            db.execute(
                f"UPDATE {self.table} SET sort_order=?,updated=? WHERE name=?",
                (order, _stamp(), name),
            )
        return self._one(name)

    def delete(self, name: str, *, cascade: bool = False, by: str = "", reason: str = "") -> dict[str, Any]:
        """**逻辑删除**（口径 2）：类别行与它下面的数据行都只是打标记，附件一律保留。

        被引用的行数照旧要 ``cascade=True`` 才允许（引用计数用的是"在用行"）。
        """
        with self._connect() as db:
            row = db.execute(f"SELECT * FROM {self.table} WHERE name=?", (name,)).fetchone()
            if row is None:
                raise HTTPException(404, f"{self.table_label}「{name}」不存在")
            if row["deleted_at"]:
                raise HTTPException(409, f"{self.table_label}「{name}」已经在回收站里了")
            if row["builtin"]:
                raise HTTPException(409, f"{self.table_label}「{name}」是内置类别，不能删除（可以新增自定义类别）")
            used = self.count(name, db=db)
            if used and not cascade:
                raise HTTPException(
                    409, f"{self.table_label}「{name}」下还有 {used} 条数据，删除需带 ?cascade=1 一起删除"
                )
            now = _stamp()
            who = _who(by)
            text = str(reason or "")[:200]
            removed = 0
            if used:
                if self.cascade is not None:
                    # 交给引用方处理：它把那些行一起**逻辑删除**（附件保留）
                    removed = int(self.cascade(db, name, by=who, reason=text))
                else:
                    db.execute(
                        f"UPDATE {self.reference_table} SET deleted_at=?,deleted_by=?,deleted_reason=?,"
                        f"updated=? WHERE {self.reference_column}=? AND deleted_at IS NULL",
                        (now, who, text, now, name),
                    )
                    removed = used
            db.execute(
                f"UPDATE {self.table} SET deleted_at=?,deleted_by=?,deleted_reason=?,updated=? "
                "WHERE name=?",
                (now, who, text, now, name),
            )
        return {
            "name": name,
            "builtin": bool(row["builtin"]),
            "removed_rows": removed,
            "removed": True,
            "deleted_at": now,
            "deleted_by": who,
            "deleted_reason": text,
        }

    def restore(self, name: str, *, by: str = "") -> dict[str, Any]:
        """从回收站恢复类别（它下面被连带删除的数据行要各自恢复，不自动跟着回来）。"""
        with self._connect() as db:
            row = db.execute(f"SELECT * FROM {self.table} WHERE name=?", (name,)).fetchone()
            if row is None:
                raise HTTPException(404, f"{self.table_label}「{name}」不存在")
            if not row["deleted_at"]:
                raise HTTPException(409, f"{self.table_label}「{name}」本来就在用，不需要恢复")
            db.execute(
                f"UPDATE {self.table} SET deleted_at=NULL,deleted_by=NULL,deleted_reason=NULL,updated=? "
                "WHERE name=?",
                (_stamp(), name),
            )
        restored = self._one(name)
        restored["restored_by"] = _who(by)
        return restored

    # ---------------- 内部 ----------------

    def _view(self, row) -> dict[str, Any]:
        return {
            "value": row["name"],
            "name": row["name"],
            "label": row["name"],
            "sort_order": int(row["sort_order"]),
            "builtin": bool(row["builtin"]),
            "source": row["source"],
        }

    def _one(self, name: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(f"SELECT * FROM {self.table} WHERE name=?", (name,)).fetchone()
        return self._view(row)

    def _session(self, db=None):
        return _SharedSession(self._connect, db)


class _SharedSession:
    """复用外部连接，或在没传时自己开一个（与 AssetStore.session 同语义）。"""

    def __init__(self, connect, db):
        self._connect = connect
        self._db = db
        self._own = None

    def __enter__(self):
        if self._db is not None:
            return self._db
        self._own = self._connect()
        return self._own.__enter__()

    def __exit__(self, *exc):
        if self._own is not None:
            return self._own.__exit__(*exc)
        return False


def _clean_name(value: Any, label: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 60:
        raise HTTPException(422, f"{label}名称必须是 1-60 个字符")
    return name
