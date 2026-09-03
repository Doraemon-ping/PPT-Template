"""Character-range bindings that leave unselected PowerPoint runs intact."""
from .shape_binding import NS, ShapeBindingError


def text_map(element):
    parts, spans, offset = [], [], 0
    for index, paragraph in enumerate(element.xpath('.//a:p', namespaces=NS)):
        if index:
            parts.append('\n')
            offset += 1
        for node in paragraph.iter():
            if node.tag == '{%s}t' % NS['a']:
                value = node.text or ''
                spans.append((node, offset, offset + len(value)))
                parts.append(value)
                offset += len(value)
            elif node.tag == '{%s}br' % NS['a']:
                parts.append('\n')
                offset += 1
    return ''.join(parts), spans


def full_text(element):
    return text_map(element)[0]


def text_target(shape, options):
    if 'row' not in options and 'column' not in options:
        return shape
    try:
        row, col = int(options['row']), int(options['column'])
        if row < 0 or col < 0:
            raise IndexError
        return shape.xpath('.//a:tbl/a:tr', namespaces=NS)[row].xpath('./a:tc', namespaces=NS)[col]
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise ShapeBindingError('局部文本绑定的表格行列不存在') from exc


def replace_text_segments(target, options, resolver):
    original, spans = text_map(target)
    if original != options.get('original_text'):
        raise ShapeBindingError('模板原文已变化，请重新选择文字片段并绑定')
    replacements = options.get('replacements')
    if not isinstance(replacements, list) or not replacements:
        raise ShapeBindingError('请至少选择一处文字片段')
    edits, last_end = [], -1
    try:
        ordered = sorted(replacements, key=lambda entry: entry['start'])
        for entry in ordered:
            start, end = entry['start'], entry['end']
            if type(start) is not int or type(end) is not int or not (0 <= start < end <= len(original)):
                raise ValueError
            if start < last_end or original[start:end] != entry['text'] or '\n' in original[start:end]:
                raise ValueError
            last_end = end
            value, found = resolver.resolve(entry['source'])
            # Missing optional form data must not erase the selected source text.
            if not found or value is None or value == '':
                continue
            if isinstance(value, (dict, list, tuple)) or str(value).startswith('data:image/'):
                raise ShapeBindingError('文字片段只能绑定文字或数字，不能绑定图片或表格')
            edits.append((start, end, str(value)))
    except (KeyError, TypeError, ValueError) as exc:
        raise ShapeBindingError('文字片段无效、重叠或跨行，请重新选择') from exc
    # Right-to-left replacement keeps offsets of earlier selections valid.
    for start, end, value in reversed(edits):
        touched = [(node, left, right) for node, left, right in spans if left < end and right > start]
        for index, (node, left, right) in enumerate(touched):
            text = node.text or ''
            node.text = text[:max(0, start-left)] + (value if index == 0 else '') + text[min(len(text), end-left):]
    return len(edits)
