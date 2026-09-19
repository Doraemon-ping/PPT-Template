"""项目级业务数据（1b：工序 ``project_processes`` + 工序刀具行 ``project_process_tools``）。

与 ``app/machining_project.py``（项目信息）同为"项目级"数据，区别是这两张表**一个项目多行**：

* 行级读写：页面上改一个格 = ``PATCH`` 一行的一个字段，不再整份 JSON 覆盖；
* **永不物理删除**（已确认口径 2）：``soft_delete()`` 只写 ``deleted_at/by/reason``，回收站可恢复；
* **价格快照**（口径 4）：刀具行选型时把库里的 ``price/life`` 拷进快照列，
  之后库改价/改名/删库都不影响已存行；快照列不进旧读模型，只走类型化接口；
* **派生字段不落库**（口径 5）：``_ct/_vc/_vf/_fz`` 在 :func:`calc_derived` 里读时算，
  数字按 JS 序列化规则归一（``32.0`` → ``32``），保证与前端算出来**逐字节相同**；
* 旧读模型 ``pr[]`` 由 :func:`compose_processes` 精确还原（老短键照旧），
  所以报价表、导出、PPT、报表链路全部不用改。

**启用是显式的**：``MachiningDFMStore`` 只在 ``app_settings.project_business_version >= 1``
（或环境变量 ``MACHINING_PROJECT_BUSINESS=1``）时才建这两张表，并在有数据时用表数据替代
``projects.state_json`` 里的 ``pr``。没启用时一切照旧——代码可以先上线，数据迁移由
``tools/migrate_project_processes.py`` 单独执行。
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Any, Iterable, NamedTuple

from fastapi import HTTPException

from .machining_library import (
    AttachmentSpec,
    LibraryField,
    TypedLibrary,
    _stamp,
    quote_identifier,
)

PROCESS_TABLE = "project_processes"
PROCESS_TOOL_TABLE = "project_process_tools"

#: ``app_settings`` 版本键：≥1 表示"工序已落表"（建表与切读模型都看它）
BUSINESS_VERSION_KEY = "project_business_version"
BUSINESS_VERSION = 1

#: 非加工时间的六个计数（旧 ``nc`` 对象，固定六键）
NC_KEYS = ("cc", "co", "mc_", "sc", "ac", "it")
NC_DEFAULTS = {"cc": 2, "co": 2, "mc_": 2, "sc": 2, "ac": 1, "it": 5}

#: 旧读模型里"看得见"的键（compose 不多不少输出这些）
LEGACY_PROCESS_KEYS = ("nm", "mc", "cI", "nc", "tl", "fixP", "eqP", "mid", "mi")
LEGACY_TOOL_KEYS = ("id", "tp", "ds", "d", "n", "vf", "ln", "ps", "cn", "bg", "td",
                    "fi", "tt", "sd", "_ct", "_vc", "_vf", "_fz", "cat", "hld", "acc")

#: 旧刀具行的键 → 类型化视图的键（``id`` 是刀号，不是行主键，所以必须显式对应）
TOOL_LEGACY_FROM_TYPED = {
    "id": "code", "tp": "tp", "ds": "ds", "d": "d", "n": "n", "vf": "vf", "ln": "ln",
    "ps": "ps", "cn": "cn", "bg": "bg", "td": "td", "fi": "photo", "tt": "tt", "sd": "sd",
    "cat": "cat", "hld": "hld", "acc": "acc",
}

# ---------------- 字段登记表（列名可读，JSON 键沿用旧短键） ----------------

PROCESS_FIELDS: tuple[LibraryField, ...] = (
    LibraryField("nm", "name", "text", "", "工序名称", limit=120),
    LibraryField("mc", "machine_count", "int", 1, "设备台数", maximum=99),
    LibraryField("mid", "machine_id", "text", "", "设备", limit=64),
    LibraryField("fixP", "fixture_price", "real", 0, "夹具费", unit="元"),
    LibraryField("eqP", "equipment_price", "real", 0, "设备费", unit="元"),
)

PROCESS_ATTACHMENTS: tuple[AttachmentSpec, ...] = (
    AttachmentSpec("layout", "process_photo", "fixture_photo_id", "cI", value_keys=("cI",)),
)

TOOL_FIELDS: tuple[LibraryField, ...] = (
    LibraryField("code", "code", "text", "", "刀号", limit=32),
    LibraryField("tp", "tool_name", "text", "", "刀具型号", limit=200),
    LibraryField("cat", "tool_category", "text", "other", "类型", limit=40),
    LibraryField("ds", "description", "text", "", "加工特征", limit=200),
    LibraryField("d", "diameter", "real", 0, "D", unit="mm"),
    LibraryField("n", "spindle_rpm", "real", 0, "n", unit="r/min"),
    LibraryField("vf", "feed_rate", "real", 0, "vf", unit="mm/min"),
    LibraryField("ln", "cut_length", "real", 0, "L", unit="mm"),
    LibraryField("ps", "passes", "real", 1, "次数"),
    LibraryField("cn", "flutes", "real", 1, "刃数"),
    LibraryField("bg", "roughing", "int", 0, "大刀", maximum=1),
    LibraryField("td", "cut_time", "real", 500, "快移距", unit="mm"),
    LibraryField("tt", "aux_time", "real", 2, "换刀时", unit="s"),
    LibraryField("sd", "depth", "real", 1, "主轴延时", unit="s"),
    LibraryField("hld", "handle_name", "text", "", "刀柄选型", limit=200),
    LibraryField("acc", "accessory_name", "text", "", "配件选型", limit=200),
    # 快照与引用列：不在旧 JSON 契约里，只走类型化接口（口径 4）
    LibraryField("tool_id", "tool_id", "text", "", "刀具库编号", limit=64),
    LibraryField("tool_grp", "tool_group", "text", "", "刀具组", limit=20),
    LibraryField("tool_price", "tool_price_snapshot", "real", 0, "刀具价格快照", unit="元"),
    LibraryField("tool_life", "tool_life_snapshot", "real", 0, "刀具寿命快照", unit="min"),
    LibraryField("hld_id", "handle_id", "text", "", "刀柄库编号", limit=64),
    LibraryField("hld_price", "handle_price_snapshot", "real", 0, "刀柄价格快照", unit="元"),
    LibraryField("acc_id", "accessory_id", "text", "", "配件库编号", limit=64),
    LibraryField("acc_price", "accessory_price_snapshot", "real", 0, "配件价格快照", unit="元"),
)

TOOL_ATTACHMENTS: tuple[AttachmentSpec, ...] = (
    AttachmentSpec("photo", "process_photo", "tool_photo_id", "fi", value_keys=("fi",)),
)

#: 不出现在旧读模型里的键（快照与引用）
SNAPSHOT_KEYS = ("tool_id", "tool_grp", "tool_price", "tool_life",
                 "hld_id", "hld_price", "acc_id", "acc_price")


#: 旧刀具行里是数字的键（REAL 列取回来是 ``50.0``，旧 JSON 是 ``50``，要归一）
NUMERIC_LEGACY_KEYS = ("d", "n", "vf", "ln", "ps", "cn", "td", "tt", "sd")
#: 旧刀具行里是布尔的键（表里存 INTEGER 0/1，读模型要给回布尔）
BOOLEAN_LEGACY_KEYS = ("bg",)
#: 旧工序行里是数字的键
NUMERIC_PROCESS_KEYS = ("mc", "fixP", "eqP")


def js_number(value: Any) -> Any:
    """按 JS 的 JSON 数字序列化规则归一：整数值不带小数点（``32.0`` → ``32``）。

    前端算出的 ``_ct`` 在 JS 里 ``JSON.stringify(32.0)`` 就是 ``32``；服务端若原样写 ``32.0``，
    数值相同但读模型字节会变，历史快照 diff 与成本基线比对会出现假差异。
    """
    if isinstance(value, float) and value.is_integer() and abs(value) < 2 ** 53:
        return int(value)
    return value


def calc_derived(tool: dict[str, Any]) -> dict[str, Any]:
    """``_ct/_vc/_vf/_fz``：与前端 ``calcT()`` 同一套公式，读时算、不落库（口径 5）。"""
    n = tool.get("n") or 0
    vf = tool.get("vf") or 0
    ln = tool.get("ln") or 0
    ps = tool.get("ps") or 0
    cn = tool.get("cn") or 0
    return {
        "_ct": js_number((ln / vf * 60) * ps * cn if vf > 0 else 0),
        "_vc": js_number(round(math.pi * (tool.get("d") or 0) * n / 1000)),
        "_vf": js_number(vf),
        "_fz": js_number(vf / n if n > 0 else 0),
    }


def clean_count(payload: Any) -> dict[str, int]:
    """``nc`` 六个计数：**不无中生有**——整份缺失就存空，给了某个键才补其余键的默认值。

    * ``None`` / ``{}`` → ``{}``（旧数据里本来没有 ``nc`` 的项目，读模型也不该凭空多出这个键，
      否则"迁移前后逐键一致"就不成立；前端自己会用默认值兜底）；
    * 给了 ``{"cc": 5}`` → 六个键齐全（``cc=5``，其余取默认），与页面 ``updNC`` 的语义一致；
    * 多的键**保留**（不丢用户数据），非数字报 422。
    """
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "非加工时间计数必须是 JSON 对象")
    if not payload:
        return {}
    counts: dict[str, Any] = dict(NC_DEFAULTS)
    for key, value in payload.items():
        if isinstance(value, str) and not value.strip():
            counts[str(key)] = 0
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"非加工时间计数 {key} 必须是数字") from exc
        if number != number or number in (float("inf"), float("-inf")):
            raise HTTPException(422, f"非加工时间计数 {key} 不是有效数字")
        if number < 0:
            raise HTTPException(422, f"非加工时间计数 {key} 不能为负数")
        counts[str(key)] = js_number(number)
    return counts


def clean_snapshot(payload: Any) -> dict[str, Any]:
    """设备快照：任意 JSON 对象（只读列，选设备时写入）。"""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "设备快照必须是 JSON 对象")
    return payload


def clean_json_object(payload: Any) -> dict[str, Any]:
    """通用 JSON 对象列（不做计数校验）。"""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "该字段必须是 JSON 对象")
    return payload


def _asset_value(asset_store, asset_id: str | None, inline: bool) -> Any:
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


class _ProjectRows(TypedLibrary):
    """项目级多行表的公共部分：项目作用域 + 可选父行 + 逻辑删除 + 排序。

    **外键口径**：凡是"指向别的表里的行"的列，一律用真外键（``REFERENCES``），
    不做"存个字符串自己心里有数"的软引用。父行（工序）默认必填，子表可声明
    ``parent_nullable``；另有 ``foreign_keys`` 声明若干可空外键列（问题清单指工序、
    选型报价指夹具/检具库与类别字典）。
    """

    project_column = "project_id"
    #: 需要挂父行的表填列名（工序刀具行 → ``process_id``）
    parent_column = ""
    #: 父行指向哪张表 / 可不可以为空（问题清单可以只挂项目，不挂工序）
    parent_table = PROCESS_TABLE
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
    #: 没在 ``json_cleaners`` 里点名的 JSON 列用哪个校验器
    default_json_cleaner: Any = clean_count
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

    def change_label(self, column: str, key: str = "") -> str:
        """某个字段在流水里叫什么。"""
        label = self.label_map.get(column) or self.label_map.get(key) or column
        extra = self.change_field_labels.get(column) or self.change_field_labels.get(key)
        if extra and label.isascii():
            return f"{extra} {label}"
        return label

    #: 图片槽位在流水里的中文名（槽位名 ``photo``/``layout`` 是给程序看的）
    change_slot_labels = {
        "photo": "照片", "layout": "布局图",
        "before": "修改前", "after": "修改后", "doc": "资料",
    }

    def change_slot_label(self, spec: Any) -> str:
        return self.change_slot_labels.get(spec.slot) or spec.legacy_key or spec.column

    def _note_change(self, action: str, *, row: dict[str, Any] | None = None,
                     label: str = "", record_id: str | None = None,
                     extra: dict[str, Any] | None = None) -> None:
        """把"刚发生了什么"交给 store（阶段 3b 的变更流水）。

        这里**只交草稿**，不写库：真正的插入发生在 ``_bump_project`` 那个事务里
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

    def __init__(self, connect, assets):
        super().__init__(connect, assets)
        #: 目标表有没有 deleted_at 的缓存（每次写都去 PRAGMA 太浪费）
        self._soft_cache: dict[str, bool] = {}

    # ---------------- 表结构 ----------------

    def ddl(self) -> str:
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

    @property
    def check_expressions(self) -> tuple[str, ...]:
        """表级 CHECK：可以写成一条字符串，也可以写成多条（各自补上 ``CHECK``）。"""
        if not self.check_sql:
            return ()
        items = (self.check_sql,) if isinstance(self.check_sql, str) else tuple(self.check_sql)
        return tuple(item if item.upper().startswith("CHECK") else f"CHECK ({item})" for item in items)

    def index_ddl(self) -> str:
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

    @property
    def key_columns(self) -> tuple[str, ...]:
        """除项目列之外的"外键列"（父行 + 额外外键），读写都要带上。"""
        columns = [self.parent_column] if self.parent_column else []
        columns.extend(fk.column for fk in self.fks)
        return tuple(columns)

    def schema(self, db) -> None:
        db.executescript(self.ddl())
        db.executescript(self.index_ddl())

    @property
    def insert_columns(self) -> tuple[str, ...]:
        columns = ["id", self.project_column]
        columns.extend(self.key_columns)
        columns.append("sort_order")
        columns.extend(self.field_columns)
        columns.extend(self.json_columns.values())
        columns.extend(self.attachment_columns)
        columns.extend(("deleted_at", "deleted_by", "deleted_reason", "created", "updated"))
        return tuple(columns)

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

    def rows(
        self, project_id: str | None = None, *, include_deleted: bool = False, db=None
    ) -> list[Any]:
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

    def require_in_project(self, project_id: str, record_id: str, *, allow_deleted: bool = False) -> Any:
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
        now = _stamp()
        stamp = str(created).strip() if created else now
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
            body.extend((None, "", "", stamp, stamp))
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
                    (*values.values(), _stamp(), record_id),
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
                (asset_id, _stamp(), record_id),
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
        now = _stamp()
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
        row = self.find(record_id)
        if row is None:
            raise HTTPException(404, f"{self.table_label}记录不存在")
        with self.assets.session(db) as conn:
            conn.execute(
                f"UPDATE {self.table} SET deleted_at=NULL,deleted_by='',deleted_reason='',updated=? "
                "WHERE id=?",
                (_stamp(), record_id),
            )
        view = self._typed(self.find(record_id))
        self._note_change("restore", row=view,
                          label=f"恢复{self.table_label}：{self.row_title(view)}")
        return view

    def reorder(self, project_id: str, record_ids: Iterable[str]) -> list[dict[str, Any]]:
        wanted = [str(item) for item in record_ids]
        existing = {row["id"] for row in self.rows(project_id, include_deleted=True)}
        unknown = [item for item in wanted if item not in existing]
        if unknown:
            raise HTTPException(404, f"{self.table_label}里有记录不属于该项目：{'、'.join(unknown[:3])}")
        with self.assets.session(db=None) as conn:
            for order, record_id in enumerate(wanted):
                conn.execute(f"UPDATE {self.table} SET sort_order=?,updated=? WHERE id=?",
                             (order, _stamp(), record_id))
            rest = [row["id"] for row in self.rows(project_id, include_deleted=True)
                    if row["id"] not in wanted]
            for offset, record_id in enumerate(rest, start=len(wanted)):
                conn.execute(f"UPDATE {self.table} SET sort_order=?,updated=? WHERE id=?",
                             (offset, _stamp(), record_id))
        self._note_change("reorder", label=f"{self.table_label}排序调整（{len(wanted)} 行）",
                          extra={"ids": wanted[:20]})
        return self.list_typed(project_id)

    def forget(self, project_id: str, *, db=None) -> None:
        """项目被物理删除时连带清理（当前口径永不物理删除，仅备用）。"""
        with self.assets.session(db) as conn:
            conn.execute(f"DELETE FROM {self.table} WHERE {self.project_column}=?", (project_id,))


class ProjectProcesses(_ProjectRows):
    """``project_processes``：一行一道工序。"""

    table = PROCESS_TABLE
    table_label = "工序"
    fields = PROCESS_FIELDS
    attachments = PROCESS_ATTACHMENTS
    json_columns = {"nc": "count_json", "machine_snapshot": "machine_snapshot"}
    json_cleaners = {"nc": clean_count, "machine_snapshot": clean_snapshot}
    #: 阶段 3b：工序的每次改动都进变更流水
    change_entity = "process"
    title_keys = ("nm",)
    #: 设备是真外键（``ON DELETE SET NULL``）：设备库是共享库、会被整表重建，
    #: 库行删掉时列置空**不挡住删除**，型号/价格仍按 ``machine_snapshot`` 算（口径 4）。
    foreign_keys = (ForeignKey("machine_id", "machines", on_delete="SET NULL"),)

    def set_machine(self, record_id: str, machine: dict[str, Any] | None) -> dict[str, Any]:
        """选设备：写 id + 快照（源库改了/删了，读模型仍拿得到当时的型号）。

        **修过的坑**：``machine`` 常常是 ``Machines.find(...)`` 的返回值，那是 ``sqlite3.Row``，
        没有 ``.get()`` —— 原来直接 ``machine.get(key)``，于是"换设备"这条路一调就是 500。
        这里先统一成 dict。
        """
        self._require(record_id)
        before = self._typed(self.find(record_id)) if self.change_sink is not None else {}
        data: dict[str, Any] = {}
        if machine:
            data = machine if isinstance(machine, dict) else dict(machine)
        snapshot: dict[str, Any] = {}
        if data:
            snapshot = {key: data.get(key)
                        for key in ("id", "brand", "model", "xyz", "rapid", "tc", "price")}
        with self.assets.session(db=None) as conn:
            conn.execute(
                f"UPDATE {self.table} SET machine_id=?,machine_snapshot=?,updated=? WHERE id=?",
                # 没选设备就写 NULL（空串在 SQLite 里是一个真值，会踩外键）
                (str(data.get("id") or "") or None,
                 json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                 _stamp(), record_id),
            )
        row = self._typed(self.find(record_id))
        # 流水里写"型号"而不是设备 id：读的人认的是"兄弟 S500Z1"，不是一串 uuid
        def machine_name(snapshot: Any, mid: Any) -> str:
            data = snapshot if isinstance(snapshot, dict) else {}
            text = " ".join(str(data.get(key) or "").strip()
                            for key in ("brand", "model")).strip()
            return text or str(mid or "").strip()

        before_name = machine_name(before.get("machine_snapshot"), before.get("mid"))
        after_name = machine_name(row.get("machine_snapshot"), row.get("mid"))
        same = before_name == after_name and before.get("mid") == row.get("mid")
        fields = [{"key": "mid", "label": "设备",
                   "before": before.get("mid"), "after": row.get("mid")}]
        self._note_change("update", row=row,
                          label=f"{self.table_label} {self.row_title(row)}：设备 "
                                f"{self.display_value('mid', before_name)}→"
                                f"{self.display_value('mid', after_name)}"
                                + ("（重新选定，型号没变）" if same else ""),
                          extra={"field": "mid", "fields": fields, "unchanged": same})
        return row


class ProjectProcessTools(_ProjectRows):
    """``project_process_tools``：一行一条工序刀具记录。"""

    table = PROCESS_TOOL_TABLE
    table_label = "工序刀具行"
    parent_column = "process_id"
    fields = TOOL_FIELDS
    attachments = TOOL_ATTACHMENTS
    json_columns: dict[str, str] = {}
    #: 阶段 3b：刀具行的每次改动都进变更流水（级联删除也逐行记）
    change_entity = "tool"
    title_keys = ("code", "tp")
    change_slot_labels = {"photo": "刀具图"}
    #: 刀具/刀柄/配件都是真外键（``ON DELETE SET NULL``）：库行删掉时列置空，
    #: 价格与寿命仍按 ``tool_price``/``tool_life``/``hld_price``/``acc_price`` 快照算（口径 4）。
    foreign_keys = (
        ForeignKey("tool_id", "tools", on_delete="SET NULL"),
        ForeignKey("handle_id", "tools", on_delete="SET NULL"),
        ForeignKey("accessory_id", "tools", on_delete="SET NULL"),
    )

    def by_process(self, process_id: str) -> list[dict[str, Any]]:
        with self.assets.session(db=None) as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.table} WHERE {self.parent_column}=? AND deleted_at IS NULL "
                "ORDER BY sort_order, id",
                (process_id,),
            ).fetchall()
        return [self._typed(row) for row in rows]

    #: 随工序一起被逻辑删除的刀具行，删除原因带这个前缀，恢复时按它挑回来
    CASCADE_PREFIX = "随工序删除"

    def soft_delete_by_process(self, process_id: str, *, by: str = "") -> int:
        """工序被删时连带逻辑删除它的刀具行（口径 2：只是标记，不物理删）。"""
        now = _stamp()
        # 行要先取出来：UPDATE 之后 `by_process()` 就查不到它们了（deleted_at 已置上）
        doomed = self.by_process(process_id)
        with self.assets.session(db=None) as conn:
            cursor = conn.execute(
                f"UPDATE {self.table} SET deleted_at=?,deleted_by=?,deleted_reason=?,updated=? "
                f"WHERE {self.parent_column}=? AND deleted_at IS NULL",
                (now, by, f"{self.CASCADE_PREFIX}:{process_id}", now, process_id),
            )
            count = int(cursor.rowcount or 0)
        # 级联删除：逐行留流水（这样"某条刀具行什么时候没的、跟着哪道工序走的"查得到）
        for row in doomed:
            self._note_change("delete", row=row,
                              label=f"删除{self.table_label}：{self.row_title(row)}（随工序删除）",
                              extra={"by": by, "cascade": process_id})
        return count

    def restore_by_process(self, process_id: str) -> int:
        """恢复工序时，把"随工序删除"的刀具行一起恢复（单独删的保持删除状态）。"""
        now = _stamp()
        with self.assets.session(db=None) as conn:
            pending = conn.execute(
                f"SELECT * FROM {self.table} WHERE {self.parent_column}=? "
                "AND deleted_reason LIKE ?",
                (process_id, f"{self.CASCADE_PREFIX}%"),
            ).fetchall()
            cursor = conn.execute(
                f"UPDATE {self.table} SET deleted_at=NULL,deleted_by='',deleted_reason='',updated=? "
                f"WHERE {self.parent_column}=? AND deleted_reason LIKE ?",
                (now, process_id, f"{self.CASCADE_PREFIX}%"),
            )
            count = int(cursor.rowcount or 0)
        for raw in pending:
            row = self._typed(raw)
            self._note_change("restore", row=row,
                              label=f"恢复{self.table_label}：{self.row_title(row)}（随工序恢复）",
                              extra={"cascade": process_id})
        return count

    def reorder_in_process(self, process_id: str, record_ids: Iterable[str]) -> list[dict[str, Any]]:
        wanted = [str(item) for item in record_ids]
        rows = self.by_process(process_id)
        existing = {row["id"] for row in rows}
        unknown = [item for item in wanted if item not in existing]
        if unknown:
            raise HTTPException(404, f"{self.table_label}里有记录不属于这道工序：{'、'.join(unknown[:3])}")
        with self.assets.session(db=None) as conn:
            for order, record_id in enumerate(wanted):
                conn.execute(f"UPDATE {self.table} SET sort_order=?,updated=? WHERE id=?",
                             (order, _stamp(), record_id))
            rest = [row["id"] for row in rows if row["id"] not in wanted]
            for offset, record_id in enumerate(rest, start=len(wanted)):
                conn.execute(f"UPDATE {self.table} SET sort_order=?,updated=? WHERE id=?",
                             (offset, _stamp(), record_id))
        self._note_change("reorder", label=f"{self.table_label}排序调整（{len(wanted)} 行）",
                          extra={"ids": wanted[:20], "process_id": process_id})
        return self.by_process(process_id)


# ---------------- 读模型：表行 → 旧 pr[] ----------------

def compose_processes(
    process_rows: list[dict[str, Any]],
    tool_rows: list[dict[str, Any]],
    machines: list[dict[str, Any]] | None = None,
    *,
    inline_assets: bool = False,
    asset_store=None,
) -> list[dict[str, Any]]:
    """把表行还原成旧 ``pr[]``：老短键、老结构，派生值读时算（口径 5）。

    入参是**类型化视图**（``list_typed`` / ``rows`` 转出来的 dict）。旧键集合固定为
    :data:`LEGACY_PROCESS_KEYS` / :data:`LEGACY_TOOL_KEYS`：快照与引用列一律不输出，
    免得读模型字节变化影响报表绑定与历史快照对比。
    """
    machine_index = {str(row.get("id")): index for index, row in enumerate(machines or [])}
    tools_by_process: dict[str, list[dict[str, Any]]] = {}
    for tool in tool_rows:
        if tool.get("deleted_at"):
            continue
        tools_by_process.setdefault(str(tool.get("process_id") or ""), []).append(tool)

    result: list[dict[str, Any]] = []
    for row in sorted((item for item in process_rows if not item.get("deleted_at")),
                      key=lambda item: (item.get("sort_order", 0), str(item.get("id")))):
        # 设备列是真外键：库行被删掉时列会被置空，这时按**当时的快照**还原 mid（口径 4），
        # 免得库一动、项目里的设备名就凭空消失。
        snapshot = row.get("machine_snapshot") or {}
        mid_value = str(row.get("mid") or snapshot.get("id") or "")
        process: dict[str, Any] = {
            "nm": row.get("nm") or "",
            "mc": js_number(row.get("mc") if row.get("mc") is not None else 1),
            "cI": _asset_value(asset_store, row.get("layout_id"), inline_assets),
            "tl": [],
            "fixP": row.get("fixP") or 0,
            "eqP": row.get("eqP") or 0,
            "mid": mid_value,
        }
        counts = row.get("nc")
        if counts:
            # 旧数据里没有 nc 的项目不凭空补这个键（保证迁移前后逐键一致）
            process["nc"] = dict(counts)
        for key in NUMERIC_PROCESS_KEYS:
            if process.get(key) is not None:
                process[key] = js_number(process[key])
        for tool in sorted(tools_by_process.get(str(row.get("id")), []),
                           key=lambda item: (item.get("sort_order", 0), str(item.get("id")))):
            item: dict[str, Any] = {}
            for legacy_key, typed_key in TOOL_LEGACY_FROM_TYPED.items():
                if typed_key == "photo":
                    item[legacy_key] = _asset_value(asset_store, tool.get("photo_id"), inline_assets)
                else:
                    item[legacy_key] = tool.get(typed_key)
            for key in NUMERIC_LEGACY_KEYS:
                if key in item:
                    item[key] = js_number(item[key]) if item[key] is not None else 0
            for key in BOOLEAN_LEGACY_KEYS:
                if key in item:
                    item[key] = bool(item[key])
            item.update(calc_derived({**tool, **item}))
            process["tl"].append({key: item.get(key) for key in LEGACY_TOOL_KEYS})
        index = machine_index.get(mid_value)
        process["mi"] = index if index is not None else -1
        legacy = {key: process.get(key) for key in LEGACY_PROCESS_KEYS if key in process}
        result.append(legacy)
    return result


def legacy_processes(
    processes: "ProjectProcesses | None",
    tools: "ProjectProcessTools | None",
    project_id: str,
    *,
    machines: list[dict[str, Any]] | None = None,
    inline_assets: bool = False,
    asset_store=None,
) -> list[dict[str, Any]] | None:
    """从两张表读出旧 ``pr[]``；这个项目表里一行都没有时返回 ``None``。

    返回 ``None`` 让调用方回退到 ``projects.state_json`` 里的 ``pr`` ——
    这样"迁移前/没迁移的项目"行为完全不变（含逻辑删除后仍有行的项目）。
    """
    if processes is None or tools is None:
        return None
    if not processes.rows(project_id, include_deleted=True):
        return None
    return compose_processes(
        processes.list_typed(project_id, include_deleted=True),
        tools.list_typed(project_id, include_deleted=True),
        machines,
        inline_assets=inline_assets,
        asset_store=asset_store,
    )


# ---------------- 反向：旧 pr[] → 表行（迁移用） ----------------

#: 旧刀具行的键 → 建行用的类型化键（快照列由 :func:`bind_tool` 另填）
TOOL_PAYLOAD_FROM_LEGACY = {
    "id": "code", "tp": "tp", "ds": "ds", "d": "d", "n": "n", "vf": "vf", "ln": "ln",
    "ps": "ps", "cn": "cn", "bg": "bg", "td": "td", "tt": "tt", "sd": "sd",
    "cat": "cat", "hld": "hld", "acc": "acc",
}


def bind_tool(
    tool: dict[str, Any],
    by_name: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str]:
    """按名字绑刀具库 id：唯一就绑；重名用 ``grp`` + 直径再筛；仍不唯一就不绑、绝不猜。

    返回 ``(库行, 绑定方式)``；绑定方式是 ``unique`` / ``by_size`` / ``ambiguous`` / ``missing``，
    迁移报告按它分类，``ambiguous`` 与 ``missing`` 的行留给人工确认。
    """
    hits = by_name.get(str(tool.get("tp") or ""), [])
    if not hits:
        return None, "missing"
    if len(hits) == 1:
        return hits[0], "unique"
    narrowed = [hit for hit in hits if (hit.get("d") or 0) == (tool.get("d") or 0)]
    if len(narrowed) == 1:
        return narrowed[0], "by_size"
    return None, "ambiguous"


def split_state(
    state: dict[str, Any],
    *,
    tools_library: list[dict[str, Any]] | None = None,
    machines: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """把旧读模型拆成 ``(工序行载荷, 刀具行载荷, 报告)``，供迁移工具逐行 ``create``。

    载荷里的键就是类型化视图的键（``nm``/``mc``/``mid``/``fixP``/``eqP``/``nc`` 等），
    图片按旧键给出（``cI``/``fi``），由 ``create(..., attachments=...)`` 落成附件。
    """
    library = tools_library if tools_library is not None else state.get("tdb") or []
    machine_rows = machines if machines is not None else state.get("mdb") or []
    by_name: dict[str, list[dict[str, Any]]] = {}
    for tool in library:
        by_name.setdefault(str(tool.get("tp") or ""), []).append(tool)

    report: dict[str, Any] = {"bind": {}, "price_missing": 0, "processes": 0, "tools": 0,
                              "machine_missing": []}
    process_payloads: list[dict[str, Any]] = []
    tool_payloads: list[dict[str, Any]] = []
    for index, process in enumerate(state.get("pr") or []):
        if not isinstance(process, dict):
            continue
        sid = f"p{index + 1}"
        machine = next((item for item in machine_rows
                        if str(item.get("id")) == str(process.get("mid") or "")), None)
        # 设备列是**真外键**：只有设备库里真有这台才写，否则留空并报出来让人看见
        # （旧数据里指向不存在的设备 = 这条引用本来就是坏的，不硬塞进外键）
        legacy_mid = str(process.get("mid") or "")
        if legacy_mid and machine is None:
            report["machine_missing"].append(legacy_mid)
        process_payloads.append({
            "sid": sid,
            "payload": {
                "nm": process.get("nm") or "",
                "mc": process.get("mc") if process.get("mc") is not None else 1,
                "mid": str(machine.get("id")) if machine else "",
                "fixP": process.get("fixP") or 0,
                "eqP": process.get("eqP") or 0,
                "nc": process.get("nc"),
                "machine_snapshot": ({key: machine.get(key) for key in
                                      ("id", "brand", "model", "xyz", "rapid", "tc", "price")}
                                     if machine else {}),
            },
            "attachments": {"fixture_photo_id": process.get("cI")},
        })
        report["processes"] += 1
        for position, tool in enumerate(process.get("tl") or []):
            if not isinstance(tool, dict):
                continue
            bound, how = bind_tool(tool, by_name)
            report["bind"][how] = report["bind"].get(how, 0) + 1
            price = float((bound or {}).get("price") or 0)
            life = float((bound or {}).get("life") or 0)
            if price == 0 and life == 0:
                report["price_missing"] += 1
            payload: dict[str, Any] = {"sid": sid, "code": tool.get("id") or f"T{position + 1}"}
            for legacy_key, typed_key in TOOL_PAYLOAD_FROM_LEGACY.items():
                if legacy_key == "id":
                    continue
                payload[typed_key] = tool.get(legacy_key)
            payload.update({
                "tool_id": str((bound or {}).get("id") or ""),
                "tool_grp": str((bound or {}).get("grp") or ""),
                "tool_price": price,
                "tool_life": life,
            })
            tool_payloads.append({"sid": sid, "payload": payload,
                                  "attachments": {"tool_photo_id": tool.get("fi")}})
            report["tools"] += 1
    return process_payloads, tool_payloads, report


def apply_split(
    processes: "ProjectProcesses",
    tools: "ProjectProcessTools",
    project_id: str,
    state: dict[str, Any],
    *,
    tools_library: list[dict[str, Any]] | None = None,
    machines: list[dict[str, Any]] | None = None,
    db=None,
) -> dict[str, Any]:
    """把一个项目的旧 ``pr[]`` 灌进两张表（迁移用；调用方负责备份与归档）。

    **幂等**：项目在表里已经有行（含已逻辑删除的）就什么都不做，只报告 ``skipped``。
    这样迁移中途崩了可以原样重跑，不会把工序灌成两份（口径 2：永不物理删除，
    所以这里也绝不用"先清空再灌"的做法）。
    """
    existing = processes.count(project_id, include_deleted=True)
    if existing:
        report = split_state(state, tools_library=tools_library, machines=machines)[2]
        report["skipped"] = True
        report["existing_rows"] = existing
        return report
    process_payloads, tool_payloads, report = split_state(
        state, tools_library=tools_library, machines=machines
    )
    id_map: dict[str, str] = {}
    for item in process_payloads:
        row = processes.create(project_id, item["payload"], attachments=item["attachments"], db=db)
        id_map[item["sid"]] = row["id"]
    for item in tool_payloads:
        tools.create(project_id, {**item["payload"], "process_id": id_map[item["sid"]]},
                     attachments=item["attachments"], db=db)
    report["skipped"] = False
    report["existing_rows"] = 0
    return report
