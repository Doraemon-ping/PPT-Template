# -*- coding: utf-8 -*-
"""Persistent template registry for uploaded and built-in templates.

Built-in templates (official / exact / pilot / demo) live in the repository.
User-uploaded templates are stored under ``data/templates/<template_id>/`` with
a small ``template.json`` metadata record, and the whole registry is persisted
to ``data/templates/registry.json`` so uploads survive restarts.
"""
import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

UPLOADED_DIR = "data"
TEMPLATES_SUBDIR = "templates"
REGISTRY_FILE = "registry.json"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB safety cap

_BUILTIN_PATHS = {
    "official": "1-基础数据/高压项目DFM交流模板A12版_中文_2025-09-30.pptx  -  已修复.pptx",
    "exact": "templates/DFM_Master_exact_v1.pptx",
    "pilot": "templates/DFM_Master_v1.pptx",
    "demo": "templates/DFM_Template_Placeholder_Demo.pptx",
    "table-demo": "templates/DFM_Template_Table_Demo.pptx",
}

_SLIDE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class TemplateRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class TemplateRecord:
    template_id: str
    path: Path
    origin: str  # builtin | uploaded
    source_name: str = ""
    sha256: str = ""
    uploaded_at: str = ""
    version: str = "1"

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "path": str(self.path),
            "origin": self.origin,
            "source_name": self.source_name,
            "sha256": self.sha256,
            "uploaded_at": self.uploaded_at,
            "version": self.version,
            "exists": self.path.is_file(),
            "size": self.path.stat().st_size if self.path.is_file() else 0,
        }


class TemplateRegistry:
    """Resolve template ids to files; persists uploaded templates on disk."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.storage = self.root / UPLOADED_DIR / TEMPLATES_SUBDIR
        self.registry_file = self.storage / REGISTRY_FILE
        self._uploaded: Dict[str, TemplateRecord] = {}
        self._load()

    # ------------------------------------------------------------------ list
    def list(self) -> List[TemplateRecord]:
        records = []
        for template_id, relative in _BUILTIN_PATHS.items():
            records.append(TemplateRecord(
                template_id=template_id,
                path=self.root / relative,
                origin="builtin",
                source_name=relative,
            ))
        records.extend(sorted(self._uploaded.values(), key=lambda r: r.uploaded_at))
        return records

    def resolve(self, template_id: str) -> TemplateRecord:
        wanted = str(template_id or "").casefold()
        for record in self.list():
            if record.template_id == wanted or record.template_id.casefold() == wanted:
                if not record.path.is_file():
                    raise TemplateRegistryError(f"template file missing: {template_id} -> {record.path}")
                return record
        known = ", ".join(record.template_id for record in self.list())
        raise TemplateRegistryError(f"unknown template: {template_id} (known: {known})")

    # ---------------------------------------------------------------- upload
    def register_upload(
        self,
        *,
        template_id: str,
        data: bytes,
        source_name: str = "",
        version: str = "1",
    ) -> TemplateRecord:
        template_id = self._normalize_id(template_id)
        if template_id in _BUILTIN_PATHS:
            raise TemplateRegistryError(f"template id conflicts with built-in template: {template_id}")
        if not data:
            raise TemplateRegistryError("uploaded file is empty")
        if len(data) > MAX_UPLOAD_BYTES:
            raise TemplateRegistryError(
                f"uploaded file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"
            )
        target_dir = self.storage / template_id
        target_dir.mkdir(parents=True, exist_ok=True)
        master = target_dir / "master.pptx"
        master.write_bytes(data)
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        record = TemplateRecord(
            template_id=template_id,
            path=master,
            origin="uploaded",
            source_name=str(source_name or master.name),
            sha256=sha256_of(data),
            uploaded_at=now,
            version=str(version or "1"),
        )
        self._uploaded[template_id] = record
        self._save()
        return record

    def delete(self, template_id: str) -> bool:
        record = self._uploaded.get(template_id)
        if record is None:
            raise TemplateRegistryError(f"uploaded template not found: {template_id}")
        shutil.rmtree(record.path.parent, ignore_errors=True)
        del self._uploaded[template_id]
        self._save()
        return True

    # --------------------------------------------------------------- helpers
    def _normalize_id(self, template_id: str) -> str:
        value = str(template_id or "").strip().casefold()
        value = re.sub(r"[^A-Za-z0-9_-]", "-", value)
        if not _SLIDE_ID_RE.match(value):
            raise TemplateRegistryError(f"invalid template id: {template_id!r}")
        return value

    def _load(self) -> None:
        if not self.registry_file.is_file():
            return
        try:
            payload = json.loads(self.registry_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for item in payload.get("templates", []):
            path = self.storage / item["template_id"] / "master.pptx"
            self._uploaded[item["template_id"]] = TemplateRecord(
                template_id=item["template_id"],
                path=path,
                origin="uploaded",
                source_name=item.get("source_name", ""),
                sha256=item.get("sha256", ""),
                uploaded_at=item.get("uploaded_at", ""),
                version=item.get("version", "1"),
            )

    def _save(self) -> None:
        self.storage.mkdir(parents=True, exist_ok=True)
        payload = {
            "templates": [
                {
                    "template_id": record.template_id,
                    "source_name": record.source_name,
                    "sha256": record.sha256,
                    "uploaded_at": record.uploaded_at,
                    "version": record.version,
                }
                for record in self._uploaded.values()
            ]
        }
        self.registry_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
