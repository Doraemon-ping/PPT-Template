# -*- coding: utf-8 -*-
"""项目级多行表的公共基类（工序 / 刀具行 / 问题清单 / 选型 / 履历 / 变更流水共用）。

**为什么单独一个模块**：这几张表的引擎原本挤在"工序"那个业务域里，于是问题清单、选型、
版本履历、变更流水四个域都得反过来 import 工序模块的私有符号（``_ProjectRows`` /
``ForeignKey`` / ``clean_json_object``）。那是**同级反向依赖**：工序和它们本是平级业务域，
却被迫当成了别人的底座。把公共部分下沉到本模块之后，依赖方向变成单向的

    domains/*  →  db/rows.py  →  db/library.py  →  core/*

业务域之间不再互相 import，新增业务域（比如"检验记录"）只继承本模块即可，不必动工序。

**这里有什么**：项目作用域 + 可选父行 + 逻辑删除 + 排序 + 真外键校验 + 变更流水挂钩。
**这里没有什么**：任何机加专有的字段、公式与读模型（那些留在各自 ``app/domains/`` 里）。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Iterable, NamedTuple

from fastapi import HTTPException

from ..core.utils import js_number, stamp
from .library import AttachmentSpec, TypedLibrary, quote_identifier

__all__ = [
    "ForeignKey",
    "normalize_foreign",
    "clean_json_object",
    "asset_value",
    "ProjectRows",
]


def clean_json_object(payload: Any) -> dict[str, Any]:
    """通用 JSON 对象列的校验器：任意对象照存，非对象报 422（默认不做键级校验）。"""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "该字段必须是 JSON 对象")
    return payload


def asset_value(asset_store, asset_id: str | None, inline: bool) -> Any:
    """附件列的读模型取值：``inline`` 时给 data URL（PPT 快照要字节），否则给本站下载地址。"""
    if not asset_id:
        return None
    if asset_store is None:
        return asset_id
    return asset_store.data_url(asset_id) if inline else asset_store.url(asset_id)


class ForeignKey(NamedTuple):
    """一个真外键列：``列名 → 目标表(目标列)``。

    ``soft`` 表示"目标表逻辑删除的行算不算不存在"：``None``（默认）**自动看目标表有没有
    ``deleted_at`` 列**——库表（``machines``/``fixtures``/``gauges``/``assets``）都是物理删除、
    没有这一列，项目级行表（``project_processes`` 等）有。自动探测是为了不让人猜错：
    写死 ``True`` 去查一张没有 ``deleted_at`` 的表会直接 SQL 报错。

    ``on_delete`` 只在需要"目标行没了也别拦住删除"时填 ``SET NULL``：库行被删掉时，
    选型行把外键置空、靠快照列继续算价（口径 4），既不卡住删除也不丢数据。
    """

    column: str
    table: str
    target: str = "id"
    soft: bool | None = None
    on_delete: str = ""


def normalize_foreign(items: Any) -> tuple[ForeignKey, ...]:
    """把 ``(列, 表)`` / ``(列, 表, 目标列)`` / :class:`ForeignKey` 统一成 ForeignKey。

    允许简写是为了让各表的声明短一点；解析只做一次，DDL 与校验都走同一份。
    """
    result: list[ForeignKey] = []
    for item in items or ():
        if isinstance(item, ForeignKey):
            result.append(item)
        elif len(item) == 2:
            result.append(ForeignKey(str(item[0]), str(item[1])))
        elif len(item) == 3:
            result.append(ForeignKey(str(item[0]), str(item[1]), str(item[2])))
        else:
            result.append(ForeignKey(str(item[0]), str(item[1]), str(item[2]),
                                     None if item[3] is None else bool(item[3]),
                                     str(item[4]) if len(item) > 4 else ""))
    return tuple(result)


class ProjectRows(TypedLibrary):
    """项目级多行表的公共部分：项目作用域 + 可选父行 + 逻辑删除 + 排序。

    **外键口径**：凡是"指向别的表里的行"的列，一律用真外键（``REFERENCES``），
    不做"存个字符串自己心里有数"的软引用。父行（工序）默认必填，子表可声明
    ``parent_nullable``；另有 ``foreign_keys`` 声明若干可空外键列（问题清单指工序、
    选型报价指夹具/检具库与类别字典）。
    """

    project_column = "project_id"
    #: 需要挂父行的表填列名（工序刀具行 → ``process_id``）
    parent_column = ""
    #: 父行指向哪张表。**故意不给默认值**：父表是业务域自己的表，基类不认识它，
    #: 需要父行的子类必须显式声明（``ProjectProcessTools`` 写 ``PROCESS_TABLE``）。
    parent_table = ""
    #: 父行可不可以为空（问题清单可以只挂项目，不挂工序）
    parent_nullable = False
    #: 排序范围：``parent`` = 每个父行各自一条序列（刀具行在工序内排序）；
    #: ``project`` = 整个项目一条序列（问题清单在页面上就是一张平表）
    order_scope = "parent"
    #: 额外的可空外键列：``((列名, 目标表[, 目标列]), ...)``，见 :class:`ForeignKey`
    foreign_keys: tuple[Any, ...] = ()
    #: 表级 CHECK（例如"选型要么挂夹具库要么挂检具库，不能都挂"）
    check_sql = ""
    json_columns: dict[str, str] = {}
    #: 每个 JSON 列各自的校验器（``nc`` 是六个计数，设备快照是任意对象）
    json_cleaners: dict[str, Any] = {}
    #: 没在 ``json_cleaners`` 里点名的 JSON 列用哪个校验器。
    #: 必须包 ``staticmethod``：直接赋值函数会变成绑定方法，调用时把 ``self`` 当成载荷传进去。
    default_json_cleaner: Any = staticmethod(clean_json_object)
    #: 额外的**可空**列（原样写进 DDL，放在 JSON 列之后）：给"历史遗留、只读、
    #: 不参与校验"的列留位置（例如变更流水里指向已废弃多态表的 ``selection_row_id``）。
    #: 这类列不建外键、不进 ``fields``，也不出现在写入载荷里。
    extra_columns: tuple[str, ...] = ()

    #: 阶段 3b 变更流水用：这张表的行算什么"实体"（``project_changes.entity``）。
    #: 空串 = 这张表不进变更流水（基础库那几张表就不进）。
    change_entity = ""
    #: 写变更流水的出口：``store._note_change``（由 store 在构造时挂上；没挂就不记 = 迁移工具里不记）
    change_sink: Any = None
    #: 组合"这条记录叫什么"用哪几个键（读模型键，如工序的 ``nm``）
    title_keys: tuple[str, ...] = ()
    #: 变更流水里字段值的最大展示长度（超了截断，别把 4000 字的问题描述塞进一行流水）
    change_text_limit = 60
    #: 纯符号字段的中文补名：登记表里的 ``label`` 就是页面表头（``n``/``vf``/``D``），
    #: 表格里看得懂，但流水是一句人话——只写"n 3000→3500"没人知道是什么
    change_field_labels = {
        "n": "转速", "vf": "进给", "d": "直径", "ln": "切削长度",
        "sd": "主轴延时", "tt": "换刀时间", "td": "快移距离", "ps": "走刀次数",
    }

    #: 图片槽位在流水里的中文名（槽位名 ``photo``/``layout`` 是给程序看的）
    change_slot_labels = {
        "photo": "照片", "layout": "布局图",
        "before": "修改前", "after": "修改后", "doc": "资料",
    }

    def __init__(self, connect, assets):
        super().__init__(connect, assets)
        #: 目标表有没有 deleted_at 的缓存（每次写都去 PRAGMA 太浪费）
        self._soft_cache: dict[str, bool] = {}

    # ---------------- 变更流水：这条记录怎么称呼、改了哪几个字段 ----------------

    def change_label(self, column: str, key: str = "") -> str:
        """某个字段在流水里叫什么。"""
        label = self.label_map.get(column) or self.label_map.get(key) or column
        extra = self.change_field_labels.get(column) or self.change_field_labels.get(key)
        if extra and label.isascii():
            return f"{extra} {label}"
        return label

    def change_slot_label(self, spec: Any) -> str:
        """图片槽位在流水里的中文名（``photo`` → 照片）。"""
        return self.change_slot_labels.get(spec.slot) or spec.legacy_key or spec.column

    def _note_change(self, action: str, *, row: dict[str, Any] | None = None,
                     label: str = "", record_id: str | None = None,
                     extra: dict[str, Any] | None = None) -> None:
        """把"刚发生了什么"交给 store（阶段 3b 的变更流水）。

        这里**只交草稿**，不写库：真正的插入发生在 ``store`` 的 ``_bump_project`` 那个事务里
        （那时才知道这次保存的版本行 id），所以流水与保存版本同生共死。
        """
        if self.change_sink is None or not self.change_entity:
            return
        self.change_sink({
            "entity": self.change_entity,
            "action": action,
            "label": label,
            "record_id": record_id if record_id is not None else (row or {}).get("id"),
            "extra": extra or {},
        })

    def row_title(self, row: dict[str, Any] | None) -> str:
        """这条记录"叫什么"（工序按名称、刀具按编号+类型、履历按版本号……）。"""
        if not row:
            return ""
        parts: list[str] = []
        for key in self.title_keys:
            value = row.get(key)
            if value in (None, ""):
                continue
            text = str(value).strip()
            if text and text not in parts:
                parts.append(text)
        if not parts:
            return str(row.get("id") or "")[:8]
        text = " ".join(parts)
        if len(text) > self.change_text_limit:
            return text[: self.change_text_limit] + "…"
        return text

    @property
    def label_map(self) -> dict[str, str]:
        """字段 → 中文名（变更流水里写"转速 3000→3500"用）。"""
        mapping: dict[str, str] = {}
        for field in self.fields:
            mapping[field.column] = field.label
        return mapping

    def display_value(self, key: str, value: Any) -> str:
        """变更流水里怎么展示一个值：数字按 JS 口径、布尔说人话、文本截断。"""
        if isinstance(value, bool):
            return "是" if value else "否"
        if value is None:
            return "（空）"
        if isinstance(value, (int, float)):
            return str(js_number(value))
        text = str(value)
        if not text:
            return "（空）"
        text = text.replace("\n", " ").strip()
        if len(text) > self.change_text_limit:
            text = text[: self.change_text_limit] + "…"
        return text

    # ---------------- 列清单 ----------------

    @property
    def fks(self) -> tuple[ForeignKey, ...]:
        """规范化后的外键清单（子类写 2 元组也行）。"""
        return normalize_foreign(self.foreign_keys)

    @property
    def fk_columns(self) -> tuple[str, ...]:
        """外键列名。这些列可能同时登记在 ``fields`` 里（``machine_id``/``tool_id``……）：

        登记表管它的**键名与校验**，SQL 里则必须由外键那一份声明的（可空 TEXT REFERENCES）
        来建列 —— 建列**只有一次**，否则 DDL 与 INSERT 都会出现同名列。
        """
        return tuple(fk.column for fk in self.fks)

    @property
    def field_columns(self) -> tuple[str, ...]:
        """普通字段列（外键列不重复出现）。"""
        skip = set(self.fk_columns)
        return tuple(field.column for field in self.fields if field.column not in skip)

    @property
    def key_columns(self) -> tuple[str, ...]:
        """除项目列之外的"外键列"（父行 + 额外外键），读写都要带上。"""
        columns = [self.parent_column] if self.parent_column else []
        columns.extend(fk.column for fk in self.fks)
        return tuple(columns)

    @property
    def check_expressions(self) -> tuple[str, ...]:
        """表级 CHECK：可以写成一条字符串，也可以写成多条（各自补上 ``CHECK``）。"""
        if not self.check_sql:
            return ()
        items = (self.check_sql,) if isinstance(self.check_sql, str) else tuple(self.check_sql)
        return tuple(item if item.upper().startswith("CHECK") else f"CHECK ({item})" for item in items)

    @property
    def insert_columns(self) -> tuple[str, ...]:
        """INSERT 的列顺序（DDL 与写入必须严格按这一份，否则列对不上）。"""
        columns = ["id", self.project_column]
        columns.extend(self.key_columns)
        columns.append("sort_order")
        columns.extend(self.field_columns)
        columns.extend(self.json_columns.values())
        columns.extend(self.attachment_columns)
        columns.extend(("deleted_at", "deleted_by", "deleted_reason", "created", "updated"))
        return tuple(columns)

    # ---------------- 表结构 ----------------

    def ddl(self) -> str:
        """建表语句：项目列 → 父行 → 排序 → 普通字段 → JSON 列 → 外键 → 附件 → 逻辑删除时间戳。"""
        lines = [
            "id TEXT PRIMARY KEY",
            f"{self.project_column} TEXT NOT NULL REFERENCES projects(id)",
        ]
        if self.parent_column:
            null = "" if self.parent_nullable else " NOT NULL"
            lines.append(f"{self.parent_column} TEXT{null} REFERENCES {self.parent_table}(id)")
        lines.append("sort_order INTEGER NOT NULL DEFAULT 0")
        ddl_types = {"text": "TEXT", "choice": "TEXT", "real": "REAL", "int": "INTEGER"}
        fk_columns = set(self.fk_columns)
        for field in self.fields:
            if field.column in fk_columns:
                continue  # 这一列由下面的外键声明建（可空 + REFERENCES）
            sql_type = ddl_types.get(field.kind, "TEXT")
            if field.kind in {"text", "choice"}:
                literal = "'" + str(field.default).replace("'", "''") + "'"
            else:
                literal = repr(float(field.default)) if field.kind == "real" else str(int(field.default))
            lines.append(f"{quote_identifier(field.column)} {sql_type} NOT NULL DEFAULT {literal}")
        for column in self.json_columns.values():
            lines.append(f"{quote_identifier(column)} TEXT NOT NULL DEFAULT '{{}}'")
        lines.extend(self.extra_columns)
        for fk in self.fks:
            on_delete = f" ON DELETE {fk.on_delete}" if fk.on_delete else ""
            lines.append(
                f"{quote_identifier(fk.column)} TEXT REFERENCES {fk.table}({fk.target}){on_delete}"
            )
        for spec in self.attachments:
            lines.append(f"{quote_identifier(spec.column)} TEXT REFERENCES assets(id)")
        lines.extend(
            (
                "deleted_at TEXT",
                "deleted_by TEXT NOT NULL DEFAULT ''",
                "deleted_reason TEXT NOT NULL DEFAULT ''",
                "created TEXT NOT NULL",
                "updated TEXT NOT NULL",
            )
        )
        for expression in self.check_expressions:
            lines.append(expression)
        return f"CREATE TABLE IF NOT EXISTS {self.table}(\n    " + ",\n    ".join(lines) + "\n);\n"

    def index_ddl(self) -> str:
        """索引：项目+排序、父行+排序、每个外键列各一条。"""
        script = (
            f"CREATE INDEX IF NOT EXISTS idx_machining_dfm_{self.table}_scope "
            f"ON {self.table}({self.project_column}, sort_order, id);\n"
        )
        if self.parent_column:
            script += (
                f"CREATE INDEX IF NOT EXISTS idx_machining_dfm_{self.table}_parent "
                f"ON {self.table}({self.parent_column}, sort_order, id);\n"
            )
        for fk in self.fks:
            script += (
                f"CREATE INDEX IF NOT EXISTS idx_machining_dfm_{self.table}_{fk.column} "
                f"ON {self.table}({fk.column});\n"
            )
        return script

    def schema(self, db) -> None:
        """建表 + 建索引（幂等，每次开库都跑一遍）。"""
        db.executescript(self.ddl())
        db.executescript(self.index_ddl())

    # ---------------- 视图 ----------------

    def _json(self, row: Any, key: str) -> dict[str, Any]:
        column = self.json_columns.get(key)
        raw = row[column] if column else "{}"
        try:
            parsed = json.loads(raw or "{}")
        except (TypeError, ValueError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def _typed(self, row: Any) -> dict[str, Any]:
        """一行 → 类型化视图（加上项目列、外键列、逻辑删除列与解开的 JSON 列）。"""
        view = super()._typed(row)
        view[self.project_column] = row[self.project_column]
        for column in self.key_columns:
            value = row[column]
            field = next((item for item in self.fields if item.column == column), None)
            if field is not None and value is None:
                # **同时登记成字段**的外键列（machine_id/tool_id/handle_id/accessory_id）：
                # 空 = 没绑（NULL），对外仍旧是空串 —— 这些列旧形态就是 NOT NULL DEFAULT ''，
                # 读模型（mid/hld/acc 这些页面键）一个字都不能变。
                # 纯外键列（fixture_id/gauge_id/process_id…）保持 None：接口按"没绑"判断。
                value = ""
                view[field.key] = value
            view[column] = value
        view["deleted_at"] = row["deleted_at"]
        view["deleted_by"] = row["deleted_by"]
        view["deleted_reason"] = row["deleted_reason"]
        for key in self.json_columns:
            view[key] = self._json(row, key)
        return view

    # ---------------- 读取 ----------------

    def rows(self, project_id: str | None = None, *, include_deleted: bool = False,
             db=None) -> list[Any]:
        """按项目取原始行（``project_id=None`` = 全表）。默认滤掉已逻辑删除的行。"""
        sql = f"SELECT * FROM {self.table}"
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append(f"{self.project_column}=?")
            params.append(project_id)
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY sort_order, id"
        with self.assets.session(db) as conn:
            return conn.execute(sql, tuple(params)).fetchall()

    def list_typed(self, project_id: str, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        """按项目取类型化视图。"""
        return [self._typed(row) for row in self.rows(project_id, include_deleted=include_deleted)]

    def recycle_bin(self, project_id: str) -> list[dict[str, Any]]:
        """回收站：这个项目里被逻辑删除的行（口径 2，永不物理删除）。"""
        return [self._typed(row) for row in self.rows(project_id, include_deleted=True)
                if row["deleted_at"]]

    def count(self, project_id: str | None = None, *, include_deleted: bool = False) -> int:
        return len(self.rows(project_id, include_deleted=include_deleted))

    def _require(self, record_id: str) -> Any:
        row = self.find(record_id)
        if row is None or row["deleted_at"]:
            raise HTTPException(404, f"{self.table_label}记录不存在，可能已被删除")
        return row

    def require_in_project(self, project_id: str, record_id: str, *,
                           allow_deleted: bool = False) -> Any:
        """行必须属于这个项目（接口层用：防止拿 A 项目的 id 去改 B 项目的数据）。"""
        row = self.find(record_id)
        if row is None or str(row[self.project_column]) != str(project_id):
            raise HTTPException(404, f"{self.table_label}记录不属于该项目")
        if row["deleted_at"] and not allow_deleted:
            raise HTTPException(410, f"{self.table_label}已删除，可在回收站恢复")
        return row

    # ---------------- 写入 ----------------

    def _clean(self, payload: dict[str, Any], *, partial: bool, strict: bool = True) -> dict[str, Any]:
        """校验成 ``{列: 值}``：普通字段走字段登记表，JSON 列与**外键列**单独处理。

        ``strict=False`` 只放宽取值枚举（旧数据迁移用：旧值不认识也照存，不中断迁移）。
        """
        skip = (self.project_column, *self.key_columns)
        body = {key: value for key, value in payload.items()
                if key not in self.json_columns and key not in skip}
        values = self.clean_values(body, partial=partial, strict=strict)
        for key, column in self.json_columns.items():
            cleaner = self.json_cleaners.get(key) or self.default_json_cleaner
            if key in payload:
                values[column] = json.dumps(cleaner(payload[key]), ensure_ascii=False,
                                            separators=(",", ":"))
            elif not partial:
                values[column] = json.dumps(cleaner(None), ensure_ascii=False,
                                            separators=(",", ":"))
        return values

    # ---------------- 外键校验（有关联就必须是真外键，报错也要说人话） ----------------

    def _require_foreign(self, conn, column: str, table: str, value: str,
                         *, target: str = "id", soft: bool | None = None) -> None:
        """目标行必须真存在；目标表有 ``deleted_at`` 时，"已逻辑删除的行"也算不存在。"""
        if soft is None:
            soft = self._soft_target(conn, table)
        if soft:
            row = conn.execute(
                f"SELECT deleted_at FROM {table} WHERE {quote_identifier(target)}=?", (value,)
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE {quote_identifier(target)}=?", (value,)
            ).fetchone()
        if row is None:
            raise HTTPException(422, f"{column} 指向的 {table} 记录不存在：{value}")
        if soft and row[0]:
            raise HTTPException(422, f"{column} 指向的 {table} 记录已被删除：{value}")

    def _soft_target(self, conn, table: str) -> bool:
        """目标表支不支持逻辑删除：看它有没有 ``deleted_at``（结果按表缓存）。"""
        cached = self._soft_cache.get(table)
        if cached is None:
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            cached = "deleted_at" in columns
            self._soft_cache[table] = cached
        return cached

    def _clean_foreign(self, conn, payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
        """外键列：空值 → ``NULL``（可空列）；有值必须真存在。

        取值时**列名与字段键都认**：外键列往往同时登记在 ``fields`` 里，而页面/旧数据用的是
        字段键（``mid`` → ``machine_id``、``hld_id`` → ``handle_id``、``acc_id`` →
        ``accessory_id``）。只认列名的话，页面提交 ``mid`` 会被当成"没给值"而写成 NULL。
        """
        values: dict[str, Any] = {}
        targets: dict[str, ForeignKey] = {fk.column: fk for fk in self.fks}
        if self.parent_column:
            targets[self.parent_column] = ForeignKey(self.parent_column, self.parent_table)
        aliases: dict[str, tuple[str, ...]] = {
            field.column: (field.column, field.key) for field in self.fields
        }
        for column, fk in targets.items():
            is_parent = bool(self.parent_column) and column == self.parent_column
            keys = aliases.get(column, (column,))
            source = next((key for key in keys if key in payload), None)
            if source is None:
                if partial:
                    continue
                if is_parent and not self.parent_nullable:
                    raise HTTPException(422, f"{self.table_label}必须指定 {column}")
                values[column] = None
                continue
            value = payload.get(source)
            if value is None or str(value).strip() == "":
                if is_parent and not self.parent_nullable:
                    raise HTTPException(422, f"{self.table_label}必须指定 {column}")
                values[column] = None
                continue
            text = str(value).strip()
            self._require_foreign(conn, column, fk.table, text, target=fk.target, soft=fk.soft)
            values[column] = text
        return values

    def _next_order(self, conn, scope_column: str, scope_value: str) -> int:
        return int(
            conn.execute(
                f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {self.table} WHERE {scope_column}=?",
                (scope_value,),
            ).fetchone()[0]
        )

    def create(
        self,
        project_id: str,
        payload: dict[str, Any],
        *,
        attachments: dict[str, Any] | None = None,
        db=None,
        strict: bool = True,
        order: int | None = None,
        record_id: str | None = None,
        created: str | None = None,
    ) -> dict[str, Any]:
        """新增一行。

        ``record_id`` / ``created`` 只有**迁移与复制**会传：迁移要"同样一份数据重复跑得到同一行"
        （幂等），也要保留历史时间戳；平时一律由服务端生成。
        """
        values = self._clean(payload, partial=False, strict=strict)
        record_id = str(record_id).strip() if record_id else uuid.uuid4().hex
        now = stamp()
        created_at = str(created).strip() if created else now
        with self.assets.session(db) as conn:
            keys = self._clean_foreign(conn, payload, partial=False)
            parent = str(keys.get(self.parent_column) or "") if self.parent_column else ""
            # 排序范围：``parent`` 的表按父行各自排序（刀具行在工序内）；
            # ``project`` 的表整个项目一条序列（问题清单是一张平表）。
            # 踩过的坑：问题清单曾经按"父行列"去算序号，而 process_id 为空时
            # `WHERE process_id='<项目 id>'` 匹配不到任何行 → 每行都拿到 0，顺序变成随机的。
            if self.order_scope == "parent" and self.parent_column and parent:
                scope_column, scope_value = self.parent_column, parent
            else:
                scope_column, scope_value = self.project_column, project_id
            # ``order`` 给了就用它：选型报价的"格子下标"由页面按类别顺序指定，
            # 不能另算一套（改了类别顺序、下标就对不上了）。
            slot = self._next_order(conn, scope_column, scope_value) if order is None else int(order)
            columns = self.insert_columns
            body: list[Any] = [record_id, project_id]
            body.extend(keys[column] for column in self.key_columns)
            body.append(slot)
            body.extend(values[column] for column in self.field_columns)
            body.extend(values.get(column, "{}") for column in self.json_columns.values())
            for spec in self.attachments:
                body.append((attachments or {}).get(spec.column))
            body.extend((None, "", "", created_at, created_at))
            conn.execute(
                f"INSERT INTO {self.table}("
                + ",".join(quote_identifier(column) for column in columns)
                + ") VALUES("
                + ",".join("?" * len(columns))
                + ")",
                tuple(body),
            )
        row = self._typed(self.find(record_id))
        self._note_change("create", row=row,
                          label=f"新增{self.table_label}：{self.row_title(row)}")
        return row

    def update(self, record_id: str, payload: dict[str, Any], *, db=None,
               strict: bool = True) -> dict[str, Any]:
        """行级保存：只改提交上来的字段。"""
        self._require(record_id)
        # 只有"要记变更流水"时才多读一次旧值（关着的时候不多花这一次查询）
        before = self._typed(self.find(record_id)) if self.change_sink is not None else {}
        values = self._clean(payload, partial=True, strict=strict)
        with self.assets.session(db) as conn:
            values.update(self._clean_foreign(conn, payload, partial=True))
            if values:
                assignments = ",".join(f"{quote_identifier(column)}=?" for column in values)
                conn.execute(
                    f"UPDATE {self.table} SET {assignments},updated=? WHERE id=?",
                    (*values.values(), stamp(), record_id),
                )
        row = self._typed(self.find(record_id))
        fields = self._diff_fields(before, row, values)
        # 值真变了才记流水：页面上的"失焦即保存"会发很多次"什么都没改"的请求，
        # 那种一条都不该进流水（流水是一句人话，不是访问日志）。
        if fields:
            self._note_change("update", row=row, label=self._diff_label(fields, row),
                              extra={"fields": fields})
        return row

    def _diff_fields(self, before: dict[str, Any], after: dict[str, Any],
                     values: dict[str, Any]) -> list[dict[str, Any]]:
        """这一次真正改了哪些字段（``[{key,label,before,after}]``）。

        字段是按 legacy 键对外报的（``_typed`` 给的是 nm/vf 这些），payload 也用同一套键，
        所以先把"改动的列"翻译成 legacy 键再取旧值/新值。

        结构化的一份存进 ``extra_json``（流水行里那一句人话只列前几个字段，
        真要逐字段对比/做界面的，读这一份，信息不丢）。
        """
        pending = set(values)
        columns = {field.column: field.key for field in self.fields}
        fields: list[dict[str, Any]] = []
        for column in self.insert_columns:
            key = columns.get(column, column)
            if column not in pending and key not in pending:
                continue
            old, new = before.get(key), after.get(key)
            if old == new:
                continue
            fields.append({"key": key, "label": self.change_label(column, key),
                           "before": old, "after": new})
        return fields

    def _diff_label(self, fields: list[dict[str, Any]], after: dict[str, Any],
                    limit: int = 6) -> str:
        """把"这一次到底改了什么"写成一句人话：``刀具 T01：转速 n 3000→3500；寿命 60→90``。

        ``fields`` 为空时给"值没变"：`update()` 自己不会走这条路（没变就不记流水），
        留在这里是给直接调用它的地方一个说得清的结果。
        """
        title = self.row_title(after)
        if not fields:
            return f"保存{self.table_label}：{title}（值没变）"
        parts = [f"{item['label']} {self.display_value(item['key'], item['before'])}"
                 f"→{self.display_value(item['key'], item['after'])}"
                 for item in fields[:limit]]
        if len(fields) > limit:
            parts.append(f"等 {len(fields)} 项")
        return f"{self.table_label} {title}：" + "；".join(parts)

    def _resolve_asset(self, db, spec: AttachmentSpec, value: Any) -> str | None:
        """接受原始字节、旧 data URL、本站附件地址，或**直接给附件编号**。

        ``TypedLibrary._attachment_id`` 只认 data URL 与完整 URL；上传接口手上拿到的
        是刚落库的附件编号，所以这里补一条"裸编号"的识别。
        """
        if isinstance(value, str) and value and "/" not in value and ":" not in value:
            if self.assets.record(value, db=db) is not None:
                return value
        return self._attachment_id(db, spec, value)

    def set_attachment_value(self, record_id: str, slot: str, value: Any) -> dict[str, Any]:
        """写图片槽：接受原始字节、旧 data URL、本站附件地址或附件编号；换图时回收上一张。

        先改行、再回收旧图——反过来外键还指着它，SQLite 会直接拒绝删除（第一阶段踩过）。
        """
        spec = self.attachment(slot)
        self._require(record_id)
        with self.assets.session(db=None) as conn:
            asset_id = self._resolve_asset(conn, spec, value)
            if value and not asset_id:
                raise HTTPException(422, f"{spec.legacy_key} 不是可识别的图片")
            previous = self.find(record_id)[spec.column]
            conn.execute(
                f"UPDATE {self.table} SET {quote_identifier(spec.column)}=?,updated=? WHERE id=?",
                (asset_id, stamp(), record_id),
            )
            if previous and previous != asset_id:
                self._release_asset(conn, previous)
        row = self._typed(self.find(record_id))
        self._note_change("photo", row=row,
                          label=f"{self.table_label} {self.row_title(row)}："
                                f"{'换图' if asset_id else '清空图片'}"
                                f"（{self.change_slot_label(spec)}）",
                          extra={"slot": spec.slot, "column": spec.column,
                                 "has_asset": bool(asset_id)})
        return row

    def soft_delete(self, record_id: str, *, by: str = "", reason: str = "") -> dict[str, Any]:
        """逻辑删除（口径 2：永不物理删除，回收站可恢复）。"""
        self._require(record_id)
        now = stamp()
        with self.assets.session(db=None) as conn:
            conn.execute(
                f"UPDATE {self.table} SET deleted_at=?,deleted_by=?,deleted_reason=?,updated=? "
                "WHERE id=?",
                (now, by, reason, now, record_id),
            )
        row = self._typed(self.find(record_id))
        suffix = f"（{reason}）" if reason else ""
        self._note_change("delete", row=row,
                          label=f"删除{self.table_label}：{self.row_title(row)}{suffix}",
                          extra={"by": by, "reason": reason})
        return row

    def restore(self, record_id: str, *, db=None) -> dict[str, Any]:
        """从回收站恢复一行（``deleted_at`` 清空，删除人与原因一并清掉）。"""
        row = self.find(record_id)
        if row is None:
            raise HTTPException(404, f"{self.table_label}记录不存在")
        with self.assets.session(db) as conn:
            conn.execute(
                f"UPDATE {self.table} SET deleted_at=NULL,deleted_by='',deleted_reason='',updated=? "
                "WHERE id=?",
                (stamp(), record_id),
            )
        view = self._typed(self.find(record_id))
        self._note_change("restore", row=view,
                          label=f"恢复{self.table_label}：{self.row_title(view)}")
        return view

    def reorder(self, project_id: str, record_ids: Iterable[str]) -> list[dict[str, Any]]:
        """按给定顺序重排：给到的 id 依次排 0..n，没给到的接在后面。"""
        wanted = [str(item) for item in record_ids]
        existing = {row["id"] for row in self.rows(project_id, include_deleted=True)}
        unknown = [item for item in wanted if item not in existing]
        if unknown:
            raise HTTPException(404, f"{self.table_label}里有记录不属于该项目：{'、'.join(unknown[:3])}")
        with self.assets.session(db=None) as conn:
            for order, record_id in enumerate(wanted):
                conn.execute(f"UPDATE {self.table} SET sort_order=?,updated=? WHERE id=?",
                             (order, stamp(), record_id))
            rest = [row["id"] for row in self.rows(project_id, include_deleted=True)
                    if row["id"] not in wanted]
            for offset, record_id in enumerate(rest, start=len(wanted)):
                conn.execute(f"UPDATE {self.table} SET sort_order=?,updated=? WHERE id=?",
                             (offset, stamp(), record_id))
        self._note_change("reorder", label=f"{self.table_label}排序调整（{len(wanted)} 行）",
                          extra={"ids": wanted[:20]})
        return self.list_typed(project_id)

    def forget(self, project_id: str, *, db=None) -> None:
        """项目被物理删除时连带清理（当前口径永不物理删除，仅备用）。"""
        with self.assets.session(db) as conn:
            conn.execute(f"DELETE FROM {self.table} WHERE {self.project_column}=?", (project_id,))
