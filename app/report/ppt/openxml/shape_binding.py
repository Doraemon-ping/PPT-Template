# -*- coding: utf-8 -*-
"""Explicit shape-name bindings at the OOXML level.

Unlike the ``{path}`` placeholder convention (which binds by writing the path
inside the template text), these helpers bind a *shape name* to a data path.
They work on templates that have no placeholders at all — including the formal
84-page deck, whose objects only carry PowerPoint auto-generated names.
"""
from typing import Optional

from lxml import etree

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}

_SHAPE_TAGS = (
    "{%s}sp" % NS["p"],
    "{%s}pic" % NS["p"],
    "{%s}graphicFrame" % NS["p"],
    "{%s}grpSp" % NS["p"],
)


class ShapeBindingError(RuntimeError):
    pass


def find_shape(root, shape_name: str, *, shape_id=None, context: str = "slide"):
    """Locate a shape by stable PowerPoint id, falling back to its name.

    PowerPoint permits duplicate display names, so new editor bindings persist
    ``shape_id``. Older name-only schemes keep their previous strict behaviour.
    """
    matches = []
    for element in root.iter():
        if element.tag not in _SHAPE_TAGS:
            continue
        if element.tag == "{%s}pic" % NS["p"] and any(
            ancestor.tag == "{%s}graphicFrame" % NS["p"] for ancestor in element.iterancestors()
        ):
            continue
        cNvPr = element.find(".//{%s}cNvPr" % NS["p"])
        id_matches = shape_id is not None and cNvPr is not None and cNvPr.get("id") == str(shape_id)
        name_matches = shape_id is None and cNvPr is not None and cNvPr.get("name") == shape_name
        if id_matches or name_matches:
            matches.append(element)
    if not matches:
        suffix = f", id={shape_id}" if shape_id is not None else ""
        raise ShapeBindingError(f"shape not found: {shape_name}{suffix} (slide={context})")
    if len(matches) > 1:
        raise ShapeBindingError(f"shape duplicated: {shape_name} (slide={context})")
    return matches[0]


def set_shape_text(shape, value: str) -> int:
    """Replace every text node in the shape, keeping the first run's rPr."""
    text_nodes = shape.xpath(".//a:t", namespaces=NS)
    if not text_nodes:
        raise ShapeBindingError("shape has no text node to bind")
    rendered = "" if value is None else str(value)
    lines = rendered.splitlines()
    paragraphs = shape.xpath(".//a:p", namespaces=NS)
    writable_paragraphs = [p for p in paragraphs if p.xpath(".//a:t", namespaces=NS)]
    if len(lines) > 1 and len(writable_paragraphs) >= len(lines):
        # Composite template cells commonly already contain one styled
        # paragraph per line. Reusing paragraphs preserves bullets, indentation
        # and line spacing even when a paragraph contains several styled runs.
        for index, paragraph in enumerate(writable_paragraphs):
            nodes = paragraph.xpath(".//a:t", namespaces=NS)
            nodes[0].text = lines[index] if index < len(lines) else ""
            for node in nodes[1:]:
                node.text = ""
    else:
        text_nodes[0].text = rendered
        for node in text_nodes[1:]:
            node.text = ""
    return len(text_nodes)


def set_table_cell(shape, row: int, column: int, value: str) -> None:
    """Set one table cell text; coordinates are 0-based."""
    table = shape.xpath(".//a:tbl", namespaces=NS)
    if not table:
        raise ShapeBindingError("shape is not a table")
    rows = table[0].xpath("./a:tr", namespaces=NS)
    if row < 0 or row >= len(rows):
        raise ShapeBindingError(f"table row out of range: {row} (rows={len(rows)})")
    cells = rows[row].xpath("./a:tc", namespaces=NS)
    if column < 0 or column >= len(cells):
        raise ShapeBindingError(f"table column out of range: {column} (cols={len(cells)})")
    set_shape_text(cells[column], value)


def set_table_rows(
    shape,
    records,
    *,
    columns_keys=None,
    columns_map=None,
    start_row: int = 1,
    uniform_height=None,
    style_row=None,
) -> int:
    """整表填入：把 records（行字典列表）写入表格。

    列对应关系二选一：
    - ``columns_keys``：数据键列表，按顺序对应表格 0..N 列（旧行为）；
    - ``columns_map``：{表格列号: 数据键}，可只填部分列、任意顺序
      （PPT 表格列数与表单不一致时用映射逐列绑定）。
    保留前 start_row 行（通常第 1 行为表头）；数据行不足自动复制末行补足，
    超出则删除多余行。返回实际写入的数据行数。
    """
    from copy import deepcopy

    table = shape.xpath(".//a:tbl", namespaces=NS)
    if not table:
        raise ShapeBindingError("shape is not a table")
    table = table[0]
    # 中性化数据区纵向合并；表头的合并与格式必须原样保留。
    # PowerPoint 不显示，会导致“第一行有、第二行为空”；先拆开让每行每格独立可写。
    for row in table.xpath("./a:tr", namespaces=NS)[start_row:]:
        for tc in row.xpath('./a:tc', namespaces=NS):
            for attr in ("rowSpan", "vMerge"):
                if attr in tc.attrib:
                    del tc.attrib[attr]
            if uniform_height is not None:
                for attr in ('gridSpan', 'hMerge'):
                    tc.attrib.pop(attr, None)
    rows = table.xpath("./a:tr", namespaces=NS)
    if start_row < 0 or start_row > len(rows):
        raise ShapeBindingError(f"start_row out of range: {start_row} (rows={len(rows)})")
    if not columns_keys and not columns_map:
        raise ShapeBindingError("columns_keys 或 columns_map 必须提供其一")
    if columns_map is not None:
        mapping = {int(index): key for index, key in columns_map.items()}
    else:
        mapping = None
    sequential_keys = list(columns_keys or [])
    records = list(records or [])
    body = rows[start_row:]
    if records and not body:
        raise ShapeBindingError("表格没有可写入的数据行（start_row 之后无行）")

    if uniform_height is not None:
        reference = deepcopy(rows[style_row if style_row is not None else start_row])
        for tr in body:
            table.remove(tr)
        for index, record in enumerate(records):
            tr = deepcopy(reference)
            tr.set('h', str(uniform_height))
            # Unmapped columns remain user-owned, including their original cell contents.
            if index < len(body):
                old_cells = body[index].xpath('./a:tc', namespaces=NS)
                for col, cell in enumerate(tr.xpath('./a:tc', namespaces=NS)):
                    mapped = col in mapping if mapping is not None else col < len(sequential_keys)
                    if not mapped and col < len(old_cells):
                        tr.replace(cell, deepcopy(old_cells[col]))
            table.append(tr)
        rows = table.xpath('./a:tr', namespaces=NS)
        body = rows[start_row:]

    # 1) 行数不足 -> 克隆最后一行补足
    needed = len(records)
    if needed > len(body):
        template = deepcopy(body[-1])
        for _ in range(needed - len(body)):
            table.append(deepcopy(template))
        rows = table.xpath("./a:tr", namespaces=NS)

    # 2) 逐行写值（按列映射）
    written = 0
    for index, record in enumerate(records[:needed]):
        tr = rows[start_row + index]
        cells = tr.xpath("./a:tc", namespaces=NS)
        for column in range(len(cells)):
            if mapping is not None:
                key = mapping.get(column)
            else:
                key = sequential_keys[column] if column < len(sequential_keys) else None
            if key is None:
                continue
            _set_cell_text(cells[column], str(record.get(key, "") if isinstance(record, dict) else record))
        written += 1

    # 3) 删除多余数据行
    for tr in rows[start_row + needed:]:
        table.remove(tr)
    if uniform_height is not None:
        ext = shape.find('p:xfrm/a:ext', namespaces=NS)
        if ext is not None:
            ext.set('cy', str(sum(int(r.get('h', 0)) for r in table.findall('a:tr', NS))))
    return written


def _set_cell_text(cell, value: str) -> None:
    """写单元格文本：保留首个 a:t，清空其余；无 a:t 时补建。

    写入后确保该 run 带深色 rPr（sz + schemeClr dk1）——部分模板空行/合并延续
    行的单元格没有可见样式，缺 rPr 时 PowerPoint 继承段落默认导致文字看不见。
    """
    text_nodes = cell.xpath(".//a:t", namespaces=NS)
    target = None
    if text_nodes:
        target = text_nodes[0]
        target.text = value
        for node in text_nodes[1:]:
            node.text = ""
    else:
        paragraphs = cell.xpath("./a:txBody/a:p", namespaces=NS)
        paragraph = paragraphs[0] if paragraphs else None
        if paragraph is None:
            body = cell.find("{%s}txBody" % NS["a"])
            if body is None:
                raise ShapeBindingError("table cell has no text body")
            paragraph = etree.SubElement(body, "{%s}p" % NS["a"])
        run = etree.Element("{%s}r" % NS["a"])
        # endParaRPr 必须在 run 之后：若段落已有 endParaRPr，把新 run 插到它前面，
        # 否则 PowerPoint 会忽略 run（表现为“第二行看不见”）。
        end_para = paragraph.find("{%s}endParaRPr" % NS["a"])
        # Empty template cells often store their font on endParaRPr. Inherit it
        # for the inserted run instead of silently falling back to 14 pt.
        font_props = end_para if end_para is not None else paragraph.find('a:pPr/a:defRPr', NS)
        if font_props is not None:
            from copy import deepcopy
            rpr = deepcopy(font_props)
            rpr.tag = '{%s}rPr' % NS['a']
            run.append(rpr)
        if end_para is not None:
            paragraph.insert(paragraph.index(end_para), run)
        else:
            paragraph.append(run)
        target = etree.SubElement(run, "{%s}t" % NS["a"])
        target.text = value
        target.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run = target.getparent() if target is not None else None
    if run is not None and etree.QName(run).localname == "r":
        _ensure_visible_run_props(run)


def _ensure_visible_run_props(run) -> None:
    """确保 run 带可见（深色）rPr：强制 solidFill srgbClr 262626，字号缺省 1400。

    某些模板表格空行/合并延续行自带白字样式（rPr 有 solidFill 浅色），继承下来会
    让填进去的字“看不见”；这里直接覆盖为纯深色，保证任何模板下都可见。
    """
    rpr = run.find("{%s}rPr" % NS["a"])
    if rpr is None:
        rpr = etree.Element("{%s}rPr" % NS["a"])
        rpr.set("lang", "zh-CN")
        rpr.set("sz", "1400")
        run.insert(0, rpr)
    if rpr.get("sz") is None:
        rpr.set("sz", "1400")
    # 移除旧填充并强制深色实心填充
    for solid in rpr.findall("a:solidFill", namespaces=NS):
        rpr.remove(solid)
    solid = etree.Element("{%s}solidFill" % NS["a"])
    clr = etree.SubElement(solid, "{%s}srgbClr" % NS["a"])
    clr.set("val", "262626")
    if len(rpr) == 0:
        rpr.append(solid)
    else:
        rpr.insert(0, solid)


def replace_named_text(xml: bytes, shape_name: str, value: str) -> Optional[bytes]:
    """Convenience: replace text of a named shape inside one slide XML."""
    root = etree.fromstring(xml)
    shape = find_shape(root, shape_name)
    set_shape_text(shape, value)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
