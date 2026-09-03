# -*- coding: utf-8 -*-
"""Visual bindings for non-picture template objects.

The template workbench may use an AutoShape as an image placeholder, and old
PowerPoint files often store equations as embedded OLE objects.  Generated
reports do not need those objects to remain editable: replacing the selected
object *at the same z-order and geometry* with a picture is safer and keeps the
rest of the source slide byte-for-byte unchanged.
"""
import io
import re
from copy import deepcopy

from lxml import etree
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .image_binding import decode_image_bytes
from .shape_binding import ShapeBindingError, find_shape

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
EMU_PER_INCH = 914400
_TOKEN_RE = re.compile(r"\[\[(.*?)\|(.*?)\]\]")
_PATH_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.\[\]-]*)\}")


def render_data_template(template: str, resolver, *, missing: str = "keep") -> str:
    """Resolve ``{dotted.path}`` tokens in an editor-authored display template."""
    def replace(match):
        value, found = resolver.resolve(match.group(1))
        if found:
            return "" if value is None else str(value)
        if missing == "clear":
            return ""
        if missing == "error":
            raise ShapeBindingError(f"template data missing: {match.group(1)}")
        return match.group(0)
    return _PATH_RE.sub(replace, template or "")


def render_formula_png(text: str, width_emu: int, height_emu: int, options=None) -> bytes:
    """Render a transparent formula image.

    The small ``[[numerator|denominator]]`` syntax renders a stacked fraction;
    ordinary text and Unicode superscripts/subscripts remain available.  This
    avoids a Microsoft Equation/MathType runtime dependency on the server.
    """
    options = dict(options or {})
    dpi = max(96, int(options.get("dpi", 180)))
    width = max(80, round(max(width_emu, EMU_PER_INCH) / EMU_PER_INCH * dpi))
    height = max(28, round(max(height_emu, EMU_PER_INCH / 5) / EMU_PER_INCH * dpi))
    font_size = int(options.get("font_size", max(18, min(height * 0.46, 52))))
    font_path = options.get("font_path") or "C:/Windows/Fonts/msyh.ttc"
    try:
        font = ImageFont.truetype(font_path, font_size)
        small_font = ImageFont.truetype(font_path, max(12, int(font_size * 0.72)))
    except OSError:
        font = ImageFont.load_default()
        small_font = font
    color = options.get("color", "#111111")
    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)

    tokens = []
    cursor = 0
    for match in _TOKEN_RE.finditer(text or ""):
        if match.start() > cursor:
            tokens.append(("text", text[cursor:match.start()]))
        tokens.append(("fraction", match.group(1), match.group(2)))
        cursor = match.end()
    if cursor < len(text or ""):
        tokens.append(("text", text[cursor:]))
    if not tokens:
        tokens = [("text", text or "")]

    measured = []
    total_width = 0
    for token in tokens:
        if token[0] == "text":
            box = draw.textbbox((0, 0), token[1], font=font)
            tw = max(0, box[2] - box[0])
        else:
            nbox = draw.textbbox((0, 0), token[1], font=small_font)
            dbox = draw.textbbox((0, 0), token[2], font=small_font)
            tw = max(nbox[2] - nbox[0], dbox[2] - dbox[0]) + 12
        measured.append(tw)
        total_width += tw
    scale = min(1.0, (width - 8) / max(total_width, 1))
    if scale < 0.99:
        font_size = max(10, int(font_size * scale))
        font = ImageFont.truetype(font_path, font_size)
        small_font = ImageFont.truetype(font_path, max(9, int(font_size * 0.72)))
        return render_formula_png(text, width_emu, height_emu, {
            **options, "font_size": font_size, "dpi": dpi,
        }) if options.get("font_size") is None else _render_formula_fixed(
            text, width, height, font, small_font, color)
    return _render_formula_fixed(text, width, height, font, small_font, color)


def _render_formula_fixed(text, width, height, font, small_font, color):
    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    tokens = []
    cursor = 0
    for match in _TOKEN_RE.finditer(text or ""):
        if match.start() > cursor:
            tokens.append(("text", text[cursor:match.start()]))
        tokens.append(("fraction", match.group(1), match.group(2)))
        cursor = match.end()
    if cursor < len(text or ""):
        tokens.append(("text", text[cursor:]))
    if not tokens:
        tokens = [("text", text or "")]
    widths = []
    for token in tokens:
        if token[0] == "text":
            box = draw.textbbox((0, 0), token[1], font=font)
            widths.append(max(0, box[2] - box[0]))
        else:
            nb = draw.textbbox((0, 0), token[1], font=small_font)
            db = draw.textbbox((0, 0), token[2], font=small_font)
            widths.append(max(nb[2] - nb[0], db[2] - db[0]) + 12)
    x = max(2, (width - sum(widths)) // 2)
    mid = height // 2
    for token, tw in zip(tokens, widths):
        if token[0] == "text":
            box = draw.textbbox((0, 0), token[1], font=font)
            th = box[3] - box[1]
            draw.text((x, mid - th // 2 - box[1]), token[1], font=font, fill=color)
        else:
            num, den = token[1], token[2]
            nb = draw.textbbox((0, 0), num, font=small_font)
            db = draw.textbbox((0, 0), den, font=small_font)
            nw, nh = nb[2] - nb[0], nb[3] - nb[1]
            dw, dh = db[2] - db[0], db[3] - db[1]
            line_y = mid
            draw.text((x + (tw - nw) / 2, line_y - nh - 4 - nb[1]), num, font=small_font, fill=color)
            draw.line((x + 2, line_y, x + tw - 2, line_y), fill=color, width=max(1, height // 80))
            draw.text((x + (tw - dw) / 2, line_y + 4 - db[1]), den, font=small_font, fill=color)
        x += tw
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class VisualBindingFiller:
    """Replace a selected shape/OLE object with a generated picture."""

    def fill_region(self, package, slide_index, shape_name, value, *, shape_id=None, options=None):
        raw = decode_image_bytes(value)
        return self._replace(package, slide_index, shape_name, raw, shape_id=shape_id, options=options)

    def fill_table_region(self, package, slide_index, shape_name, value, *, shape_id=None, options=None):
        """Place a picture in a selected table grid slot without replacing the table.

        A merged continuation has no independent fill or text. A sibling picture
        uses the clicked grid slot, preserving the merge and its anchor content.
        """
        options = dict(options or {})
        slide_part, root, target = self._target(package, slide_index, shape_name, shape_id)
        table = target.find('.//a:tbl', NS)
        if table is None:
            raise ShapeBindingError('单元格图片绑定的对象不是表格')
        rows = table.findall('a:tr', NS)
        widths = [int(c.get('w')) for c in table.findall('a:tblGrid/a:gridCol', NS)]
        row, col = int(options['row']), int(options['column'])
        if not 0 <= row < len(rows) or not 0 <= col < len(widths):
            raise ShapeBindingError('单元格图片行列超出表格范围')
        heights = [int(r.get('h')) for r in rows]
        left, top, _, _ = self._box(target)
        left += sum(widths[:col]); top += sum(heights[:row])
        width, height = widths[col], heights[row]
        if width <= 0 or height <= 0:
            raise ShapeBindingError('所选单元格没有可见区域，请选择有宽高的单元格')
        inset = min(12700, width // 10, height // 10)
        left += inset; top += inset; width -= 2 * inset; height -= 2 * inset
        png = self._prepare_image(decode_image_bytes(value), width, height, options.get('fit', 'contain'))
        cell = rows[row].findall('a:tc', NS)[col]
        if not any(cell.get(attr) for attr in ('rowSpan', 'gridSpan', 'hMerge', 'vMerge')):
            for node in cell.findall('.//a:t', NS):
                node.text = ''
        return self._replace_parsed(package, slide_part, root, target,
            f'{shape_name} [cell:{row},{col}]', png, left, top, width, height, options, insert_after=True)

    def fill_formula(self, package, slide_index, shape_name, text, *, shape_id=None, options=None):
        slide_part, root, target = self._target(package, slide_index, shape_name, shape_id)
        left, top, width, height = self._box(target)
        png = render_formula_png(text, width, height, options)
        return self._replace_parsed(
            package, slide_part, root, target, shape_name, png,
            left, top, width, height, options or {},
        )

    def _replace(self, package, slide_index, shape_name, raw, *, shape_id=None, options=None):
        slide_part, root, target = self._target(package, slide_index, shape_name, shape_id)
        left, top, width, height = self._box(target)
        png = self._prepare_image(raw, width, height, (options or {}).get("fit", "cover"))
        return self._replace_parsed(
            package, slide_part, root, target, shape_name, png,
            left, top, width, height, options or {},
        )

    @staticmethod
    def _target(package, slide_index, shape_name, shape_id):
        slide_part = package.slide_parts().get(slide_index)
        if slide_part is None:
            raise ShapeBindingError(f"slide index out of range: {slide_index}")
        root = etree.fromstring(package.read(slide_part))
        target = find_shape(root, shape_name, shape_id=shape_id, context=slide_part)
        return slide_part, root, target

    @staticmethod
    def _box(target):
        xfrm = target.find("./p:xfrm", namespaces=NS)
        if xfrm is None:
            xfrm = target.find("./p:spPr/a:xfrm", namespaces=NS)
        if xfrm is None:
            xfrm = target.find("./p:grpSpPr/a:xfrm", namespaces=NS)
        if xfrm is None:
            raise ShapeBindingError("shape has no replaceable geometry")
        off = xfrm.find("a:off", namespaces=NS)
        ext = xfrm.find("a:ext", namespaces=NS)
        if off is None or ext is None:
            raise ShapeBindingError("shape geometry is incomplete")
        return tuple(int(v) for v in (off.get("x"), off.get("y"), ext.get("cx"), ext.get("cy")))

    @staticmethod
    def _prepare_image(raw, width, height, fit):
        with Image.open(io.BytesIO(raw)) as source:
            source = source.convert("RGBA")
            target_w = max(1, round(1200 * width / max(width, height, 1)))
            target_h = max(1, round(1200 * height / max(width, height, 1)))
            if fit == "stretch":
                result = source.resize((target_w, target_h), Image.Resampling.LANCZOS)
            elif fit == "contain":
                contained = ImageOps.contain(source, (target_w, target_h), Image.Resampling.LANCZOS)
                result = Image.new("RGBA", (target_w, target_h), (255, 255, 255, 0))
                result.alpha_composite(contained, ((target_w-contained.width)//2, (target_h-contained.height)//2))
            else:
                result = ImageOps.fit(source, (target_w, target_h), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            result.save(output, format="PNG")
            return output.getvalue()

    def _replace_parsed(self, package, slide_part, root, target, name, png,
                        left, top, width, height, options, *, insert_after=False):
        rels_part = package.rels_part_for(slide_part)
        if not rels_part or not package.has_part(rels_part):
            raise ShapeBindingError(f"relationship part missing: {rels_part}")
        rels = etree.fromstring(package.read(rels_part))
        used = {rel.get("Id", "") for rel in rels.findall("{%s}Relationship" % NS["rel"])}
        index = 1
        while f"rId{index}" in used:
            index += 1
        r_id = f"rId{index}"
        media_index = 1
        while package.has_part(f"ppt/media/generated{media_index}.png"):
            media_index += 1
        media_part = f"ppt/media/generated{media_index}.png"
        package.write(media_part, png)
        package.ensure_content_type(media_part, "image/png")
        rel = etree.SubElement(rels, "{%s}Relationship" % NS["rel"])
        rel.set("Id", r_id)
        rel.set("Type", IMAGE_REL)
        rel.set("Target", f"../media/generated{media_index}.png")
        package.write(rels_part, etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True))

        c_nv = target.find(".//p:cNvPr", namespaces=NS)
        object_id = c_nv.get("id", "1") if c_nv is not None else "1"
        object_name = c_nv.get("name", name) if c_nv is not None else name
        if insert_after:
            object_id = str(max([int(n.get('id', 0)) for n in root.findall('.//p:cNvPr', NS)] or [0]) + 1)
            object_name = name
        pic = self._picture(object_id, object_name, r_id, left, top, width, height)
        parent = target.getparent()
        if insert_after:
            parent.insert(parent.index(target) + 1, pic)
        else:
            parent.replace(target, pic)
        package.write(slide_part, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True))
        return media_part

    @staticmethod
    def _picture(object_id, name, r_id, left, top, width, height):
        pic = etree.Element("{%s}pic" % NS["p"])
        nv = etree.SubElement(pic, "{%s}nvPicPr" % NS["p"])
        c_nv = etree.SubElement(nv, "{%s}cNvPr" % NS["p"])
        c_nv.set("id", str(object_id)); c_nv.set("name", name)
        etree.SubElement(nv, "{%s}cNvPicPr" % NS["p"])
        etree.SubElement(nv, "{%s}nvPr" % NS["p"])
        fill = etree.SubElement(pic, "{%s}blipFill" % NS["p"])
        blip = etree.SubElement(fill, "{%s}blip" % NS["a"])
        blip.set("{%s}embed" % NS["r"], r_id)
        stretch = etree.SubElement(fill, "{%s}stretch" % NS["a"])
        etree.SubElement(stretch, "{%s}fillRect" % NS["a"])
        sp_pr = etree.SubElement(pic, "{%s}spPr" % NS["p"])
        xfrm = etree.SubElement(sp_pr, "{%s}xfrm" % NS["a"])
        off = etree.SubElement(xfrm, "{%s}off" % NS["a"])
        off.set("x", str(left)); off.set("y", str(top))
        ext = etree.SubElement(xfrm, "{%s}ext" % NS["a"])
        ext.set("cx", str(width)); ext.set("cy", str(height))
        geom = etree.SubElement(sp_pr, "{%s}prstGeom" % NS["a"])
        geom.set("prst", "rect"); etree.SubElement(geom, "{%s}avLst" % NS["a"])
        return pic
