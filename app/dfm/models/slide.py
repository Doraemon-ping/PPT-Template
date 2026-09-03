# -*- coding: utf-8 -*-
"""Pure-data page planning contracts.

These models intentionally have no dependency on ``python-pptx``. They describe
what should be rendered, not how a PowerPoint slide should be manipulated.
"""

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SlideType(str, Enum):
    COVER = "cover"
    SUMMARY = "summary"
    PART_SPECIFICATIONS = "part_specifications"
    ISSUE_STANDARD = "issue_standard"
    ISSUE_COMPARE = "issue_compare"
    CONCLUSION = "conclusion"


class SlidePlan(BaseModel):
    """One ordered rendering instruction produced by :class:`SlidePlanner`."""

    order: int = Field(..., ge=1)
    slide_type: SlideType
    template_key: str = Field(..., min_length=1)
    data: Any
    issue_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
