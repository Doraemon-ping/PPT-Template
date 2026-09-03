# -*- coding: utf-8 -*-
import io
import unittest
import zipfile
from pathlib import Path

from lxml import etree
from pptx import Presentation

from app.report.ppt.openxml import OoxmlPackage, clone_slide, rebuild_presentation

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "templates" / "DFM_Template_Placeholder_Demo.pptx"


class SlideRepeaterTests(unittest.TestCase):
    def test_clone_slide_creates_part_rels_and_content_type(self):
        package = OoxmlPackage(DEMO)
        mapping = clone_slide(package, "ppt/slides/slide1.xml", "ppt/slides/slide9.xml")
        self.assertIn("ppt/slides/slide9.xml", package.part_names())
        self.assertIn("ppt/slides/_rels/slide9.xml.rels", package.part_names())
        self.assertTrue(mapping)
        content_types = package.read("[Content_Types].xml").decode("utf-8")
        self.assertIn("/ppt/slides/slide9.xml", content_types)

    def test_rebuild_presentation_orders_and_keeps_only_output_slides(self):
        package = OoxmlPackage(DEMO)
        for number in (4, 5, 6):
            clone_slide(package, "ppt/slides/slide3.xml", f"ppt/slides/slide{number}.xml")
        rebuild_presentation(package, ["ppt/slides/slide4.xml", "ppt/slides/slide5.xml", "ppt/slides/slide6.xml"])
        output = package.save()

        with zipfile.ZipFile(io.BytesIO(output)) as archive:
            names = set(archive.namelist())
            self.assertFalse(any(name.startswith("ppt/slides/slide1.xml") for name in names))
            self.assertFalse(any(name.startswith("ppt/slides/slide2.xml") for name in names))
            self.assertFalse(any(name.startswith("ppt/slides/slide3.xml") for name in names))
            self.assertIn("ppt/slides/slide4.xml", names)
            self.assertIn("ppt/slides/slide5.xml", names)
            presentation = archive.read("ppt/presentation.xml")
            pres_rels = archive.read("ppt/_rels/presentation.xml.rels")

        root = etree.fromstring(presentation)
        ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
        sld_ids = [el.get("{%s}id" % "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
                   for el in root.findall(".//p:sldIdLst/p:sldId", namespaces=ns)]
        self.assertEqual(3, len(sld_ids))
        rels_root = etree.fromstring(pres_rels)
        rel_ns = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
        targets = [rel.get("Target") for rel in rels_root.findall("rel:Relationship", namespaces=rel_ns)]
        self.assertIn("slides/slide4.xml", targets)
        self.assertIn("slides/slide6.xml", targets)

        # 输出仍可被 python-pptx 打开，页面顺序与数量正确
        prs = Presentation(io.BytesIO(output))
        self.assertEqual(3, len(prs.slides))

    def test_rebuild_rejects_empty_output(self):
        package = OoxmlPackage(DEMO)
        with self.assertRaises(Exception):
            rebuild_presentation(package, [])


if __name__ == "__main__":
    unittest.main()
