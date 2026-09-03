# -*- coding: utf-8 -*-
import unittest
from pathlib import Path

from app.report.ppt.openxml import OoxmlPackage, PlaceholderScanner

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "templates" / "DFM_Template_Placeholder_Demo.pptx"

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp><p:nvSpPr><p:cNvPr id="1" name="COVER_TITLE"/></p:nvSpPr><p:spPr/></p:sp>
      <p:sp><p:nvSpPr><p:cNvPr id="2" name="COVER_BODY"/></p:nvSpPr><p:spPr/>
        <p:txBody><a:p><a:r><a:t>客户：{f.custName} 零件：{f.partNo}</a:t></a:r></a:p></p:txBody>
      </p:sp>
      <p:sp><p:nvSpPr><p:cNvPr id="3" name="NO_PLACEHOLDER"/></p:nvSpPr><p:spPr/>
        <p:txBody><a:p><a:r><a:t>普通文本</a:t></a:r></a:p></p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>
"""


class PlaceholderScannerTests(unittest.TestCase):
    def test_scans_demo_template_inventory(self):
        scan = PlaceholderScanner().scan(DEMO)
        self.assertEqual(3, scan.slide_count)
        self.assertEqual(16, scan.placeholder_count)
        self.assertIn("f.partNo", scan.placeholder_paths)
        self.assertIn("no", scan.placeholder_paths)
        by_slide = {s.slide_index: {p.path for p in s.placeholders} for s in scan.slides}
        self.assertIn("f.dfmDate", by_slide[1])
        self.assertIn("f.material", by_slide[2])
        self.assertIn("desc", by_slide[3])

    def test_scans_keep_byte_level_shape_name(self):
        scan = PlaceholderScanner().scan(DEMO)
        slide1 = next(s for s in scan.slides if s.slide_index == 1)
        cover = next(p for p in slide1.placeholders if p.path == "f.partNo")
        self.assertEqual("COVER_PART_NUMBER", cover.shape_name)

    def test_scanner_does_not_modify_template(self):
        before = DEMO.read_bytes()
        PlaceholderScanner().scan(DEMO)
        self.assertEqual(before, DEMO.read_bytes())


class SlideXmlScannerUnitTests(unittest.TestCase):
    def test_finds_placeholders_in_mixed_run_and_shape_name(self):
        matches = PlaceholderScanner._scan_slide_xml(SAMPLE_XML.encode("utf-8"), 1)
        found = {(m.shape_name, m.path) for m in matches}
        self.assertEqual({("COVER_BODY", "f.custName"), ("COVER_BODY", "f.partNo")}, found)
        self.assertEqual([], [m for m in matches if m.shape_name == "NO_PLACEHOLDER"])

    def test_ooxml_package_round_trip_keeps_part_content(self):
        import io
        import zipfile

        package = OoxmlPackage(DEMO)
        out = package.save()
        self.assertNotEqual(b"", out)
        with zipfile.ZipFile(io.BytesIO(out)) as archive:
            self.assertEqual(set(package.part_names()), set(archive.namelist()))
        with zipfile.ZipFile(DEMO) as original:
            for name in package.part_names():
                self.assertEqual(original.read(name), package.read(name), name)


if __name__ == "__main__":
    unittest.main()
