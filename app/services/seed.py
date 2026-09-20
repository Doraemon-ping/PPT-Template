"""Initial data for the machining DFM service.

The seed used to be one monolithic JSON file.  It is now split per entity so a
single table can be seeded — and reviewed — on its own::

    app/resources/machining_dfm_seed/
        project.json      项目数据（G / pr / is / vh）
        machines.json     设备库（每行对应设备表的一个列集合）
        tools.json        刀具库
        fixtures.json     夹具库
        gauges.json       检具库
        categories.json   自定义类别（icnX / fcnX）
        assets/machines/  设备照片文件（数据库只存元数据）

A legacy monolithic seed file is still accepted so older callers keep working:
in that mode machine rows get deterministic ``seed-NN`` ids and ``pr[].mi``
indexes are translated into ``pr[].mid`` references.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


class SeedBundle:
    """Reads the split seed resources (or a legacy monolithic seed file)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.split = self.path.is_dir()
        if not self.split and not self.path.is_file():
            raise RuntimeError(f"机加 DFM 初始数据不存在：{self.path}")

    # ---------------- helpers ----------------

    def _read_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def _split_file(self, name: str) -> Path:
        return self.path / f"{name}.json"

    def _legacy(self) -> dict[str, Any]:
        return {} if self.split else self._read_json(self.path)

    # ---------------- entities ----------------

    def machines(self) -> list[dict[str, Any]]:
        if not self.split:
            rows: list[dict[str, Any]] = []
            for index, row in enumerate(self._legacy().get("mdb", [])):
                if not isinstance(row, dict):
                    continue
                rows.append({**row, "id": f"seed-{index:02d}"})
            return rows
        path = self._split_file("machines")
        raw = self._read_json(path) if path.is_file() else {"machines": []}
        rows = raw.get("machines", []) if isinstance(raw, dict) else raw
        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            entry = {key: value for key, value in row.items() if key != "photo"}
            photo = row.get("photo")
            if isinstance(photo, str) and photo:
                asset = self.path / photo
                if not asset.is_file():
                    raise RuntimeError(f"设备库初始照片不存在：{asset}")
                entry["photo"] = asset.read_bytes()
                entry["photo_mime"] = MIME_BY_SUFFIX.get(asset.suffix.lower(), "image/jpeg")
            result.append(entry)
        return result

    def machine_ids(self) -> list[str]:
        return [str(row.get("id") or "") for row in self.machines()]

    def _array(self, name: str, legacy_key: str | None = None) -> list[dict[str, Any]]:
        if self.split:
            path = self._split_file(name)
            raw = self._read_json(path) if path.is_file() else []
        else:
            raw = self._legacy().get(legacy_key or name, [])
        if isinstance(raw, dict):
            raw = raw.get(name, [])
        return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []

    def tools(self) -> list[dict[str, Any]]:
        return self._array("tools", "tdb")

    def fixtures(self) -> list[dict[str, Any]]:
        return self._array("fixtures", "fdb")

    def gauges(self) -> list[dict[str, Any]]:
        return self._array("gauges", "idb")

    def categories(self) -> dict[str, list[str]]:
        if self.split:
            path = self._split_file("categories")
            raw = self._read_json(path) if path.is_file() else {}
        else:
            general = self._legacy().get("G", {})
            raw = {"icnX": general.get("icnX", []), "fcnX": general.get("fcnX", [])}
        return {
            "icnX": [str(item) for item in raw.get("icnX", [])],
            "fcnX": [str(item) for item in raw.get("fcnX", [])],
        }

    def project(self) -> dict[str, Any]:
        """Project-owned seed data with ``pr[].mid`` pointing at library rows."""
        if self.split:
            path = self._split_file("project")
            raw = self._read_json(path) if path.is_file() else {}
        else:
            legacy = self._legacy()
            raw = {key: legacy.get(key, {} if key == "G" else []) for key in ("G", "pr", "is", "vh")}
        result = {
            "G": dict(raw.get("G") or {}),
            "pr": list(raw.get("pr") or []),
            "is": list(raw.get("is") or []),
            "vh": list(raw.get("vh") or []),
        }
        machine_ids = [machine_id for machine_id in self.machine_ids() if machine_id]
        fallback = ""
        for row in self.machines():
            if row.get("is_fallback"):
                fallback = str(row.get("id") or "")
                break
        if not fallback and machine_ids:
            fallback = machine_ids[-1]
        for process in result["pr"]:
            if not isinstance(process, dict):
                continue
            reference = str(process.get("mid") or "").strip()
            if not reference or reference not in machine_ids:
                legacy_index = process.get("mi")
                try:
                    index = int(legacy_index)
                except (TypeError, ValueError):
                    index = -1
                reference = machine_ids[index] if 0 <= index < len(machine_ids) else fallback
                process["mid"] = reference
            process.pop("mi", None)
        return result

    def legacy_library(self, key: str) -> list[dict[str, Any]]:
        """Legacy key (``tdb`` / ``fdb`` / ``idb``) → seed rows."""
        return {
            "tdb": self.tools,
            "fdb": self.fixtures,
            "idb": self.gauges,
        }[key]()
