# -*- coding: utf-8 -*-
"""Fill ``{path}`` placeholders inside slide XML text runs.

Each placeholder is replaced in place. When a run mixes placeholder and plain
text, the run is split into sibling runs that share the original run
properties, so font, size and color are preserved (same idea as the
pptx-template text substitution step, implemented at the OOXML level).
"""
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from lxml import etree

from .placeholder_scanner import PLACEHOLDER_RE

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}

_MISSING = object()


class PlaceholderResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class FillStats:
    replaced: int = 0
    missing: tuple = ()
    cleared: int = 0

    def to_dict(self) -> dict:
        return {"replaced": self.replaced, "missing": list(self.missing), "cleared": self.cleared}


@dataclass(frozen=True)
class PathResolver:
    """Resolve dotted/array paths against a scope chain (item first, then global)."""

    scopes: Tuple[Any, ...] = ()

    def __call__(self, path: str):
        return self.resolve(path)

    def resolve(self, path: str):
        for scope in self.scopes:
            value = _lookup(scope, path, _MISSING)
            if value is not _MISSING:
                return value, True
        return None, False


def _lookup(root: Any, path: str, default: Any = _MISSING):
    current = root
    for raw_segment in path.split("."):
        if raw_segment == "":
            return default
        bracket = raw_segment.find("[")
        if bracket >= 0:
            key = raw_segment[:bracket]
            if key:
                current = _step(current, key, default)
                if current is default:
                    return default
            for index in re.findall(r"\[(\d+)\]", raw_segment[bracket:]):
                if isinstance(current, (list, tuple)):
                    current = current[int(index)] if int(index) < len(current) else default
                else:
                    return default
                if current is default:
                    return default
        else:
            current = _step(current, raw_segment, default)
            if current is default:
                return default
    return current


def _step(current: Any, key: str, default: Any):
    if isinstance(current, dict):
        return current.get(key, default)
    if isinstance(current, (list, tuple)) and key.isdigit():
        index = int(key)
        return current[index] if index < len(current) else default
    return getattr(current, key, default)


class TextBindingFiller:
    """Replace placeholders in one slide XML document."""

    def __init__(self, missing: str = "keep") -> None:
        if missing not in {"keep", "clear", "error"}:
            raise ValueError(f"unsupported missing policy: {missing}")
        self.missing = missing

    def fill(self, xml: bytes, resolver: Callable[[str], Tuple[Any, bool]]) -> Tuple[bytes, FillStats]:
        # 快速短路：没有占位符的部件保持原始字节，不做任何 XML 序列化。
        if not re.search(rb"\{[A-Za-z_][A-Za-z0-9_.\[\]-]*\}", xml):
            return xml, FillStats()
        root = etree.fromstring(xml)
        stats = {"replaced": 0, "cleared": 0}
        missing: List[str] = []
        for a_t in root.iter("{%s}t" % NS["a"]):
            text = a_t.text or ""
            matches = list(PLACEHOLDER_RE.finditer(text))
            if not matches:
                continue
            segments: List[Tuple[str, bool]] = []  # (text, was_replaced_or_cleared)
            last = 0
            for match in matches:
                if match.start() > last:
                    segments.append((text[last:match.start()], False))
                path = match.group(1)
                value, found = resolver(path)
                if found:
                    segments.append(("" if value is None else str(value), True))
                    stats["replaced"] += 1
                elif self.missing == "error":
                    raise PlaceholderResolutionError(f"missing data for placeholder {{{path}}}")
                elif self.missing == "clear":
                    segments.append(("", True))
                    stats["cleared"] += 1
                else:
                    segments.append((match.group(0), False))
                    missing.append(path)
                last = match.end()
            if last < len(text):
                segments.append((text[last:], False))
            self._replace_run(a_t, segments)
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True), FillStats(
            replaced=stats["replaced"], missing=tuple(dict.fromkeys(missing)), cleared=stats["cleared"]
        )

    @staticmethod
    def _replace_run(a_t, segments: List[Tuple[str, bool]]):
        """Split ``<a:r>`` into sibling runs, each preserving the original rPr."""
        run = a_t.getparent()  # <a:r>
        paragraph = run.getparent()  # <a:p>
        rpr = run.find("{%s}rPr" % NS["a"])
        index = paragraph.index(run)
        created = []
        for text, _ in segments:
            new_run = etree.Element("{%s}r" % NS["a"])
            if rpr is not None:
                new_run.append(deepcopy(rpr))
            new_t = etree.SubElement(new_run, "{%s}t" % NS["a"])
            new_t.text = text
            new_t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            created.append(new_run)
        paragraph.remove(run)
        for offset, new_run in enumerate(created):
            paragraph.insert(index + offset, new_run)
