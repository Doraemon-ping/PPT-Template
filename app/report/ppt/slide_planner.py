# -*- coding: utf-8 -*-
"""Convert a :class:`DFMReport` into an ordered, renderer-free slide plan."""

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

from ...dfm.models import DFMIssue, DFMReport, SlidePlan, SlideType


@dataclass(frozen=True)
class SlidePlannerConfig:
    """Template/layout choices kept outside business and rendering code."""

    template_keys: Mapping[SlideType, str] = field(default_factory=lambda: {
        SlideType.COVER: "COVER",
        SlideType.SUMMARY: "SUMMARY",
        SlideType.PART_SPECIFICATIONS: "PART_SPECIFICATIONS",
        SlideType.ISSUE_STANDARD: "ISSUE_STANDARD",
        SlideType.ISSUE_COMPARE: "ISSUE_COMPARE",
        SlideType.CONCLUSION: "CONCLUSION",
    })
    category_layouts: Mapping[str, SlideType] = field(default_factory=dict)
    include_cover: bool = True
    include_summary: bool = True
    include_part_specifications: bool = True
    include_conclusion: bool = True


class SlidePlanner:
    """Plan pages from report data without importing or touching PPT objects."""

    def __init__(self, config: Optional[SlidePlannerConfig] = None) -> None:
        self.config = config or SlidePlannerConfig()
        self._validate_config()
        self._category_layouts = {
            category.casefold(): layout
            for category, layout in self.config.category_layouts.items()
        }

    def plan(self, report: DFMReport) -> List[SlidePlan]:
        plans: List[SlidePlan] = []

        if self.config.include_cover:
            self._append(plans, SlideType.COVER, report.project)
        if self.config.include_summary:
            self._append(plans, SlideType.SUMMARY, report.summary)
        if self.config.include_part_specifications and report.part_specifications.has_content():
            self._append(plans, SlideType.PART_SPECIFICATIONS, report.part_specifications)

        for issue in report.issues:
            slide_type = self._select_issue_slide_type(issue)
            self._append(
                plans,
                slide_type,
                issue,
                issue_id=issue.id,
                context={"category": issue.category, "severity": issue.severity.value},
            )

        if self.config.include_conclusion:
            self._append(
                plans,
                SlideType.CONCLUSION,
                report.summary,
                context={"report_id": report.metadata.report_id},
            )

        return plans

    def _select_issue_slide_type(self, issue: DFMIssue) -> SlideType:
        configured = self._category_layouts.get(issue.category.casefold())
        if configured is not None:
            return configured
        if self._has_image(issue, "before") and self._has_image(issue, "after"):
            return SlideType.ISSUE_COMPARE
        return SlideType.ISSUE_STANDARD

    @staticmethod
    def _has_image(issue: DFMIssue, key: str) -> bool:
        value = issue.images.get(key)
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return any(isinstance(item, str) and item.strip() for item in value)
        return False

    def _append(
        self,
        plans: List[SlidePlan],
        slide_type: SlideType,
        data: object,
        *,
        issue_id: Optional[str] = None,
        context: Optional[Dict[str, object]] = None,
    ) -> None:
        plans.append(SlidePlan(
            order=len(plans) + 1,
            slide_type=slide_type,
            template_key=self.config.template_keys[slide_type],
            data=data,
            issue_id=issue_id,
            context=dict(context or {}),
        ))

    def _validate_config(self) -> None:
        required = {
            SlideType.COVER,
            SlideType.SUMMARY,
            SlideType.PART_SPECIFICATIONS,
            SlideType.ISSUE_STANDARD,
            SlideType.ISSUE_COMPARE,
            SlideType.CONCLUSION,
        }
        missing = required.difference(self.config.template_keys)
        if missing:
            names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"SlidePlanner template keys missing: {names}")
        invalid_layouts = {
            layout for layout in self.config.category_layouts.values()
            if layout not in {SlideType.ISSUE_STANDARD, SlideType.ISSUE_COMPARE}
        }
        if invalid_layouts:
            names = ", ".join(sorted(item.value for item in invalid_layouts))
            raise ValueError(f"Category layouts must be issue slide types: {names}")


def plan_slides(report: DFMReport, config: Optional[SlidePlannerConfig] = None) -> List[SlidePlan]:
    """Convenience entry point for stateless planning."""

    return SlidePlanner(config).plan(report)
