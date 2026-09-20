"""项目级业务数据（本轮：项目信息 ``project_settings``）。

与基础库共用同一套"字段登记表"思路（``app/db/library.py``）：

* 页面上一个字段 = 一个 ``LibraryField``：同时决定建表列、JSON 键、校验规则与旧数据迁移；
* ``project_settings`` 是 **1:1** 表（主键 ``project_id``），一个项目一行，**每个项目存自己的数据**；
* 旧读模型 ``state.G`` 由 :meth:`ProjectSettings.legacy_g` 精确还原 —— 老短键照旧，
  建模之外的键（``lang``、``_vSnap`` 或将来新增的键）整份进 ``extra_json`` 兜底，一个都不丢；
* 项目图片从"塞在 JSON 里的 data URL"改成 ``assets`` 外键：列表/页面拿附件地址，
  **导出与 PPT** 走 ``inline=True`` 再换回 data URL，原渲染器与契约不变。

JSON 沿用**旧短键**（``cust`` / ``hpd`` / ``prj`` …），数据库列名可读
（``customer`` / ``hours_per_day`` / ``project_type``），与刀具库 ``tp`` ↔ ``name``、
设备库 ``n`` ↔ ``spindle_rpm`` 的约定一致。
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from fastapi import HTTPException

from ..core.utils import stamp
from ..db.library import (
    AttachmentSpec,
    LibraryField,
    TypedLibrary,
    asset_used_elsewhere,
    quote_identifier,
)
from ..db.tables import SETTINGS_TABLE

#: 项目信息字段（顺序即页面顺序；``label`` 与页面 ``bSetup``/``bSettings`` 一致）
SETTINGS_FIELDS: tuple[LibraryField, ...] = (
    LibraryField("cust", "customer", "text", "", "客户名称", limit=120),
    LibraryField("part", "part", "text", "", "零件名称", limit=200),
    LibraryField(
        "prj",
        "project_type",
        "choice",
        "hp",
        "项目类型",
        choices=("hp", "dp"),
        choice_labels=(("hp", "高压项目"), ("dp", "差压项目")),
    ),
    LibraryField("custVer", "customer_version", "text", "", "客户版本", limit=60),
    LibraryField("dfmDate", "dfm_date", "text", "", "DFM完成时间", limit=40),
    LibraryField("hpd", "hours_per_day", "real", 0, "日可动时间", unit="小时", maximum=24),
    LibraryField("sft", "shifts", "real", 0, "日班次", maximum=10),
    LibraryField("dpm", "days_per_month", "real", 0, "月可动日", maximum=31),
    LibraryField("avl", "availability", "real", 0, "可动率", maximum=2),
    LibraryField("len", "length", "real", 0, "长度 L", unit="mm"),
    LibraryField("wid", "width", "real", 0, "宽度 W", unit="mm"),
    LibraryField("hgt", "height", "real", 0, "高度 H", unit="mm"),
    LibraryField("wgt", "weight", "real", 0, "重量", unit="kg"),
    LibraryField("showFlow", "show_flow", "int", 1, "流程图显示", maximum=1),
    LibraryField("bInspType", "blank_insp_type", "text", "", "毛坯检具类型", limit=120),
    LibraryField("bInspPrice", "blank_insp_price", "real", 0, "毛坯检具价格", unit="元"),
    LibraryField("fInspType", "final_insp_type", "text", "", "成品检具类型", limit=120),
    LibraryField("fInspPrice", "final_insp_price", "real", 0, "成品检具价格", unit="元"),
    LibraryField("msInspPrice", "ms_insp_price", "real", 0, "测量支架价格", unit="元"),
)

#: 项目级图片：老键（``pI``/``pf``/``bInspImg``/``fInspImg``）保持不变，值换成附件
SETTINGS_ATTACHMENTS: tuple[AttachmentSpec, ...] = (
    AttachmentSpec("product", "project_photo", "product_photo_id", "pI", value_keys=("pI",)),
    AttachmentSpec("product2", "project_photo", "product2_photo_id", "pf", value_keys=("pf",)),
    AttachmentSpec(
        "blank_insp", "inspection_photo", "blank_insp_photo_id", "bInspImg", value_keys=("bInspImg",)
    ),
    AttachmentSpec(
        "final_insp", "inspection_photo", "final_insp_photo_id", "fInspImg", value_keys=("fInspImg",)
    ),
)

_DDL_TYPES = {"text": "TEXT", "choice": "TEXT", "real": "REAL", "int": "INTEGER"}

#: ``save()`` 里"这页压根没提交这个图片槽"的哨兵（区分"提交了空值"与"没提交"）
_ABSENT = object()


class ProjectSettings(TypedLibrary):
    """``project_settings``：一行一个项目的项目信息（行级读写，不是整份 JSON）。"""

    table = SETTINGS_TABLE
    table_label = "项目信息"
    key_column = "project_id"
    fields = SETTINGS_FIELDS
    attachments = SETTINGS_ATTACHMENTS

    # ---------------- 表结构 ----------------

    def ddl(self) -> str:
        lines = [f"{self.key_column} TEXT PRIMARY KEY REFERENCES projects(id)"]
        for field in self.fields:
            sql_type = _DDL_TYPES.get(field.kind, "TEXT")
            if field.kind in {"text", "choice"}:
                literal = "'" + str(field.default).replace("'", "''") + "'"
            else:
                literal = repr(float(field.default)) if field.kind == "real" else str(int(field.default))
            lines.append(f"{quote_identifier(field.column)} {sql_type} NOT NULL DEFAULT {literal}")
        for spec in self.attachments:
            lines.append(f"{quote_identifier(spec.column)} TEXT REFERENCES assets(id)")
        lines.extend(
            (
                "extra_json TEXT NOT NULL DEFAULT '{}'",
                "deleted_at TEXT",
                "deleted_by TEXT NOT NULL DEFAULT ''",
                "deleted_reason TEXT NOT NULL DEFAULT ''",
                "created TEXT NOT NULL",
                "updated TEXT NOT NULL",
            )
        )
        return f"CREATE TABLE IF NOT EXISTS {self.table}(\n    " + ",\n    ".join(lines) + "\n);\n"

    def index_ddl(self) -> str:
        # 主键就是项目 id，不需要额外索引（旧的 sort_order 索引不适用）
        return ""

    def schema(self, db) -> None:
        db.executescript(self.ddl())

    @property
    def insert_columns(self) -> tuple[str, ...]:
        return (
            self.key_column,
            *self.field_columns,
            *self.attachment_columns,
            "extra_json",
            "deleted_at",
            "deleted_by",
            "deleted_reason",
            "created",
            "updated",
        )

    def _defaults(self) -> list[Any]:
        values: list[Any] = []
        for field in self.fields:
            values.append(float(field.default) if field.kind == "real" else field.default)
        values.extend([None] * len(self.attachment_columns))
        return values

    # ---------------- 读取 ----------------

    def find(self, project_id: str | None, *, db=None) -> Any:
        if not project_id:
            return None
        with self.assets.session(db) as conn:
            return conn.execute(
                f"SELECT * FROM {self.table} WHERE {self.key_column}=?", (project_id,)
            ).fetchone()

    def exists(self, project_id: str, *, db=None) -> bool:
        return self.find(project_id, db=db) is not None

    def ensure(self, project_id: str, *, db=None) -> Any:
        """没有就建一行全默认（旧项目迁移、新建项目都走这里）。"""
        row = self.find(project_id, db=db)
        if row is not None:
            return row
        now = stamp()
        columns = self.insert_columns
        payload = [project_id, *self._defaults(), "{}", None, "", "", now, now]
        with self.assets.session(db) as conn:
            conn.execute(
                f"INSERT INTO {self.table}("
                + ",".join(quote_identifier(column) for column in columns)
                + ") VALUES("
                + ",".join("?" * len(columns))
                + ")",
                tuple(payload),
            )
        return self.find(project_id)

    def extra(self, row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        try:
            parsed = json.loads(row["extra_json"] or "{}")
        except (TypeError, ValueError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def typed(self, project_id: str | None = None, *, row: Any = None) -> dict[str, Any]:
        """类型化视图：可读键 + 附件地址/编号（前端、接口用这个）。"""
        row = row if row is not None else self.find(project_id)
        if row is None:
            raise HTTPException(404, "项目信息不存在，请先创建项目")
        view: dict[str, Any] = {self.key_column: row[self.key_column]}
        for field in self.fields:
            view[field.key] = row[field.column]
        for spec in self.attachments:
            asset_id = row[spec.column]
            view[f"{spec.slot}_id"] = asset_id
            view[f"{spec.slot}_url"] = self.assets.url(asset_id, download=spec.download)
        view["extra"] = self.extra(row)
        view["created"] = row["created"]
        view["updated"] = row["updated"]
        return view

    def legacy_g(
        self,
        project_id: str | None = None,
        *,
        row: Any = None,
        inline: bool = False,
        selections: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """旧读模型 ``G``：老短键 + 未知键兜底 + 图片（``inline=True`` 时回 data URL）。

        ``selections`` 给了就覆盖 ``fixQ/fixQC/insp/inspQ`` 四个键——阶段 2b 之后这四项
        由 ``project_selections`` 表算出来（选型行的当前库值），``extra_json`` 里那份
        原样留着当回滚副本。
        """
        row = row if row is not None else self.find(project_id)
        if row is None:
            raise HTTPException(404, "项目信息不存在，请先创建项目")
        view: dict[str, Any] = dict(self.extra(row))
        if selections:
            view.update(selections)
        for field in self.fields:
            view[field.key] = row[field.column]
        for spec in self.attachments:
            asset_id = row[spec.column]
            view[spec.legacy_key] = (
                self.assets.data_url(asset_id) if inline else self.assets.url(asset_id, download=spec.download)
            )
        return view

    def fields_spec(self) -> dict[str, Any]:
        return {
            "fields": self.headers(),
            "attachments": [
                {
                    "slot": spec.slot,
                    "kind": spec.kind,
                    "legacy_key": spec.legacy_key,
                    "key": f"{spec.slot}_url",
                }
                for spec in self.attachments
            ],
        }

    # ---------------- 写入 ----------------

    def _coerce(self, payload: dict[str, Any], *, lenient: bool) -> tuple[dict[str, Any], dict[str, Any]]:
        """把一页输入校验成 ``({列: 值}, {未知键: 原值})``。

        ``lenient=True``（迁移旧数据用）遇到不合规的取值不报错，而是把**原值**放进
        未知键里兜底，保证一个字段都不丢。
        """
        if not isinstance(payload, dict):
            raise HTTPException(422, f"{self.table_label}数据必须是 JSON 对象")
        values: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        known = {field.key for field in self.fields}
        # 图片键（旧键 pI/pf/bInspImg/fInspImg 与类型化键）由附件逻辑处理，
        # 绝不能落进 extra_json —— 否则 data URL 又回到库里，等于没搬走。
        attachment_keys: set[str] = set()
        for spec in self.attachments:
            attachment_keys.update(spec.value_keys)
            attachment_keys.update({f"{spec.slot}_url", f"{spec.slot}_id"})
        for field in self.fields:
            if field.key not in payload:
                continue
            raw = payload[field.key]
            try:
                if field.kind in {"text", "choice"}:
                    text = "" if raw is None else str(raw).strip()
                    if len(text) > field.limit:
                        raise HTTPException(422, f"{field.label}超过 {field.limit} 个字符")
                    if field.kind == "choice" and field.choices and text and text not in field.choices:
                        labels = field.choice_map()
                        allowed = "、".join(f"{code}（{labels.get(code, code)}）" for code in field.choices)
                        raise HTTPException(422, f"{field.label}只能是：{allowed}")
                    values[field.column] = text
                else:
                    if raw is None or (isinstance(raw, str) and not raw.strip()):
                        values[field.column] = field.default
                        continue
                    try:
                        number = float(raw)
                    except (TypeError, ValueError) as exc:
                        raise HTTPException(422, f"{field.label}必须是数字") from exc
                    if field.kind == "int":
                        number = float(round(number))
                    if number != number or number in (float("inf"), float("-inf")):
                        raise HTTPException(422, f"{field.label}不是有效数字")
                    if number < 0:
                        raise HTTPException(422, f"{field.label}不能为负数")
                    if field.maximum is not None and number > field.maximum:
                        raise HTTPException(422, f"{field.label}超过上限 {field.maximum:g}")
                    values[field.column] = int(number) if field.kind == "int" else number
            except (HTTPException, TypeError, ValueError):
                if not lenient:
                    raise
                extra[field.key] = raw
        for key, value in payload.items():
            if key not in known and key not in attachment_keys:
                extra[key] = value
        return values, extra

    def save(
        self,
        project_id: str,
        payload: dict[str, Any],
        *,
        partial: bool = False,
        lenient: bool = False,
        db=None,
    ) -> dict[str, Any]:
        """行级保存：``partial=True`` 只改提交上来的字段（页面上改一个格存一个格）。

        ``partial=False`` 是"整份项目信息"语义：没提交的字段回默认值，没提交的图片清空。
        图片既能按旧键（``pI``/``bInspImg``…）提交 data URL / 附件地址，也能按类型化键
        （``product_url``/``product_id``）提交；页面上传走 ``set_photo``。
        """
        self.ensure(project_id, db=db)
        row = self.find(project_id, db=db)
        values, extra = self._coerce(payload, lenient=lenient)
        merged_extra = self.extra(row)
        merged_extra.update(extra)
        assignments = [f"{quote_identifier(field.column)}=?" for field in self.fields]
        params: list[Any] = []
        for field in self.fields:
            if field.column in values:
                params.append(values[field.column])
            elif partial:
                params.append(row[field.column])
            else:
                params.append(float(field.default) if field.kind == "real" else field.default)
        with self.assets.session(db) as conn:
            stale: list[tuple[str, str]] = []
            for spec in self.attachments:
                submitted = self._submitted_attachment(payload, spec)
                if submitted is _ABSENT and partial:
                    continue
                value = None if submitted is _ABSENT else submitted
                asset_id = None
                if value:
                    asset_id = self._attachment_id(conn, spec, value)
                    if not asset_id:
                        raise HTTPException(422, f"{spec.legacy_key} 不是可识别的图片")
                previous = row[spec.column]
                assignments.append(f"{quote_identifier(spec.column)}=?")
                params.append(asset_id)
                if previous and previous != asset_id:
                    stale.append((spec.column, previous))
            assignments.append("extra_json=?")
            params.append(json.dumps(merged_extra, ensure_ascii=False, separators=(",", ":")))
            assignments.append("updated=?")
            params.append(stamp())
            params.append(project_id)
            conn.execute(
                f"UPDATE {self.table} SET " + ",".join(assignments) + f" WHERE {self.key_column}=?",
                tuple(params),
            )
            # 先改行、再回收旧图：反过来的话外键还指着它，SQLite 会直接拒绝删除
            for column, asset_id in stale:
                self._release_asset(conn, asset_id, skip=project_id, skip_column=column)
        return self.find(project_id)

    @staticmethod
    def _submitted_attachment(payload: dict[str, Any], spec: AttachmentSpec) -> Any:
        """这页提交里有没有这个图片槽：``_ABSENT`` 表示压根没提交。"""
        for key in (*spec.value_keys, f"{spec.slot}_url", f"{spec.slot}_id"):
            if key in payload:
                return payload[key]
        return _ABSENT

    def apply_state(self, project_id: str, state: dict[str, Any], *, lenient: bool = False) -> None:
        """把整份 ``state`` 里的 ``G`` 灌进表（迁移与旧整份保存接口都用它）。

        ``partial=False``：没给的字段回默认值、没给的图片清空，与旧"整份覆盖"语义一致。
        """
        general = state.get("G") if isinstance(state.get("G"), dict) else {}
        self.save(project_id, general, partial=False, lenient=lenient)

    # ---------------- 附件（项目图片） ----------------

    def _asset_in_use(
        self, db, asset_id: str | None, *, skip: str | None = None, skip_column: str = ""
    ) -> bool:
        """同一张图可能被多个项目/多个槽位/别的表共用，删之前先看全库在不在用。

        ``skip_column`` 是"这一次被清掉的那一列"：本行**其它**图片槽位仍然算在用，
        否则两个槽位共用一张图时会把手还指着的附件行删掉。
        """
        return asset_used_elsewhere(
            db, asset_id, skip_table=self.table, skip_key=self.key_column, skip_value=skip,
            skip_column=skip_column,
        )

    def _assign_attachment(self, project_id: str, spec: AttachmentSpec, asset_id: str | None) -> None:
        """写附件外键并回收上一张（按内容去重，所以只有在没人用的时候才删）。"""
        row = self.find(project_id)
        previous = row[spec.column] if row is not None else None
        with self.assets.session() as db:
            db.execute(
                f"UPDATE {self.table} SET {quote_identifier(spec.column)}=?,updated=? "
                f"WHERE {self.key_column}=?",
                (asset_id, stamp(), project_id),
            )
            if previous and previous != asset_id:
                self._release_asset(db, previous, skip=project_id, skip_column=spec.column)

    def set_photo(
        self, project_id: str, slot: str, data: bytes, mime: str | None, name: str = ""
    ) -> dict[str, Any]:
        spec = self.attachment(slot)
        self.ensure(project_id)
        with self.assets.session() as db:
            record = self.assets.put(spec.kind, data, mime, name, db=db)
        self._assign_attachment(project_id, spec, record["id"])
        return self.typed(project_id)

    def clear_photo(self, project_id: str, slot: str) -> dict[str, Any]:
        spec = self.attachment(slot)
        if self.find(project_id) is None:
            raise HTTPException(404, "项目信息不存在，请先创建项目")
        self._assign_attachment(project_id, spec, None)
        return self.typed(project_id)

    # ---------------- 与项目同生共死 ----------------

    def forget(self, project_id: str, *, db=None) -> None:
        """项目被物理删除时连带清理（当前口径是永不物理删除，仅备用）。"""
        with self.assets.session(db) as conn:
            conn.execute(f"DELETE FROM {self.table} WHERE {self.key_column}=?", (project_id,))

    def project_ids(self) -> Iterable[str]:
        with self._connect() as db:
            return [row[0] for row in db.execute(f"SELECT {self.key_column} FROM {self.table} ORDER BY {self.key_column}")]
