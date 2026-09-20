"""检具库：按检具类别维护检具，可按产品尺寸/检具尺寸检索选型报价。

页面列（分组卡片，按检具类别）：
类别 | 图片 | 检具名称 | 检具图号 | 产品尺寸(mm) | 检具尺寸(mm) | 价格(万¥) | 设计周期(天) | 制造周期(天)

两类数据落在两张表里：

* ``gauge_categories``  检具类别字典（类别即中文名，主键）
* ``gauges``            检具本体，``type`` 是指向字典表的外键

项目侧的选择键是 ``"检具类别|名称|图号"``（``G.insp``），成本表据此回查
``price``（万元·未税）/``dc``/``mc``，因此排序/删除检具不会让项目数据错位。
"""

from __future__ import annotations

from typing import Any

from ..core.utils import stamp
from ..db.library import (
    AttachmentSpec,
    LibraryField,
    NameDictionary,
    TypedLibrary,
)

PHOTO_KIND = "gauge_photo"

GAUGE_FIELDS: tuple[LibraryField, ...] = (
    LibraryField(
        "type", "category", "choice", "", "检具类别",
        limit=60, references="gauge_categories(name)",
    ),
    LibraryField("name", "name", "text", "", "检具名称", limit=200),
    LibraryField("drw", "drawing", "text", "", "检具图号", limit=80),
    LibraryField("prdSize", "product_size", "text", "", "产品尺寸", "mm", limit=80),
    LibraryField("inspSize", "inspection_size", "text", "", "检具尺寸", "mm", limit=80),
    LibraryField("price", "price", "real", 0.0, "价格", "万¥", maximum=10_000),
    LibraryField("dc", "design_days", "int", 0, "设计周期", "天", maximum=3650),
    LibraryField("mc", "process_days", "int", 0, "制造周期", "天", maximum=3650),
)

GAUGE_ATTACHMENTS: tuple[AttachmentSpec, ...] = (
    AttachmentSpec(
        slot="photo",
        kind=PHOTO_KIND,
        column="photo_id",
        legacy_key="img",
        value_keys=("img", "photo"),
        mime_key="img_mime",
        default_mime="image/jpeg",
    ),
)

GAUGE_COLUMNS: tuple[str, ...] = tuple(field.column for field in GAUGE_FIELDS)
LEGACY_KEYS = tuple(field.key for field in GAUGE_FIELDS) + ("img",)

#: 内置检具类别（首次建库/迁移时灌进字典表，之后以表为准）
GAUGE_CATEGORY_SEED: tuple[str, ...] = (
    "毛坯检具",
    "成品机械检具",
    "成品总成检具",
    "成品电子检具",
    "测量支架",
)


def field_headers(dictionaries: "GaugeCategories | None" = None) -> list[dict[str, Any]]:
    headers = [field.describe() for field in GAUGE_FIELDS]
    if dictionaries is None:
        return headers
    by_key = {item["key"]: item for item in headers}
    by_key["type"]["choices"] = [
        {"value": item["name"], "label": item["label"], "builtin": item["builtin"]}
        for item in dictionaries.names()
    ]
    return headers


def clean_values(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    return GaugeLibrary.clean_values(payload, partial=partial)


class GaugeCategories(NameDictionary):
    table = "gauge_categories"
    table_label = "检具类别"
    reference_table = "gauges"
    reference_column = "category"  # 本体表里的列名（JSON 键仍是 `type`）
    seed = GAUGE_CATEGORY_SEED


class GaugeLibrary(TypedLibrary):
    table = "gauges"
    table_label = "检具"
    fields = GAUGE_FIELDS
    attachments = GAUGE_ATTACHMENTS
    supports_fallback = False
    display_keys = ("name", "drw")
    indexes = (("category", ("category",)), ("drawing", ("drawing",)))

    def __init__(self, connect, assets, categories: GaugeCategories | None = None):
        super().__init__(connect, assets)
        self.categories = categories or GaugeCategories(connect)

    # ---------------- 字典 ----------------

    def validate_values(self, values: dict[str, Any], payload: dict[str, Any]) -> None:
        self.categories.require(str(values.get("category") or "").strip())

    def prepare_rows(self, db, rows: list[dict[str, Any]]) -> None:
        """灌数据前：把行里用到的检具类别补进字典表（旧数据里未知类别自动补录）。"""
        self.categories.register(
            [str(row.get("type") or "").strip() for row in rows], db=db
        )

    def delete_by_category(self, db, category: str, *, by: str = "", reason: str = "") -> int:
        """把某个类别下的全部检具**逻辑删除**（口径 2：附件保留、回收站可恢复），返回条数。"""
        rows = db.execute(
            "SELECT id FROM gauges WHERE category=? AND deleted_at IS NULL", (category,)
        ).fetchall()
        now = stamp()
        for row in rows:
            db.execute(
                "UPDATE gauges SET deleted_at=?,deleted_by=?,deleted_reason=?,updated=? WHERE id=?",
                (now, by or "admin", reason or f"随检具类别「{category}」一起删除", now, row["id"]),
            )
        return len(rows)

    def reference_counts(self, db=None) -> dict[str, int]:
        return self.categories.usage(db=db)

    def natural_key(self, values: dict[str, Any]) -> tuple:
        # 旧整体保存按 (类别, 名称, 图号) 匹配，与项目里的选择键一致。
        return (values.get("category", ""), values.get("name", ""), values.get("drawing", ""))

    def used_names(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for row in self.rows():
            grouped.setdefault(row["category"], []).append(row["name"])
        return grouped
