"""Plan table continuations against the original fixed table frame, before filling."""
import math
import unicodedata
from dataclasses import replace

from lxml import etree

from .shape_binding import NS, ShapeBindingError, find_shape
from .text_binding import PathResolver


def _text_height(cell, value, width):
    """Conservative wrapping estimate in EMU; never shrink the template font."""
    props = cell.find('a:tcPr', NS)
    margin = lambda name, default: int(props.get(name, default)) if props is not None else default
    available = max(1, width - margin('marL', 91440) - margin('marR', 91440))
    sizes = cell.xpath('.//a:rPr/@sz | .//a:defRPr/@sz | .//a:endParaRPr/@sz', namespaces=NS)
    font = max([float(s) / 100 for s in sizes] or [14]) * 12700
    # Latin glyphs average 0.6 em; CJK/full-width glyphs 1 em. Leave a 10% safety margin.
    lines = 0
    for line in str(value if value is not None else '').replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        advance = sum(1 if unicodedata.east_asian_width(c) in 'WF' else (2.4 if c == '\t' else .6) for c in line)
        lines += max(1, math.ceil(advance * font * 1.1 / available))
    spacing = cell.xpath('.//a:lnSpc/a:spcPct/@val', namespaces=NS)
    line_height = font * max([float(s) / 100000 for s in spacing] or [1.25])
    points = cell.xpath('.//a:lnSpc/a:spcPts/@val', namespaces=NS)
    if points:
        line_height = max(line_height, max(float(s) for s in points) * 127)
    extra = cell.xpath('.//a:spcBef/a:spcPts/@val | .//a:spcAft/a:spcPts/@val', namespaces=NS)
    return math.ceil(lines * line_height + sum(float(s) * 127 for s in extra)
                     + margin('marT', 45720) + margin('marB', 45720))


def table_chunks(shape, records, options, slide_height):
    tables = shape.xpath('.//a:tbl', namespaces=NS)
    if not tables:
        raise ShapeBindingError('绑定对象不是表格')
    table = tables[0]
    rows = table.findall('a:tr', NS)
    start = int(options.get('start_row', 1))
    if not 0 <= start < len(rows):
        raise ShapeBindingError('表头之后需要至少一条样式参考数据行')
    style = int(options.get('style_row', start))
    if not start <= style < len(rows):
        raise ShapeBindingError('样式参考行必须位于模板数据区域')
    reference = rows[style]
    cells = reference.findall('a:tc', NS)
    widths = [int(c.get('w')) for c in table.findall('a:tblGrid/a:gridCol', NS)]
    mapping = options.get('columns_map')
    mapping = ({int(k): v for k, v in mapping.items()} if mapping is not None
               else dict(enumerate(options.get('columns_keys') or [])))
    minimum_height = 1
    for record in records:
        for col, cell in enumerate(cells):
            value = record.get(mapping[col], '') if col in mapping else ''.join(cell.xpath('.//a:t/text()', namespaces=NS))
            width = widths[col] if col < len(widths) else 914400
            minimum_height = max(minimum_height, _text_height(cell, value, width))
    xfrm = shape.find('p:xfrm', NS)
    total = sum(int(r.get('h', 0)) for r in rows)
    if xfrm is not None:
        ext, off = xfrm.find('a:ext', NS), xfrm.find('a:off', NS)
        if ext is not None:
            total = min(total, int(ext.get('cy')))
        if off is not None:
            total = min(total, slide_height - int(off.get('y')))
    budget = total - sum(int(r.get('h', 0)) for r in rows[:start])
    if budget <= 0:
        raise ShapeBindingError('表头之后没有可用的数据区域，请调整模板表格')
    if records and minimum_height > budget:
        raise ShapeBindingError('单条表格内容超出一页可用高度，请缩短内容或在数据中拆成多条记录')
    raw_limit = options.get('rows_per_page')
    try:
        limit = int(raw_limit or 0)
        valid = raw_limit in (None, '') or (not isinstance(raw_limit, bool) and float(raw_limit) == limit)
    except (TypeError, ValueError, OverflowError):
        valid = False
        limit = 0
    if not valid or limit < 0:
        raise ShapeBindingError('每页条数必须为正整数或自动')
    if limit:
        # Explicit count controls layout, not merely an upper bound on automatic capacity.
        # Use the same height on every continuation, including a partially filled last page.
        height = budget // limit
        if height < minimum_height:
            maximum = max(1, budget // minimum_height)
            raise ShapeBindingError(f'每页 {limit} 行放不下当前文字；保持模板字号最多可放 {maximum} 行。'
                                    '请减少每页行数、缩短内容，或留空自动分页')
        capacity = limit
    else:
        height = max(minimum_height, int(reference.get('h', 0)), 1)
        if records and height > budget:
            raise ShapeBindingError('样式参考行高度超出数据区域，请更换参考行或填写每页数据行数')
        capacity = max(1, budget // height)
    return [(records[i:i + capacity], height, style) for i in range(0, len(records), capacity)] or [([], height, style)]


def paginate_op(package, op, context):
    root = etree.fromstring(package.read(package.slide_parts()[op.source_index]))
    pres = etree.fromstring(package.read('ppt/presentation.xml'))
    size = pres.find('p:sldSz', NS)
    slide_height = int(size.get('cy'))
    result = []
    for item in op.items:
        resolver = PathResolver(tuple(([item] if item is not None else []) + [context]))
        tables = {}
        for key, spec in op.bindings.items():
            if spec.type != 'table_rows' or spec.options.get('paginate', True) is False:
                continue
            value, found = resolver.resolve(spec.source)
            if not found:
                continue
            records = [r for r in (value if isinstance(value, (list, tuple)) else [value]) if isinstance(r, dict)]
            try:
                shape = find_shape(root, spec.shape or key, shape_id=spec.options.get('shape_id'))
                tables[key] = table_chunks(shape, records, spec.options, slide_height)
            except ShapeBindingError as exc:
                if not spec.required:
                    continue
                raise ShapeBindingError(f'第 {op.source_index} 页表格「{spec.shape or key}」：{exc}') from exc
        count = max([len(pages) for pages in tables.values()] or [1])
        for page in range(count):
            # Parallel tables advance together; an exhausted table keeps its header, not stale records.
            overrides = {key: pages[page] if page < len(pages) else ([], pages[0][1], pages[0][2])
                         for key, pages in tables.items()}
            result.append(replace(op, items=(item,), table_data=overrides))
    return result
