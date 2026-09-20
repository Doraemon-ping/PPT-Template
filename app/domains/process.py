"""项目级业务数据（1b：工序 ``project_processes`` + 工序刀具行 ``project_process_tools``）。

与 ``app/domains/project.py``（项目信息）同为"项目级"数据，区别是这两张表**一个项目多行**：

* 行级读写：页面上改一个格 = ``PATCH`` 一行的一个字段，不再整份 JSON 覆盖；
* **永不物理删除**（已确认口径 2）：``soft_delete()`` 只写 ``deleted_at/by/reason``，回收站可恢复；
* **价格快照**（口径 4）：刀具行选型时把库里的 ``price/life`` 拷进快照列，
  之后库改价/改名/删库都不影响已存行；快照列不进旧读模型，只走类型化接口；
* **派生字段不落库**（口径 5）：``_ct/_vc/_vf/_fz`` 在 :func:`calc_derived` 里读时算，
  数字按 JS 序列化规则归一（``32.0`` → ``32``），保证与前端算出来**逐字节相同**；
* 旧读模型 ``pr[]`` 由 :func:`compose_processes` 精确还原（老短键照旧），
  所以报价表、导出、PPT、报表链路全部不用改。

**行表基类在下层**：项目作用域 / 父行 / 逻辑删除 / 排序 / 真外键校验这些公共部分住在
``app/db/rows.py``（:class:`~app.db.rows.ProjectRows`）。本模块只是它的一个使用者，
不再向其它业务域提供底座——问题清单、选型、履历、变更流水都直接继承那个基类。

**启用是显式的**：``app.services.store.MachiningStore`` 只在
``app_settings.project_business_version >= 1``（或环境变量 ``MACHINING_PROJECT_BUSINESS=1``）
时才建这两张表，并在有数据时用表数据替代 ``projects.state_json`` 里的 ``pr``。
没启用时一切照旧——代码可以先上线，数据迁移由 ``tools/migrate_project_processes.py`` 单独执行。
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Any, Iterable

from fastapi import HTTPException

from ..core.utils import js_number, stamp
from ..db.library import AttachmentSpec, LibraryField
from ..db.rows import (
    ForeignKey,
    ProjectRows,
    asset_value,
)

from ..db.tables import PROCESS_TABLE, PROCESS_TOOL_TABLE

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


class ProjectProcesses(ProjectRows):
    """``project_processes``：一行一道工序。"""

    table = PROCESS_TABLE
    table_label = "工序"
    fields = PROCESS_FIELDS
    attachments = PROCESS_ATTACHMENTS
    json_columns = {"nc": "count_json", "machine_snapshot": "machine_snapshot"}
    json_cleaners = {"nc": clean_count, "machine_snapshot": clean_snapshot}
    #: 本表两个 JSON 列都已在上面点名；这里显式声明，免得将来新增 JSON 列时
    #: 落到基类的通用校验器上（基类默认只做"是不是 JSON 对象"，不校验计数）
    default_json_cleaner = staticmethod(clean_count)
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
                 stamp(), record_id),
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


class ProjectProcessTools(ProjectRows):
    """``project_process_tools``：一行一条工序刀具记录。"""

    table = PROCESS_TOOL_TABLE
    table_label = "工序刀具行"
    parent_column = "process_id"
    #: 父行指向工序表（基类故意不给默认值，由子类自己声明）
    parent_table = PROCESS_TABLE
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
        now = stamp()
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
        now = stamp()
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
                             (order, stamp(), record_id))
            rest = [row["id"] for row in rows if row["id"] not in wanted]
            for offset, record_id in enumerate(rest, start=len(wanted)):
                conn.execute(f"UPDATE {self.table} SET sort_order=?,updated=? WHERE id=?",
                             (offset, stamp(), record_id))
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
            "cI": asset_value(asset_store, row.get("layout_id"), inline_assets),
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
                    item[legacy_key] = asset_value(asset_store, tool.get("photo_id"), inline_assets)
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
