# -*- coding: utf-8 -*-
"""Print the current demo project's legacy-retirement readiness as JSON."""

import json
from pathlib import Path
import sys

from pptx import Presentation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.demo import demo_state  # noqa: E402
from app.dfm import adapt_legacy_report  # noqa: E402
from app.ppt import build_pptx  # noqa: E402
from app.report.ppt import SlidePlanner, audit_legacy_retirement  # noqa: E402


def main() -> int:
    state = demo_state()
    report = adapt_legacy_report(state["f"], state["t"], state["i"])
    plans = SlidePlanner().plan(report)
    legacy = Presentation(build_pptx(state["f"], state["t"], state["i"]))
    result = audit_legacy_retirement(
        state["f"], state["t"], state["i"],
        legacy_slide_count=len(legacy.slides),
        new_slide_count=len(plans),
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
