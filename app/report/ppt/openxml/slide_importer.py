# -*- coding: utf-8 -*-
"""Import slides from another PPTX package into the output package.

Used for decks that mix pages from several templates (template A page 1..3 +
template B page 1..2 in one output). Dependency parts referenced by an imported
slide — layouts, masters, themes, media — are copied into the output package
under fresh names, deduplicated by content hash, and their relationship ids are
rewritten so the final file opens normally in PowerPoint.
"""
import hashlib
import re
from typing import Dict, Optional

from lxml import etree

from .package_editor import OoxmlPackage, OoxmlPackageError

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}

REL_SLIDE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
REL_MASTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"


class SlideImportError(RuntimeError):
    pass


class SlideImporter:
    """Copy one source slide (with dependencies) into an output package."""

    def __init__(self) -> None:
        self._by_hash: Dict[str, str] = {}  # leaf media hash or source-part identity -> output part

    # ------------------------------------------------------------- public
    def import_slide(self, out: OoxmlPackage, source: OoxmlPackage, source_slide: str) -> str:
        if source_slide not in source.part_names():
            raise SlideImportError(f"source slide missing: {source_slide}")
        new_slide = f"ppt/slides/slide{out.next_slide_number()}.xml"
        out.write(new_slide, source.read(source_slide))
        out.ensure_content_type(
            new_slide,
            "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
        )
        self._copy_relationships(out, source, source_slide, new_slide)
        return new_slide

    # ----------------------------------------------------------- internals
    def _copy_relationships(self, out, source, source_part: str, target_part: str) -> None:
        source_rels = _rels_part(source_part)
        if source_rels is None or not source.has_part(source_rels):
            return
        rels_root = etree.fromstring(source.read(source_rels))
        relationships = list(rels_root.findall("{%s}Relationship" % NS["rel"]))
        mapping: Dict[str, str] = {}
        clones = []
        counter = 1
        for relationship in relationships:
            rel_type = relationship.get("Type")
            # Deck rebuild omits notes; do not traverse their slide back-links
            # and accidentally import a second hidden copy of the source slide.
            if rel_type.endswith('/notesSlide'):
                continue
            rel_target = relationship.get("Target") or ""
            rel_mode = relationship.get("TargetMode")
            old_id = relationship.get("Id")
            new_id = f"rId{counter}"
            counter += 1
            mapping[old_id] = new_id
            clone = etree.Element("{%s}Relationship" % NS["rel"])
            clone.set("Id", new_id)
            clone.set("Type", rel_type)
            if rel_mode:  # 外部链接（超链接等）原样保留
                clone.set("TargetMode", rel_mode)
                clone.set("Target", rel_target)
            else:
                resolved = _resolve_target(source_part, rel_target)
                if resolved is not None and source.has_part(resolved):
                    imported = self._import_part(out, source, resolved)
                    clone.set("Target", _rel_path(_dirname(target_part), imported))
                else:
                    clone.set("Target", rel_target)
            clones.append(clone)

        target_rels = _rels_part(target_part)
        if target_rels is not None:
            new_rels = etree.Element("{%s}Relationships" % NS["rel"], nsmap={None: NS["rel"]})
            for clone in clones:
                new_rels.append(clone)
            out.write(target_rels, etree.tostring(new_rels, xml_declaration=True,
                                                  encoding="UTF-8", standalone=True))
        self._rewrite_ids(out, target_part, mapping)

    @staticmethod
    def _rewrite_ids(out, part: str, mapping: Dict[str, str]) -> None:
        xml = out.read(part)
        root = etree.fromstring(xml)
        changed = False
        for element in root.iter():
            for attr in ("{%s}embed" % NS["r"], "{%s}link" % NS["r"], "{%s}id" % NS["r"]):
                old = element.get(attr)
                if old in mapping:
                    element.set(attr, mapping[old])
                    changed = True
        if changed:
            out.write(part, etree.tostring(root, xml_declaration=True,
                                           encoding="UTF-8", standalone=True))

    # -------------------------------------------------------- dependencies
    def _import_part(self, out: OoxmlPackage, source: OoxmlPackage, part: str) -> str:
        if part.startswith('ppt/tags/'):
            # Slide-owned tags cannot be hash-deduplicated across imported slides.
            number = 1
            while out.has_part(f'ppt/tags/tag{number}.xml'):
                number += 1
            new_name = f'ppt/tags/tag{number}.xml'
            out.write(new_name, source.read(part))
            self._ensure_content_type(out, source, part, new_name)
            self._copy_relationships(out, source, part, new_name)
            return new_name
        # Equal XML bytes are not equal dependencies: the same rId in two
        # templates can point to different layouts/masters/media. Cache those
        # graphs by source + part; only leaf media can be shared by content.
        digest = (hashlib.sha256(source.read(part)).hexdigest()
                  if part.startswith('ppt/media/') and not source.has_part(_rels_part(part))
                  else f'{id(source)}:{part}')
        cached = self._by_hash.get(digest)
        if cached is not None:
            return cached
        new_name = self._allocate(out, source, part)
        self._by_hash[digest] = new_name  # 占位，防止递归环
        out.write(new_name, source.read(part))
        self._ensure_content_type(out, source, part, new_name)
        self._copy_relationships(out, source, part, new_name)
        if _is_master(part):
            self._append_master(out, new_name)
        return new_name

    # -------------------------------------------------------------- masters
    def _append_master(self, out: OoxmlPackage, master_name: str) -> None:
        presentation = etree.fromstring(out.read("ppt/presentation.xml"))
        master_id_list = presentation.find("{%s}sldMasterIdLst" % NS["p"])
        pres_rels = etree.fromstring(out.read("ppt/_rels/presentation.xml.rels"))
        rid = _next_rid(pres_rels)
        relationship = etree.SubElement(pres_rels, "{%s}Relationship" % NS["rel"])
        relationship.set("Id", rid)
        relationship.set("Type", REL_MASTER)
        relationship.set("Target", master_name.removeprefix("ppt/"))
        ids = [int(el.get("id") or 0) for el in master_id_list] if master_id_list is not None else []
        # Master/layout IDs occupy a presentation-wide namespace in Office.
        # Copying a second master verbatim otherwise collides with existing layouts.
        for name in out.part_names():
            if _is_master(name):
                master = etree.fromstring(out.read(name))
                ids.extend(int(v) for v in master.xpath('.//p:sldLayoutId/@id', namespaces=NS))
        new_id = max(ids, default=2147483647) + 1
        imported_master = etree.fromstring(out.read(master_name))
        for offset, layout in enumerate(imported_master.findall('.//p:sldLayoutId', NS), start=1):
            layout.set('id', str(new_id + offset))
        out.write(master_name, etree.tostring(imported_master, xml_declaration=True, encoding='UTF-8', standalone=True))
        if master_id_list is None:
            master_id_list = etree.SubElement(presentation, "{%s}sldMasterIdLst" % NS["p"])
        element = etree.SubElement(master_id_list, "{%s}sldMasterId" % NS["p"])
        element.set("id", str(new_id))
        element.set("{%s}id" % NS["r"], rid)
        out.write("ppt/presentation.xml", etree.tostring(presentation, xml_declaration=True,
                                                         encoding="UTF-8", standalone=True))
        out.write("ppt/_rels/presentation.xml.rels", etree.tostring(pres_rels, xml_declaration=True,
                                                                    encoding="UTF-8", standalone=True))

    # -------------------------------------------------------------- naming
    def _allocate(self, out: OoxmlPackage, source: OoxmlPackage, part: str) -> str:
        stem, ext = _splitext(_basename(part))
        if _is_theme(part):
            number = _count_parts(out, "ppt/theme/theme") + 1
            return f"ppt/theme/theme{number}.xml"
        if _is_master(part):
            number = _count_parts(out, "ppt/slideMasters/slideMaster") + 1
            return f"ppt/slideMasters/slideMaster{number}.xml"
        if _is_layout(part):
            number = _count_parts(out, "ppt/slideLayouts/slideLayout") + 1
            return f"ppt/slideLayouts/slideLayout{number}.xml"
        if part.startswith("ppt/media/"):
            counter = 1
            while True:
                name = f"ppt/media/{stem}{'' if counter == 1 else counter}{ext}"
                if not out.has_part(name):
                    return name
                counter += 1
        # 图表/嵌入等其它部件：尽量沿用原路径，同名且内容不同时加后缀
        candidate = part
        if out.has_part(candidate) and out.read(candidate) != source.read(part):
            candidate = f"{_dirname(part)}/{stem}-imp{ext}"
        return candidate

    def _ensure_content_type(self, out, source, part: str, new_name: str) -> None:
        content_type = _content_type_of(source, part)
        if content_type:
            out.ensure_content_type(new_name, content_type)


def _next_rid(rels_root) -> str:
    numbers = [
        int(m.group(1))
        for relationship in rels_root.findall("{%s}Relationship" % NS["rel"])
        if (m := re.match(r"rId(\d+)", relationship.get("Id") or ""))
    ]
    return f"rId{max(numbers, default=0) + 1}"


def _count_parts(package: OoxmlPackage, prefix: str) -> int:
    return sum(1 for name in package.part_names() if name.startswith(prefix) and name.endswith(".xml"))


def _rels_part(part: str) -> Optional[str]:
    if "/" not in part:
        return None
    directory, base = _dirname(part), _basename(part)
    return f"{directory}/_rels/{base}.rels"


def _dirname(part: str) -> str:
    return part.rsplit("/", 1)[0] if "/" in part else ""


def _basename(part: str) -> str:
    return part.rsplit("/", 1)[-1]


def _splitext(base: str):
    return (base.rsplit(".", 1) + [""])[:2] if "." in base else (base, "")


def _resolve_target(part: str, target: str) -> Optional[str]:
    if target.startswith("/"):
        return target.lstrip("/")
    return _normalize(_dirname(part) + "/" + target)


def _normalize(path: str) -> str:
    parts = []
    for segment in path.replace("\\", "/").split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/".join(parts)


def _rel_path(from_dir: str, target: str) -> str:
    from_parts = [p for p in from_dir.split("/") if p]
    to_parts = [p for p in target.split("/") if p]
    while from_parts and to_parts and from_parts[0] == to_parts[0]:
        from_parts.pop(0)
        to_parts.pop(0)
    return "/".join([".."] * len(from_parts) + to_parts)


def _content_type_of(package: OoxmlPackage, part: str) -> str:
    if not package.has_part("[Content_Types].xml"):
        return ""
    root = etree.fromstring(package.read("[Content_Types].xml"))
    target = "/" + part
    for override in root.findall("{%s}Override" % NS["ct"]):
        if override.get("PartName") == target:
            return override.get("ContentType", "")
    if "." in part:
        ext = "." + part.rsplit(".", 1)[-1].casefold()
        for default in root.findall("{%s}Default" % NS["ct"]):
            if ("." + (default.get("Extension") or "").casefold()) == ext:
                return default.get("ContentType", "")
    return ""


def _is_theme(part: str) -> bool:
    return part.startswith("ppt/theme/") and part.endswith(".xml")


def _is_master(part: str) -> bool:
    return part.startswith("ppt/slideMasters/") and part.endswith(".xml")


def _is_layout(part: str) -> bool:
    return part.startswith("ppt/slideLayouts/") and part.endswith(".xml")
