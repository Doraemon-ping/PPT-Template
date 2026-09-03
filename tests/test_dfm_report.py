# -*- coding: utf-8 -*-
import unittest

from pydantic import ValidationError

from app.dfm.models import DFMProject, DFMReport, DFMSummary


class DFMReportModelTests(unittest.TestCase):
    def test_report_uses_independent_collection_defaults(self):
        first = DFMReport(project=DFMProject(), summary=DFMSummary())
        second = DFMReport(project=DFMProject(), summary=DFMSummary())

        first.metadata.extra_data["key"] = "value"

        self.assertEqual([], first.issues)
        self.assertNotIn("key", second.metadata.extra_data)

    def test_summary_rejects_negative_counts(self):
        with self.assertRaises(ValidationError):
            DFMSummary(total=-1)

