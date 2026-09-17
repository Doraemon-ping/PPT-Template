# -*- coding: utf-8 -*-
"""PPT 生成边界（本分支仅保留 OOXML 绑定层）。

三服务拆分后：
- 压铸表单服务（hpdc 分支）只用 OOXML 包编辑做模板导入校验与表单平台导出检查；
- 通用 PPT 工作台（workbench 分支）保留完整引擎（deck / template_engine / scheme / registry）。
"""

from .openxml import (  # noqa: F401
    FillStats,
    ImageBindingError,
    ImageBindingFiller,
    OoxmlPackage,
    OoxmlPackageError,
    PathResolver,
    PlaceholderMatch,
    PlaceholderResolutionError,
    PlaceholderScanner,
    ShapeBindingError,
    ShapeInfo,
    ShapeInventoryScanner,
    SlideRepeaterError,
    SlideScan,
    SlideShapeInventory,
    TemplateScan,
    TemplateShapeInventory,
    TextBindingFiller,
    clone_slide,
    decode_image_bytes,
    find_shape,
    open_package,
    rebuild_presentation,
    set_shape_text,
    set_table_cell,
    set_table_rows,
)

__all__ = [
    "FillStats",
    "ImageBindingError",
    "ImageBindingFiller",
    "OoxmlPackage",
    "OoxmlPackageError",
    "PathResolver",
    "PlaceholderMatch",
    "PlaceholderResolutionError",
    "PlaceholderScanner",
    "ShapeBindingError",
    "ShapeInfo",
    "ShapeInventoryScanner",
    "SlideRepeaterError",
    "SlideScan",
    "SlideShapeInventory",
    "TemplateScan",
    "TemplateShapeInventory",
    "TextBindingFiller",
    "clone_slide",
    "decode_image_bytes",
    "find_shape",
    "open_package",
    "rebuild_presentation",
    "set_shape_text",
    "set_table_cell",
    "set_table_rows",
]
