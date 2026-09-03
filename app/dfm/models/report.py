# -*- coding: utf-8 -*-
"""Unified, renderer-independent DFM report contract."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .issue import DFMIssue


class DFMProject(BaseModel):
    project_id: str = ""
    project_name: str = ""
    part_name: str = ""
    part_number: str = ""
    customer_name: str = ""
    version: str = ""
    report_date: str = ""
    extra_data: Dict[str, Any] = Field(default_factory=dict)


class DFMSummary(BaseModel):
    total: int = Field(default=0, ge=0)
    critical: int = Field(default=0, ge=0)
    major: int = Field(default=0, ge=0)
    minor: int = Field(default=0, ge=0)
    info: int = Field(default=0, ge=0)
    unknown: int = Field(default=0, ge=0)


class DFMPartSpecifications(BaseModel):
    """Presentation-neutral product inputs migrated from the legacy form."""

    finished_weight: str = ""
    casting_weight: str = ""
    runner_weight: str = ""
    overflow_weight: str = ""
    wall_thickness: str = ""
    maximum_wall_thickness: str = ""
    length: str = ""
    width: str = ""
    height: str = ""
    cavity_count: str = ""
    casting_pressure: str = ""
    material: str = ""
    annual_volume: str = ""
    project_type: str = ""
    surface_requirement: str = ""
    leak_requirement: str = ""

    def has_content(self) -> bool:
        values = self.model_dump().values() if hasattr(self, "model_dump") else self.dict().values()
        return any(str(value).strip() for value in values)


class DFMReportMetadata(BaseModel):
    report_id: str = ""
    source_format: str = "legacy_f_t_i"
    adapter_version: str = "1.0"
    generated_at: datetime = Field(default_factory=datetime.now)
    template_version: Optional[str] = None
    generator_version: Optional[str] = None
    extra_data: Dict[str, Any] = Field(default_factory=dict)


class DFMReport(BaseModel):
    """Only data contract future PPT planning/rendering layers should accept."""

    project: DFMProject
    summary: DFMSummary
    part_specifications: DFMPartSpecifications = Field(default_factory=DFMPartSpecifications)
    issues: List[DFMIssue] = Field(default_factory=list)
    metadata: DFMReportMetadata = Field(default_factory=DFMReportMetadata)
