# -*- coding: utf-8 -*-
"""Generate the supplied one-page product-analysis template.

This is an executable reference for a complete set of generic editor bindings
for this page; the workbench itself contains no page-specific action.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.demo import demo_state
from app.report.ppt.deck import DeckDefinition, DeckSlide
from app.report.ppt.openxml.shape_inventory import ShapeInventoryScanner
from app.report.ppt.template_engine import TemplateEngine


FORMULAS = (
    "F产 = [[A产|10]] = [[{ppt.force.area_part} cm² × {ppt.force.pressure} MPa|10]] = {ppt.force.part} kN",
    "F滑 = [[A滑|10]] = [[{ppt.force.area_slider} cm² × {ppt.force.pressure} MPa|10]]{ppt.force.slider_term} = {ppt.force.slider} kN",
    "F流 = [[A流|10]] = [[{ppt.force.area_runner} cm² × {ppt.force.pressure} MPa|10]] = {ppt.force.runner} kN",
    "F渣 = [[A渣|10]] = [[{ppt.force.area_overflow} cm² × {ppt.force.pressure} MPa|10]] = {ppt.force.overflow} kN",
    "F总 = F产 + F流 + F渣 + F滑 = {ppt.force.total} kN",
    "F锁 ≥ K(F总) = {ppt.force.clamp_factor} × {ppt.force.total} kN = {ppt.force.clamp_required} kN",
)


def build_slide(template: Path) -> DeckSlide:
    inventory = ShapeInventoryScanner().scan(template)
    if len(inventory.slides) != 1:
        raise RuntimeError("产品分析页面模板必须是单页 PPTX")
    shapes = inventory.slides[0].shapes
    table = next((shape for shape in shapes if shape.kind == "table" and shape.shape_name == "表格 8"), None)
    formulas = sorted((shape for shape in shapes if shape.kind == "ole"), key=lambda shape: shape.top)
    if table is None or len(formulas) != 6:
        raise RuntimeError("未识别到表格 8 与六个 Equation OLE 对象")
    bindings = {
        f"shape:{table.shape_id}#1x1": {
            "type": "text_template", "source": "f", "shape": table.shape_name,
            "options": {"shape_id": table.shape_id, "row": 1, "column": 1,
                        "template": "{ppt.product_info}"},
        }
    }
    for shape in shapes:
        if shape.kind == "text" and "产品+浇排正面" in shape.text:
            bindings[f"shape:{shape.shape_id}"] = {
                "type": "image_region", "source": "i.productRunnerFrontImg[0]", "shape": shape.shape_name,
                "required": False, "options": {"shape_id": shape.shape_id, "fit": "contain"},
            }
        elif shape.kind == "text" and "产品+浇排反面" in shape.text:
            bindings[f"shape:{shape.shape_id}"] = {
                "type": "image_region", "source": "i.productRunnerBackImg[0]", "shape": shape.shape_name,
                "required": False, "options": {"shape_id": shape.shape_id, "fit": "contain"},
            }
    for shape, formula in zip(formulas, FORMULAS):
        bindings[f"shape:{shape.shape_id}"] = {
            "type": "formula", "source": "f", "shape": shape.shape_name,
            "options": {"shape_id": shape.shape_id, "template": formula, "dpi": 180},
        }
    return DeckSlide(source=1, bindings=bindings)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data", type=Path, help="project JSON; omitted uses built-in demo data")
    parser.add_argument("--front", type=Path)
    parser.add_argument("--back", type=Path)
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8")) if args.data else demo_state()
    data.setdefault("i", {})
    if args.front:
        data["i"]["productRunnerFrontImg"] = [args.front]
    if args.back:
        data["i"]["productRunnerBackImg"] = [args.back]
    deck = DeckDefinition(
        template="product-analysis", output_mode="in_place", slides=[build_slide(args.template)]
    )
    result = TemplateEngine(args.template).generate(deck, data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(result.buffer)
    print(json.dumps({"output": str(args.output), "slides": result.slide_count,
                      "stats": dict(result.stats)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
