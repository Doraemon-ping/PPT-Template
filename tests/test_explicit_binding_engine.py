# -*- coding: utf-8 -*-
import io
import tempfile
import unittest
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from app.demo import demo_state
from app.report.ppt.deck import DeckDefinition, DeckSlide
from app.report.ppt.template_engine import TemplateEngine

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "templates" / "DFM_Template_Placeholder_Demo.pptx"
TABLE = ROOT / "templates" / "DFM_Template_Table_Demo.pptx"

HISTORY_TEMPLATE = ROOT / "data" / "_history_fixture.pptx"


def _build_history_fixture() -> Path:
    """构造“DFM 履历表”式模板页：表头 + 3 行空数据行，5 列。"""
    if HISTORY_TEMPLATE.exists():
        return HISTORY_TEMPLATE
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.625)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    table_shape = slide.shapes.add_table(4, 5, Inches(0.4), Inches(0.5), Inches(9.2), Inches(3.2))
    table_shape.name = "HIST_TABLE"
    headers = ["版本", "日期", "编制/修订", "主要修改内容", "备注"]
    for col, header in enumerate(headers):
        table_shape.table.cell(0, col).text = header
    for row in range(1, 4):
        for col in range(5):
            table_shape.table.cell(row, col).text = ""
    HISTORY_TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    prs.save(HISTORY_TEMPLATE)
    return HISTORY_TEMPLATE


class ExplicitShapeBindingEngineTests(unittest.TestCase):
    def test_missing_or_empty_images_keep_template_content(self):
        import zipfile
        for kind in ('image', 'image_region'):
            for images in ({}, {'front': []}, {'front': [None]}, {'front': ['']}, {'front': ['  ']}):
                with self.subTest(kind=kind, images=images):
                    data = demo_state()
                    data['i'] = images
                    control = TemplateEngine(DEMO).generate(DeckDefinition(template='demo', output_mode='in_place', slides=[DeckSlide(source=2)]), data)
                    deck = DeckDefinition(template='demo', output_mode='in_place', slides=[DeckSlide(source=2, bindings={
                        'missing_image': {'type': kind, 'source': 'i.front[0]', 'shape': 'PART_IMAGE', 'required': True},
                    })])
                    result = TemplateEngine(DEMO).generate(deck, data)
                    self.assertEqual(['i.front[0]'], result.stats['images_missing'])
                    self.assertEqual(1, result.stats['bindings_skipped'])
                    self.assertEqual(0, result.stats['images_bound'])
                    self.assertTrue(result.warnings)
                    with zipfile.ZipFile(control.bytes_io) as before, zipfile.ZipFile(result.bytes_io) as after:
                        self.assertEqual(before.namelist(), after.namelist())
                        for name in before.namelist():
                            self.assertEqual(before.read(name), after.read(name), name)

    def test_supplied_invalid_image_still_raises(self):
        deck = DeckDefinition(template='demo', slides=[DeckSlide(source=2, bindings={
            'bad_image': {'type': 'image', 'source': 'i.front[0]', 'shape': 'PART_IMAGE'},
        })])
        with self.assertRaisesRegex(Exception, '图片绑定失败'):
            TemplateEngine(DEMO).generate(deck, {'i': {'front': ['not-an-image']}})

    def test_text_binding_by_shape_name_without_placeholders(self):
        deck = DeckDefinition(template="demo", output_mode="deck", slides=[
            DeckSlide(source=1, bindings={
                "COVER_PART_NUMBER": {"type": "text", "source": "f.partNo"},
                "COVER_CUSTOMER": {"type": "text", "source": "f.custName"},
            }),
        ])
        result = TemplateEngine(DEMO).generate(deck, demo_state())
        self.assertEqual(2, result.stats["bindings_applied"])
        prs = Presentation(result.bytes_io)
        texts = [sh.text for sh in prs.slides[0].shapes if getattr(sh, "has_text_frame", False) and sh.text.strip()]
        self.assertIn("TP-HPDC-2026-0087", texts)
        self.assertIn("XXXX 汽车", texts)

    def test_missing_source_raises_for_required_binding(self):
        deck = DeckDefinition(template="demo", output_mode="deck", slides=[
            DeckSlide(source=1, bindings={
                "COVER_PART_NUMBER": {"type": "text", "source": "no.such.field"},
            }),
        ])
        with self.assertRaises(Exception):
            TemplateEngine(DEMO).generate(deck, demo_state())

    def test_optional_missing_shape_is_skipped(self):
        deck = DeckDefinition(template="demo", output_mode="deck", slides=[
            DeckSlide(source=1, bindings={
                "COVER_PART_NUMBER": {"type": "text", "source": "f.partNo", "required": False},
                "NOT_A_SHAPE": {"type": "text", "source": "f.partNo", "required": False},
            }),
        ])
        result = TemplateEngine(DEMO).generate(deck, demo_state())
        self.assertEqual(1, result.stats["bindings_applied"])
        self.assertEqual(1, result.stats["bindings_skipped"])

    def test_table_cell_binding_by_shape_name(self):
        deck = DeckDefinition(template="table-demo", output_mode="deck", slides=[
            DeckSlide(source=1, bindings={
                "PART_TABLE": {"type": "table_cell", "source": "f.material",
                               "options": {"row": 4, "column": 1}},
            }),
        ])
        result = TemplateEngine(TABLE).generate(deck, demo_state())
        prs = Presentation(result.bytes_io)
        table = prs.slides[0].shapes[0].table
        self.assertEqual("AlSi10MnMg", table.cell(4, 1).text.strip())

    def test_image_binding_through_explicit_spec(self):
        deck = DeckDefinition(template="demo", output_mode="deck", slides=[
            DeckSlide(source=2, bindings={
                "PART_IMAGE": {"type": "image", "source": "i.logoImg[0]"},
            }),
        ])
        result = TemplateEngine(DEMO).generate(deck, demo_state())
        self.assertEqual(1, result.stats["images_bound"])
        prs = Presentation(result.bytes_io)
        pictures = [shape for shape in prs.slides[0].shapes if shape.shape_type == 13]
        self.assertEqual(1, len(pictures))

    def test_image_binding_to_text_field_raises_clear_error(self):
        """文本字段（公司名称等）绑到图片对象 → 报“不是图片”，而不是文件不存在。"""
        deck = DeckDefinition(template="demo", output_mode="deck", slides=[
            DeckSlide(source=2, bindings={
                "PART_IMAGE": {"type": "image", "source": "f.company"},
            }),
        ])
        state = demo_state()
        with self.assertRaises(Exception) as ctx:
            TemplateEngine(DEMO).generate(deck, state)
        message = str(ctx.exception)
        self.assertIn("图片绑定失败", message)
        self.assertIn("不是图片", message)
        self.assertNotIn("No such file", message)

    def test_image_binding_to_text_field_optional_is_skipped(self):
        deck = DeckDefinition(template="demo", output_mode="deck", slides=[
            DeckSlide(source=2, bindings={
                "PART_IMAGE": {"type": "image", "source": "f.company", "required": False},
            }),
        ])
        result = TemplateEngine(DEMO).generate(deck, demo_state())
        self.assertEqual(1, result.stats["bindings_skipped"])
        self.assertEqual(0, result.stats["images_bound"])

    def test_binding_empty_value_keep_leaves_template_text(self):
        deck = DeckDefinition(template="demo", output_mode="deck", slides=[
            DeckSlide(source=2, bindings={
                "PART_LABEL_毛坯重量 (kg)": {"type": "text", "source": "f.custName",
                                           "options": {"empty": "keep"}},
            }),
        ])
        state = demo_state()
        state["f"] = dict(state["f"])
        state["f"]["custName"] = ""
        result = TemplateEngine(DEMO).generate(deck, state)
        prs = Presentation(result.bytes_io)
        texts = [sh.text for sh in prs.slides[0].shapes if getattr(sh, "has_text_frame", False)]
        self.assertTrue(any("毛坯重量 (kg)" in text for text in texts))  # 空值且 keep -> 保留模板文本

    def test_table_rows_fills_whole_history_table(self):
        """整表填入 t.dfmHist：保留表头、写 2 行数据、删除多余空行。"""
        fixture = _build_history_fixture()
        deck = DeckDefinition(template="history", output_mode="deck", slides=[
            DeckSlide(source=1, bindings={
                "fill1": {
                    "type": "table_rows",
                    "source": "t.dfmHist",
                    "shape": "HIST_TABLE",
                    "options": {
                        "columns_keys": ["ver", "date", "author", "content", "remark"],
                        "start_row": 1,
                    },
                },
            }),
        ])
        result = TemplateEngine(fixture).generate(deck, demo_state())
        prs = Presentation(result.bytes_io)
        table = prs.slides[0].shapes[0].table
        rows = len(table.rows)
        self.assertEqual(3, rows)  # 表头 + 2 条履历（模板 3 个空数据行被删 1 行）
        self.assertEqual("版本", table.cell(0, 0).text.strip())
        self.assertEqual("A0", table.cell(1, 0).text.strip())
        self.assertEqual("2026-08-18", table.cell(1, 1).text.strip())
        self.assertEqual("首次发布 DFM 报告", table.cell(1, 3).text.strip())
        self.assertEqual("A1", table.cell(2, 0).text.strip())

    def test_table_rows_columns_map_partial_and_reorder(self):
        """PPT 表格列数与表单不一致：用 columns_map 只填指定列、可换列顺序。"""
        # 3 列表格：表头 [A,B,C]；把 dfmHist 的 content 放第0列、ver 放第2列
        prs = Presentation()
        prs.slide_width = Inches(10)
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        shp = slide.shapes.add_table(4, 3, Inches(0.4), Inches(0.5), Inches(9.2), Inches(3.0))
        shp.name = "MAP_TABLE"
        for col, header in enumerate(["内容", "其它", "版本"]):
            shp.table.cell(0, col).text = header
        for row in range(1, 4):
            for col in range(3):
                shp.table.cell(row, col).text = ""
        buffer = io.BytesIO()
        prs.save(buffer)
        deck = DeckDefinition(template="map", output_mode="deck", slides=[
            DeckSlide(source=1, bindings={
                "f1": {"type": "table_rows", "source": "t.dfmHist", "shape": "MAP_TABLE",
                       "options": {"columns_map": {0: "content", 2: "ver"}, "start_row": 1}},
            }),
        ])
        result = TemplateEngine(buffer).generate(deck, demo_state())
        out = Presentation(result.bytes_io)
        table = out.slides[0].shapes[0].table
        self.assertEqual(3, len(table.rows))  # 表头 + 2 条数据
        self.assertEqual("首次发布 DFM 报告", table.cell(1, 0).text.strip())
        self.assertEqual("A0", table.cell(1, 2).text.strip())
        self.assertEqual("A1", table.cell(2, 2).text.strip())
        # 未映射的第 1 列保持为空
        self.assertEqual("", table.cell(1, 1).text.strip())

    def test_table_rows_keeps_title_and_header_rows(self):
        """保留 2 行（标题+表头），数据从第 3 行开始写，两行数据都填。"""
        prs = Presentation()
        prs.slide_width = Inches(10)
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        shp = slide.shapes.add_table(4, 5, Inches(0.4), Inches(0.5), Inches(9.2), Inches(3.0))
        shp.name = "HIST_TABLE"
        shp.table.cell(0, 0).text = "DFM 履历表"          # 第 1 行：标题
        for col, header in enumerate(["版本", "日期", "编制/修订", "主要修改内容", "备注"]):
            shp.table.cell(1, col).text = header           # 第 2 行：表头
        for row in range(2, 4):                            # 第 3、4 行：空数据行
            for col in range(5):
                shp.table.cell(row, col).text = ""
        buffer = io.BytesIO()
        prs.save(buffer)
        deck = DeckDefinition(template="title2", output_mode="deck", slides=[
            DeckSlide(source=1, bindings={
                "f1": {"type": "table_rows", "source": "t.dfmHist", "shape": "HIST_TABLE",
                       "options": {"columns_keys": ["ver", "date", "author", "content", "remark"],
                                   "start_row": 2}},
            }),
        ])
        result = TemplateEngine(buffer).generate(deck, demo_state())
        out = Presentation(result.bytes_io)
        table = out.slides[0].shapes[0].table
        self.assertEqual(4, len(table.rows))  # 标题 + 表头 + 2 条数据
        self.assertEqual("DFM 履历表", table.cell(0, 0).text.strip())
        self.assertEqual("版本", table.cell(1, 0).text.strip())
        self.assertEqual("A0", table.cell(2, 0).text.strip())
        self.assertEqual("首次发布 DFM 报告", table.cell(2, 3).text.strip())
        self.assertEqual("A1", table.cell(3, 0).text.strip())
        self.assertEqual("客户评审后更新", table.cell(3, 4).text.strip())

    def test_table_rows_neutralizes_vertical_merges(self):
        """模板第 2 行是纵向合并延续行（vMerge）时，先拆开再填，两行都可见。"""
        import zipfile

        prs = Presentation()
        prs.slide_width = Inches(10)
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        shp = slide.shapes.add_table(3, 4, Inches(0.4), Inches(0.5), Inches(9.2), Inches(2.6))
        shp.name = "HIST_TABLE"
        for col, header in enumerate(["版本", "日期", "主要修改内容", "备注"]):
            shp.table.cell(0, col).text = header
        for row in range(1, 3):
            for col in range(4):
                shp.table.cell(row, col).text = ""
        buffer = io.BytesIO()
        prs.save(buffer)
        # 手工给第 1 数据行加 rowSpan=2、第 2 数据行加 vMerge（模拟 PowerPoint 合并表）
        buf = buffer.getvalue()
        import zipfile as zf

        ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
        with zf.ZipFile(io.BytesIO(buf)) as src:
            xml = src.read("ppt/slides/slide1.xml")
        from lxml import etree

        root = etree.fromstring(xml)
        tbl = root.find(".//{%s}tbl" % ns_a)
        trs = tbl.findall("{%s}tr" % ns_a)
        row1, row2 = trs[1], trs[2]
        for tc in row1.findall("{%s}tc" % ns_a):
            tc.set("rowSpan", "2")
        for tc in row2.findall("{%s}tc" % ns_a):
            tc.set("vMerge", "1")
        merged_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        # 重建 zip
        out = io.BytesIO()
        with zf.ZipFile(io.BytesIO(buf)) as src, zf.ZipFile(out, "w") as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == "ppt/slides/slide1.xml":
                    data = merged_xml
                dst.writestr(info, data)
        out.seek(0)

        deck = DeckDefinition(template="vm", output_mode="deck", slides=[
            DeckSlide(source=1, bindings={
                "f1": {"type": "table_rows", "source": "t.dfmHist", "shape": "HIST_TABLE",
                       "options": {"columns_keys": ["ver", "date", "content", "remark"],
                                   "start_row": 1}},
            }),
        ])
        result = TemplateEngine(out.getvalue()).generate(deck, demo_state())
        generated = Presentation(result.bytes_io)
        table = generated.slides[0].shapes[0].table
        self.assertEqual("A0", table.cell(1, 0).text.strip())
        self.assertEqual("首次发布 DFM 报告", table.cell(1, 2).text.strip())
        self.assertEqual("A1", table.cell(2, 0).text.strip())
        # 输出中不应再残留 vMerge/rowSpan
        import re as _re

        with zf.ZipFile(io.BytesIO(result.buffer)) as arch:
            slide_parts = [n for n in arch.namelist() if _re.match(r"ppt/slides/slide\d+\.xml$", n)]
            self.assertTrue(slide_parts)
            out_xml = arch.read(slide_parts[0])
        out_root = etree.fromstring(out_xml)
        found_tcs = out_root.findall(".//{%s}tc" % ns_a)
        self.assertTrue(found_tcs)
        for tc in found_tcs:
            self.assertNotIn("vMerge", tc.attrib)
            self.assertNotIn("rowSpan", tc.attrib)

    def test_table_rows_missing_source_skips_not_error(self):
        """整表填入的表数据未提供（如 t.notExist）时跳过，不报错、不动模板。"""
        fixture = _build_history_fixture()
        deck = DeckDefinition(template="history", output_mode="deck", slides=[
            DeckSlide(source=1, bindings={
                "f1": {"type": "table_rows", "source": "t.notExist", "shape": "HIST_TABLE",
                       "options": {"columns_keys": ["ver", "date", "author", "content", "remark"], "start_row": 1}},
            }),
        ])
        result = TemplateEngine(fixture).generate(deck, demo_state())
        self.assertGreaterEqual(result.stats["bindings_skipped"], 1)
        prs = Presentation(result.bytes_io)
        table = prs.slides[0].shapes[0].table
        self.assertEqual(4, len(table.rows))  # 模板原样（表头+3空行，未清空）

    def test_demo_contains_default_tables(self):
        """示例数据补全默认表格（dfmHist / fileStat / issues …），任意 t.* 整表绑定可用。"""
        from app.demo import demo_state as _ds

        state = _ds()
        self.assertIn("fileStat", state["t"])
        self.assertGreaterEqual(len(state["t"]["fileStat"]), 6)
        self.assertIn("dfmHist", state["t"])

    def test_table_rows_duplicates_rows_when_data_longer(self):
        """数据行多于模板空行：自动克隆数据行补足。"""
        fixture = _build_history_fixture()
        # 模板只有 1 个空数据行：手动把演示 dfmHist 造 3 条
        state = demo_state()
        state["t"] = dict(state["t"])
        state["t"]["dfmHist"] = [
            {"ver": "A0", "date": "2026-08-18", "author": "甲", "content": "首次发布", "remark": ""},
            {"ver": "A1", "date": "2026-09-01", "author": "乙", "content": "补充挤压销", "remark": "评审后"},
            {"ver": "A2", "date": "2026-09-10", "author": "丙", "content": "点冷优化", "remark": ""},
        ]
        # 构造只有表头 + 1 个空数据行（5 列）的模板，验证自动补行
        prs = Presentation()
        prs.slide_width = Inches(10)
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        shp = slide.shapes.add_table(2, 5, Inches(0.4), Inches(0.5), Inches(9.2), Inches(2.4))
        shp.name = "HIST_TABLE"
        for col, header in enumerate(["版本", "日期", "编制/修订", "主要修改内容", "备注"]):
            shp.table.cell(0, col).text = header
        for col in range(5):
            shp.table.cell(1, col).text = ""
        buffer = io.BytesIO()
        prs.save(buffer)
        deck = DeckDefinition(template="h2", output_mode="deck", slides=[
            DeckSlide(source=1, bindings={
                "f1": {"type": "table_rows", "source": "t.dfmHist", "shape": "HIST_TABLE",
                       "options": {"columns_keys": ["ver", "date", "author", "content", "remark"], "start_row": 1}},
            }),
        ])
        result = TemplateEngine(buffer).generate(deck, state)
        out = Presentation(result.bytes_io)
        table = out.slides[0].shapes[0].table
        self.assertEqual(3, len(out.slides))  # 固定模板容量：每页表头 + 1 行，自动续页
        self.assertEqual(2, len(table.rows))
        self.assertEqual("A2", out.slides[2].shapes[0].table.cell(1, 0).text.strip())


if __name__ == "__main__":
    unittest.main()
