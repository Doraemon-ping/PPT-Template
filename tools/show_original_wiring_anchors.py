"""打印原始单文件里几处"工序写入点"的原文（写替换清单时用来核对精确写法）。"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from integrate_machining_dfm import DEFAULT_SOURCE  # noqa: E402

ANCHORS = (
    "function addProc(",
    "function setProcMachine(",
    "].nm=",
    ".cI=''",
    "var fiFn=",
    "].fi=''",
)


def main() -> int:
    source = DEFAULT_SOURCE.read_text(encoding="utf-8-sig")
    for anchor in ANCHORS:
        start = 0
        hits = 0
        print(f"\n=== {anchor} ===")
        while True:
            index = source.find(anchor, start)
            if index < 0 or hits >= 3:
                break
            hits += 1
            line_start = source.rfind("\n", 0, index) + 1
            line_end = source.find("\n", index)
            line = source[line_start:line_end]
            print(f"  #{hits} ({len(line)} 字符)")
            print("   ", line if len(line) < 900 else line[:900] + " …")
            start = index + 1
        if not hits:
            print("   （没找到）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
