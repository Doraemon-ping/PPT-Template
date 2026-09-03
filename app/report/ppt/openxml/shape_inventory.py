# -*- coding: utf-8 -*-
"""Inspect every shape of a template at the zip level.

Gives the visual binding editor a precise object map: each shape's name, kind,
text, absolute geometry in EMU (group offsets resolved) and, for tables, every
cell's rectangle and text. Positions come straight from the template XML, so a
clickable overlay drawn from this data matches the real slide layout exactly.
"""
from dataclasses import dataclass, field
from typing import List, Tuple

from lxml import etree

from .package_editor import OoxmlPackage
from .partial_text import full_text

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}

_SHAPE_TAGS = (
    "{%s}sp" % NS["p"],
    "{%s}pic" % NS["p"],
    "{%s}graphicFrame" % NS["p"],
    "{%s}grpSp" % NS["p"],
)


@dataclass(frozen=True)
class CellInfo:
    row: int
    column: int
    left: int
    top: int
    width: int
    height: int
    text: str
    full_text: str = ''

    def to_dict(self) -> dict:
        return {
            "row": self.row,
            "column": self.column,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "text": self.text[:120],
            "full_text": self.full_text,
        }


@dataclass(frozen=True)
class ShapeInfo:
    shape_id: int
    shape_name: str
    kind: str  # text | picture | table | chart | group | graphic | shape
    has_text: bool
    text: str
    placeholder_count: int
    placeholder_paths: tuple
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    rows: int = 0
    cols: int = 0
    cells: tuple = ()
    z_order: int = 0
    full_text: str = ''

    def to_dict(self) -> dict:
        return {
            "shape_id": self.shape_id,
            "shape_name": self.shape_name,
            "kind": self.kind,
            "has_text": self.has_text,
            "text": self.text[:300],
            "full_text": self.full_text,
            "placeholder_count": self.placeholder_count,
            "placeholder_paths": list(self.placeholder_paths),
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "rows": self.rows,
            "cols": self.cols,
            "cells": [cell.to_dict() for cell in self.cells],
            "z_order": self.z_order,
        }


@dataclass(frozen=True)
class SlideShapeInventory:
    slide_index: int
    part_name: str
    shapes: tuple

    def to_dict(self) -> dict:
        return {
            "slide_index": self.slide_index,
            "part_name": self.part_name,
            "shapes": [shape.to_dict() for shape in self.shapes],
        }


@dataclass(frozen=True)
class TemplateShapeInventory:
    slide_count: int
    slide_width: int = 0
    slide_height: int = 0
    slides: tuple = ()

    def to_dict(self) -> dict:
        return {
            "slide_count": self.slide_count,
            "slide_width": self.slide_width,
            "slide_height": self.slide_height,
            "slides": [slide.to_dict() for slide in self.slides],
        }


class ShapeInventoryScanner:
    """Read-only shape inventory with absolute geometry; never modifies parts."""

    def scan(self, source) -> TemplateShapeInventory:
        package = OoxmlPackage(source)
        slide_width, slide_height = self._slide_size(package)
        inventories = []
        for slide_index, part_name in sorted(package.slide_parts().items()):
            root = etree.fromstring(package.read(part_name))
            shapes = self._scan_slide(root)
            inventories.append(SlideShapeInventory(
                slide_index=slide_index,
                part_name=part_name,
                shapes=tuple(shapes),
            ))
        return TemplateShapeInventory(
            slide_count=len(inventories),
            slide_width=slide_width,
            slide_height=slide_height,
            slides=tuple(inventories),
        )

    @staticmethod
    def _slide_size(package: OoxmlPackage) -> Tuple[int, int]:
        if not package.has_part("ppt/presentation.xml"):
            return 12192000, 6858000
        root = etree.fromstring(package.read("ppt/presentation.xml"))
        sld_sz = root.find("{%s}sldSz" % NS["p"])
        if sld_sz is None:
            return 12192000, 6858000
        try:
            return int(sld_sz.get("cx")), int(sld_sz.get("cy"))
        except (TypeError, ValueError):
            return 12192000, 6858000

    def _scan_slide(self, root) -> List[ShapeInfo]:
        result: List[ShapeInfo] = []
        z_order = 0
        for element in root.iter():
            if element.tag not in _SHAPE_TAGS:
                continue
            # OLE graphicFrames contain an internal fallback p:pic. Expose the
            # OLE as one selectable object, not as two overlapping objects.
            if element.tag == "{%s}pic" % NS["p"] and any(
                ancestor.tag == "{%s}graphicFrame" % NS["p"] for ancestor in element.iterancestors()
            ):
                continue
            z_order += 1
            name = self._name_of(element)
            kind = self._kind_of(element)
            left, top, width, height = self._absolute_box(element)
            text = self._all_text(element)
            rows, cols, cells = self._table_geometry(element, left, top)
            placeholders = self._placeholders(element)
            result.append(ShapeInfo(
                shape_id=self._id_of(element),
                shape_name=name,
                kind=kind,
                has_text=bool(text.strip()),
                text=text.strip(),
                full_text=full_text(element),
                placeholder_count=len(placeholders),
                placeholder_paths=tuple(dict.fromkeys(placeholders)),
                left=left,
                top=top,
                width=width,
                height=height,
                rows=rows,
                cols=cols,
                cells=tuple(cells),
                z_order=z_order,
            ))
        return result

    # ------------------------------------------------------------- geometry
    def _absolute_box(self, element) -> Tuple[int, int, int, int]:
        """EMU box of a shape, adding group ancestor offsets."""
        xfrm = element.find(".//{%s}xfrm" % NS["a"])
        if xfrm is None:
            xfrm = element.find(".//{%s}xfrm" % NS["p"])  # graphicFrame 用 p:xfrm
        left = top = width = height = 0
        if xfrm is not None:
            off = xfrm.find("{%s}off" % NS["a"])
            ext = xfrm.find("{%s}ext" % NS["a"])
            if off is not None:
                try:
                    left = int(off.get("x") or 0)
                    top = int(off.get("y") or 0)
                except (TypeError, ValueError):
                    pass
            if ext is not None:
                try:
                    width = int(ext.get("cx") or 0)
                    height = int(ext.get("cy") or 0)
                except (TypeError, ValueError):
                    pass
        # 累加组合对象祖先的偏移（组内对象坐标是相对组的）
        parent = element.getparent()
        while parent is not None:
            if parent.tag == "{%s}grpSp" % NS["p"]:
                gxfrm = parent.find(".//{%s}xfrm" % NS["a"])
                if gxfrm is None:
                    gxfrm = parent.find(".//{%s}xfrm" % NS["p"])
                off = gxfrm.find("{%s}off" % NS["a"]) if gxfrm is not None else None
                if off is not None:
                    try:
                        left += int(off.get("x") or 0)
                        top += int(off.get("y") or 0)
                    except (TypeError, ValueError):
                        pass
            parent = parent.getparent()
        return left, top, width, height

    @staticmethod
    def _table_geometry(element, shape_left: int, shape_top: int):
        tables = element.xpath(".//a:tbl", namespaces=NS)
        if not tables:
            return 0, 0, ()
        table = tables[0]
        rows_el = table.xpath("./a:tr", namespaces=NS)
        grid = table.xpath("./a:tblGrid/a:gridCol", namespaces=NS)
        col_widths = []
        for col in grid:
            try:
                col_widths.append(int(col.get("w") or 0))
            except (TypeError, ValueError):
                col_widths.append(0)
        row_heights = []
        for tr in rows_el:
            try:
                row_heights.append(int(tr.get("h") or 0))
            except (TypeError, ValueError):
                row_heights.append(0)
        cells = []
        y = 0
        for row_index, tr in enumerate(rows_el):
            tcs = tr.xpath("./a:tc", namespaces=NS)
            x = 0
            for col_index, tc in enumerate(tcs):
                cell_width = col_widths[col_index] if col_index < len(col_widths) else 0
                cell_height = row_heights[row_index] if row_index < len(row_heights) else 0
                texts = tc.xpath(".//a:t/text()", namespaces=NS)
                cells.append(CellInfo(
                    row=row_index,
                    column=col_index,
                    left=shape_left + x,
                    top=shape_top + y,
                    width=cell_width,
                    height=cell_height,
                    text="".join(texts).strip(),
                    full_text=full_text(tc),
                ))
                x += cell_width
            y += row_heights[row_index] if row_index < len(row_heights) else 0
        return len(rows_el), len(col_widths), cells

    # ---------------------------------------------------------------- text
    @staticmethod
    def _all_text(element) -> str:
        return "".join(element.xpath(".//a:t/text()", namespaces=NS))

    @staticmethod
    def _placeholders(element):
        import re

        found = []
        for text in element.xpath(".//a:t/text()", namespaces=NS):
            found.extend(re.findall(r"\{([A-Za-z_][A-Za-z0-9_.\[\]-]*)\}", text or ""))
        return found

    @staticmethod
    def _name_of(element) -> str:
        cNvPr = element.find(".//{%s}cNvPr" % NS["p"])
        return cNvPr.get("name", "") if cNvPr is not None else ""

    @staticmethod
    def _id_of(element) -> int:
        cNvPr = element.find(".//{%s}cNvPr" % NS["p"])
        try:
            return int(cNvPr.get("id", "0")) if cNvPr is not None else 0
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _kind_of(element) -> str:
        tag = etree.QName(element).localname
        if tag == "pic":
            return "picture"
        if tag == "grpSp":
            return "group"
        if tag == "graphicFrame":
            data = element.find(".//{%s}graphicData" % NS["a"])
            uri = data.get("uri", "") if data is not None else ""
            if "table" in uri:
                return "table"
            if "chart" in uri:
                return "chart"
            if "ole" in uri or element.find(".//{%s}oleObj" % NS["p"]) is not None:
                return "ole"
            return "graphic"
        if element.find(".//{%s}txBody" % NS["p"]) is not None:
            return "text"
        return "shape"
