# -*- coding: utf-8 -*-
"""Zip-level OOXML package editing.

This module never re-saves the package through ``python-pptx``. Untouched parts
keep their original bytes, compression and timestamps, so unbound template
objects, masters, themes, OLE and unknown relationships remain byte-identical.
"""
import io
import re
import zipfile
from pathlib import Path
from typing import Dict, Optional

from lxml import etree

_SLIDE_PART_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_SLIDE_RELS_RE = re.compile(r"^ppt/slides/_rels/slide(\d+)\.xml\.rels$")


def _serialize(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


class OoxmlPackageError(RuntimeError):
    pass


class OoxmlPackage:
    """In-memory view of a PPTX zip with selective, part-level editing."""

    def __init__(self, source) -> None:
        if isinstance(source, (str, Path)):
            with open(source, "rb") as fp:
                self._seed = fp.read()
        elif isinstance(source, bytes):
            self._seed = source
        elif isinstance(source, io.BytesIO):
            self._seed = source.getvalue()
        else:
            raise OoxmlPackageError(f"unsupported source: {type(source)!r}")
        self._parts: Dict[str, bytes] = {}
        self._infos: Dict[str, zipfile.ZipInfo] = {}
        self._changed: set = set()
        self._read_zip()

    # ------------------------------------------------------------------ read
    def _read_zip(self) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(self._seed)) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    self._parts[info.filename] = archive.read(info.filename)
                    self._infos[info.filename] = info
        except zipfile.BadZipFile as exc:
            raise OoxmlPackageError(f"invalid pptx zip: {exc}") from exc

    def part_names(self):
        return tuple(sorted(self._parts))

    def has_part(self, name: str) -> bool:
        return name in self._parts

    def read(self, name: str) -> bytes:
        try:
            return self._parts[name]
        except KeyError as exc:
            raise OoxmlPackageError(f"part not found: {name}") from exc

    def write(self, name: str, data: bytes) -> None:
        if name not in self._parts:
            # New parts default to ZIP_DEFLATED with the package timestamp.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            self._infos[name] = info
        self._parts[name] = data
        self._changed.add(name)

    def remove(self, name: str) -> None:
        self._parts.pop(name, None)
        self._infos.pop(name, None)
        self._changed.discard(name)

    # ----------------------------------------------------------- slide parts
    def slide_parts(self) -> Dict[int, str]:
        """Return {slide_index: part_name} preserving template order."""
        matches = []
        for name in self._parts:
            match = _SLIDE_PART_RE.match(name)
            if match:
                matches.append((int(match.group(1)), name))
        return {index: name for index, name in sorted(matches)}

    def next_slide_number(self) -> int:
        numbers = list(self.slide_parts())
        for part_name in self._parts:
            match = _SLIDE_PART_RE.match(part_name)
            if match:
                numbers.append(int(match.group(1)))
        return (max(numbers) + 1) if numbers else 1

    def rels_part_for(self, slide_part_name: str) -> Optional[str]:
        match = _SLIDE_PART_RE.match(slide_part_name)
        if not match:
            return None
        return f"ppt/slides/_rels/slide{match.group(1)}.xml.rels"

    # ------------------------------------------------------------------ save
    def ensure_content_type(self, part_name: str, content_type: str) -> None:
        """Register a new slide/media part in ``[Content_Types].xml``."""
        ct_name = "[Content_Types].xml"
        if not self.has_part(ct_name):
            return
        ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
        xml = self.read(ct_name)
        root = etree.fromstring(xml)
        target = "/" + part_name
        for override in root.findall(f"{{{ct_ns}}}Override"):
            if override.get("PartName") == target:
                if override.get("ContentType") != content_type:
                    override.set("ContentType", content_type)
                    self.write(ct_name, _serialize(root))
                return
        override = etree.SubElement(root, f"{{{ct_ns}}}Override")
        override.set("PartName", target)
        override.set("ContentType", content_type)
        self.write(ct_name, _serialize(root))

    def save(self) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name in sorted(self._parts):
                info = self._infos.get(name)
                if info is None or name in self._changed:
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, self._parts[name])
        output.seek(0)
        return output.getvalue()

    def save_to(self, path) -> None:
        Path(path).write_bytes(self.save())


def open_package(source) -> OoxmlPackage:
    return OoxmlPackage(source)
