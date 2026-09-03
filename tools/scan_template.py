# -*- coding: utf-8 -*-
"""CLI: scan any PPTX template and print the ``{path}`` placeholder inventory.

Usage:
    python tools/scan_template.py templates/DFM_Template_Placeholder_Demo.pptx
    python tools/scan_template.py "1-基础数据/高压项目DFM交流模板A12版_中文_2025-09-30.pptx  -  已修复.pptx" --json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.report.ppt.openxml import PlaceholderScanner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a PPTX template for {path} placeholders")
    parser.add_argument("template", help="path to a .pptx template")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a text report")
    args = parser.parse_args()

    path = Path(args.template)
    if not path.is_file():
        print(f"template not found: {path}", file=sys.stderr)
        return 1

    scan = PlaceholderScanner().scan(path)
    if args.json:
        print(json.dumps(scan.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"template: {path}")
    print(f"slides: {scan.slide_count} | placeholders: {scan.placeholder_count} | "
          f"media: {scan.media_part_count} | notes: {scan.notes_slide_count} | OLE: {scan.ole_part_count}")
    if not scan.placeholder_paths:
        print("no {path} placeholders found — open the template in PowerPoint and replace "
              "target text with placeholders like {f.partNo} (pptx-template convention).")
        return 0
    print("placeholder paths:")
    for path_value in scan.placeholder_paths:
        print(f"  {{{path_value}}}")
    print("\nby slide:")
    for slide in scan.slides:
        if not slide.placeholders:
            continue
        print(f"  slide {slide.slide_index} ({slide.part_name}):")
        for item in slide.placeholders:
            print(f"    shape={item.shape_name!r} {{{item.path}}} x{item.occurrences}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
