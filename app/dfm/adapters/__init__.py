# -*- coding: utf-8 -*-
"""Adapters from existing application payloads into domain contracts."""

from .legacy import LegacyDFMReportAdapter, adapt_legacy_report

__all__ = ["LegacyDFMReportAdapter", "adapt_legacy_report"]
