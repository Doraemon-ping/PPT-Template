# -*- coding: utf-8 -*-
"""Render images into named template frames without stretching or overflow."""

import base64
import io
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from ..exceptions import RendererError
from .base import RenderContext


class ImageRenderMode(str, Enum):
    CONTAIN = "contain"
    COVER = "cover"
    CENTER_CROP = "center_crop"
    PRESERVE_ASPECT_RATIO = "preserve_aspect_ratio"


@dataclass(frozen=True)
class ImageRenderResult:
    mode: ImageRenderMode
    image_width_px: int
    image_height_px: int
    left: int
    top: int
    width: int
    height: int
    crop_left: float
    crop_right: float
    crop_top: float
    crop_bottom: float


class ImageRenderer:
    name = "image"

    def render(
        self,
        shape,
        value: Any,
        context: Optional[RenderContext] = None,
    ) -> ImageRenderResult:
        ctx = context or RenderContext()
        mode = self._mode(ctx.options.get("mode", ImageRenderMode.CONTAIN.value), ctx, shape)
        stream = self._image_stream(value, ctx, shape)
        try:
            with Image.open(stream) as image:
                image_width_px, image_height_px = image.size
                image.verify()
        except Exception as exc:
            raise RendererError(self.name, ctx.slide_key, shape.name, f"invalid image: {exc}") from exc
        if image_width_px <= 0 or image_height_px <= 0:
            raise RendererError(self.name, ctx.slide_key, shape.name, "image dimensions must be positive")
        stream.seek(0)

        box_left, box_top = shape.left, shape.top
        box_width, box_height = shape.width, shape.height
        parent = shape._parent
        if not hasattr(parent, "add_picture"):
            raise RendererError(self.name, ctx.slide_key, shape.name, "shape parent cannot contain pictures")

        if mode in {ImageRenderMode.CONTAIN, ImageRenderMode.PRESERVE_ASPECT_RATIO}:
            left, top, width, height = self._contain_geometry(
                box_left, box_top, box_width, box_height, image_width_px, image_height_px
            )
            picture = parent.add_picture(stream, left, top, width=width, height=height)
        else:
            left, top, width, height = box_left, box_top, box_width, box_height
            picture = parent.add_picture(stream, left, top, width=width, height=height)
            self._apply_center_crop(picture, image_width_px, image_height_px, box_width, box_height)

        original_name = shape.name
        picture.name = original_name
        shape._element.getparent().remove(shape._element)
        return ImageRenderResult(
            mode=mode,
            image_width_px=image_width_px,
            image_height_px=image_height_px,
            left=picture.left,
            top=picture.top,
            width=picture.width,
            height=picture.height,
            crop_left=picture.crop_left,
            crop_right=picture.crop_right,
            crop_top=picture.crop_top,
            crop_bottom=picture.crop_bottom,
        )

    @staticmethod
    def _contain_geometry(left, top, box_width, box_height, image_width, image_height):
        scale = min(box_width / image_width, box_height / image_height)
        width = max(1, round(image_width * scale))
        height = max(1, round(image_height * scale))
        return (
            left + (box_width - width) // 2,
            top + (box_height - height) // 2,
            width,
            height,
        )

    @staticmethod
    def _apply_center_crop(picture, image_width, image_height, box_width, box_height):
        image_aspect = image_width / image_height
        box_aspect = box_width / box_height
        if image_aspect > box_aspect:
            crop = (1.0 - box_aspect / image_aspect) / 2.0
            picture.crop_left = crop
            picture.crop_right = crop
        elif image_aspect < box_aspect:
            crop = (1.0 - image_aspect / box_aspect) / 2.0
            picture.crop_top = crop
            picture.crop_bottom = crop

    def _mode(self, value: Any, context: RenderContext, shape) -> ImageRenderMode:
        try:
            return ImageRenderMode(str(value).strip().lower())
        except ValueError as exc:
            raise RendererError(
                self.name,
                context.slide_key,
                shape.name,
                f"unsupported image mode={value}",
            ) from exc

    def _image_stream(self, value: Any, context: RenderContext, shape) -> io.BytesIO:
        if isinstance(value, (list, tuple)):
            value = next((item for item in value if item not in (None, "")), None)
        try:
            if isinstance(value, io.BytesIO):
                return io.BytesIO(value.getvalue())
            if isinstance(value, bytes):
                return io.BytesIO(value)
            if isinstance(value, Path):
                return io.BytesIO(value.read_bytes())
            if isinstance(value, str) and value.startswith("data:") and "," in value:
                header, payload = value.split(",", 1)
                if ";base64" not in header:
                    raise ValueError("only base64 data URIs are supported")
                return io.BytesIO(base64.b64decode(payload, validate=True))
            if isinstance(value, str) and value.strip():
                return io.BytesIO(Path(value).read_bytes())
        except Exception as exc:
            raise RendererError(self.name, context.slide_key, shape.name, str(exc)) from exc
        raise RendererError(self.name, context.slide_key, shape.name, "image source is empty or unsupported")
