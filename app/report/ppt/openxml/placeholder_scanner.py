# -*- coding: utf-8 -*-
"""Scan template slide XML for ``{path.to.data}`` placeholders.

Follows the pptx-template convention: the placeholder inside the text is the
binding itself. The scanner reports every placeholder found, the PowerPoint
shape that contains it, and the slide index, so editors can locate objects and
the generator can fill them without any manifest bookkeeping.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lxml import etree

from .package_editor import OoxmlPackage, OoxmlPackageError

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.\[\]-]*)\}")

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


@dataclass(frozen=True)
class PlaceholderMatch:
    slide_index: int
    shape_name: str
    path: str
    text: str
    occurrences: int


@dataclass(frozen=True)
class SlideScan:
    slide_index: int
    part_name: str
    placeholders: tuple = ()

    @property
    def paths(self):
        return tuple(sorted({item.path for item in self.placeholders}))


@dataclass(frozen=True)
class TemplateScan:
    slide_count: int
    slides: tuple
    placeholder_paths: tuple = ()
    placeholder_count: int = 0
    media_part_count: int = 0
    notes_slide_count: int = 0
    ole_part_count: int = 0
    warnings: tuple = ()

    def to_dict(self) -> dict:
        return {
            "slide_count": self.slide_count,
            "placeholder_count": self.placeholder_count,
            "placeholder_paths": list(self.placeholder_paths),
            "media_part_count": self.media_part_count,
            "notes_slide_count": self.notes_slide_count,
            "ole_part_count": self.ole_part_count,
            "warnings": list(self.warnings),
            "slides": [
                {
                    "slide_index": slide.slide_index,
                    "part_name": slide.part_name,
                    "placeholders": [
                        {
                            "shape_name": item.shape_name,
                            "path": item.path,
                            "text": item.text,
                            "occurrences": item.occurrences,
                        }
                        for item in slide.placeholders
                    ],
                }
                for slide in self.slides
            ],
        }


class PlaceholderScanner:
    """Inventory ``{path}`` placeholders without modifying any part."""

    def scan(self, source) -> TemplateScan:
        package = OoxmlPackage(source)
        slide_parts = package.slide_parts()
        scans: List[SlideScan] = []
        warnings = []
        for slide_index, part_name in sorted(slide_parts.items()):
            xml = package.read(part_name)
            try:
                placeholders = self._scan_slide_xml(xml, slide_index)
            except etree.XMLSyntaxError as exc:
                warnings.append(f"slide {slide_index} XML parse failed: {exc}")
                placeholders = ()
            scans.append(SlideScan(slide_index=slide_index, part_name=part_name, placeholders=tuple(placeholders)))
        paths = sorted({item.path for scan in scans for item in scan.placeholders})
        count = sum(item.occurrences for scan in scans for item in scan.placeholders)
        return TemplateScan(
            slide_count=len(slide_parts),
            slides=tuple(scans),
            placeholder_paths=tuple(paths),
            placeholder_count=count,
            media_part_count=self._count_prefix(package, "ppt/media/"),
            notes_slide_count=self._count_prefix(package, "ppt/notesSlides/"),
            ole_part_count=self._count_ole(package),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _scan_slide_xml(xml: bytes, slide_index: int) -> List[PlaceholderMatch]:
        root = etree.fromstring(xml)
        per_shape: Dict[str, List[str]] = {}
        for a_t in root.iter("{%s}t" % NS["a"]):
            text = a_t.text or ""
            for match in PLACEHOLDER_RE.finditer(text):
                shape_name = PlaceholderScanner._shape_name(a_t)
                per_shape.setdefault(shape_name, []).append(match.group(1))
        matches = []
        for shape_name, paths in per_shape.items():
            counts: Dict[str, int] = {}
            for path in paths:
                counts[path] = counts.get(path, 0) + 1
            for path, occurrences in counts.items():
                matches.append(PlaceholderMatch(
                    slide_index=slide_index,
                    shape_name=shape_name,
                    path=path,
                    text=", ".join(paths),
                    occurrences=occurrences,
                ))
        return matches

    @staticmethod
    def _shape_name(a_t) -> str:
        """Climb from ``<a:t>`` to the owning shape's ``<p:cNvPr>``."""
        parent = a_t.getparent()
        while parent is not None:
            cNvPr = parent.find(".//{%s}cNvPr" % NS["p"])
            if cNvPr is not None:
                name = cNvPr.get("name")
                if name:
                    return name
            if parent.tag in ("{%s}sp" % NS["p"], "{%s}pic" % NS["p"],
                              "{%s}graphicFrame" % NS["p"], "{%s}grpSp" % NS["p"]):
                return "<unnamed>"
            parent = parent.getparent()
        return "<unknown>"

    @staticmethod
    def _count_prefix(package: OoxmlPackage, prefix: str) -> int:
        return sum(1 for name in package.part_names() if name.startswith(prefix))

    @staticmethod
    def _count_ole(package: OoxmlPackage) -> int:
        return sum(1 for name in package.part_names() if name.startswith("ppt/embeddings/"))
