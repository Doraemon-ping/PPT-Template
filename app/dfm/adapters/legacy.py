# -*- coding: utf-8 -*-
"""Adapter for the current front-end state shape: ``{f, t, i}``.

This module deliberately performs mapping only. It does not call DFM
calculations and does not make new process-quality judgements.
"""

from collections import Counter
from typing import Any, Dict, Mapping, Optional

from ..models.issue import DFMIssue, IssueSeverity
from ..models.report import (
    DFMPartSpecifications,
    DFMProject,
    DFMReport,
    DFMReportMetadata,
    DFMSummary,
)


_SEVERITY_ALIASES = {
    "critical": IssueSeverity.CRITICAL,
    "严重": IssueSeverity.CRITICAL,
    "致命": IssueSeverity.CRITICAL,
    "major": IssueSeverity.MAJOR,
    "主要": IssueSeverity.MAJOR,
    "重要": IssueSeverity.MAJOR,
    "minor": IssueSeverity.MINOR,
    "次要": IssueSeverity.MINOR,
    "一般": IssueSeverity.MINOR,
    "info": IssueSeverity.INFO,
    "提示": IssueSeverity.INFO,
}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _severity(value: Any) -> IssueSeverity:
    text = _text(value)
    if not text:
        return IssueSeverity.UNKNOWN
    return _SEVERITY_ALIASES.get(text.casefold(), IssueSeverity.UNKNOWN)


class LegacyDFMReportAdapter:
    """Convert legacy request dictionaries without mutating their contents."""

    version = "1.0"

    def adapt(
        self,
        f: Optional[Mapping[str, Any]] = None,
        t: Optional[Mapping[str, Any]] = None,
        i: Optional[Mapping[str, Any]] = None,
        *,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> DFMReport:
        fields = dict(f or {})
        tables = dict(t or {})
        images = dict(i or {})
        issue_rows = tables.get("issues") or []

        issues = [self._adapt_issue(row, index) for index, row in enumerate(issue_rows, start=1)]
        counts = Counter(issue.severity for issue in issues)

        project_id = _text(fields.get("projectId") or fields.get("projNo") or fields.get("partNo"))
        report_id = _text(fields.get("reportId")) or self._default_report_id(fields)

        project = DFMProject(
            project_id=project_id,
            project_name=_text(fields.get("projName")),
            part_name=_text(fields.get("partName")),
            part_number=_text(fields.get("partNo")),
            customer_name=_text(fields.get("custName")),
            version=_text(fields.get("version")),
            report_date=_text(fields.get("dfmDate")),
            extra_data={
                key: fields[key]
                for key in ("projType", "material", "company", "maker", "checker", "approver")
                if key in fields
            },
        )
        summary = DFMSummary(
            total=len(issues),
            critical=counts[IssueSeverity.CRITICAL],
            major=counts[IssueSeverity.MAJOR],
            minor=counts[IssueSeverity.MINOR],
            info=counts[IssueSeverity.INFO],
            unknown=counts[IssueSeverity.UNKNOWN],
        )
        part_specifications = DFMPartSpecifications(
            finished_weight=_text(fields.get("wFinish")),
            casting_weight=_text(fields.get("wCast")),
            runner_weight=_text(fields.get("wRunner")),
            overflow_weight=_text(fields.get("wOverflow")),
            wall_thickness=_text(fields.get("wall")),
            maximum_wall_thickness=_text(fields.get("wallMax")),
            length=_text(fields.get("dimL")),
            width=_text(fields.get("dimW")),
            height=_text(fields.get("dimH")),
            cavity_count=_text(fields.get("cav")),
            casting_pressure=_text(fields.get("castP")),
            material=_text(fields.get("material")),
            annual_volume=_text(fields.get("annual")),
            project_type=_text(fields.get("projType")),
            surface_requirement=_text(fields.get("surfaceReq")),
            leak_requirement=" ".join(filter(None, (
                _text(fields.get("leakReq")), _text(fields.get("leakVal")),
            ))),
        )

        metadata_values: Dict[str, Any] = dict(metadata or {})
        metadata_extra = dict(metadata_values.pop("extra_data", {}) or {})
        metadata_extra.setdefault("legacy_table_keys", sorted(tables.keys()))
        metadata_extra.setdefault("legacy_image_keys", sorted(images.keys()))
        metadata_values.setdefault("report_id", report_id)
        metadata_values.setdefault("source_format", "legacy_f_t_i")
        metadata_values.setdefault("adapter_version", self.version)
        metadata_values["extra_data"] = metadata_extra
        report_metadata = DFMReportMetadata(**metadata_values)
        return DFMReport(
            project=project,
            summary=summary,
            part_specifications=part_specifications,
            issues=issues,
            metadata=report_metadata,
        )

    @staticmethod
    def _default_report_id(fields: Mapping[str, Any]) -> str:
        parts = [_text(fields.get("partNo")), _text(fields.get("version"))]
        return "-".join(part for part in parts if part)

    @staticmethod
    def _adapt_issue(row: Any, index: int) -> DFMIssue:
        source = dict(row) if isinstance(row, Mapping) else {"desc": row}
        issue_id = _text(source.get("id") or source.get("no")) or f"DFM-{index:03d}"
        description = _text(source.get("description") or source.get("desc"))
        title = _text(source.get("title")) or description
        recommendation = _text(source.get("recommendation") or source.get("prop"))
        severity = _severity(source.get("severity") or source.get("level"))
        category = _text(source.get("category") or source.get("type")) or "OpenIssue"

        raw_images = source.get("images")
        issue_images = dict(raw_images) if isinstance(raw_images, Mapping) else {}
        parameters = source.get("parameters")
        issue_parameters = dict(parameters) if isinstance(parameters, Mapping) else {}

        consumed = {
            "id", "no", "category", "type", "severity", "level", "title",
            "description", "desc", "recommendation", "prop", "images", "parameters",
        }
        extra_data = {key: value for key, value in source.items() if key not in consumed}
        return DFMIssue(
            id=issue_id,
            category=category,
            severity=severity,
            title=title,
            description=description,
            recommendation=recommendation,
            images=issue_images,
            parameters=issue_parameters,
            extra_data=extra_data,
        )


def adapt_legacy_report(
    f: Optional[Mapping[str, Any]] = None,
    t: Optional[Mapping[str, Any]] = None,
    i: Optional[Mapping[str, Any]] = None,
    *,
    metadata: Optional[Mapping[str, Any]] = None,
) -> DFMReport:
    """Convenience entry point for callers that do not need adapter state."""

    return LegacyDFMReportAdapter().adapt(f, t, i, metadata=metadata)
