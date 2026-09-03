# -*- coding: utf-8 -*-
"""DFM domain boundary models and adapters.

The existing calculation and PPT modules intentionally remain unchanged during
the first migration stage.
"""

from .adapters.legacy import LegacyDFMReportAdapter, adapt_legacy_report
from .models.report import DFMReport

__all__ = ["DFMReport", "LegacyDFMReportAdapter", "adapt_legacy_report"]
