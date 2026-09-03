# -*- coding: utf-8 -*-
"""Render pre-composited DFM evidence while keeping composition out of PPT code."""

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

from ..exceptions import RendererError
from .base import RenderContext
from .image_renderer import ImageRenderResult, ImageRenderer


@dataclass(frozen=True)
class ComplexImagePayload:
    """A bitmap whose CAD view, callouts and annotations are already composited."""

    image: Any
    annotations_baked_in: bool = True
    source: str = "legacy"
    alt_text: str = ""


@runtime_checkable
class SnapshotBackend(Protocol):
    """Future HTML/CSS snapshot boundary (for example, a Playwright backend)."""

    def render_html(self, html: str, *, width_px: int, height_px: int) -> bytes:
        """Return a rendered PNG without knowing anything about PowerPoint."""


class ComplexImageRenderer:
    """Place an existing composite bitmap; never recreates DFM annotations."""

    name = "complex_image"

    def __init__(self, image_renderer: Optional[ImageRenderer] = None) -> None:
        self.image_renderer = image_renderer or ImageRenderer()

    def render(
        self,
        shape,
        value: Any,
        context: Optional[RenderContext] = None,
    ) -> ImageRenderResult:
        ctx = context or RenderContext()
        payload = self._payload(value, ctx, shape)
        try:
            return self.image_renderer.render(shape, payload.image, ctx)
        except RendererError as exc:
            raise RendererError(self.name, ctx.slide_key, shape.name, exc.reason) from exc

    def _payload(self, value: Any, context: RenderContext, shape) -> ComplexImagePayload:
        if isinstance(value, ComplexImagePayload):
            payload = value
        elif isinstance(value, Mapping) and "image" in value:
            payload = ComplexImagePayload(
                image=value.get("image"),
                annotations_baked_in=value.get("annotations_baked_in", True) is not False,
                source=str(value.get("source", "legacy")),
                alt_text=str(value.get("alt_text", "")),
            )
        else:
            # Backwards-compatible path for current strings, bytes, data URIs and lists.
            payload = ComplexImagePayload(image=value)
        if not payload.annotations_baked_in:
            raise RendererError(
                self.name,
                context.slide_key,
                shape.name,
                "annotations_baked_in must be true; composition belongs upstream",
            )
        return payload
