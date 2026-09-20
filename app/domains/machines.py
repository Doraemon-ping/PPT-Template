"""设备数据库 / Machine DB：字段登记表 + 行级读写。

页面契约就是唯一事实来源：``MACHINE_FIELDS`` 与设备表头一一对应，同时决定建表
SQL、JSON 视图、校验和旧数据迁移 —— 改一列只改一处，不再有 ``payload_json`` 大
字段需要反解。

真正的读写引擎是 ``app.db.library.TypedLibrary``；本模块只声明"设备库长什么样"。
设备特有之处：兜底机型（``is_fallback``）、按 ``pr[].mid`` 的解析，以及删除前的
项目引用检查（在 ``app.services.store`` 的 store 里）。
"""

from __future__ import annotations

from typing import Any

from ..db.library import AttachmentSpec, LibraryField, TypedLibrary

PHOTO_KIND = "machine_photo"
DOC_KIND = "machine_doc"

# 与前端页面表头一一对应：图片 Photo / 品牌 Brand / 型号 Model / XYZ行程 mm /
# 定位精度 mm / 重复定位精度 mm / 快移 Rapid m/min / 换刀 TC s / 转速 RPM /
# 刀库 ATC / 价格(万¥) / 说明 Desc（图片与资料是 assets 附件，不是列）。
MACHINE_FIELDS: tuple[LibraryField, ...] = (
    LibraryField("brand", "brand", "text", "", "品牌 Brand", limit=120),
    LibraryField("model", "model", "text", "", "型号 Model", limit=120),
    LibraryField("xyz", "xyz", "text", "", "XYZ行程", "mm", 60),
    LibraryField("pa", "pos_acc", "text", "", "定位精度", "mm", 60),
    LibraryField("rpa", "rep_acc", "text", "", "重复定位精度", "mm", 60),
    LibraryField("rapid", "rapid", "real", 30.0, "快移 Rapid", "m/min", maximum=1000),
    LibraryField("tc", "tool_change", "real", 2.0, "换刀 TC", "s", maximum=3600),
    LibraryField("spm", "spindle_rpm", "real", 8000.0, "转速", "RPM", maximum=200000),
    LibraryField("atc", "atc", "int", 20, "刀库 ATC", maximum=2000),
    LibraryField("price", "price", "real", 0.0, "价格", "万¥", maximum=1_000_000),
    LibraryField("desc", "remark", "text", "", "说明 Desc", limit=500),
)

MACHINE_ATTACHMENTS: tuple[AttachmentSpec, ...] = (
    AttachmentSpec(
        slot="photo",
        kind=PHOTO_KIND,
        column="photo_id",
        legacy_key="img",
        value_keys=("photo", "img"),
        mime_key="photo_mime",
        default_mime="image/jpeg",
    ),
    AttachmentSpec(
        slot="doc",
        kind=DOC_KIND,
        column="doc_id",
        legacy_key="doc",
        download=True,
        name_column="doc_name",
        name_key="docName",
        value_keys=("doc", "doc_file"),
        mime_key="doc_mime",
    ),
)

MACHINE_COLUMNS: tuple[str, ...] = tuple(field.column for field in MACHINE_FIELDS)
FIELD_BY_KEY = {field.key: field for field in MACHINE_FIELDS}
FIELD_BY_COLUMN = {field.column: field for field in MACHINE_FIELDS}
LEGACY_KEYS = tuple(field.key for field in MACHINE_FIELDS)


def field_headers() -> list[dict[str, Any]]:
    """页面/文档用的字段说明（由登记表推导）。"""
    return [field.describe() for field in MACHINE_FIELDS]


def clean_values(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """兼容旧调用名：校验一行设备输入。"""
    return MachineLibrary.clean_values(payload, partial=partial)


def resolve_machine_ref(index: Any, machine_ids: list[str], fallback: str) -> str:
    """旧下标引用 ``pr[].mi`` → 稳定设备 id；下标越界或不是数字就用兜底机型。

    这是**历史包袱的翻译器**：早期工序里记的是"设备库第几行"（``mi`` 下标），
    库一排序引用就错位了，所以后来改成记 id（``mid``）。老库搬迁时靠它把下标记法
    一次性翻成 id（见 ``app/services/migrations.py`` 的 ``rewrite_process_machine_refs``），
    读模型投影也用它兜住还没翻过来的老数据。
    """
    try:
        position = int(index)
    except (TypeError, ValueError):
        position = -1
    if 0 <= position < len(machine_ids):
        return machine_ids[position]
    return fallback


class MachineLibrary(TypedLibrary):
    table = "machines"
    table_label = "设备"
    fields = MACHINE_FIELDS
    attachments = MACHINE_ATTACHMENTS
    supports_fallback = True
    display_keys = ("brand", "model")
    indexes = (("brand_model", ("brand", "model")),)

    def natural_key(self, values: dict[str, Any]) -> tuple:
        return (values.get("brand", ""), values.get("model", ""))

    def resolve_machine(self, machine_id: str | None = None, index: int | None = None) -> dict[str, Any] | None:
        return self.resolve(machine_id, index)
