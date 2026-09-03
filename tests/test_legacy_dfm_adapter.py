# -*- coding: utf-8 -*-
import copy
import unittest

from app.demo import demo_state
from app.dfm.adapters import LegacyDFMReportAdapter, adapt_legacy_report
from app.dfm.models import IssueSeverity


class LegacyDFMReportAdapterTests(unittest.TestCase):
    def test_maps_part_specifications_without_calculation(self):
        report = adapt_legacy_report({
            "wFinish": "3.85", "wCast": "4.20", "wall": "3.0",
            "dimL": "486", "dimW": "212", "dimH": "138",
            "material": "AlSi10MnMg", "annual": "120000",
        }, {}, {})
        specs = report.part_specifications
        self.assertEqual("3.85", specs.finished_weight)
        self.assertEqual("4.20", specs.casting_weight)
        self.assertEqual("3.0", specs.wall_thickness)
        self.assertEqual(("486", "212", "138"), (specs.length, specs.width, specs.height))
        self.assertEqual("AlSi10MnMg", specs.material)
        self.assertEqual("120000", specs.annual_volume)

    def test_maps_current_demo_state_without_mutating_it(self):
        state = demo_state()
        original = copy.deepcopy(state)

        report = adapt_legacy_report(state["f"], state["t"], state["i"])

        self.assertEqual("某新能源汽车后纵梁支架", report.project.project_name)
        self.assertEqual("TP-HPDC-2026-0087", report.project.part_number)
        self.assertEqual(2, report.summary.total)
        self.assertEqual(2, report.summary.unknown)
        self.assertEqual("1", report.issues[0].id)
        self.assertEqual("OpenIssue", report.issues[0].category)
        self.assertEqual("开放", report.issues[0].extra_data["st"])
        self.assertEqual(original, state)

    def test_counts_only_explicit_severity_without_business_inference(self):
        report = LegacyDFMReportAdapter().adapt(
            {"partNo": "P-1", "version": "A"},
            {"issues": [
                {"no": "1", "desc": "A", "severity": "Critical"},
                {"no": "2", "desc": "B", "level": "主要"},
                {"no": "3", "desc": "C", "severity": "Minor"},
                {"no": "4", "desc": "D", "st": "开放"},
            ]},
            {},
        )

        self.assertEqual(4, report.summary.total)
        self.assertEqual(1, report.summary.critical)
        self.assertEqual(1, report.summary.major)
        self.assertEqual(1, report.summary.minor)
        self.assertEqual(1, report.summary.unknown)
        self.assertEqual(IssueSeverity.UNKNOWN, report.issues[-1].severity)

    def test_generates_stable_fallback_issue_id(self):
        report = adapt_legacy_report({}, {"issues": [{"desc": "missing id"}]}, {})
        self.assertEqual("DFM-001", report.issues[0].id)


if __name__ == "__main__":
    unittest.main()
