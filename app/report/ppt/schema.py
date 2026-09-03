# -*- coding: utf-8 -*-
"""Typed contracts for declarative slide-to-shape data binding."""

from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel, Field

from ...dfm.models import SlideType


class RendererType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    COMPLEX_IMAGE = "complex_image"
    TABLE = "table"
    BADGE = "badge"


class SchemaField(BaseModel):
    source: str = Field(..., min_length=1)
    shape: str = Field(..., min_length=1)
    renderer: RendererType
    required: bool = True
    options: Dict[str, Any] = Field(default_factory=dict)


class SlideSchema(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    template_version: str = Field(..., min_length=1)
    slide_type: SlideType
    template: str = Field(..., min_length=1)
    fields: Dict[str, SchemaField]
