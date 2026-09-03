# -*- coding: utf-8 -*-
"""Replace template text while preserving existing run-level visual styling."""

import math
from dataclasses import dataclass
from typing import Any, Optional

from ..exceptions import RendererError
from .base import RenderContext


@dataclass(frozen=True)
class TextRenderResult:
    original_length: int
    rendered_length: int
    truncated: bool
    possible_overflow: bool
    estimated_lines: int


class TextRenderer:
    """Text-only renderer; it never assigns font name, size, color, or bold."""

    name = "text"

    def render(
        self,
        shape,
        value: Any,
        context: Optional[RenderContext] = None,
    ) -> TextRenderResult:
        ctx = context or RenderContext()
        if not getattr(shape, "has_text_frame", False):
            raise RendererError(self.name, ctx.slide_key, shape.name, "shape has no text frame")

        original = "" if value is None else str(value)
        options = dict(ctx.options)
        rendered, truncated = self._truncate(original, options.get("max_length"))
        estimated_lines = self._estimate_lines(rendered, options.get("chars_per_line"))
        max_lines = self._positive_int(options.get("max_lines"))
        possible_overflow = truncated or (max_lines is not None and estimated_lines > max_lines)

        text_frame = shape.text_frame
        text_frame.word_wrap = True
        target_run = self._first_run(text_frame)
        target_run.text = rendered
        for paragraph in text_frame.paragraphs:
            for run in paragraph.runs:
                if run._r is not target_run._r:
                    run.text = ""

        return TextRenderResult(
            original_length=len(original),
            rendered_length=len(rendered),
            truncated=truncated,
            possible_overflow=possible_overflow,
            estimated_lines=estimated_lines,
        )

    @staticmethod
    def _first_run(text_frame):
        for paragraph in text_frame.paragraphs:
            if paragraph.runs:
                return paragraph.runs[0]
        return text_frame.paragraphs[0].add_run()

    @classmethod
    def _truncate(cls, text: str, max_length: Any):
        limit = cls._positive_int(max_length)
        if limit is None or len(text) <= limit:
            return text, False
        if limit == 1:
            return "…", True
        return text[: limit - 1].rstrip() + "…", True

    @classmethod
    def _estimate_lines(cls, text: str, chars_per_line: Any) -> int:
        width = cls._positive_int(chars_per_line)
        lines = text.splitlines() or [""]
        if width is None:
            return len(lines)
        return sum(max(1, math.ceil(len(line) / width)) for line in lines)

    @staticmethod
    def _positive_int(value: Any):
        if value in (None, ""):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None
