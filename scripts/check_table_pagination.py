"""Generate a regression sample from the user's imported table template (read only)."""
from pathlib import Path
import hashlib
import sys

from app.main import _registry
from app.demo import demo_state
from app.report.ppt.deck import DeckDefinition, DeckSlide
from app.report.ppt.template_engine import TemplateEngine
from app.report.ppt.slide_preview import render_slide_preview


def main():
    record = _registry().resolve('3')
    before = hashlib.sha256(record.path.read_bytes()).hexdigest()
    out = Path('output/table-pagination-check')
    out.mkdir(parents=True, exist_ok=True)
    data = demo_state()
    base = data['t']['fileStat']
    data['t']['fileStat'] = [dict(base[i % len(base)], ver=f'A{i+1}') for i in range(13)]
    deck = DeckDefinition(template='3', slides=[DeckSlide(source=1, bindings={'rows': {
        'type': 'table_rows', 'source': 't.fileStat', 'shape': '表格 3',
        'options': {'shape_id': 4, 'start_row': 1, 'columns_keys': ['name', 'ver', 'state', 'remark']},
    }})])
    result = TemplateEngine(record.path).generate(deck, data)
    if '--cross' in sys.argv:
        deck.slides[0].template = '3'
        deck.template = '2'
        deck.slides.insert(0, DeckSlide(source=1))
        result = TemplateEngine(_registry().resolve('2').path).generate(deck, data, template_map={'3': record.path})
    target = out / ('cross-pagination-13-rows.pptx' if '--cross' in sys.argv else 'pagination-13-rows.pptx')
    target.write_bytes(result.buffer)
    print(f'Generated {result.slide_count} pages: {target}', flush=True)
    for page in ([1, 2, result.slide_count] if '--cross' in sys.argv else range(1, result.slide_count+1)):
        print(render_slide_preview(target, page, out / 'rendered'), flush=True)
    assert before == hashlib.sha256(record.path.read_bytes()).hexdigest()


if __name__ == '__main__':
    main()
