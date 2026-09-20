"""机加 DFM 选型：**夹具选型** ``project_fixtures`` / **检具选型** ``project_gauges``。

## 结构口径：一切都是项目的

```
项目 project
├── 项目信息 project_settings            客户 / 零件 / 产能 / 图片
├── 工序     project_processes           多道工序，**每道工序选一台设备**
│     └── 刀具行 project_process_tools
├── 夹具选型 project_fixtures            ← 本模块：项目级一份，按模具中心分格
├── 检具选型 project_gauges              ← 本模块：项目级一份，按检具类别分格
├── 问题清单 project_issues
└── 版本履历 project_versions / 变更流水 project_changes
```

夹具选型、检具选型都是**项目级**资源（不是每道工序各一套）：一个项目一份清单，
清单按类别字典分格——夹具按**模具中心**、检具按**检具类别**，一格一行。

## 为什么从"一张多态大表"改成"两张小表"

2b 阶段为了少改代码，把两类选型塞进了同一张 ``project_selections``：
靠 ``kind`` 列区分，靠三条跨类 ``CHECK``（"夹具行不许挂检具列"）兜住写错的可能。
代价是**每个调用点都要先想"我现在是夹具还是检具"**：查询要带 ``kind`` 过滤、
建行要现算 ``kind``、表结构里一半列对任何一行都是废列。现在两张表各自只放自己需要的列：

| | ``project_fixtures`` | ``project_gauges`` |
| --- | --- | --- |
| 类别列 | ``fixture_center`` → ``fixture_centers(name)`` | ``gauge_category`` → ``gauge_categories(name)`` |
| 库行 | ``fixture_id`` → ``fixtures(id)`` | ``gauge_id`` → ``gauges(id)`` |
| 快照 | 名称 / 价格 / 制造周期 | 名称 / 图号 / 价格 / 制造周期 / 设计周期 |

**没有 ``kind`` 列，也没有跨类 CHECK**——"这是夹具表"这件事由表名说清楚，不再由数据说。

老表 ``project_selections`` 不再被读写，只作为迁移来源（``copy_legacy_rows``）。

## 读模型：四个旧数组逐字节不变

``legacy_selection_arrays`` 按**当前字典顺序**把行放回数组下标位置（按类别名定位，
不认死下标，所以字典插一条也不会串位），元素仍拼成旧格式：

* 夹具：``中心|名称``（名称取**当前**库行 → 库里改名自动跟随；库行没了用快照）
* 检具：``类别|名称|图号``

两张表里一行都没有（没迁移的项目）→ 返回 ``None``，读模型回退 ``extra_json`` 里那四个数组。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from fastapi import HTTPException

from ..core.utils import stamp
from ..db.library import LibraryField
from ..db.rows import ForeignKey, ProjectRows
#: 夹具选型表 / 检具选型表 / 老多态表：表名登记在 db 层，本模块只做业务声明
from ..db.tables import FIXTURE_TABLE, GAUGE_TABLE, LEGACY_SELECTION_TABLE

#: 能力级别（1 = 工序，2 = 问题清单，3 = 选型报价）
SELECTION_VERSION = 3

KIND_FIXTURE = "fixture"
KIND_GAUGE = "gauge"
SELECTION_KINDS = (KIND_FIXTURE, KIND_GAUGE)


@dataclass(frozen=True)
class SelectionKind:
    """一类选型的全部坐标：表、类别字典、库表、旧数组键。

    支持 ``spec["category_column"]`` 这种字典式取值（老调用点很多），
    内部就是 ``getattr``——两种写法都对，不用为了取一个常量改一片代码。
    """

    key: str
    label: str
    table: str
    array: str
    quoted: str
    category_column: str
    category_table: str
    id_column: str
    library_table: str
    library_label: str
    slot_unit: str
    fields: tuple[LibraryField, ...]
    foreign_keys: tuple[ForeignKey, ...]

    def __getitem__(self, name: str) -> Any:
        try:
            return getattr(self, name)
        except AttributeError as exc:  # pragma: no cover - 拼错键名时给出人话提示
            raise KeyError(f"选型口径里没有 {name}") from exc

    def get(self, name: str, default: Any = None) -> Any:
        return getattr(self, name, default)


#: 夹具选型：类别 = 模具中心，快照 = 名称 / 价格 / 制造周期
FIXTURE_FIELDS = (
    LibraryField("legacy_key", "legacy_key", "text", "", "旧值（兼容用）", limit=400),
    LibraryField("name_snapshot", "name_snapshot", "text", "", "名称快照", limit=300),
    LibraryField("price_snapshot", "price_snapshot", "real", 0.0, "价格快照"),
    LibraryField("days_snapshot", "days_snapshot", "real", 0.0, "制造周期快照"),
    LibraryField("quoted", "quoted", "int", 1, "是否报价", maximum=1),
)

#: 检具选型：类别 = 检具类别，比夹具多一个图号（报价/选型要写进 DFM 报告）和设计周期
GAUGE_FIELDS = (
    LibraryField("legacy_key", "legacy_key", "text", "", "旧值（兼容用）", limit=400),
    LibraryField("name_snapshot", "name_snapshot", "text", "", "名称快照", limit=300),
    LibraryField("drawing_snapshot", "drawing_snapshot", "text", "", "图号快照", limit=120),
    LibraryField("price_snapshot", "price_snapshot", "real", 0.0, "价格快照"),
    LibraryField("days_snapshot", "days_snapshot", "real", 0.0, "制造周期快照"),
    LibraryField("design_days_snapshot", "design_days_snapshot", "real", 0.0, "设计周期快照"),
    LibraryField("quoted", "quoted", "int", 1, "是否报价", maximum=1),
)

#: 两类选型字段的合并视图（只用于老接口的 ``fields`` 键：新接口各自给各自的字段表）
SELECTION_FIELDS = (
    LibraryField("legacy_key", "legacy_key", "text", "", "旧值（兼容用）", limit=400),
    LibraryField("name_snapshot", "name_snapshot", "text", "", "名称快照", limit=300),
    LibraryField("drawing_snapshot", "drawing_snapshot", "text", "", "图号快照", limit=120),
    LibraryField("price_snapshot", "price_snapshot", "real", 0.0, "价格快照"),
    LibraryField("days_snapshot", "days_snapshot", "real", 0.0, "制造周期快照"),
    LibraryField("design_days_snapshot", "design_days_snapshot", "real", 0.0, "设计周期快照"),
    LibraryField("quoted", "quoted", "int", 1, "是否报价", maximum=1),
)

#: 外键：类别字典（主键是名字）+ 库行，两处都 ``SET NULL``。
#: 口径 4 要求"源库删了也要按当时快照算"，所以库行被删时把外键置空、用 ``*_snapshot`` 继续算价；
#: 类别列同样 ``SET NULL``：字典里删掉一个类别时这一格变成"类别已不存在"，
#: 读模型不再输出它（本来也不该出现在报价表里），行留在表里当历史。
FIXTURE_FOREIGN_KEYS = (
    ForeignKey("fixture_center", "fixture_centers", "name", False, "SET NULL"),
    ForeignKey("fixture_id", "fixtures", target="id", on_delete="SET NULL"),
)
GAUGE_FOREIGN_KEYS = (
    ForeignKey("gauge_category", "gauge_categories", "name", False, "SET NULL"),
    ForeignKey("gauge_id", "gauges", target="id", on_delete="SET NULL"),
)

#: 两类选型的登记表：口径全在这一个地方，别处不许再写死键名
KIND_SPECS: dict[str, SelectionKind] = {
    KIND_FIXTURE: SelectionKind(
        key=KIND_FIXTURE, label="夹具", table=FIXTURE_TABLE,
        array="fixQ", quoted="fixQC",
        category_column="fixture_center", category_table="fixture_centers",
        id_column="fixture_id", library_table="fixtures", library_label="夹具库",
        slot_unit="中心", fields=FIXTURE_FIELDS, foreign_keys=FIXTURE_FOREIGN_KEYS,
    ),
    KIND_GAUGE: SelectionKind(
        key=KIND_GAUGE, label="检具", table=GAUGE_TABLE,
        array="insp", quoted="inspQ",
        category_column="gauge_category", category_table="gauge_categories",
        id_column="gauge_id", library_table="gauges", library_label="检具库",
        slot_unit="类", fields=GAUGE_FIELDS, foreign_keys=GAUGE_FOREIGN_KEYS,
    ),
}

#: 四个旧数组键（读模型里的顺序）
SELECTION_ARRAY_KEYS = ("fixQ", "fixQC", "insp", "inspQ")

#: 选型现在落在哪几张表里（工具/校验脚本用；老表不在其中）
SELECTION_TABLE_NAMES = (FIXTURE_TABLE, GAUGE_TABLE)


class _SelectionRows(ProjectRows):
    """一类选型的项目级表：``(项目, 类别)`` 一行，``sort_order`` = 页面上的格子下标。"""

    kind = ""
    project_column = "project_id"
    parent_column = ""
    order_scope = "project"
    title_keys = ("name_snapshot", "id")
    #: "是否报价"只能是 0/1（夹具表不再有跨类 CHECK——列都不在同一张表里了）
    check_sql = "quoted IN (0,1)"
    #: 变更流水里两类选型共用一个实体名（夹具/检具靠草稿里的 ``kind`` 分列挂行，见 machining_changes）
    change_entity = "selection"

    def _note_change(self, action: str, *, row: dict[str, Any] | None = None,
                     label: str = "", record_id: str | None = None,
                     extra: dict[str, Any] | None = None) -> None:
        """交草稿时带上 ``kind``：流水表要按它决定挂 ``fixture_row_id`` 还是 ``gauge_row_id``。"""
        payload = dict(extra or {})
        payload.setdefault("kind", self.kind)
        super()._note_change(action, row=row, label=label, record_id=record_id, extra=payload)

    @property
    def spec(self) -> SelectionKind:
        return KIND_SPECS[self.kind]

    @property
    def array_keys(self) -> tuple[str, str]:
        return (self.spec.array, self.spec.quoted)

    def row_title(self, row: dict[str, Any] | None) -> str:
        """一条选型记录"叫什么"：``夹具第 3 格（两点式拉杆四轴机加夹具…）``。

        页面天然按"类别 + 格子下标"说话（不认行 id），所以流水里也这么写——
        光记一个行 id，人根本对不上是哪一格。
        """
        if not row:
            return ""
        name = str(row.get("name_snapshot") or row.get("legacy_key") or "").strip()
        name = name.split("|")[-1]
        slot = row.get("sort_order")
        what = (f"{self.spec.label}第 {int(slot) + 1} 格" if slot is not None
                else f"{self.spec.label}选型")
        return f"{what}（{name[: self.change_text_limit]}）" if name else what

    def slot_row(self, project_id: str, slot: int, *, db=None) -> Any:
        """按格子下标取行（不认行 id：页面天然只知道下标）。"""
        for row in self.rows(project_id, include_deleted=True, db=db):
            if int(row["sort_order"]) == int(slot):
                return row
        return None

    def slot_rows(self, project_id: str, *, include_deleted: bool = True) -> dict[int, Any]:
        """``{格子下标: 行}`` —— 列表接口一次拿全，不再每格查一次。"""
        return {int(row["sort_order"]): row
                for row in self.rows(project_id, include_deleted=include_deleted)}


class ProjectFixtures(_SelectionRows):
    """夹具选型（项目级）：一格 = 一个模具中心。"""

    kind = KIND_FIXTURE
    table = FIXTURE_TABLE
    table_label = "夹具选型"
    fields = FIXTURE_FIELDS
    foreign_keys = FIXTURE_FOREIGN_KEYS


class ProjectGauges(_SelectionRows):
    """检具选型（项目级）：一格 = 一个检具类别。"""

    kind = KIND_GAUGE
    table = GAUGE_TABLE
    table_label = "检具选型"
    fields = GAUGE_FIELDS
    foreign_keys = GAUGE_FOREIGN_KEYS


class ProjectSelections:
    """夹具选型 + 检具选型两张表的**门面**：调用方只跟这个对象打交道。

    ``list_typed`` 把两张表的行合并返回，并且每行补一个 ``kind`` —— 行的形状
    与老的多态表一模一样，所以读模型、回收站、变更流水那些消费方一行都不用改。
    """

    def __init__(self, connect, assets) -> None:
        self.connect = connect
        self.assets = assets
        self.subjects: dict[str, _SelectionRows] = {
            KIND_FIXTURE: ProjectFixtures(connect, assets),
            KIND_GAUGE: ProjectGauges(connect, assets),
        }

    # ---------------- 两张表 ----------------

    @property
    def fixtures(self) -> ProjectFixtures:
        return self.subjects[KIND_FIXTURE]           # type: ignore[return-value]

    @property
    def gauges(self) -> ProjectGauges:
        return self.subjects[KIND_GAUGE]             # type: ignore[return-value]

    @property
    def tables(self) -> tuple[str, ...]:
        return tuple(subject.table for subject in self.subjects.values())

    def subject(self, kind: str) -> _SelectionRows:
        """取某一类选型的表对象（``kind`` 不合法就 422，不是 500）。"""
        spec = spec_for(kind)
        return self.subjects[spec.key]

    def schema(self, db) -> None:
        for subject in self.subjects.values():
            subject.schema(db)

    # ---------------- 合并视图（行形状与老表一致） ----------------

    def rows(self, project_id: str, *, include_deleted: bool = False, db=None) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for key, subject in self.subjects.items():
            for row in subject.rows(project_id, include_deleted=include_deleted, db=db):
                item = dict(row)
                item["kind"] = key
                merged.append(item)
        return merged

    def list_typed(self, project_id: str, *, include_deleted: bool = False) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for key, subject in self.subjects.items():
            for row in subject.list_typed(project_id, include_deleted=include_deleted):
                item = dict(row)
                item["kind"] = key
                merged.append(item)
        return merged

    def count(self, project_id: str | None = None, *, include_deleted: bool = False) -> int:
        return sum(subject.count(project_id, include_deleted=include_deleted)
                   for subject in self.subjects.values())

    def slot_row(self, project_id: str, kind: str, slot: int, *, db=None) -> Any:
        return self.subject(kind).slot_row(project_id, slot, db=db)

    # ---------------- 写入（接口层用） ----------------

    def save_slot(self, project_id: str, kind: str, slot: int, payload: dict[str, Any], *,
                  categories: dict[str, Sequence[str]], library: dict[str, dict[str, dict[str, Any]]],
                  ) -> dict[str, Any]:
        """保存一格：选型（给库行 id 或旧串）或只改"是否报价"；行不存在就现建。"""
        subject = self.subject(kind)
        row = subject.slot_row(project_id, slot)
        current = subject._typed(row) if row is not None else None
        values = selection_payload(kind, int(slot), payload,
                                   categories=categories, library=library, current=current)
        if row is None:
            return subject.create(project_id, values, order=int(slot))
        return subject.update(row["id"], values)

    def clear_slot(self, project_id: str, kind: str, slot: int, *,
                   categories: dict[str, Sequence[str]]) -> Any:
        """清空一格：解绑 + 旧值清掉（行保留，"是否报价"的勾选也留着）。

        不做物理删除（口径 2）：清空前的值仍在版本快照里可查、可比。
        """
        subject = self.subject(kind)
        spec = subject.spec
        names = slot_categories(categories, kind)
        row = subject.slot_row(project_id, slot)
        if row is None:
            return None
        # 这一格本来就空（懒迁移会把每个格子都建好行）→ 什么都不用写。
        # 否则"点一下清空"会白记一个版本，"清空一个空格子"不该产生任何变更。
        current = subject._typed(row)
        if (not str(current.get("legacy_key") or "").strip()
                and not current.get(spec.id_column)
                and not str(current.get("name_snapshot") or "").strip()):
            return None
        values: dict[str, Any] = {
            spec.category_column: names[int(slot)] if int(slot) < len(names) else None,
            "legacy_key": "", spec.id_column: None,
            "name_snapshot": "", "price_snapshot": 0.0, "days_snapshot": 0.0,
        }
        if kind == KIND_GAUGE:
            values["drawing_snapshot"] = ""
            values["design_days_snapshot"] = 0.0
        return subject.update(row["id"], values)


def spec_for(kind: str) -> SelectionKind:
    spec = KIND_SPECS.get(str(kind or ""))
    if spec is None:
        raise HTTPException(422, f"选型类别只能是 {' 或 '.join(SELECTION_KINDS)}，收到：{kind}")
    return spec


def selection_table(kind: str) -> str:
    """这一类选型的表名（工具与接口用）。"""
    return spec_for(kind).table


def slot_categories(categories: dict[str, Sequence[str]], kind: str) -> list[str]:
    """某一类选型的**类别顺序**（就是页面上那串格子的顺序）。"""
    return [str(item) for item in (categories.get(kind) or [])]


def slot_index(categories: dict[str, Sequence[str]], kind: str, category: str) -> int | None:
    """类别名 → 格子下标；类别不在字典里返回 ``None``（这一格不再出现）。"""
    names = slot_categories(categories, kind)
    text = str(category or "")
    for index, name in enumerate(names):
        if name == text:
            return index
    return None


def compose_value(kind: str, row: dict[str, Any], library_row: dict[str, Any] | None) -> str:
    """把一行选型还原成旧字符串（``中心|名称`` / ``类别|名称|图号``）。

    名称、图号**优先取当前库行**（库里改名后选型跟着走，这是修 bug 的地方）；
    库行不在了（``ON DELETE SET NULL``）才用快照；都没有就退回 ``legacy_key`` 原样。
    """
    spec = KIND_SPECS[kind]
    category = str(row.get(spec.category_column) or "")
    if not category:
        return ""  # 类别被字典删了：这一格已经不是"某一类"，由调用方跳过
    if library_row:
        name = str(library_row.get("name") or "")
        if kind == KIND_GAUGE:
            return f"{category}|{name}|{str(library_row.get('drw') or '')}"
        return f"{category}|{name}"
    snapshot_name = str(row.get("name_snapshot") or "")
    if not snapshot_name:
        return str(row.get("legacy_key") or "")
    if kind == KIND_GAUGE:
        return f"{category}|{snapshot_name}|{str(row.get('drawing_snapshot') or '')}"
    return f"{category}|{snapshot_name}"


def compose_selection_arrays(
    rows: Sequence[dict[str, Any]],
    *,
    categories: dict[str, Sequence[str]],
    library: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, list[Any]]:
    """表行 → 四个旧数组（长度 = 当前类别数，未选型的格子是 ``""`` / ``1``）。

    ``rows`` 是两张表合并后的行（每行带 ``kind``），与老的多态表行同形状。
    """
    books = library or {}
    result: dict[str, list[Any]] = {}
    for kind, spec in KIND_SPECS.items():
        names = slot_categories(categories, kind)
        values: list[Any] = [""] * len(names)
        quoted: list[Any] = [1] * len(names)
        for row in rows:
            if str(row.get("kind") or "") != kind:
                continue
            index = slot_index(categories, kind, row.get(spec.category_column))
            if index is None:
                continue  # 类别已从字典里删掉：这一行留着当历史，但不再出现在报价表里
            bound = books.get(kind, {}).get(str(row.get(spec.id_column) or ""))
            values[index] = compose_value(kind, row, bound)
            quoted[index] = 1 if int(row.get("quoted") or 0) else 0
        result[spec.array] = values
        result[spec.quoted] = quoted
    return result


def legacy_selection_arrays(
    selections: "ProjectSelections | None",
    project_id: str,
    *,
    categories: dict[str, Sequence[str]],
    library: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, list[Any]] | None:
    """读模型里的四个数组；这个项目**两张表里一行都没有**时返回 ``None``（回退 ``extra_json``）。"""
    if selections is None:
        return None
    if not selections.count(project_id, include_deleted=True):
        return None
    return compose_selection_arrays(
        selections.list_typed(project_id, include_deleted=True),
        categories=categories,
        library=library,
    )


def selection_total(
    rows: Sequence[dict[str, Any]], *, library: dict[str, dict[str, dict[str, Any]]]
) -> dict[str, float]:
    """一类选型的报价合计（只算勾了"要报价"的格子，价格取当前库行、否则快照）。"""
    price = 0.0
    days = 0.0
    counted = 0
    for row in rows:
        if not int(row.get("quoted") or 0):
            continue
        spec = KIND_SPECS.get(str(row.get("kind") or ""))
        bound_id = str(row.get(spec.id_column) or "") if spec else ""
        bound = library.get(str(row.get("kind") or ""), {}).get(bound_id)
        price += float(bound.get("price") or 0) if bound else float(row.get("price_snapshot") or 0)
        days += float(bound.get("mc") or 0) if bound else float(row.get("days_snapshot") or 0)
        counted += 1
    return {"count": float(counted), "price": round(price, 4), "days": round(days, 4)}


# ---------------- 迁移：旧数组 / 老表 → 两张新表 ----------------

def _split_key(value: Any) -> tuple[str, str, str]:
    """旧元素 → ``(类别, 名称, 图号)``。"""
    parts = str(value or "").split("|")
    if len(parts) >= 3:
        return parts[0], parts[1], "|".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return "", "", ""


def resolve_category(
    kind: str,
    slot: int,
    legacy_key: str,
    categories: dict[str, Sequence[str]],
) -> str:
    """这一行到底属于哪个类别：**旧串自己的类别优先，它不在字典里才退回格子所在类别**。

    正常数据里两者永远一致（页面就是按格子类别拼的串）。不一致时以串里的类别为准，
    这样"表是唯一权威"之后读模型还能原样还给旧值；串里的类别已经不在字典里了，
    就只能按格子记，并在迁移报告里列出来让人看见。
    """
    names = slot_categories(categories, kind)
    parsed, _name, _drawing = _split_key(legacy_key)
    if parsed and parsed in names:
        return parsed
    return names[slot] if slot < len(names) else ""


def bind_library_row(
    kind: str,
    category: str,
    name: str,
    drawing: str,
    book: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    """按 ``(类别, 名称[, 图号])`` 在库里找行：唯一才绑，重名不猜。

    返回 ``(库行, 绑定方式)``；绑定方式是 ``unique`` / ``missing`` / ``ambiguous``。
    """
    wanted = [row for row in book.values()
              if str(row.get("center") if kind == KIND_FIXTURE else row.get("type") or "") == category
              and str(row.get("name") or "") == name]
    if kind == KIND_GAUGE and drawing:
        narrowed = [row for row in wanted if str(row.get("drw") or "") == drawing]
        if narrowed:
            wanted = narrowed
    if not wanted:
        return None, "missing"
    if len(wanted) > 1:
        return None, "ambiguous"
    return wanted[0], "unique"


def _snapshot_payload(kind: str, library_row: dict[str, Any] | None) -> dict[str, Any]:
    if not library_row:
        return {}
    payload = {
        "name_snapshot": str(library_row.get("name") or ""),
        "price_snapshot": float(library_row.get("price") or 0),
        "days_snapshot": float(library_row.get("mc") or 0),
    }
    if kind == KIND_GAUGE:
        payload["drawing_snapshot"] = str(library_row.get("drw") or "")
        payload["design_days_snapshot"] = float(library_row.get("dc") or 0)
    return payload


def split_selections(
    selections: ProjectSelections,
    project_id: str,
    general: dict[str, Any],
    *,
    categories: dict[str, Sequence[str]],
    library: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """旧 ``G`` 里那四个数组 → 两张新表。**每个格子都建行**（未选型的格子也要留）——

    因为"是否报价"（``fixQC``/``inspQ``）是按格子记的，只建选中的格子会把勾选状态弄丢。
    """
    report: dict[str, Any] = {"rows": 0, "bound": 0, "missing": 0, "ambiguous": 0,
                              "slots": 0, "details": [], "tables": {}}
    for kind, spec in KIND_SPECS.items():
        subject = selections.subject(kind)
        names = slot_categories(categories, kind)
        values = list(general.get(spec.array) or [])
        quotes = list(general.get(spec.quoted) or [])
        # 旧数组可能比类别短（新加的类别页面自己会补）：取两者的并集，一个格子都不漏
        for slot in range(max(len(names), len(values), len(quotes))):
            value = str(values[slot]) if slot < len(values) else ""
            quoted = 1 if (slot >= len(quotes) or quotes[slot]) else 0
            category = resolve_category(kind, slot, value, categories)
            payload: dict[str, Any] = {
                spec.category_column: category or None,
                "legacy_key": value,
                "quoted": quoted,
            }
            if value:
                parsed_category, name, drawing = _split_key(value)
                bound, how = bind_library_row(kind, parsed_category, name, drawing,
                                              library.get(kind) or {})
                if bound is not None:
                    payload[spec.id_column] = bound["id"]
                    payload.update(_snapshot_payload(kind, bound))
                    report["bound"] += 1
                    slot_name = names[slot] if slot < len(names) else "（没有这一格）"
                    if parsed_category != slot_name:
                        # 旧串里的类别与它所在格子不一致：以串为准（读模型才能原样还原），
                        # 但记下来让人看得见
                        report["details"].append(
                            f"{spec.label}第 {slot} 格：旧串类别「{parsed_category}」"
                            f"与格子的「{slot_name}」不一致，按串里的类别记"
                        )
                else:
                    report[how] += 1
                    # 库里没有（或重名）：不绑库，但把**旧串里的名称/图号存成快照**——
                    # 这样以后库同名重建（复活的规矩）还能按快照认回来，读模型也不依赖解析旧串。
                    # 只对"类别|名称[|图号]"这种规整的串存快照：不规整的串（老数据里直接写了个
                    # 名字）就只留 legacy_key，读模型原样还给旧值。
                    if parsed_category:
                        payload["name_snapshot"] = name
                        payload["drawing_snapshot"] = drawing
                    report["details"].append(
                        f"{spec.label}第 {slot} 格「{parsed_category}|{name}」在库里"
                        + ("找不到（多个同名候选）" if how == "ambiguous" else "找不到")
                        + "，只留旧值不绑库"
                    )
            subject.create(project_id, payload, strict=False, order=slot)
            report["rows"] += 1
            report["slots"] += 1
            report["tables"][spec.table] = report["tables"].get(spec.table, 0) + 1
    return report


def copy_legacy_rows(
    selections: ProjectSelections,
    project_id: str,
    legacy_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """老表 ``project_selections`` 的行 → 两张新表（**按 kind 分表，没有 kind 列就没有 kind 列**）。

    行上只留这类选型自己的列：老表里"不属于这一类的列"一律丢掉（它们在老表里本来就是 NULL）。
    """
    report: dict[str, Any] = {"rows": 0, "details": [], "tables": {}}
    for row in legacy_rows:
        kind = str(row.get("kind") or "")
        if kind not in KIND_SPECS:
            report["details"].append(f"跳过一行：kind={kind!r} 不认识")
            continue
        spec = KIND_SPECS[kind]
        subject = selections.subject(kind)
        payload = {
            spec.category_column: row.get(spec.category_column),
            "legacy_key": str(row.get("legacy_key") or ""),
            "quoted": 1 if int(row.get("quoted") or 0) else 0,
            spec.id_column: row.get(spec.id_column),
            "name_snapshot": str(row.get("name_snapshot") or ""),
            "price_snapshot": float(row.get("price_snapshot") or 0),
            "days_snapshot": float(row.get("days_snapshot") or 0),
        }
        if kind == KIND_GAUGE:
            payload["drawing_snapshot"] = str(row.get("drawing_snapshot") or "")
            payload["design_days_snapshot"] = float(row.get("design_days_snapshot") or 0)
        subject.create(project_id, payload, strict=False,
                       order=int(row.get("sort_order") or 0),
                       record_id=row.get("id"), created=row.get("created"))
        report["rows"] += 1
        report["tables"][spec.table] = report["tables"].get(spec.table, 0) + 1
    return report


def apply_selection_split(
    selections: ProjectSelections,
    project_id: str,
    general: dict[str, Any],
    *,
    categories: dict[str, Sequence[str]],
    library: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """幂等：这个项目两张表里已有任何一行（含逻辑删除）就跳过。"""
    existing = selections.count(project_id, include_deleted=True)
    if existing:
        return {"skipped": True, "rows": existing, "bound": 0, "missing": 0,
                "ambiguous": 0, "slots": 0, "details": [], "tables": {}}
    return split_selections(selections, project_id, general,
                            categories=categories, library=library)


# ---------------- 写入（接口层用） ----------------

def selection_payload(
    kind: str,
    slot: int,
    payload: dict[str, Any],
    *,
    categories: dict[str, Sequence[str]],
    library: dict[str, dict[str, dict[str, Any]]],
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """页面提交 → 表行载荷：``{"fixture_id": ...}`` / ``{"legacy_key": "中心|名称"}`` / ``{"quoted": 0}``。

    * 给了库行 id：校验它属于这一格的类别（防止把 1059 中心的夹具选到 1025 那一格），
      并**现抄一份快照**（口径 4：选型当时的价格/周期）；
    * 只给 ``legacy_key``：按"唯一才绑"的规矩找库行；
    * ``legacy_key`` 为空串 = 清空这一格（行保留，"是否报价"的勾选也留着）；
    * 只给 ``quoted``：只改勾选。
    """
    spec = spec_for(kind)
    names = slot_categories(categories, kind)
    if slot < 0 or slot >= len(names):
        raise HTTPException(422, f"{spec.label}格子下标超范围：{slot}（共 {len(names)} 格）")
    category = names[slot]
    result: dict[str, Any] = {spec.category_column: category}
    if "quoted" in payload:
        raw = payload.get("quoted")
        if isinstance(raw, bool):
            result["quoted"] = 1 if raw else 0
        elif raw in (0, 1, "0", "1"):
            result["quoted"] = int(raw)
        else:
            raise HTTPException(422, f"是否报价只能是 0 或 1，收到：{raw}")
    elif current is None:
        result["quoted"] = 1

    given_id = payload.get(spec.id_column)
    if given_id is None and "library_id" in payload:
        given_id = payload.get("library_id")
    book = library.get(kind) or {}
    if given_id is not None and str(given_id).strip():
        bound = book.get(str(given_id).strip())
        if bound is None:
            raise HTTPException(422, f"{spec.library_label}里没有这条记录：{given_id}")
        found_category = str(bound.get("center") if kind == KIND_FIXTURE else bound.get("type") or "")
        if found_category != category:
            raise HTTPException(
                422,
                f"这条{spec.label}属于「{found_category}」，不能选到「{category}」这一格",
            )
        result[spec.id_column] = bound["id"]
        result["legacy_key"] = compose_value(
            kind, {spec.category_column: category, "name_snapshot": bound.get("name")}, bound
        )
        result.update(_snapshot_payload(kind, bound))
        return result

    if "legacy_key" in payload:
        value = str(payload.get("legacy_key") or "")
        result[spec.category_column] = resolve_category(kind, slot, value, categories)
        result["legacy_key"] = value
        if not value:
            # 清空：解绑、快照清零（历史仍在版本里）
            result[spec.id_column] = None
            result.update({"name_snapshot": "", "drawing_snapshot": "",
                           "price_snapshot": 0.0, "days_snapshot": 0.0,
                           "design_days_snapshot": 0.0})
            return result
        parsed_category, name, drawing = _split_key(value)
        bound, how = bind_library_row(kind, parsed_category or category, name, drawing, book)
        if bound is None:
            if how == "ambiguous":
                raise HTTPException(
                    422, f"「{name}」在{spec.library_label}里有多条同名记录，请直接选具体的行"
                )
            # 库里没有：照旧存字符串（旧客户端/历史值上来的情况），不猜、不报错
            result[spec.id_column] = None
            result.update({"name_snapshot": name, "drawing_snapshot": drawing})
            return result
        result[spec.id_column] = bound["id"]
        result.update(_snapshot_payload(kind, bound))
        return result

    return result


def _slot_entries(
    selections: "ProjectSelections | None",
    project_id: str,
    kind: str,
    *,
    categories: dict[str, Sequence[str]],
    library: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """某一类选型的格子清单（页面按格子读写，所以坐标是"类别 + 下标"）。"""
    spec = KIND_SPECS[kind]
    names = slot_categories(categories, kind)
    rows = selections.subject(kind).list_typed(project_id, include_deleted=True) if selections else []
    by_slot = {int(row["sort_order"]): row for row in rows}
    arrays = compose_selection_arrays(
        [{**row, "kind": kind} for row in rows], categories=categories, library=library)
    entries: list[dict[str, Any]] = []
    for slot, category in enumerate(names):
        row = by_slot.get(slot)
        bound_id = str(row.get(spec.id_column) or "") if row else ""
        bound = library.get(kind, {}).get(bound_id)
        entries.append({
            "slot": slot,
            "category": category,
            "id": (row or {}).get("id"),
            "kind": kind,
            spec.id_column: bound_id or None,
            "legacy_key": (row or {}).get("legacy_key", ""),
            "quoted": arrays[spec.quoted][slot] if slot < len(arrays[spec.quoted]) else 1,
            "value": arrays[spec.array][slot] if slot < len(arrays[spec.array]) else "",
            "bound": bool(bound),
            "price": float(bound.get("price") or 0) if bound else float((row or {}).get("price_snapshot") or 0),
            "days": float(bound.get("mc") or 0) if bound else float((row or {}).get("days_snapshot") or 0),
            "stale": bool(row) and not bound and bool(row.get("name_snapshot")),
        })
    return entries


def selection_listing(
    selections: "ProjectSelections | None",
    project_id: str,
    kind: str,
    *,
    categories: dict[str, Sequence[str]],
    library: dict[str, dict[str, dict[str, Any]]],
    enabled: bool,
) -> dict[str, Any]:
    """**一类**选型的清单：类别顺序 + 每格一行（页面按格子读写）。"""
    spec = spec_for(kind)
    names = slot_categories(categories, kind)
    if not enabled or selections is None:
        return {"enabled": False, "kind": kind, "label": spec.label, "table": spec.table,
                "categories": names, "slots": [], "arrays": {},
                "fields": [field.describe() for field in spec.fields], "rows": []}
    rows = selections.subject(kind).list_typed(project_id, include_deleted=True)
    arrays = compose_selection_arrays([{**row, "kind": kind} for row in rows],
                                      categories=categories, library=library)
    slots = _slot_entries(selections, project_id, kind, categories=categories, library=library)
    quoted = [entry for entry in slots if entry["quoted"]]
    return {
        "enabled": True,
        "kind": kind,
        "label": spec.label,
        "table": spec.table,
        "slot_unit": spec.slot_unit,
        "categories": names,
        "slots": slots,
        "arrays": arrays,
        "fields": [field.describe() for field in spec.fields],
        "rows": rows,
        "total": {
            "slots": len(slots),
            "selected": sum(1 for entry in slots if entry["value"]),
            "quoted": len(quoted),
            "price": round(sum(entry["price"] for entry in quoted), 4),
        },
        "updated": stamp(),
    }


def selections_listing(
    selections: "ProjectSelections | None",
    project_id: str,
    *,
    categories: dict[str, Sequence[str]],
    library: dict[str, dict[str, dict[str, Any]]],
    enabled: bool,
) -> dict[str, Any]:
    """**两类**选型一起给（老接口的返回形状：``slots`` 按 kind 分组）。

    新接口走 :func:`selection_listing`（一次一类），这个函数留给"一屏看全"的调用方。
    """
    names = {kind: slot_categories(categories, kind) for kind in SELECTION_KINDS}
    if not enabled or selections is None:
        return {"enabled": False, "slots": {}, "categories": names,
                "fields": [field.describe() for field in SELECTION_FIELDS], "rows": []}
    rows = selections.list_typed(project_id, include_deleted=True)
    arrays = compose_selection_arrays(rows, categories=categories, library=library)
    return {
        "enabled": True,
        "slots": {kind: _slot_entries(selections, project_id, kind,
                                      categories=categories, library=library)
                  for kind in SELECTION_KINDS},
        "arrays": arrays,
        "categories": names,
        "tables": {kind: KIND_SPECS[kind].table for kind in SELECTION_KINDS},
        "fields": [field.describe() for field in SELECTION_FIELDS],
        "rows": rows,
        "updated": stamp(),
    }
