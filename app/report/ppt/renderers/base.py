# -*- coding: utf-8 -*-
"""Shared renderer context."""

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class RenderContext:
    slide_key: str = "UNKNOWN"
    field_name: str = "UNKNOWN"
    options: Mapping[str, Any] = field(default_factory=dict)
