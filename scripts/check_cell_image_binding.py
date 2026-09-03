"""Reproduce legacy cell-image bindings without modifying the saved scheme."""
import hashlib
import json
import sys
from pathlib import Path

from app.main import _registry
from app.demo import demo_state
from app.report.ppt.deck import DeckDefinition
from app.report.ppt.template_engine import TemplateEngine
from app.report.ppt.slide_preview import render_slide_preview


def main():
    scheme_path = Path('data/schemes/tp-dfm--v1-0.json')
    before = hashlib.sha256(scheme_path.read_bytes()).hexdigest()
    scheme = json.loads(scheme_path.read_text(encoding='utf-8'))
    deck = DeckDefinition(template=scheme['template'], **scheme['deck'])
    if '--control' in sys.argv:
        deck.slides[-1].bindings.pop('shape:11#3x1', None)
    if '--single' in sys.argv:
        deck.slides = deck.slides[-1:]
        deck.template = deck.slides[0].template
    pick = sys.argv[sys.argv.index('--pick') + 1] if '--pick' in sys.argv else ''
    if pick:
        deck.slides = [deck.slides[int(i)-1] for i in pick.split(',')]
    registry = _registry()
    templates = {p.template: registry.resolve(p.template).path for p in deck.slides if p.template}
    data = demo_state()
    # Use an existing sample image as a diagnostic input, not as user report content.
    data['i']['productRunnerFrontImg'] = data['i']['logoImg']
    result = TemplateEngine(registry.resolve(deck.template).path).generate(deck, data, template_map=templates)
    out = Path('output/cell-image-check')
    out.mkdir(parents=True, exist_ok=True)
    target = out / ('legacy-scheme' + ('-control' if '--control' in sys.argv else '-cell-image') + ('-single' if '--single' in sys.argv else '') + ('-pick'+pick if pick else '') + '.pptx')
    target.write_bytes(result.buffer)
    print(f'Generated {result.slide_count} pages: {target}', flush=True)
    for page in (range(1, result.slide_count+1) if '--all' in sys.argv else [result.slide_count]):
        print(render_slide_preview(target, page, out / 'rendered'), flush=True)
    assert before == hashlib.sha256(scheme_path.read_bytes()).hexdigest()


if __name__ == '__main__':
    main()
