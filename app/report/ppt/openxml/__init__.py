# -*- coding: utf-8 -*-
"""Open XML zip-level package editing for template-driven generation."""

from .image_binding import ImageBindingError, ImageBindingFiller, decode_image_bytes
from .package_editor import OoxmlPackage, OoxmlPackageError, open_package
from .placeholder_scanner import PlaceholderMatch, PlaceholderScanner, SlideScan, TemplateScan
from .shape_binding import (
    ShapeBindingError,
    find_shape,
    set_shape_text,
    set_table_cell,
    set_table_rows,
)
from .shape_inventory import (
    ShapeInfo,
    ShapeInventoryScanner,
    SlideShapeInventory,
    TemplateShapeInventory,
)
from .slide_repeater import SlideRepeaterError, clone_slide, rebuild_presentation
from .text_binding import (
    FillStats,
    PathResolver,
    PlaceholderResolutionError,
    TextBindingFiller,
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
