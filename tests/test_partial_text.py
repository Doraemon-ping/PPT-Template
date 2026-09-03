import unittest
from lxml import etree

from app.report.ppt.openxml.partial_text import full_text, replace_text_segments, text_target
from app.report.ppt.openxml.shape_binding import NS, ShapeBindingError
from app.report.ppt.openxml.text_binding import PathResolver
from app.report.ppt.openxml.shape_inventory import CellInfo


class PartialTextTests(unittest.TestCase):
    def test_inventory_has_untruncated_original_text(self):
        text = '重量：7kg\n' * 100
        cell = CellInfo(0, 0, 0, 0, 1, 1, text, text)
        self.assertEqual(text, cell.to_dict()['full_text'])
        self.assertEqual(120, len(cell.to_dict()['text']))

    def fixture(self):
        return etree.fromstring(('''<p:sp xmlns:p="%s" xmlns:a="%s"><p:txBody>
          <a:p><a:pPr marL="123"/><a:r><a:rPr b="1"/><a:t>成品重量：</a:t></a:r>
          <a:r><a:rPr sz="1400"/><a:t>7.</a:t></a:r><a:r><a:rPr i="1"/><a:t>14</a:t></a:r>
          <a:r><a:rPr sz="1100"/><a:t>kg；毛坯：7.14kg</a:t></a:r><a:endParaRPr/></a:p>
          <a:p><a:r><a:t>材料：铝合金😀</a:t></a:r></a:p>
        </p:txBody></p:sp>''' % (NS['p'], NS['a'])).encode())

    def options(self, node, *entries):
        text = full_text(node)
        return {'original_text': text, 'replacements': [
            {'start': start, 'end': start+len(word), 'text': word, 'source': source}
            for start, word, source in entries
        ]}

    def test_cross_run_replacement_preserves_styles_and_other_text(self):
        node = self.fixture()
        styles = [etree.tostring(n) for n in node.xpath('.//a:rPr|.//a:pPr|.//a:endParaRPr', namespaces=NS)]
        replace_text_segments(node, self.options(node, (5, '7.14', 'f.weight')), PathResolver(({'f': {'weight': 3.85}},)))
        self.assertEqual('成品重量：3.85kg；毛坯：7.14kg\n材料：铝合金😀', full_text(node))
        self.assertEqual(styles, [etree.tostring(n) for n in node.xpath('.//a:rPr|.//a:pPr|.//a:endParaRPr', namespaces=NS)])

    def test_duplicate_text_is_replaced_by_position(self):
        node = self.fixture()
        second = full_text(node).rindex('7.14')
        replace_text_segments(node, self.options(node, (second, '7.14', 'f.weight')), PathResolver(({'f': {'weight': 4.2}},)))
        self.assertIn('成品重量：7.14kg；毛坯：4.2kg', full_text(node))

    def test_multiple_replacements_in_same_run_and_unicode(self):
        node = etree.fromstring(('<p:sp xmlns:p="%s" xmlns:a="%s"><a:p><a:r><a:t>😀A=12 B=34 mm</a:t></a:r></a:p></p:sp>' % (NS['p'], NS['a'])).encode())
        replace_text_segments(node, self.options(node, (3, '12', 'f.a'), (8, '34', 'f.b')),
                              PathResolver(({'f': {'a': 123456, 'b': 0}},)))
        self.assertEqual('😀A=123456 B=0 mm', full_text(node))

    def test_missing_data_keeps_original_segment(self):
        node = self.fixture()
        before = full_text(node)
        replace_text_segments(node, self.options(node, (5, '7.14', 'f.missing')), PathResolver(({'f': {}},)))
        self.assertEqual(before, full_text(node))

    def test_template_change_is_rejected(self):
        node = self.fixture()
        options = self.options(node, (5, '7.14', 'f.weight'))
        options['original_text'] += 'changed'
        with self.assertRaisesRegex(ShapeBindingError, '原文已变化'):
            replace_text_segments(node, options, PathResolver(({},)))

    def test_overlapping_ranges_and_cross_line_are_rejected(self):
        node = self.fixture()
        with self.assertRaises(ShapeBindingError):
            replace_text_segments(node, self.options(node, (5, '7.14', 'f.a'), (7, '14', 'f.b')), PathResolver(({},)))
        text = full_text(node)
        start = text.index('\n') - 1
        with self.assertRaises(ShapeBindingError):
            replace_text_segments(node, self.options(node, (start, text[start:start+3], 'f.a')), PathResolver(({},)))

    def test_image_or_object_value_is_rejected(self):
        for value in ({'bad': 1}, ['bad'], 'data:image/png;base64,abc'):
            node = self.fixture()
            with self.assertRaises(ShapeBindingError):
                replace_text_segments(node, self.options(node, (5, '7.14', 'f.a')), PathResolver(({'f': {'a': value}},)))

    def test_table_target_does_not_touch_other_cells(self):
        shape = etree.fromstring(('<p:graphicFrame xmlns:p="%s" xmlns:a="%s"><a:tbl><a:tr><a:tc><a:p><a:r><a:t>重量7kg</a:t></a:r></a:p></a:tc><a:tc><a:p><a:r><a:t>不变</a:t></a:r></a:p></a:tc></a:tr></a:tbl></p:graphicFrame>' % (NS['p'], NS['a'])).encode())
        target = text_target(shape, {'row': 0, 'column': 0})
        replace_text_segments(target, self.options(target, (2, '7', 'f.a')), PathResolver(({'f': {'a': 9}},)))
        self.assertEqual('重量9kg', full_text(target))
        self.assertEqual('不变', full_text(text_target(shape, {'row': 0, 'column': 1})))
