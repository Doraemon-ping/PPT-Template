# -*- coding: utf-8 -*-
import unittest

from app.dfm.models import (
    DFMIssue,
    DFMPartSpecifications,
    DFMProject,
    DFMReport,
    DFMSummary,
    IssueSeverity,
    SlideType,
)
from app.report.ppt import SlidePlanner, SlidePlannerConfig, plan_slides


def make_report(issues):
    return DFMReport(
        project=DFMProject(project_name="Project", part_number="P-001"),
        summary=DFMSummary(
            total=len(issues),
            critical=sum(i.severity == IssueSeverity.CRITICAL for i in issues),
            major=sum(i.severity == IssueSeverity.MAJOR for i in issues),
            minor=sum(i.severity == IssueSeverity.MINOR for i in issues),
        ),
        issues=issues,
    )


class SlidePlannerTests(unittest.TestCase):
    def test_includes_part_specifications_only_when_they_have_content(self):
        report = make_report([])
        report.part_specifications = DFMPartSpecifications(material="AlSi10MnMg")

        plans = plan_slides(report)

        self.assertEqual(SlideType.PART_SPECIFICATIONS, plans[2].slide_type)
        self.assertEqual("PART_SPECIFICATIONS", plans[2].template_key)
        self.assertEqual("AlSi10MnMg", plans[2].data.material)

    def test_plans_cover_summary_three_issues_and_conclusion(self):
        report = make_report([
            DFMIssue(id="DFM-001", severity=IssueSeverity.CRITICAL),
            DFMIssue(id="DFM-002", severity=IssueSeverity.MAJOR),
            DFMIssue(id="DFM-003", severity=IssueSeverity.MAJOR),
        ])

        plans = plan_slides(report)

        self.assertEqual(6, len(plans))
        self.assertEqual(
            [
                SlideType.COVER,
                SlideType.SUMMARY,
                SlideType.ISSUE_STANDARD,
                SlideType.ISSUE_STANDARD,
                SlideType.ISSUE_STANDARD,
                SlideType.CONCLUSION,
            ],
            [plan.slide_type for plan in plans],
        )
        self.assertEqual([1, 2, 3, 4, 5, 6], [plan.order for plan in plans])
        self.assertEqual(["DFM-001", "DFM-002", "DFM-003"], [p.issue_id for p in plans[2:5]])

    def test_before_after_images_select_compare_layout(self):
        issue = DFMIssue(
            id="DFM-001",
            images={"before": "before.png", "after": ["after.png"]},
        )

        plan = plan_slides(make_report([issue]))[2]

        self.assertEqual(SlideType.ISSUE_COMPARE, plan.slide_type)
        self.assertEqual("ISSUE_COMPARE", plan.template_key)

    def test_incomplete_comparison_uses_standard_layout(self):
        issue = DFMIssue(id="DFM-001", images={"before": "before.png"})
        plan = plan_slides(make_report([issue]))[2]
        self.assertEqual(SlideType.ISSUE_STANDARD, plan.slide_type)

    def test_category_rule_can_override_image_rule(self):
        issue = DFMIssue(id="DFM-001", category="DraftAngle")
        config = SlidePlannerConfig(category_layouts={"DraftAngle": SlideType.ISSUE_COMPARE})

        plan = SlidePlanner(config).plan(make_report([issue]))[2]

        self.assertEqual(SlideType.ISSUE_COMPARE, plan.slide_type)

    def test_planning_does_not_modify_report(self):
        issue = DFMIssue(id="DFM-001", title="Original")
        report = make_report([issue])

        plans = plan_slides(report)

        self.assertEqual("Original", report.issues[0].title)
        self.assertIs(report.issues[0], plans[2].data)

    def test_missing_template_mapping_fails_early(self):
        with self.assertRaisesRegex(ValueError, "template keys missing"):
            SlidePlanner(SlidePlannerConfig(template_keys={}))


if __name__ == "__main__":
    unittest.main()
