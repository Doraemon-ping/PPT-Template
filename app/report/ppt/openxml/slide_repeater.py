# -*- coding: utf-8 -*-
"""Slide cloning and presentation.xml rebuild at the zip level.

``clone_slide`` duplicates one template slide into a fresh numbered part while
rewriting relationship ids, so repeated issue slides share media/layouts
without id collisions. ``rebuild_presentation`` replaces the output slide list
in deck mode, which is how ``repeat`` slides are materialised.
"""
import re
import posixpath
from typing import Dict, List

from lxml import etree

from .package_editor import OoxmlPackage, OoxmlPackageError

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

_SLIDE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
_REL_ATTRS = ("{%s}embed" % NS["r"], "{%s}link" % NS["r"], "{%s}id" % NS["r"])
_SLIDE_PART_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_SLIDE_RELS_RE = re.compile(r"^ppt/slides/_rels/slide(\d+)\.xml\.rels$")
_NOTES_PART_RE = re.compile(r"^ppt/notesSlides/notesSlide\d+\.xml$")
_NOTES_RELS_RE = re.compile(r"^ppt/notesSlides/_rels/notesSlide\d+\.xml\.rels$")


class SlideRepeaterError(RuntimeError):
    pass


def clone_slide(package: OoxmlPackage, source_part: str, new_part: str) -> Dict[str, str]:
    """Copy a slide part and its relationships under a fresh part name."""
    if package.has_part(new_part):
        raise SlideRepeaterError(f"target slide part already exists: {new_part}")
    xml = package.read(source_part)
    source_rels = package.rels_part_for(source_part)

    mapping: Dict[str, str] = {}
    if source_rels is not None and package.has_part(source_rels):
        rels_root = etree.fromstring(package.read(source_rels))
        counter = 1
        clones = []
        for relationship in rels_root.findall("{%s}Relationship" % NS["rel"]):
            old_id = relationship.get("Id")
            new_id = f"rId{counter}"
            counter += 1
            mapping[old_id] = new_id
            clone = etree.fromstring(etree.tostring(relationship))
            clone.set("Id", new_id)
            # Unlike images/layouts, PowerPoint tags are owned by their slide.
            # Sharing a tags part between two slides makes Office reject the deck.
            if (clone.get('Type') or '').endswith('/tags') and clone.get('TargetMode') != 'External':
                target = posixpath.normpath(posixpath.join(posixpath.dirname(source_part), clone.get('Target')))
                numbers = [int(m.group(1)) for name in package.part_names()
                           if (m := re.match(r'^ppt/tags/tag(\d+)\.xml$', name))]
                tag_part = f'ppt/tags/tag{max(numbers, default=0)+1}.xml'
                package.write(tag_part, package.read(target))
                package.ensure_content_type(tag_part, 'application/vnd.openxmlformats-officedocument.presentationml.tags+xml')
                clone.set('Target', posixpath.relpath(tag_part, posixpath.dirname(new_part)))
            clones.append(clone)
        new_rels = etree.Element("{%s}Relationships" % NS["rel"], nsmap={None: NS["rel"]})
        for clone in clones:
            new_rels.append(clone)

    root = etree.fromstring(xml)
    for element in root.iter():
        for attr in _REL_ATTRS:
            old_id = element.get(attr)
            if old_id in mapping:
                element.set(attr, mapping[old_id])
    package.write(new_part, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True))
    package.ensure_content_type(
        new_part,
        "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
    )

    if source_rels is not None and package.has_part(source_rels):
        new_rels_part = package.rels_part_for(new_part)
        package.write(new_rels_part, etree.tostring(new_rels, xml_declaration=True, encoding="UTF-8", standalone=True))
    return mapping


def rebuild_presentation(package: OoxmlPackage, output_parts: List[str]) -> None:
    """Replace the deck slide list with ``output_parts`` in order (deck mode)."""
    if not output_parts:
        raise SlideRepeaterError("deck mode requires at least one output slide")
    for part in output_parts:
        if not _SLIDE_PART_RE.match(part):
            raise SlideRepeaterError(f"invalid output slide part: {part}")

    presentation = etree.fromstring(package.read("ppt/presentation.xml"))
    sld_id_list = presentation.find("{%s}sldIdLst" % NS["p"])
    if sld_id_list is None:
        raise SlideRepeaterError("presentation.xml has no sldIdLst")
    existing_ids = [int(el.get("id")) for el in sld_id_list if el.get("id")]
    next_slide_id = (max(existing_ids, default=255) + 1) if existing_ids else 256
    for element in list(sld_id_list):
        sld_id_list.remove(element)

    pres_rels_name = "ppt/_rels/presentation.xml.rels"
    if not package.has_part(pres_rels_name):
        raise SlideRepeaterError("presentation relationships part missing")
    pres_rels = etree.fromstring(package.read(pres_rels_name))
    rid_numbers = []
    for relationship in pres_rels.findall("{%s}Relationship" % NS["rel"]):
        match = re.match(r"rId(\d+)", relationship.get("Id") or "")
        if match:
            rid_numbers.append(int(match.group(1)))
    next_rid = max(rid_numbers, default=0) + 1

    for relationship in list(pres_rels.findall("{%s}Relationship" % NS["rel"])):
        target = relationship.get("Target") or ""
        if target.startswith("slides/slide") and target.endswith(".xml") and "slideLayout" not in target:
            pres_rels.remove(relationship)

    for index, part in enumerate(output_parts):
        rid = f"rId{next_rid}"
        next_rid += 1
        relationship = etree.SubElement(pres_rels, "{%s}Relationship" % NS["rel"])
        relationship.set("Id", rid)
        relationship.set("Type", _SLIDE_REL_TYPE)
        relationship.set("Target", part.removeprefix("ppt/"))
        slide_id = etree.SubElement(sld_id_list, "{%s}sldId" % NS["p"])
        slide_id.set("id", str(next_slide_id))
        slide_id.set("{%s}id" % NS["r"], rid)
        next_slide_id += 1

    package.write("ppt/presentation.xml",
                  etree.tostring(presentation, xml_declaration=True, encoding="UTF-8", standalone=True))
    package.write(pres_rels_name,
                  etree.tostring(pres_rels, xml_declaration=True, encoding="UTF-8", standalone=True))

    _drop_original_slides(package, output_parts)


def _drop_original_slides(package: OoxmlPackage, output_parts: List[str]) -> None:
    kept_numbers = set()
    for part in output_parts:
        match = _SLIDE_PART_RE.match(part)
        if match:
            kept_numbers.add(int(match.group(1)))
    for name in list(package.part_names()):
        match = _SLIDE_PART_RE.match(name)
        if match:
            number = int(match.group(1))
            if number not in kept_numbers:
                package.remove(name)
                rels = package.rels_part_for(name)
                if rels:
                    package.remove(rels)
        elif _NOTES_PART_RE.match(name) or _NOTES_RELS_RE.match(name):
            package.remove(name)
        elif _SLIDE_RELS_RE.match(name):
            number = int(_SLIDE_RELS_RE.match(name).group(1))
            if number not in kept_numbers:
                package.remove(name)

    # Notes were removed above. Retaining their relationships/overrides makes
    # continued slides reference missing parts and can trigger PowerPoint repair.
    for part in output_parts:
        rels = package.rels_part_for(part)
        if rels and package.has_part(rels):
            root = etree.fromstring(package.read(rels))
            removed = False
            for rel in list(root):
                if (rel.get('Type') or '').endswith('/notesSlide'):
                    root.remove(rel)
                    removed = True
            if removed:
                package.write(rels, etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True))
    ct = etree.fromstring(package.read('[Content_Types].xml'))
    removed = False
    for override in list(ct):
        name = override.get('PartName')
        if name and not package.has_part(name.lstrip('/')):
            ct.remove(override)
            removed = True
    if removed:
        package.write('[Content_Types].xml', etree.tostring(ct, xml_declaration=True, encoding='UTF-8', standalone=True))
