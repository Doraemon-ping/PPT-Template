"""刀具库 + 两张字典表（库分类 / 类型）。

页面列：库分类 | 型号 | 图片 | 类型 | D(mm) | 长度L(mm) | 转速n(rpm) |
进给vf(mm/min) | 每齿进给fz(自动) | 线速度Vc(自动) | 寿命(min) | 价格(¥)

数据落在三张表里：

* ``tool_groups``      库分类字典（高压项目刀具 / 差压项目刀具 / 刀柄 / 配件）
* ``tool_categories``  类型字典（47 个刀具分类 + 国内/进口；``scope`` 区分切削与非切削）
* ``tools``            刀具本体，``tool_group`` / ``category`` 是**指向两张字典表的文本码外键**

字典表由内置种子初始化，之后以表为准：可以在管理设置里改名称、调顺序、加类型
（接口见 ``/api/machining-dfm/tool-groups``、``/tool-categories``），改名称立刻反映到
所有引用行的显示上；删除被刀具引用的字典项会被外键挡住（409）。

自动列 ``fz``/``vc`` 不入库，由页面按 ``vf/n`` 与 ``π·d·n/1000`` 现算。
项目工序刀具行只按名称（``tp``）引用刀具库（成本表按 ``price``/``life`` 查表），
不存下标，因此排序/删除刀具不会错位引用项目数据。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..core.utils import stamp
from ..db.library import AttachmentSpec, LibraryField, TypedLibrary

PHOTO_KIND = "tool_photo"
SCOPE_CUT = "cut"  # 切削刀具
SCOPE_NC = "nc"  # 刀柄 / 配件

# ---------------------------------------------------------------- 内置字典种子
# 首次启动灌进字典表（INSERT OR IGNORE：管理员改过的名称与新增项不会被覆盖）。

TOOL_GROUP_SEED: tuple[tuple[str, str], ...] = (
    ("hp", "高压项目刀具"),
    ("dp", "差压项目刀具"),
    ("hld", "刀柄"),
    ("acc", "配件"),
)

TOOL_CATEGORY_SEED: tuple[tuple[str, str, str], ...] = (
    # (code, label, scope)
    ("f", "面铣刀", SCOPE_CUT),
    ("pf", "PCD面铣刀", SCOPE_CUT),
    ("pt", "PCD-T型刀", SCOPE_CUT),
    ("pc", "PCD倒角刀", SCOPE_CUT),
    ("pb", "PCD反勾刀", SCOPE_CUT),
    ("pg", "PCD复合切槽刀", SCOPE_CUT),
    ("pk", "PCD锪刀", SCOPE_CUT),
    ("pr", "PCD铰刀", SCOPE_CUT),
    ("pj", "PCD精镗刀", SCOPE_CUT),
    ("pd", "PCD盘刀", SCOPE_CUT),
    ("pq", "PCD球刀", SCOPE_CUT),
    ("pm", "PCD铣刀", SCOPE_CUT),
    ("py", "PCD玉米铣刀", SCOPE_CUT),
    ("pz", "PCD锥度刀", SCOPE_CUT),
    ("pa", "PCD钻铰刀", SCOPE_CUT),
    ("po", "PCD钻头", SCOPE_CUT),
    ("ud", "U钻", SCOPE_CUT),
    ("bm", "波纹合金铣刀", SCOPE_CUT),
    ("cb", "粗镗刀（刀片）", SCOPE_CUT),
    ("hc", "合金倒角刀", SCOPE_CUT),
    ("ht", "合金挤压丝锥", SCOPE_CUT),
    ("hr", "合金内R铣刀", SCOPE_CUT),
    ("hb", "合金球刀", SCOPE_CUT),
    ("he", "合金球头铣刀", SCOPE_CUT),
    ("hm", "合金铣刀", SCOPE_CUT),
    ("hz", "合金锥度铣刀", SCOPE_CUT),
    ("hd", "合金钻头", SCOPE_CUT),
    ("nw", "网纹铣刀（刀片）", SCOPE_CUT),
    ("hq", "合金钻铣刀", SCOPE_CUT),
    ("ps", "PCD成型刀", SCOPE_CUT),
    ("pv", "PCD成型钻头", SCOPE_CUT),
    ("hs", "合金阶梯钻", SCOPE_CUT),
    ("hu", "合金台阶钻", SCOPE_CUT),
    ("kb", "开粗镗刀", SCOPE_CUT),
    ("hp", "合金深孔钻", SCOPE_CUT),
    ("pgd", "PCD导条刀", SCOPE_CUT),
    ("psr", "PCD阶梯铰刀", SCOPE_CUT),
    ("hgd", "合金导条刀", SCOPE_CUT),
    ("hj", "合金铰刀", SCOPE_CUT),
    ("hjr", "合金阶梯铰刀", SCOPE_CUT),
    ("hda", "合金钻铰刀", SCOPE_CUT),
    ("rt", "挤压丝锥", SCOPE_CUT),
    ("ct", "切削丝锥", SCOPE_CUT),
    ("tm", "螺纹铣刀", SCOPE_CUT),
    ("pts", "PCD套刀", SCOPE_CUT),
    ("br", "毛刷", SCOPE_CUT),
    ("other", "其他", SCOPE_CUT),
    ("cn", "国内", SCOPE_NC),
    ("im", "进口", SCOPE_NC),
)

# 页面自动列（不入库）
TOOL_DERIVED: tuple[dict[str, Any], ...] = (
    {"key": "fz", "label": "每齿进给", "unit": "mm", "formula": "vf/n", "module": "刀具库"},
    {"key": "vc", "label": "线速度", "unit": "m/min", "formula": "π·d·n/1000", "module": "刀具库"},
)

# 旧版本（migCat 之前）的分类码 → 现分类码的归一化规则，与前端 migCat() 完全一致
LEGACY_CATEGORY_CODES = ("milling", "drill", "tap", "chamfer", "spot")


def normalize_category(code: str, name: str = "") -> str:
    """把旧版分类码按原名与型号归一到现在 47 个分类里（前端 migCat 的等价实现）。"""
    code = str(code or "").strip()
    if code not in LEGACY_CATEGORY_CODES:
        return code
    text = str(name or "")
    pcd = "PCD" in text.upper()
    if code == "tap":
        return "ht" if "挤" in text else "ct"
    if code == "spot":
        return "pk" if pcd else "other"
    if code == "chamfer":
        return "pc" if pcd else "hc"
    if pcd:
        for pattern, target in (
            ("玉米", "py"), ("球", "pq"), ("锥", "pz"), ("盘刀", "pd"),
            ("盘铣", "pf"), ("面铣", "pf"), ("成型", "ps"), ("倒角", "pc"), ("镗", "pj"),
        ):
            if pattern in text:
                return target
        return "pm"
    for pattern, target in (
        ("波纹", "bm"), ("球头", "he"), ("球", "hb"), ("锥", "hz"), ("内R", "hr"),
        ("网纹", "nw"), ("盘铣", "f"), ("面铣", "f"), ("盘刀", "f"),
        ("倒角", "hc"), ("镗", "kb"),
    ):
        if pattern in text:
            return target
    return "hm"


# ---------------------------------------------------------------- 字段登记表

TOOL_FIELDS: tuple[LibraryField, ...] = (
    LibraryField(
        "grp", "tool_group", "choice", "hp", "库分类",
        limit=8, references="tool_groups(code)",
    ),
    LibraryField("tp", "name", "text", "", "型号", limit=120),
    LibraryField(
        "cat", "category", "choice", "other", "类型",
        limit=12, references="tool_categories(code)",
    ),
    LibraryField("d", "diameter", "real", 0.0, "D", "mm", maximum=1000),
    LibraryField("ln", "length", "real", 0.0, "长度L", "mm", maximum=5000),
    LibraryField("n", "spindle_rpm", "real", 0.0, "转速n", "rpm", maximum=200000),
    LibraryField("vf", "feed_rate", "real", 0.0, "进给vf", "mm/min", maximum=200000),
    LibraryField("life", "life_minutes", "real", 0.0, "寿命", "min", maximum=1_000_000),
    LibraryField("price", "price", "real", 0.0, "价格", "¥", maximum=10_000_000),
)

TOOL_ATTACHMENTS: tuple[AttachmentSpec, ...] = (
    AttachmentSpec(
        slot="photo",
        kind=PHOTO_KIND,
        column="photo_id",
        legacy_key="tI",
        value_keys=("tI", "photo", "img"),
        mime_key="tI_mime",
        default_mime="image/jpeg",
    ),
)

TOOL_COLUMNS: tuple[str, ...] = tuple(field.column for field in TOOL_FIELDS)
FIELD_BY_KEY = {field.key: field for field in TOOL_FIELDS}
LEGACY_KEYS = tuple(field.key for field in TOOL_FIELDS) + ("tI",)


# ---------------------------------------------------------------- 字典表


class ToolDictionary:
    """库分类 / 类型两张字典表的读写（外键目标，先于 ``tools`` 建表与灌数据）。"""

    GROUP_TABLE = "tool_groups"
    CATEGORY_TABLE = "tool_categories"
    SCOPES = (SCOPE_CUT, SCOPE_NC)

    #: 内置项不可删除（每次启动按种子补齐），管理员可改名称与顺序、可新增自定义项
    BUILTIN_SOURCES = ("seed",)

    def __init__(self, connect):
        self._connect = connect

    # ---------------- 建表 / 种子 ----------------

    def ddl(self) -> str:
        return """
CREATE TABLE IF NOT EXISTS tool_groups(
    code TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    builtin INTEGER NOT NULL DEFAULT 1,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    deleted_at TEXT,
    deleted_by TEXT,
    deleted_reason TEXT
);
CREATE TABLE IF NOT EXISTS tool_categories(
    code TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'cut',
    sort_order INTEGER NOT NULL DEFAULT 0,
    builtin INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'seed',
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    deleted_at TEXT,
    deleted_by TEXT,
    deleted_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_machining_dfm_tool_categories_scope
    ON tool_categories(scope, sort_order);
"""

    def trash_index_ddl(self) -> str:
        """回收站索引要在**补列之后**建（老库先有表后有列，先建索引会报 no such column）。"""
        return (
            "CREATE INDEX IF NOT EXISTS idx_machining_dfm_tool_groups_trash "
            "ON tool_groups(deleted_at, sort_order);\n"
            "CREATE INDEX IF NOT EXISTS idx_machining_dfm_tool_categories_trash "
            "ON tool_categories(deleted_at, sort_order);\n"
        )

    def ensure_trash_columns(self, db) -> list[str]:
        """老库补上三个逻辑删除列（幂等、可空、不动任何既有数据）。"""
        added: list[str] = []
        for table in (self.GROUP_TABLE, self.CATEGORY_TABLE):
            existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for column in ("deleted_at", "deleted_by", "deleted_reason"):
                if column not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
                    added.append(f"{table}.{column}")
        return added

    def schema(self, db) -> None:
        db.executescript(self.ddl())
        self.ensure_trash_columns(db)
        db.executescript(self.trash_index_ddl())

    def seed(self, db) -> None:
        """内置字典：只补不改（管理员的改名与新增项都保留）。"""
        now = stamp()
        for index, (code, label) in enumerate(TOOL_GROUP_SEED):
            db.execute(
                "INSERT OR IGNORE INTO tool_groups(code,label,sort_order,builtin,created,updated) "
                "VALUES(?,?,?,1,?,?)",
                (code, label, index, now, now),
            )
        for index, (code, label, scope) in enumerate(TOOL_CATEGORY_SEED):
            db.execute(
                "INSERT OR IGNORE INTO tool_categories"
                "(code,label,scope,sort_order,builtin,source,created,updated) VALUES(?,?,?,?,1,'seed',?,?)",
                (code, label, scope, index, now, now),
            )

    # ---------------- 读取 ----------------

    def groups(self, *, db=None) -> list[dict[str, Any]]:
        with _session(self._connect, db) as conn:
            rows = conn.execute(
                f"SELECT * FROM {self.GROUP_TABLE} WHERE deleted_at IS NULL ORDER BY sort_order, code"
            ).fetchall()
        return [_group_view(row) for row in rows]

    def categories(self, *, scope: str = "", db=None) -> list[dict[str, Any]]:
        with _session(self._connect, db) as conn:
            if scope:
                rows = conn.execute(
                    f"SELECT * FROM {self.CATEGORY_TABLE} WHERE scope=? AND deleted_at IS NULL "
                    "ORDER BY sort_order, code",
                    (scope,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM {self.CATEGORY_TABLE} WHERE deleted_at IS NULL "
                    "ORDER BY sort_order, code"
                ).fetchall()
        return [_category_view(row) for row in rows]

    def group_codes(self, *, db=None) -> dict[str, dict[str, Any]]:
        return {row["value"]: row for row in self.groups(db=db)}

    def category_codes(self, *, scope: str = "", db=None) -> dict[str, dict[str, Any]]:
        return {row["value"]: row for row in self.categories(scope=scope, db=db)}

    def scope_of(self, code: str, *, db=None) -> str:
        with _session(self._connect, db) as conn:
            row = conn.execute(
                f"SELECT scope FROM {self.CATEGORY_TABLE} WHERE code=? AND deleted_at IS NULL", (code,)
            ).fetchone()
        return row["scope"] if row else ""

    # ---------------- 校验 / 补录 ----------------

    def require_group(self, code: str, *, db=None) -> None:
        if code not in self.group_codes(db=db):
            raise HTTPException(422, f"库分类 {code} 不在分类字典里，请先在管理设置里维护分类")

    def require_category(self, code: str, scope: str = "", *, db=None) -> None:
        found = self.category_codes(db=db).get(code)
        if found is None:
            raise HTTPException(422, f"类型 {code} 不在类型字典里，请先在管理设置里维护类型")
        if scope and found["scope"] != scope:
            want = "刀柄/配件" if scope == SCOPE_NC else "切削刀具"
            raise HTTPException(422, f"类型「{found['label']}」只用于{want}")

    def register_categories(self, codes: dict[str, str], *, db=None) -> list[str]:
        """把字典里还没有的码补录进类型表（旧数据迁移用），返回补录的码。"""
        pending = {code: label for code, label in codes.items() if code}
        if not pending:
            return []
        added: list[str] = []
        with _session(self._connect, db) as conn:
            existing = {row["code"] for row in conn.execute(f"SELECT code FROM {self.CATEGORY_TABLE}")}
            now = stamp()
            order = int(
                conn.execute(
                    f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {self.CATEGORY_TABLE}"
                ).fetchone()[0]
            )
            for code, label in pending.items():
                if code in existing:
                    continue
                conn.execute(
                    f"INSERT INTO {self.CATEGORY_TABLE}"
                    "(code,label,scope,sort_order,builtin,source,created,updated) VALUES(?,?,?,?,0,'legacy',?,?)",
                    (code, label or code, SCOPE_CUT, order, now, now),
                )
                order += 1
                added.append(code)
        return added

    def register_groups(self, codes: dict[str, str], *, db=None) -> list[str]:
        pending = {code: label for code, label in codes.items() if code}
        if not pending:
            return []
        added: list[str] = []
        with _session(self._connect, db) as conn:
            existing = {row["code"] for row in conn.execute(f"SELECT code FROM {self.GROUP_TABLE}")}
            now = stamp()
            order = int(
                conn.execute(
                    f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {self.GROUP_TABLE}"
                ).fetchone()[0]
            )
            for code, label in pending.items():
                if code in existing:
                    continue
                conn.execute(
                    f"INSERT INTO {self.GROUP_TABLE}(code,label,sort_order,builtin,created,updated) "
                    "VALUES(?,?,?,0,?,?)",
                    (code, label or code, order, now, now),
                )
                order += 1
                added.append(code)
        return added

    # ---------------- 维护接口 ----------------

    def create_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = _clean_code(payload.get("code"))
        label = _clean_label(payload.get("label"), "库分类名称")
        with self._connect() as db:
            row = db.execute(f"SELECT * FROM {self.GROUP_TABLE} WHERE code=?", (code,)).fetchone()
            if row is not None and not row["deleted_at"]:
                raise HTTPException(409, f"库分类 {code} 已存在")
            if row is not None:
                # 同名重建 = 复活原行（口径 3）
                db.execute(
                    f"UPDATE {self.GROUP_TABLE} SET label=?,deleted_at=NULL,deleted_by=NULL,"
                    "deleted_reason=NULL,updated=? WHERE code=?",
                    (label, stamp(), code),
                )
                revived = self._group(code)
                revived["revived"] = True
                return revived
            order = int(
                db.execute(f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {self.GROUP_TABLE}").fetchone()[0]
            )
            now = stamp()
            db.execute(
                f"INSERT INTO {self.GROUP_TABLE}(code,label,sort_order,builtin,created,updated) "
                "VALUES(?,?,?,0,?,?)",
                (code, label, order, now, now),
            )
        return self._group(code)

    def create_category(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = _clean_code(payload.get("code"))
        label = _clean_label(payload.get("label"), "类型名称")
        scope = str(payload.get("scope") or SCOPE_CUT).strip()
        if scope not in self.SCOPES:
            raise HTTPException(422, "类型归属只能是 cut（切削刀具）或 nc（刀柄/配件）")
        with self._connect() as db:
            row = db.execute(f"SELECT * FROM {self.CATEGORY_TABLE} WHERE code=?", (code,)).fetchone()
            if row is not None and not row["deleted_at"]:
                raise HTTPException(409, f"类型 {code} 已存在")
            if row is not None:
                # 同名重建 = 复活原行（口径 3）
                db.execute(
                    f"UPDATE {self.CATEGORY_TABLE} SET label=?,scope=?,deleted_at=NULL,deleted_by=NULL,"
                    "deleted_reason=NULL,updated=? WHERE code=?",
                    (label, scope, stamp(), code),
                )
                revived = self._category(code)
                revived["revived"] = True
                return revived
            order = int(
                db.execute(
                    f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {self.CATEGORY_TABLE}"
                ).fetchone()[0]
            )
            now = stamp()
            db.execute(
                f"INSERT INTO {self.CATEGORY_TABLE}"
                "(code,label,scope,sort_order,builtin,source,created,updated) VALUES(?,?,?,?,0,'admin',?,?)",
                (code, label, scope, order, now, now),
            )
        return self._category(code)

    def update_group(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        label = _clean_label(payload.get("label"), "库分类名称")
        with self._connect() as db:
            if not db.execute(f"SELECT 1 FROM {self.GROUP_TABLE} WHERE code=?", (code,)).fetchone():
                raise HTTPException(404, f"库分类 {code} 不存在")
            db.execute(
                f"UPDATE {self.GROUP_TABLE} SET label=?,updated=? WHERE code=?", (label, stamp(), code)
            )
        return self._group(code)

    def update_category(self, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        label = _clean_label(payload.get("label"), "类型名称")
        scope = str(payload.get("scope") or "").strip()
        if scope and scope not in self.SCOPES:
            raise HTTPException(422, "类型归属只能是 cut（切削刀具）或 nc（刀柄/配件）")
        with self._connect() as db:
            current = db.execute(f"SELECT * FROM {self.CATEGORY_TABLE} WHERE code=?", (code,)).fetchone()
            if current is None:
                raise HTTPException(404, f"类型 {code} 不存在")
            if scope and scope != current["scope"]:
                used = int(
                    db.execute(
                        "SELECT COUNT(*) FROM tools WHERE category=? AND deleted_at IS NULL", (code,)
                    ).fetchone()[0]
                )
                if used:
                    raise HTTPException(409, f"类型「{current['label']}」已被 {used} 件刀具使用，不能改归属")
            db.execute(
                f"UPDATE {self.CATEGORY_TABLE} SET label=?,scope=?,updated=? WHERE code=?",
                (label, scope or current["scope"], stamp(), code),
            )
        return self._category(code)

    def delete_group(self, code: str, *, by: str = "", reason: str = "") -> dict[str, Any]:
        return self._delete(self.GROUP_TABLE, code, "tool_group", "库分类", by=by, reason=reason)

    def delete_category(self, code: str, *, by: str = "", reason: str = "") -> dict[str, Any]:
        return self._delete(self.CATEGORY_TABLE, code, "category", "类型", by=by, reason=reason)

    def restore_group(self, code: str, *, by: str = "") -> dict[str, Any]:
        return self._restore(self.GROUP_TABLE, code, "库分类", by=by)

    def restore_category(self, code: str, *, by: str = "") -> dict[str, Any]:
        return self._restore(self.CATEGORY_TABLE, code, "类型", by=by)

    def trash(self, *, db=None) -> list[dict[str, Any]]:
        """回收站：两张字典表里已逻辑删除的项（按删除时间倒序）。"""
        items: list[dict[str, Any]] = []
        with _session(self._connect, db) as conn:
            for table, view, label in (
                (self.GROUP_TABLE, _group_view, "库分类"),
                (self.CATEGORY_TABLE, _category_view, "类型"),
            ):
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE deleted_at IS NOT NULL "
                    "ORDER BY deleted_at DESC, sort_order, code"
                ).fetchall()
                for row in rows:
                    item = view(row)
                    item.update({
                        "table": table,
                        "table_label": label,
                        "deleted_at": row["deleted_at"],
                        "deleted_by": row["deleted_by"] or "",
                        "deleted_reason": row["deleted_reason"] or "",
                    })
                    items.append(item)
        return items

    def _restore(self, table: str, code: str, label: str, *, by: str = "") -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(f"SELECT * FROM {table} WHERE code=?", (code,)).fetchone()
            if row is None:
                raise HTTPException(404, f"{label} {code} 不存在")
            if not row["deleted_at"]:
                raise HTTPException(409, f"{label}「{row['label']}」本来就在用，不需要恢复")
            db.execute(
                f"UPDATE {table} SET deleted_at=NULL,deleted_by=NULL,deleted_reason=NULL,updated=? "
                "WHERE code=?",
                (stamp(), code),
            )
        return {"code": code, "label": row["label"], "restored": True}

    def _delete(self, table: str, code: str, column: str, label: str, *,
                by: str = "", reason: str = "") -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(f"SELECT * FROM {table} WHERE code=?", (code,)).fetchone()
            if row is None:
                raise HTTPException(404, f"{label} {code} 不存在")
            if row["deleted_at"]:
                raise HTTPException(409, f"{label}「{row['label']}」已经在回收站里了")
            used = int(db.execute(
                f"SELECT COUNT(*) FROM tools WHERE {column}=? AND deleted_at IS NULL", (code,)
            ).fetchone()[0])
            if used:
                raise HTTPException(409, f"{label}「{row['label']}」仍被 {used} 件刀具使用，不能删除")
            if row["builtin"]:
                raise HTTPException(409, f"{label}「{row['label']}」是内置项，不能删除（可以改名称）")
            now = stamp()
            # 口径 2：逻辑删除（没有彻底删除，回收站里随时恢复）
            db.execute(
                f"UPDATE {table} SET deleted_at=?,deleted_by=?,deleted_reason=?,updated=? WHERE code=?",
                (now, str(by or "").strip()[:40] or "admin", str(reason or "")[:200], now, code),
            )
        return {"code": code, "label": row["label"], "removed": True, "deleted_at": now}

    # ---------------- 单项读取 ----------------

    def _group(self, code: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(f"SELECT * FROM {self.GROUP_TABLE} WHERE code=?", (code,)).fetchone()
        return _group_view(row)

    def _category(self, code: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(f"SELECT * FROM {self.CATEGORY_TABLE} WHERE code=?", (code,)).fetchone()
        return _category_view(row)


def _group_view(row) -> dict[str, Any]:
    return {
        "value": row["code"],
        "code": row["code"],
        "label": row["label"],
        "sort_order": int(row["sort_order"]),
        "builtin": bool(row["builtin"]),
    }


def _category_view(row) -> dict[str, Any]:
    return {
        "value": row["code"],
        "code": row["code"],
        "label": row["label"],
        "scope": row["scope"],
        "sort_order": int(row["sort_order"]),
        "builtin": bool(row["builtin"]),
        "source": row["source"],
    }


def _clean_code(value: Any) -> str:
    code = str(value or "").strip()
    if not code or len(code) > 12:
        raise HTTPException(422, "字典代码必须是 1-12 个字符")
    if not code.replace("_", "").isalnum():
        raise HTTPException(422, "字典代码只能包含字母、数字与下划线")
    return code


def _clean_label(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 40:
        raise HTTPException(422, f"{label}必须是 1-40 个字符")
    return text


class _Session:
    """复用外部连接，或在没有传入时自己开一个。"""

    def __init__(self, connect, db):
        self._connect = connect
        self._db = db

    def __enter__(self):
        if self._db is not None:
            self._own = None
            return self._db
        self._own = self._connect()
        return self._own.__enter__()

    def __exit__(self, *exc):
        if self._own is not None:
            return self._own.__exit__(*exc)
        return False


def _session(connect, db):
    return _Session(connect, db)


# ---------------------------------------------------------------- 刀具本体


def tool_field_headers(dictionaries: ToolDictionary | None = None) -> list[dict[str, Any]]:
    """字段登记表；库分类/类型的取值来自字典表（``fields[].choices``）。"""
    headers = [field.describe() for field in TOOL_FIELDS]
    if dictionaries is None:
        return headers
    by_key = {item["key"]: item for item in headers}
    by_key["grp"]["choices"] = [
        {"value": item["code"], "label": item["label"]} for item in dictionaries.groups()
    ]
    by_key["cat"]["choices"] = [
        {"value": item["code"], "label": item["label"], "scope": item["scope"]}
        for item in dictionaries.categories()
    ]
    return headers


def tool_derived_headers() -> list[dict[str, Any]]:
    return [dict(item) for item in TOOL_DERIVED]


def clean_values(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """兼容调用：校验一行刀具输入（字典外键校验需实例，见 ``ToolLibrary.validate_values``）。"""
    return ToolLibrary.clean_values(payload, partial=partial)


class ToolLibrary(TypedLibrary):
    table = "tools"
    table_label = "刀具"
    fields = TOOL_FIELDS
    attachments = TOOL_ATTACHMENTS
    supports_fallback = False
    display_keys = ("tp",)
    indexes = (("group", ("tool_group",)), ("category", ("category",)))

    def __init__(self, connect, assets, dictionaries: ToolDictionary | None = None):
        super().__init__(connect, assets)
        self.dictionaries = dictionaries or ToolDictionary(connect)

    # ---------------- 字典相关 ----------------

    def scope_for_group(self, group: str) -> str:
        return SCOPE_NC if group in {"hld", "acc"} else SCOPE_CUT

    def validate_values(self, values: dict[str, Any], payload: dict[str, Any]) -> None:
        """库分类/类型必须落在字典表里，且类型归属要与库分类一致。"""
        group = str(values.get("tool_group") or "").strip()
        category = str(values.get("category") or "").strip()
        self.dictionaries.require_group(group)
        self.dictionaries.require_category(category, self.scope_for_group(group))

    def prepare_rows(self, db, rows: list[dict[str, Any]]) -> None:
        """灌数据（种子 / 迁移 / 旧整体保存）前：归一化旧分类码，未知码补录进字典。"""
        groups: dict[str, str] = {}
        categories: dict[str, str] = {}
        for row in rows:
            group = str(row.get("grp") or row.get("tool_group") or row.get("grp_code") or "hp").strip()
            group = group or "hp"
            groups.setdefault(group, group)
            raw = str(row.get("cat") or row.get("category") or "other").strip()
            code = normalize_category(raw, str(row.get("tp") or row.get("name") or ""))
            code = code or "other"
            categories.setdefault(code, code)
            # 归一化结果写回行本身，迁移进去的就是规范码
            if "cat" in row or "category" not in row:
                row["cat"] = code
            else:
                row["category"] = code
            if "grp" not in row and "tool_group" not in row:
                row["grp"] = group
        self.dictionaries.register_groups(groups, db=db)
        self.dictionaries.register_categories(categories, db=db)

    def normalize_row_categories(self, db=None) -> dict[str, int]:
        """把表里已有的旧分类码归一化（v2→v3 迁移与字典补录用）。"""
        changed = 0
        with _session(self._connect, db) as conn:
            rows = conn.execute("SELECT id,category,name FROM tools").fetchall()
            known = {row["code"] for row in conn.execute("SELECT code FROM tool_categories")}
            now = stamp()
            for row in rows:
                code = normalize_category(row["category"], row["name"])
                if code == row["category"] and code in known:
                    continue
                if code not in known:
                    self.dictionaries.register_categories({code: code}, db=conn)
                    known.add(code)
                conn.execute(
                    "UPDATE tools SET category=?,updated=? WHERE id=?", (code, now, row["id"])
                )
                changed += 1
        return {"normalized": changed}

    def reference_counts(self, db=None) -> dict[str, dict[str, int]]:
        """每张字典表被引用的次数（删除前的检查与界面提示用）。"""
        with _session(self._connect, db) as conn:
            groups = {row[0]: row[1] for row in conn.execute(
                "SELECT tool_group, COUNT(*) FROM tools WHERE deleted_at IS NULL GROUP BY tool_group"
            )}
            categories = {row[0]: row[1] for row in conn.execute(
                "SELECT category, COUNT(*) FROM tools WHERE deleted_at IS NULL GROUP BY category"
            )}
        return {"groups": groups, "categories": categories}

    def natural_key(self, values: dict[str, Any]) -> tuple:
        # 旧整体保存按 (库分类, 型号) 匹配，保持 id 稳定。
        return (values.get("tool_group", ""), values.get("name", ""))

    def used_names(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for row in self.rows():
            grouped.setdefault(row["tool_group"], []).append(row["name"])
        return grouped
