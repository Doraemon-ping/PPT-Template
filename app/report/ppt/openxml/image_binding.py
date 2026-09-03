# -*- coding: utf-8 -*-
"""Swap the image behind a named picture shape without touching other parts.

Only the slide relationship target media part is replaced (or re-pointed to a
new PNG part); every other shape, relationship and package part stays as-is.
"""
import base64
import binascii
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lxml import etree
from PIL import Image

from .package_editor import OoxmlPackage, OoxmlPackageError

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
}

_CONTENT_TYPES = "[Content_Types].xml"


class ImageBindingError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageBindingResult:
    shape_name: str
    slide_index: int
    media_part: str
    image_width_px: int
    image_height_px: int
    replaced_in_place: bool


def decode_image_bytes(value) -> bytes:
    """Accept bytes, Path, and base64 data URIs; return raw image bytes.

    Plain text strings are rejected with a clear message instead of being
    interpreted as a missing file path (common when a text field such as a
    company name is bound to a picture shape by mistake).
    """
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if isinstance(value, bytes):
        return value
    if isinstance(value, Path):
        return value.read_bytes()
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("data:") and "," in text:
            header, payload = text.split(",", 1)
            if ";base64" not in header:
                raise ImageBindingError("只支持 base64 data URI 图片")
            try:
                return base64.b64decode(payload, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ImageBindingError(f"图片 data URI 解码失败：{exc}") from exc
        if text:
            candidate = Path(text)
            if candidate.is_file():
                try:
                    return candidate.read_bytes()
                except OSError as exc:
                    raise ImageBindingError(f"图片文件读取失败 {text!r}: {exc}") from exc
            raise ImageBindingError(
                "绑定到图片对象的值不是图片：当前值是普通文本"
                + f"（{text[:48]!r}）。请关联图片字段（上传到表单的图片，值以 data: 开头），"
                "或把该对象改为文本绑定。"
            )
    raise ImageBindingError("图片源为空或不支持的格式")


def _png_bytes(raw: bytes, shape_name: str) -> tuple:
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            width, height = image.size
    except Exception as exc:
        raise ImageBindingError(f"invalid image for shape {shape_name}: {exc}") from exc
    if width <= 0 or height <= 0:
        raise ImageBindingError(f"image dimensions must be positive for shape {shape_name}")
    output = io.BytesIO()
    with Image.open(io.BytesIO(raw)) as image:
        image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB").save(output, format="PNG")
    return output.getvalue(), width, height


class ImageBindingFiller:
    """Bind one named picture shape to new image bytes."""

    def fill(self, package: OoxmlPackage, slide_index: int, shape_name: str, value, *, shape_id=None) -> ImageBindingResult:
        slide_part = package.slide_parts().get(slide_index)
        if slide_part is None:
            raise ImageBindingError(f"slide index out of range: {slide_index}")
        raw = decode_image_bytes(value)
        png, width, height = _png_bytes(raw, shape_name)

        xml = package.read(slide_part)
        root = etree.fromstring(xml)
        picture = self._named_picture(root, shape_name, shape_id=shape_id)
        blip = picture.find(".//{%s}blip" % NS["a"])
        if blip is None:
            raise ImageBindingError(f"picture {shape_name} has no image blip")
        r_id = blip.get("{%s}embed" % NS["r"])
        if not r_id:
            raise ImageBindingError(f"picture {shape_name} is not embedded")

        rels_part = package.rels_part_for(slide_part)
        if rels_part is None or not package.has_part(rels_part):
            raise ImageBindingError(f"relationship part missing: {rels_part}")
        rels = etree.fromstring(package.read(rels_part))
        relationship = None
        for rel in rels.findall("{%s}Relationship" % NS["rel"]):
            if rel.get("Id") == r_id:
                relationship = rel
                break
        if relationship is None:
            raise ImageBindingError(f"relationship {r_id} not found for shape {shape_name}")

        target = relationship.get("Target") or ""
        media_part = self._resolve_media_part(slide_part, target)
        if not package.has_part(media_part):
            raise ImageBindingError(f"media part missing: {media_part}")

        if media_part.lower().endswith(".png"):
            package.write(media_part, png)
            replaced_in_place = True
        else:
            replaced_in_place = False
            new_name = self._new_media_name(package, media_part)
            package.write(new_name, png)
            relationship.set("Target", self._relative_target(slide_part, new_name))
            package.write(rels_part, etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True))
            self._ensure_png_default(package)
            media_part = new_name

        return ImageBindingResult(
            shape_name=shape_name,
            slide_index=slide_index,
            media_part=media_part,
            image_width_px=width,
            image_height_px=height,
            replaced_in_place=replaced_in_place,
        )

    @staticmethod
    def _named_picture(root, shape_name: str, *, shape_id=None):
        matches = []
        for pic in root.iter("{%s}pic" % NS["p"]):
            cNvPr = pic.find(".//{%s}cNvPr" % NS["p"])
            id_matches = shape_id is not None and cNvPr is not None and cNvPr.get("id") == str(shape_id)
            name_matches = shape_id is None and cNvPr is not None and cNvPr.get("name") == shape_name
            if id_matches or name_matches:
                matches.append(pic)
        if not matches:
            raise ImageBindingError(f"picture shape not found: {shape_name}")
        if len(matches) > 1:
            raise ImageBindingError(f"picture shape duplicated: {shape_name}")
        return matches[0]

    @staticmethod
    def _resolve_media_part(slide_part: str, target: str) -> str:
        # Relationships are relative to the slide part directory (ppt/slides/).
        directory = slide_part.rsplit("/", 1)[0] + "/"
        if target.startswith("/"):
            return target.lstrip("/")
        return _normalize_path(directory + target)

    @staticmethod
    def _relative_target(slide_part: str, media_part: str) -> str:
        directory = slide_part.rsplit("/", 1)[0]  # ppt/slides
        media_dir = media_part.rsplit("/", 1)[0] if "/" in media_part else ""
        if media_dir == directory:
            return media_part.rsplit("/", 1)[-1]
        return "../media/" + media_part.rsplit("/", 1)[-1]

    @staticmethod
    def _new_media_name(package: OoxmlPackage, current: str) -> str:
        counter = 1
        while True:
            name = re.sub(r"\.\w+$", "", current) + f"_replaced{counter}.png"
            if not package.has_part(name):
                return name
            counter += 1

    @staticmethod
    def _ensure_png_default(package: OoxmlPackage) -> None:
        if not package.has_part(_CONTENT_TYPES):
            return
        xml = package.read(_CONTENT_TYPES)
        root = etree.fromstring(xml)
        for default in root.findall("{%s}Default" % NS["ct"]):
            if default.get("Extension", "").casefold() == "png":
                return
        element = etree.SubElement(root, "{%s}Default" % NS["ct"])
        element.set("Extension", "png")
        element.set("ContentType", "image/png")
        package.write(_CONTENT_TYPES, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True))


def _normalize_path(path: str) -> str:
    parts = []
    for segment in path.replace("\\", "/").split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/".join(parts)
