# -*- coding: utf-8 -*-
"""Fill the formal 84-page package by editing target OOXML text nodes only."""

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from .exceptions import TemplateShapeDuplicateError, TemplateShapeMissingError


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


@dataclass(frozen=True)
class ExactTemplateGenerationResult:
    buffer: io.BytesIO
    slide_count: int
    template_version: str
    generator_version: str = "0.3-exact2"


class ExactTemplateEngine:
    """Preserve every non-target package part and all template formatting."""

    def __init__(self, template_path, *, template_version="1") -> None:
        self.template_path = Path(template_path)
        self.template_version = str(template_version)

    def generate(self, report) -> ExactTemplateGenerationResult:
        replacements = {
            "ppt/slides/slide1.xml": (
                ("shape", "EXACT_COVER_TITLE", self._cover_title(report)),
                ("shape", "EXACT_COVER_DATE", report.project.report_date),
                ("remove", "EXACT_REMOVE_COVER_INSTRUCTION"),
            ),
            "ppt/slides/slide4.xml": (
                ("cell", "EXACT_PART_ANALYSIS_TABLE", 1, 1, self._part_information(report)),
            ),
        }
        if report.issues:
            issue = report.issues[0]
            replacements["ppt/slides/slide77.xml"] = (
                ("cell", "EXACT_ISSUE_TABLE", 1, 1, issue.description or issue.title),
                ("cell", "EXACT_ISSUE_TABLE", 2, 1, issue.recommendation),
                ("cell", "EXACT_ISSUE_TABLE", 3, 1, str(issue.extra_data.get("fb", ""))),
            )

        output = io.BytesIO()
        slide_count = 0
        with zipfile.ZipFile(self.template_path, "r") as incoming, zipfile.ZipFile(output, "w") as outgoing:
            for info in incoming.infolist():
                data = incoming.read(info.filename)
                if info.filename.startswith("ppt/slides/slide") and info.filename.endswith(".xml"):
                    slide_count += 1
                if info.filename in replacements:
                    data = self._apply_replacements(data, replacements[info.filename])
                outgoing.writestr(info, data)
        output.seek(0)
        return ExactTemplateGenerationResult(
            buffer=output,
            slide_count=slide_count,
            template_version=self.template_version,
        )

    def _apply_replacements(self, xml, replacements):
        root = etree.fromstring(xml)
        for replacement in replacements:
            if replacement[0] == "remove":
                _, name = replacement
                target = self._named_shape(root, name)
                target.getparent().remove(target)
            elif replacement[0] == "shape":
                _, name, value = replacement
                self._replace_text_nodes(self._named_shape(root, name), value)
            else:
                _, name, row, column, value = replacement
                target = self._named_shape(root, name)
                rows = target.xpath(".//a:tbl/a:tr", namespaces=NS)
                if row >= len(rows):
                    raise IndexError(f"table row out of range: shape={name}; row={row}")
                cells = rows[row].xpath("./a:tc", namespaces=NS)
                if column >= len(cells):
                    raise IndexError(f"table column out of range: shape={name}; column={column}")
                self._replace_text_nodes(cells[column], value)
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    @staticmethod
    def _named_shape(root, name):
        matches = []
        candidates = root.xpath(".//p:sp | .//p:graphicFrame | .//p:grpSp | .//p:pic", namespaces=NS)
        for candidate in candidates:
            names = candidate.xpath("./p:nvSpPr/p:cNvPr/@name | ./p:nvGraphicFramePr/p:cNvPr/@name | ./p:nvGrpSpPr/p:cNvPr/@name | ./p:nvPicPr/p:cNvPr/@name", namespaces=NS)
            if names and names[0] == name:
                matches.append(candidate)
        if not matches:
            raise TemplateShapeMissingError("EXACT_TEMPLATE", name)
        if len(matches) > 1:
            raise TemplateShapeDuplicateError("EXACT_TEMPLATE", name)
        return matches[0]

    @staticmethod
    def _replace_text_nodes(target, value):
        nodes = target.xpath(".//a:t", namespaces=NS)
        if not nodes:
            raise ValueError("target contains no text node")
        nodes[0].text = "" if value is None else str(value)
        for node in nodes[1:]:
            node.text = ""

    @staticmethod
    def _cover_title(report):
        number = report.project.part_number.strip()
        return f"{number}\nDFM" if number else "DFM"

    @staticmethod
    def _part_information(report):
        p, s = report.project, report.part_specifications
        dimensions = "X".join(value for value in (s.length, s.width, s.height) if value)
        rows = [
            ("零件号", p.part_number),
            ("成品重量", f"{s.finished_weight}kg" if s.finished_weight else ""),
            ("毛坯重量", f"{s.casting_weight}kg" if s.casting_weight else ""),
            ("流道重量", f"{s.runner_weight}kg" if s.runner_weight else ""),
            ("渣包重量", f"{s.overflow_weight}kg" if s.overflow_weight else ""),
            ("基本壁厚", f"{s.wall_thickness}mm" if s.wall_thickness else ""),
            ("产品尺寸", f"{dimensions}mm" if dimensions else ""),
            ("模具结构", f"1出{s.cavity_count}" if s.cavity_count else ""),
            ("铸造压力", f"{s.casting_pressure}MPa" if s.casting_pressure else ""),
            ("材料", s.material),
        ]
        return "；\n".join(f"{label}:{value}" for label, value in rows if value)
