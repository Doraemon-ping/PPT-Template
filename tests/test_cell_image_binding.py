import base64
import unittest
from pathlib import Path

from lxml import etree

from app.report.ppt.deck import DeckDefinition, DeckSlide
from app.report.ppt.template_engine import TemplateEngine, TemplateEngineError
from app.report.ppt.openxml.package_editor import OoxmlPackage
from app.report.ppt.openxml.shape_binding import NS, find_shape
from tests.test_table_pagination import fixture
from tests.test_image_binding import _make_png


class CellImageBindingTests(unittest.TestCase):
    def generate(self, kind='image_region', images=None, row=1, column=1):
        deck = DeckDefinition(template='test', output_mode='in_place', slides=[DeckSlide(source=1, bindings={
            'cell': {'type': kind, 'source': 'i.front[0]', 'shape': 'DATA',
                     'options': {'row': row, 'column': column}},
        })])
        before = deck.model_dump()
        result = TemplateEngine(fixture()).generate(deck, {'i': images if images is not None else
            {'front': ['data:image/png;base64,' + base64.b64encode(_make_png()).decode()]}})
        self.assertEqual(before, deck.model_dump())
        return result, etree.fromstring(OoxmlPackage(result.buffer).read('ppt/slides/slide1.xml'))

    def test_new_and_legacy_cell_image_bindings_keep_table_and_other_cells(self):
        for kind in ('image_region', 'table_cell'):
            with self.subTest(kind=kind):
                result, root = self.generate(kind)
                source = etree.fromstring(OoxmlPackage(fixture()).read('ppt/slides/slide1.xml'))
                table = root.find('.//a:tbl', NS)
                old = source.find('.//a:tbl', NS)
                self.assertEqual(1, len(root.findall('.//p:pic', NS)))
                self.assertEqual(5, len(table.findall('a:tr', NS)))
                for i, (a, b) in enumerate(zip(old.findall('a:tr', NS), table.findall('a:tr', NS))):
                    for j, (c, d) in enumerate(zip(a.findall('a:tc', NS), b.findall('a:tc', NS))):
                        if (i, j) != (1, 1):
                            self.assertEqual(etree.tostring(c), etree.tostring(d))
                self.assertNotIn('data:image', ''.join(root.xpath('.//a:t/text()', namespaces=NS)))
                self.assertEqual(1, result.stats['bindings_applied'])

    def test_legacy_missing_image_keeps_all_source_content(self):
        _, root = self.generate('table_cell', images={})
        self.assertEqual(0, len(root.findall('.//p:pic', NS)))
        self.assertEqual('参考', root.find('.//a:tbl', NS).findall('a:tr', NS)[1].findall('a:tc', NS)[1].find('.//a:t', NS).text)

    def test_invalid_image_is_not_written_as_text(self):
        with self.assertRaisesRegex(TemplateEngineError, '图片绑定失败.*i.front'):
            self.generate('table_cell', images={'front': ['not-an-image']})

    def test_invalid_cell_has_actionable_error(self):
        with self.assertRaisesRegex(TemplateEngineError, '行列超出'):
            self.generate(row=20)

    def test_merged_tail_in_user_template_preserves_anchor_and_table(self):
        path = Path('data/templates/2/master.pptx')
        if not path.exists():
            self.skipTest('local user template not available')
        source = OoxmlPackage(path)
        original = etree.fromstring(source.read('ppt/slides/slide1.xml'))
        deck = DeckDefinition(template='2', output_mode='in_place', slides=[DeckSlide(source=1, bindings={
            'shape:11#3x1': {'type': 'table_cell', 'source': 'i.front[0]', 'shape': '表格 8',
                'options': {'row': 3, 'column': 1, 'shape_id': 11}}
        })])
        result = TemplateEngine(path).generate(deck, {'i': {'front': [_make_png()]}})
        root = etree.fromstring(OoxmlPackage(result.buffer).read('ppt/slides/slide1.xml'))
        before = find_shape(original, '表格 8', shape_id=11)
        after = find_shape(root, '表格 8', shape_id=11)
        self.assertEqual(etree.tostring(before), etree.tostring(after))
        picture = next(p for p in root.findall('.//p:pic', NS) if p.find('.//p:cNvPr', NS).get('name').endswith('[cell:3,1]'))
        new_id = picture.find('.//p:cNvPr', NS).get('id')
        self.assertNotIn(new_id, original.xpath('.//p:cNvPr/@id', namespaces=NS))
        y = int(picture.find('p:spPr/a:xfrm/a:off', NS).get('y'))
        top = int(after.find('p:xfrm/a:off', NS).get('y'))
        previous_rows = sum(int(r.get('h')) for r in after.findall('.//a:tr', NS)[:3])
        self.assertEqual(top + previous_rows + 12700, y)


if __name__ == '__main__':
    unittest.main()
