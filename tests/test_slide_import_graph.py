import posixpath
import unittest

from lxml import etree

from app.report.ppt.deck import DeckDefinition, DeckSlide
from app.report.ppt.openxml.package_editor import OoxmlPackage
from app.report.ppt.template_engine import TemplateEngine
from tests.test_table_pagination import fixture


class SlideImportGraphTests(unittest.TestCase):
    def test_equal_layout_xml_with_different_source_dependencies_is_not_shared(self):
        first = OoxmlPackage(fixture())
        second = OoxmlPackage(fixture())
        theme_a = first.read('ppt/theme/theme1.xml')
        theme_b = theme_a.replace(b'000000', b'123456')
        self.assertNotEqual(theme_a, theme_b)
        second.write('ppt/theme/theme1.xml', theme_b)
        deck = DeckDefinition(template='base', slides=[DeckSlide(source=1, template='a'), DeckSlide(source=1, template='b')])
        result = TemplateEngine(fixture()).generate(deck, {}, template_map={'a': first.save(), 'b': second.save()})
        out = OoxmlPackage(result.buffer)

        def dependency(part, kind):
            rel_path = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
            rels = etree.fromstring(out.read(rel_path))
            rel = next(r for r in rels if r.get('Type').endswith('/' + kind))
            return posixpath.normpath(posixpath.join(posixpath.dirname(part), rel.get('Target')))

        actual = []
        for part in out.slide_parts().values():
            layout = dependency(part, 'slideLayout')
            master = dependency(layout, 'slideMaster')
            theme = dependency(master, 'theme')
            actual.append(out.read(theme))
        self.assertEqual([theme_a, theme_b], actual)


if __name__ == '__main__':
    unittest.main()
