# -*- coding: utf-8 -*-
"""Stable issue contract shared by DFM analysis and report outputs."""

from enum import Enum
from typing import Any, Dict, List, Union

from pydantic import BaseModel, Field


class IssueSeverity(str, Enum):
    """Severity vocabulary understood by downstream report consumers."""

    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"
    INFO = "Info"
    UNKNOWN = "Unknown"


ImageValue = Union[str, List[str]]


class DFMIssue(BaseModel):
    """Renderer-independent representation of one DFM finding."""

    id: str = Field(..., min_length=1)
    category: str = "General"
    severity: IssueSeverity = IssueSeverity.UNKNOWN
    title: str = ""
    description: str = ""
    recommendation: str = ""
    images: Dict[str, ImageValue] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    extra_data: Dict[str, Any] = Field(default_factory=dict)

