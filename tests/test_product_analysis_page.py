from pathlib import Path
from unittest import TestCase

from app.demo import demo_state
from app.report.ppt.deck import DeckDefinition
from app.report.ppt.openxml.package_editor import OoxmlPackage
from app.report.ppt.openxml.shape_inventory import ShapeInventoryScanner
from app.report.ppt.template_engine import TemplateEngine
from scripts.generate_product_analysis_page import build_slide


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "1-基础数据" / "新建文件夹" / "2.pptx"


class ProductAnalysisPageTests(TestCase):
    def test_inventory_exposes_duplicate_names_by_id_and_ole_objects(self):
        shapes = ShapeInventoryScanner().scan(TEMPLATE).slides[0].shapes
        image_slots = [shape for shape in shapes if shape.shape_name == "PA_形状 26"]
        self.assertEqual(2, len(image_slots))
        self.assertEqual(2, len({shape.shape_id for shape in image_slots}))
        self.assertEqual(6, sum(shape.kind == "ole" for shape in shapes))
        self.assertEqual(11, len(shapes))

    def test_generates_composite_text_and_six_static_formula_images(self):
        deck = DeckDefinition(
            template="product-analysis", output_mode="in_place", slides=[build_slide(TEMPLATE)]
        )
        result = TemplateEngine(TEMPLATE).generate(deck, demo_state())
        package = OoxmlPackage(result.buffer)
        slide = package.read("ppt/slides/slide1.xml").decode("utf-8")
        self.assertIn("TP-HPDC-2026-0087", slide)
        self.assertNotIn("progId=\"Equation.3\"", slide)
        self.assertEqual(6, sum(name.startswith("ppt/media/generated") for name in package.part_names()))
