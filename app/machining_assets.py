"""Binary library assets (machine photos / documents).

Design rule for this service: **records live in the database, bytes live on the
filesystem**.  The ``assets`` table keeps only identity and metadata — ``kind``,
``mime``, ``name``, ``size``, ``sha256`` and the relative ``path`` — so no
library table or project snapshot ever inlines a base64 payload again.

Files are content addressed (``assets/<kind>/<sha[:2]>/<sha><ext>``) and written
atomically, which makes re-uploading the same bytes a no-op and lets the HTTP
layer serve them with a content-based ``ETag``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    mime TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    path TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_machining_dfm_assets_kind_sha_name
    ON assets(kind, sha256, name);
CREATE INDEX IF NOT EXISTS idx_machining_dfm_assets_path ON assets(path);
"""

IMAGE_MIMES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}
DOCUMENT_MIMES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/x-rar-compressed": ".rar",
    "application/x-7z-compressed": ".7z",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/octet-stream": ".bin",
}

# kind -> (allowed mime table, max bytes, human label)
KINDS: dict[str, tuple[dict[str, str], int, str]] = {
    "machine_photo": (IMAGE_MIMES, 8 * 1024 * 1024, "设备图片"),
    "machine_doc": (DOCUMENT_MIMES, 2 * 1024 * 1024, "设备资料"),
    "tool_photo": (IMAGE_MIMES, 8 * 1024 * 1024, "刀具图片"),
    "fixture_photo": (IMAGE_MIMES, 8 * 1024 * 1024, "夹具图片"),
    "gauge_photo": (IMAGE_MIMES, 8 * 1024 * 1024, "检具图片"),
    "project_photo": (IMAGE_MIMES, 8 * 1024 * 1024, "项目图片"),
    "inspection_photo": (IMAGE_MIMES, 8 * 1024 * 1024, "检具图片（项目内）"),
    # 工序夹具示意图（旧 cI）与工序刀具图（旧 fi）都归项目附件
    "process_photo": (IMAGE_MIMES, 8 * 1024 * 1024, "工序图片（项目内）"),
    # 问题清单的优化前/优化后图片（旧 bI / aI）
    "issue_photo": (IMAGE_MIMES, 8 * 1024 * 1024, "问题清单图片（项目内）"),
}

_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def extension_for(mime: str, table: dict[str, str]) -> str:
    return table.get(mime, ".bin")


def clean_kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(422, "不支持的资料类别：" + str(kind))
    if not _KIND_PATTERN.match(kind):
        raise HTTPException(422, "资料类别命名不合法")
    return kind


def _normalise_mime(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


class AssetStore:
    """Filesystem bytes + SQLite metadata for shared library attachments."""

    def __init__(self, root: Path, connect: Callable[[], Any]):
        self.root = Path(root)
        self.dir = self.root / "assets"
        self._connect = connect

    @contextmanager
    def session(self, db=None):
        """Reuse an open transaction when given one, otherwise open our own."""
        if db is not None:
            yield db
        else:
            with self._connect() as conn:
                yield conn

    # ---------------- schema / paths ----------------

    @staticmethod
    def schema(db) -> None:
        db.executescript(SCHEMA)

    def relative_path(self, kind: str, sha256: str, mime: str) -> str:
        table = KINDS[kind][0]
        return "/".join((kind, sha256[:2], sha256 + extension_for(mime, table)))

    def file_path(self, record: Any) -> Path:
        return self.dir / str(record["path"])

    def url(self, asset_id: str | None, *, download: bool = False) -> str | None:
        if not asset_id:
            return None
        suffix = "?download=1" if download else ""
        return f"/api/machining-dfm/assets/{asset_id}{suffix}"

    # ---------------- reads ----------------

    def record(self, asset_id: str | None, *, db=None) -> dict[str, Any] | None:
        if not asset_id:
            return None
        with self.session(db) as conn:
            row = conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        return dict(row) if row else None

    def read_bytes(self, asset_id: str | None) -> bytes | None:
        record = self.record(asset_id)
        if record is None:
            return None
        path = self.file_path(record)
        if not path.is_file():
            return None
        return path.read_bytes()

    def data_url(self, asset_id: str | None) -> str | None:
        """Inline the bytes for consumers that must carry the payload (PPT provider)."""
        record = self.record(asset_id)
        if record is None:
            return None
        raw = self.read_bytes(asset_id)
        if raw is None:
            return None
        return "data:%s;base64,%s" % (record["mime"], base64.b64encode(raw).decode("ascii"))

    # ---------------- writes ----------------

    def put(
        self,
        kind: str,
        data: bytes,
        mime: str | None,
        name: str = "",
        *,
        db=None,
        source_url: bool = False,
    ) -> dict[str, Any] | None:
        """Store ``data`` and return its metadata row (``None`` for empty input).

        ``source_url`` marks a payload that arrived as a legacy data URL; empty
        content is then a valid "no asset" marker instead of an error.
        """
        clean_kind(kind)
        table, limit, label = KINDS[kind]
        if not data:
            if source_url:
                return None
            raise HTTPException(422, label + "内容为空")
        if len(data) > limit:
            raise HTTPException(413, label + f"超过 {limit // (1024 * 1024)} MB 上限")
        cleaned_name = str(name or "").strip()[:160]
        resolved = _normalise_mime(mime) or "application/octet-stream"
        if resolved not in table:
            resolved = "application/octet-stream"
            if resolved not in table:
                raise HTTPException(415, label + "格式不受支持：" + str(mime or "未知"))
        digest = hashlib.sha256(data).hexdigest()
        relative = self.relative_path(kind, digest, resolved)
        with self.session(db) as conn:
            existing = conn.execute(
                "SELECT * FROM assets WHERE kind=? AND sha256=? AND name=?", (kind, digest, cleaned_name)
            ).fetchone()
            if existing:
                return dict(existing)
            target = self.dir / relative
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                handle, temporary = tempfile.mkstemp(dir=str(target.parent), suffix=".part")
                try:
                    with os.fdopen(handle, "wb") as stream:
                        stream.write(data)
                    os.replace(temporary, target)
                except BaseException:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
                    raise
            now = _stamp()
            record = {
                "id": uuid.uuid4().hex,
                "kind": kind,
                "mime": resolved,
                "name": cleaned_name,
                "size": len(data),
                "sha256": digest,
                "path": relative,
                "created": now,
            }
            conn.execute(
                "INSERT INTO assets(id,kind,mime,name,size,sha256,path,created) VALUES(?,?,?,?,?,?,?,?)",
                (record["id"], kind, resolved, cleaned_name, len(data), digest, relative, now),
            )
        return record

    def put_data_url(self, kind: str, value: str | None, name: str = "", *, db=None) -> dict[str, Any] | None:
        """Ingest a legacy ``data:<mime>;base64,<payload>`` value."""
        if not value or not isinstance(value, str) or not value.startswith("data:"):
            return None
        header, _, payload = value.partition(",")
        if "base64" not in header:
            return None
        mime = _normalise_mime(header[5:].split(";", 1)[0])
        try:
            data = base64.b64decode(payload, validate=False)
        except (binascii.Error, ValueError):
            return None
        return self.put(kind, data, mime, name, db=db, source_url=True)

    def asset_reference(self, value: Any) -> str | None:
        """Return the asset id when ``value`` is already one of our asset URLs."""
        if not value or not isinstance(value, str):
            return None
        match = re.search(r"/api/machining-dfm/assets/([A-Za-z0-9]+)", value)
        return match.group(1) if match else None

    def delete(self, asset_id: str | None, *, db=None) -> None:
        """Delete metadata and the file once no other row references it."""
        record = self.record(asset_id, db=db)
        if record is None:
            return
        with self.session(db) as conn:
            conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
            remaining = conn.execute("SELECT 1 FROM assets WHERE path=? LIMIT 1", (record["path"],)).fetchone()
        if remaining is None:
            try:
                self.file_path(record).unlink()
            except OSError:
                pass

    def prune_orphans(self) -> int:
        """Remove files no metadata row points at (crash leftovers)."""
        if not self.dir.is_dir():
            return 0
        with self._connect() as db:
            known = {row[0] for row in db.execute("SELECT path FROM assets")}
        removed = 0
        for path in self.dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.dir).as_posix()
            if relative in known or relative.endswith(".part"):
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed
