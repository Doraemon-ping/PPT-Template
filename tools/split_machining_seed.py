"""Split the monolithic machining seed into per-entity resources.

Usage:
    python tools/split_machining_seed.py [legacy_seed.json] [output_dir]

The machine library is the first table to become typed, so ``mdb`` rows become
``machines.json`` (page key per column, stable id, photo file reference) and the
embedded base64 photos are written out as real files under ``assets/machines/``.
All other entities are written as their own JSON file untouched.

``split_seed()`` is also imported by ``tools/integrate_machining_dfm.py`` so the
integrated tool writes the split layout directly, without a monolithic stopover.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

DEFAULT_SEED = Path("app/resources/machining_dfm_seed.json")
DEFAULT_OUT = Path("app/resources/machining_dfm_seed")
PAGE_KEYS = ("brand", "model", "xyz", "pa", "rpa", "rapid", "tc", "spm", "atc", "price", "desc")
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
FALLBACK_BRAND = "自定义"


def slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return cleaned[:36]


def machine_id(index: int, row: dict) -> str:
    suffix = slug(f"{row.get('brand', '')}-{row.get('model', '')}") or "machine"
    return f"m-{index:02d}-{suffix}"


def write_json(path: Path, payload, *, indent: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")


def split_seed(seed: dict, out_dir: Path) -> dict[str, int]:
    """Write one JSON resource per entity and return row counts."""
    out_dir = Path(out_dir)
    asset_dir = out_dir / "assets" / "machines"
    machines: list[dict] = []
    ids: list[str] = []
    for index, row in enumerate(seed.get("mdb", [])):
        identifier = machine_id(index, row)
        ids.append(identifier)
        entry: dict = {"id": identifier, "is_fallback": row.get("brand") == FALLBACK_BRAND}
        for key in PAGE_KEYS:
            if key in row:
                entry[key] = row[key]
        photo = row.get("img")
        if isinstance(photo, str) and photo.startswith("data:"):
            header, _, payload = photo.partition(",")
            mime = header[5:].split(";", 1)[0].strip().lower()
            extension = EXTENSIONS.get(mime, ".jpg")
            asset_dir.mkdir(parents=True, exist_ok=True)
            (asset_dir / f"{identifier}{extension}").write_bytes(base64.b64decode(payload))
            entry["photo"] = f"assets/machines/{identifier}{extension}"
        machines.append(entry)

    # 兜底机型必须唯一：优先 brand='自定义'，否则取最后一行（旧代码的数组末行约定）。
    if not any(item["is_fallback"] for item in machines):
        for item in machines:
            item["is_fallback"] = False
        if machines:
            machines[-1]["is_fallback"] = True

    processes = []
    for process in seed.get("pr", []):
        row = {key: value for key, value in process.items() if key != "mi"}
        try:
            index = int(process.get("mi", -1))
        except (TypeError, ValueError):
            index = -1
        if 0 <= index < len(ids):
            row["mid"] = ids[index]
        processes.append(row)

    general = {key: value for key, value in (seed.get("G") or {}).items() if key not in {"icnX", "fcnX"}}
    write_json(out_dir / "machines.json", {"machines": machines})
    write_json(out_dir / "project.json", {
        "G": general,
        "pr": processes,
        "is": seed.get("is", []),
        "vh": seed.get("vh", []),
    })
    write_json(out_dir / "categories.json", {
        "icnX": (seed.get("G") or {}).get("icnX", []),
        "fcnX": (seed.get("G") or {}).get("fcnX", []),
    })
    write_json(out_dir / "tools.json", seed.get("tdb", []), indent=1)
    write_json(out_dir / "fixtures.json", seed.get("fdb", []), indent=1)
    write_json(out_dir / "gauges.json", seed.get("idb", []), indent=1)
    return {
        "machines": len(machines),
        "processes": len(processes),
        "tools": len(seed.get("tdb", [])),
        "fixtures": len(seed.get("fdb", [])),
        "gauges": len(seed.get("idb", [])),
    }


def main(argv: list[str]) -> int:
    seed_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_SEED
    out_dir = Path(argv[2]) if len(argv) > 2 else DEFAULT_OUT
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    counts = split_seed(seed, out_dir)
    print(" ".join(f"{key}={value}" for key, value in counts.items()) + f" -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
