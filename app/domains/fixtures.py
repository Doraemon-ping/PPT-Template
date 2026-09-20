"""夹具库：按模具中心分类维护夹具，报价在「夹具报价选型」里勾选引用。

页面列（分组卡片，按模具中心）：
模具中心 | 图片 | 名称 | 价格(¥) | 制造周期(天) | 备注

两类数据落在两张表里：

* ``fixture_centers``  模具中心字典（类别即中文名，主键）
* ``fixtures``         夹具本体，``center`` 是指向字典表的外键

项目侧的选择键是 ``"模具中心|夹具名称"``（``G.fixQ``），成本表据此回查 ``price``，
所以类别与夹具都**按名称**被引用、不存下标：排序/删除夹具不会让项目数据错位。
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

PHOTO_KIND = "fixture_photo"

FIXTURE_FIELDS: tuple[LibraryField, ...] = (
    LibraryField(
        "center", "center", "choice", "", "模具中心",
        limit=60, references="fixture_centers(name)",
    ),
    LibraryField("name", "name", "text", "", "名称", limit=200),
    LibraryField("price", "price", "real", 0.0, "价格", "¥", maximum=10_000_000),
    LibraryField("mc", "process_days", "int", 0, "制造周期", "天", maximum=3650),
    LibraryField("rmk", "remark", "text", "", "备注", limit=300),
)

FIXTURE_ATTACHMENTS: tuple[AttachmentSpec, ...] = (
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

FIXTURE_COLUMNS: tuple[str, ...] = tuple(field.column for field in FIXTURE_FIELDS)
LEGACY_KEYS = tuple(field.key for field in FIXTURE_FIELDS) + ("img",)

#: 内置模具中心（首次建库/迁移时灌进字典表，之后以表为准）
FIXTURE_CENTER_SEED: tuple[str, ...] = (
    "1025减震模具中心",
    "1059轻合金模具中心",
    "1929底盘模具中心",
    "8107结构件模具中心",
)


def field_headers(dictionaries: "FixtureCenters | None" = None) -> list[dict[str, Any]]:
    headers = [field.describe() for field in FIXTURE_FIELDS]
    if dictionaries is None:
        return headers
    by_key = {item["key"]: item for item in headers}
    by_key["center"]["choices"] = [
        {"value": item["name"], "label": item["label"], "builtin": item["builtin"]}
        for item in dictionaries.names()
    ]
    return headers


def clean_values(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    return FixtureLibrary.clean_values(payload, partial=partial)


class FixtureCenters(NameDictionary):
    table = "fixture_centers"
    table_label = "模具中心"
    reference_table = "fixtures"
    reference_column = "center"
    seed = FIXTURE_CENTER_SEED


class FixtureLibrary(TypedLibrary):
    table = "fixtures"
    table_label = "夹具"
    fields = FIXTURE_FIELDS
    attachments = FIXTURE_ATTACHMENTS
    supports_fallback = False
    display_keys = ("name",)
    indexes = (("center", ("center",)),)

    def __init__(self, connect, assets, centers: FixtureCenters | None = None):
        super().__init__(connect, assets)
        self.centers = centers or FixtureCenters(connect)

    # ---------------- 字典 ----------------

    def validate_values(self, values: dict[str, Any], payload: dict[str, Any]) -> None:
        self.centers.require(str(values.get("center") or "").strip())

    def prepare_rows(self, db, rows: list[dict[str, Any]]) -> None:
        """灌数据（种子 / 迁移 / 旧整体保存）前：把行里用到的模具中心补进字典表。"""
        names: list[str] = []
        for row in rows:
            center = str(row.get("center") or "").strip()
            names.append(center)
        self.centers.register(names, db=db)

    def delete_by_center(self, db, center: str, *, by: str = "", reason: str = "") -> int:
        """把某个模具中心下的全部夹具**逻辑删除**（口径 2：附件保留、回收站可恢复），返回条数。"""
        rows = db.execute(
            "SELECT id FROM fixtures WHERE center=? AND deleted_at IS NULL", (center,)
        ).fetchall()
        now = stamp()
        for row in rows:
            db.execute(
                "UPDATE fixtures SET deleted_at=?,deleted_by=?,deleted_reason=?,updated=? WHERE id=?",
                (now, by or "admin", reason or f"随模具中心「{center}」一起删除", now, row["id"]),
            )
        return len(rows)

    def reference_counts(self, db=None) -> dict[str, int]:
        return self.centers.usage(db=db)

    def natural_key(self, values: dict[str, Any]) -> tuple:
        # 旧整体保存按 (模具中心, 名称) 匹配，保持 id 稳定。
        return (values.get("center", ""), values.get("name", ""))

    def used_names(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for row in self.rows():
            grouped.setdefault(row["center"], []).append(row["name"])
        return grouped
