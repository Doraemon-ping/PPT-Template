# -*- coding: utf-8 -*-
"""Persistent binding schemes (模板方案).

A scheme captures "template pptx + binding relationships": which registered
template is used and the deck (pages with repeat/condition/bindings). Saving a
scheme lets users bind once and generate repeatedly with any form data; loading
it restores the editor for a second edit.
"""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

STORAGE_DIR = "data"
SCHEMES_SUBDIR = "schemes"
SCHEME_VERSION = "1"
_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


class SchemeError(RuntimeError):
    pass


class SchemeService:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.storage = self.root / STORAGE_DIR / SCHEMES_SUBDIR

    # ------------------------------------------------------------------ save
    def save(
        self,
        *,
        name: str,
        template: str,
        slides: List[Dict[str, Any]],
        description: str = "",
        output_mode: str = "deck",
        missing: str = "keep",
    ) -> Dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            raise SchemeError("方案名称不能为空")
        if not template:
            raise SchemeError("缺少模板")
        if not slides:
            raise SchemeError("方案没有页面（先添加报告页面）")
        if output_mode not in {"deck", "in_place"}:
            raise SchemeError("output_mode 必须是 deck 或 in_place")
        if missing not in {"keep", "clear", "error"}:
            raise SchemeError("missing 必须是 keep / clear / error")
        for index, slide in enumerate(slides):
            try:
                source = int(slide.get("source", 0))
            except (TypeError, ValueError):
                raise SchemeError(f"第 {index + 1} 页的 source 无效") from None
            if source < 1:
                raise SchemeError(f"第 {index + 1} 页的 source 无效：{source!r}")
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        record = {
            "scheme_version": SCHEME_VERSION,
            "name": name,
            "description": str(description or ""),
            "template": str(template),
            "created_at": now,
            "updated_at": now,
            "deck": {
                "output_mode": output_mode,
                "missing": missing,
                "slides": slides,
            },
        }
        path = self._path_for(name)
        self.storage.mkdir(parents=True, exist_ok=True)
        history = self.storage / 'versions' / path.stem
        history.mkdir(parents=True, exist_ok=True)
        if path.exists():
            previous = json.loads(path.read_text(encoding='utf-8'))
            record['created_at'] = previous.get('created_at', now)
            record['revision'] = int(previous.get('revision', 1)) + 1
            snapshot = history / f'{record["revision"]-1}.json'
            if not snapshot.exists(): snapshot.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding='utf-8')
        else:
            record['revision'] = 1
        temporary = self.storage / ('.' + uuid.uuid4().hex + '.tmp')
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return record

    def versions(self, name):
        current = self.get(name)
        history = self.storage / 'versions' / self._path_for(name).stem
        records = [current]
        for path in history.glob('*.json'):
            records.append(json.loads(path.read_text(encoding='utf-8')))
        return sorted(records, key=lambda r: int(r.get('revision', 1)), reverse=True)

    # ------------------------------------------------------------------ read
    def list(self) -> List[Dict[str, Any]]:
        if not self.storage.is_dir():
            return []
        results = []
        for path in sorted(self.storage.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            results.append({
                "name": record.get("name", path.stem),
                "template": record.get("template", ""),
                "description": record.get("description", ""),
                "created_at": record.get("created_at", ""),
                "updated_at": record.get("updated_at", ""),
                "slide_count": len((record.get("deck") or {}).get("slides", [])),
                "binding_count": sum(
                    len((slide or {}).get("bindings", {}))
                    for slide in (record.get("deck") or {}).get("slides", [])
                ),
            })
        results.sort(key=lambda item: item["updated_at"], reverse=True)
        return results

    def get(self, name: str) -> Dict[str, Any]:
        path = self._path_for(name)
        if not path.is_file():
            raise SchemeError(f"方案不存在：{name}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise SchemeError(f"方案读取失败：{name}") from exc

    def delete(self, name: str) -> bool:
        path = self._path_for(name)
        if not path.is_file():
            raise SchemeError(f"方案不存在：{name}")
        path.unlink()
        return True

    # ---------------------------------------------------------------- paths
    def _path_for(self, name: str) -> Path:
        key = str(name).strip().casefold()
        base = _SLUG_RE.sub("-", key).strip("-")
        if not base:
            base = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
        path = self.storage / f"{base}.json"
        # 同名覆盖（同名即更新）；不同名但 slug 相同则追加短哈希避免误覆盖
        if path.is_file():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("name") != str(name).strip():
                digest = hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:8]
                path = self.storage / f"{base}-{digest}.json"
        return path
