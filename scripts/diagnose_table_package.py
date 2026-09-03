from pathlib import Path
from app.main import _registry
from app.report.ppt.deck import DeckDefinition, DeckSlide
from app.report.ppt.template_engine import TemplateEngine
from app.report.ppt.slide_preview import render_slide_preview
from app.report.ppt.openxml.package_editor import OoxmlPackage
from app.report.ppt.openxml.slide_repeater import rebuild_presentation

root = Path('output/table-pagination-check/diagnostic')
root.mkdir(parents=True, exist_ok=True)
source = _registry().resolve('3').path
binding = {'rows': {'type': 'table_rows', 'shape': '表格 3', 'source': 't.rows',
                   'options': {'shape_id': 4, 'columns_keys': ['a','b','c','d']}}}
for name, mode, slides, payload in [
    ('zip-only', 'in_place', [DeckSlide(source=1)], {}),
    ('fill-only', 'in_place', [DeckSlide(source=1, bindings=binding)], {'t': {'rows':[{'a':'test'}]*2}}),
    ('rebuild-only', 'deck', [DeckSlide(source=1)], {}),
    ('clone-only', 'deck', [DeckSlide(source=1),DeckSlide(source=1)], {}),
]:
    deck = DeckDefinition(template='3', output_mode=mode, slides=slides)
    result = TemplateEngine(source).generate(deck, payload)
    target = root / (name+'.pptx')
    target.write_bytes(result.buffer)
    try:
        print(name, render_slide_preview(target, 1, root/'png'), flush=True)
    except Exception as exc:
        print(name, 'FAIL', str(exc), flush=True)

for count in (1, 2):
    package = OoxmlPackage(source)
    parts = []
    for i in range(2, count+2):
        part = f'ppt/slides/slide{i}.xml'
        package.write(part, package.read('ppt/slides/slide1.xml'))
        package.write(package.rels_part_for(part), package.read('ppt/slides/_rels/slide1.xml.rels'))
        package.ensure_content_type(part, 'application/vnd.openxmlformats-officedocument.presentationml.slide+xml')
        parts.append(part)
    rebuild_presentation(package, parts)
    target = root / f'identity-{count}.pptx'
    target.write_bytes(package.save())
    try:
        print(target.name, render_slide_preview(target, 1, root/'png'), flush=True)
    except Exception as exc:
        print(target.name, 'FAIL', str(exc), flush=True)
