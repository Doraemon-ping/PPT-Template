# -*- coding: utf-8 -*-
"""Name formal-template shapes through PowerPoint without changing visuals."""

import argparse
import os
import subprocess
from pathlib import Path


POWERSHELL = r"""
$sourcePpt = $env:DFM_EXACT_SOURCE
$outputPpt = $env:DFM_EXACT_OUTPUT
$powerPoint = New-Object -ComObject PowerPoint.Application
try {
    $deck = $powerPoint.Presentations.Open($sourcePpt, $true, $false, $false)
    $deck.Slides.Item(1).Shapes.Item(2).Name = 'EXACT_COVER_TITLE'
    $deck.Slides.Item(1).Shapes.Item(3).Name = 'EXACT_COVER_DATE'
    $deck.Slides.Item(1).Shapes.Item(4).Name = 'EXACT_REMOVE_COVER_INSTRUCTION'
    $deck.Slides.Item(4).Shapes.Item(2).Name = 'EXACT_PART_ANALYSIS_TABLE'
    $deck.Slides.Item(77).Shapes.Item(1).Name = 'EXACT_ISSUE_TABLE'
    $deck.Slides.Item(77).Shapes.Item(6).Name = 'EXACT_ISSUE_IMAGE_BEFORE'
    $deck.Slides.Item(77).Shapes.Item(9).Name = 'EXACT_ISSUE_IMAGE_AFTER'
    $deck.SaveCopyAs($outputPpt)
    $deck.Close()
} finally {
    $powerPoint.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint) | Out-Null
}
"""


def build(source: Path, output: Path) -> None:
    source, output = source.resolve(), output.resolve()
    if source == output:
        raise ValueError("output must not overwrite source")
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["DFM_EXACT_SOURCE"] = str(source)
    environment["DFM_EXACT_OUTPUT"] = str(output)
    subprocess.run(
        ["pwsh", "-NoProfile", "-Command", POWERSHELL],
        check=True,
        env=environment,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()
