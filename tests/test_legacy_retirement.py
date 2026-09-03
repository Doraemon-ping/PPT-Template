# -*- coding: utf-8 -*-
import unittest

from app.demo import demo_state
from app.dfm import adapt_legacy_report
from app.report.ppt import SlidePlanner, audit_legacy_retirement


class LegacyRetirementTests(unittest.TestCase):
    def test_demo_is_blocked_because_new_engine_is_not_feature_equivalent(self):
        state = demo_state()
        report = adapt_legacy_report(state["f"], state["t"], state["i"])
        plans = SlidePlanner().plan(report)
        result = audit_legacy_retirement(
            state["f"], state["t"], state["i"],
            legacy_slide_count=47,
            new_slide_count=len(plans),
        )
        self.assertFalse(result.ready)
        self.assertNotEqual(47, result.new_slide_count)
        self.assertIn("new and legacy slide counts differ", result.blockers)
        self.assertTrue(result.unmapped_field_keys)
        self.assertTrue(result.unmapped_table_keys)

    def test_gate_only_opens_when_coverage_and_operational_evidence_are_complete(self):
        result = audit_legacy_retirement(
            {"partNo": "P-1"}, {"issues": []}, {},
            legacy_slide_count=4,
            new_slide_count=4,
            output_equivalence_verified=True,
            api_cutover_verified=True,
            rollback_verified=True,
        )
        self.assertTrue(result.ready)
        self.assertEqual((), result.blockers)

    def test_nonempty_top_level_image_blocks_retirement(self):
        result = audit_legacy_retirement(
            {}, {}, {"cadImg": "data:image/png;base64,abc"},
            legacy_slide_count=3,
            new_slide_count=3,
            output_equivalence_verified=True,
            api_cutover_verified=True,
            rollback_verified=True,
        )
        self.assertFalse(result.ready)
        self.assertEqual(("cadImg",), result.unmapped_image_keys)


if __name__ == "__main__":
    unittest.main()
