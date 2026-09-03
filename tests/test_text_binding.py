# -*- coding: utf-8 -*-
import unittest

from app.report.ppt.openxml.text_binding import (
    PathResolver,
    PlaceholderResolutionError,
    TextBindingFiller,
)

MIXED_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree>
    <p:sp><p:nvSpPr><p:cNvPr id="1" name="S1"/></p:nvSpPr><p:spPr/>
      <p:txBody><a:p><a:r><a:rPr lang="zh-CN" sz="1800" b="1"/><a:t>零件 {f.partNo} 版本 {f.version}</a:t></a:r></a:p></p:txBody>
    </p:sp>
    <p:sp><p:nvSpPr><p:cNvPr id="2" name="S2"/></p:nvSpPr><p:spPr/>
      <p:txBody><a:p><a:r><a:t>{t.issues[0].desc}</a:t></a:r></a:p></p:txBody>
    </p:sp>
    <p:sp><p:nvSpPr><p:cNvPr id="3" name="S3"/></p:nvSpPr><p:spPr/>
      <p:txBody><a:p><a:r><a:t>{missing.field}</a:t></a:r></a:p></p:txBody>
    </p:sp>
  </p:spTree></p:cSld>
</p:sld>
"""

DATA = {
    "f": {"partNo": "TP-001", "version": "A2"},
    "t": {"issues": [{"desc": "壁厚偏大"}, {"desc": "分型线需调整"}]},
}


class PathResolverTests(unittest.TestCase):
    def test_global_scope_resolves_dict_paths_and_array_index(self):
        resolver = PathResolver((DATA,))
        self.assertEqual(("TP-001", True), resolver("f.partNo"))
        self.assertEqual(("壁厚偏大", True), resolver("t.issues[0].desc"))
        self.assertEqual(("壁厚偏大", True), resolver("t.issues.0.desc"))

    def test_item_scope_wins_over_global(self):
        item = {"desc": "当前项", "no": "3"}
        resolver = PathResolver((item, DATA))
        self.assertEqual(("当前项", True), resolver("desc"))
        self.assertEqual(("TP-001", True), resolver("f.partNo"))
        self.assertEqual((None, False), resolver("does.not.exist"))


class TextBindingFillerTests(unittest.TestCase):
    def test_mixed_run_is_split_and_filled(self):
        filler = TextBindingFiller(missing="keep")
        xml, stats = filler.fill(MIXED_XML.encode("utf-8"), PathResolver((DATA,)))
        decoded = xml.decode("utf-8")
        self.assertEqual(3, stats.replaced)
        self.assertEqual(("missing.field",), stats.missing)
        self.assertIn("TP-001", decoded)
        self.assertIn("A2", decoded)
        self.assertIn("壁厚偏大", decoded)
        self.assertNotIn("{f.partNo}", decoded)
        self.assertNotIn("{f.version}", decoded)
        self.assertIn("{missing.field}", decoded)

    def test_clear_policy_removes_placeholder(self):
        filler = TextBindingFiller(missing="clear")
        xml, stats = filler.fill(MIXED_XML.encode("utf-8"), PathResolver((DATA,)))
        self.assertEqual(1, stats.cleared)
        self.assertNotIn("{missing.field}", xml.decode("utf-8"))

    def test_error_policy_raises(self):
        filler = TextBindingFiller(missing="error")
        with self.assertRaises(PlaceholderResolutionError):
            filler.fill(MIXED_XML.encode("utf-8"), PathResolver((DATA,)))

    def test_no_placeholder_returns_original_bytes_unchanged(self):
        plain = '<?xml version="1.0"?><p:sld xmlns:p="p"><a:t>无占位符的普通文本</a:t></p:sld>'.encode("utf-8")
        xml, stats = TextBindingFiller().fill(plain, PathResolver((DATA,)))
        self.assertIs(plain, xml)  # 未绑定部件不做任何 XML 序列化
        self.assertEqual(0, stats.replaced)

    def test_preserves_run_properties_on_split(self):
        import re

        from lxml import etree

        xml, _ = TextBindingFiller(missing="keep").fill(
            MIXED_XML.encode("utf-8"), PathResolver((DATA,))
        )
        root = etree.fromstring(xml)
        # 第一个文本框被拆成 4 个 run，每个 run 都保留原 rPr
        runs = root.xpath(
            ".//p:sp[1]//a:r",
            namespaces={"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                        "a": "http://schemas.openxmlformats.org/drawingml/2006/main"},
        )
        self.assertEqual(4, len(runs))
        self.assertTrue(all(run.find("{http://schemas.openxmlformats.org/drawingml/2006/main}rPr") is not None
                            for run in runs))
        texts = "".join(run.find("{http://schemas.openxmlformats.org/drawingml/2006/main}t").text or ""
                       for run in runs)
        self.assertEqual("零件 TP-001 版本 A2", texts)


if __name__ == "__main__":
    unittest.main()
