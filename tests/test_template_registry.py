# -*- coding: utf-8 -*-
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.report.ppt.openxml import OoxmlPackage
from app.report.ppt.openxml.shape_binding import (
    ShapeBindingError,
    find_shape,
    set_shape_text,
    set_table_cell,
)
from app.report.ppt.openxml.shape_inventory import ShapeInventoryScanner
from app.report.ppt.template_registry import TemplateRegistry

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "templates" / "DFM_Template_Placeholder_Demo.pptx"
TABLE = ROOT / "templates" / "DFM_Template_Table_Demo.pptx"


def _slide_xml(path: Path, number: int) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(f"ppt/slides/slide{number}.xml")


class ShapeInventoryScannerTests(unittest.TestCase):
    def test_inventory_demo_template_shapes(self):
        inventory = ShapeInventoryScanner().scan(DEMO)
        self.assertEqual(3, inventory.slide_count)
        slide1 = next(s for s in inventory.slides if s.slide_index == 1)
        names = {shape.shape_name for shape in slide1.shapes}
        self.assertIn("COVER_PART_NUMBER", names)
        cover = next(shape for shape in slide1.shapes if shape.shape_name == "COVER_PART_NUMBER")
        self.assertEqual("text", cover.kind)
        self.assertIn("f.partNo", cover.placeholder_paths)

    def test_inventory_table_reports_dimensions(self):
        inventory = ShapeInventoryScanner().scan(TABLE)
        table_shape = next(shape for shape in inventory.slides[0].shapes if shape.kind == "table")
        self.assertEqual("PART_TABLE", table_shape.shape_name)
        self.assertEqual(6, table_shape.rows)
        self.assertEqual(2, table_shape.cols)


class ShapeBindingUnitTests(unittest.TestCase):
    def test_set_shape_text_replaces_all_text(self):
        from lxml import etree

        xml = _slide_xml(DEMO, 1)
        root = etree.fromstring(xml)
        shape = find_shape(root, "COVER_PART_NUMBER")
        set_shape_text(shape, "ABC-001")
        texts = shape.xpath(".//a:t/text()", namespaces={"a": "http://schemas.openxmlformats.org/drawingml/2006/main"})
        self.assertEqual(["ABC-001"], texts)

    def test_find_shape_duplicates_raise(self):
        from lxml import etree

        # 给同一页复制一个同名形状再查 -> 应报重复
        xml = _slide_xml(DEMO, 1)
        root = etree.fromstring(xml)
        shape = find_shape(root, "COVER_PART_NUMBER")
        import copy

        root.append(copy.deepcopy(shape))
        with self.assertRaises(ShapeBindingError):
            find_shape(root, "COVER_PART_NUMBER")

    def test_set_table_cell_bounds(self):
        from lxml import etree

        xml = _slide_xml(TABLE, 1)
        root = etree.fromstring(xml)
        shape = find_shape(root, "PART_TABLE")
        set_table_cell(shape, 1, 1, "VALUE-1")
        with self.assertRaises(ShapeBindingError):
            set_table_cell(shape, 99, 0, "x")
        with self.assertRaises(ShapeBindingError):
            set_table_cell(shape, 0, 99, "x")


class TemplateRegistryTests(unittest.TestCase):
    def test_upload_list_delete_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = TemplateRegistry(Path(tmp))
            data = DEMO.read_bytes()
            record = registry.register_upload(template_id="My-Tpl", data=data, source_name="mine.pptx")
            self.assertEqual("uploaded", record.origin)
            self.assertTrue(record.path.is_file())
            ids = [r.template_id for r in registry.list()]
            self.assertIn("my-tpl", ids)  # id 统一小写化
            self.assertIn("demo", ids)  # builtin still listed

            # 重启持久化（重新加载注册表文件）
            registry2 = TemplateRegistry(Path(tmp))
            ids2 = [r.template_id for r in registry2.list()]
            self.assertIn("my-tpl", ids2)
            resolved = registry2.resolve("My-Tpl")
            self.assertEqual(data, resolved.path.read_bytes())

            registry2.delete("my-tpl")
            with self.assertRaises(Exception):
                registry2.resolve("my-tpl")

    def test_upload_conflicts_with_builtin_and_bad_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = TemplateRegistry(Path(tmp))
            with self.assertRaises(Exception):
                registry.register_upload(template_id="demo", data=b"x")
            with self.assertRaises(Exception):
                registry.register_upload(template_id="!!bad", data=b"x")
            with self.assertRaises(Exception):
                registry.register_upload(template_id="ok", data=b"")


if __name__ == "__main__":
    unittest.main()
