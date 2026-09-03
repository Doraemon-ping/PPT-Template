# -*- coding: utf-8 -*-
"""Render an exact slide preview through desktop PowerPoint and cache it."""
import os
import shutil
import subprocess
import threading
from pathlib import Path


class SlidePreviewError(RuntimeError):
    pass


_LOCK = threading.Lock()


def render_slide_preview(template_path: Path, slide_index: int, cache_root: Path) -> Path:
    template_path = Path(template_path).resolve()
    if not template_path.is_file():
        raise SlidePreviewError(f"template file missing: {template_path}")
    if slide_index < 1:
        raise SlidePreviewError(f"slide index out of range: {slide_index}")
    stat = template_path.stat()
    fingerprint = f"{stat.st_size}-{stat.st_mtime_ns}"
    safe_stem = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in template_path.stem)[:64]
    target = (Path(cache_root) / safe_stem / fingerprint / f"slide_{slide_index:03d}.png").resolve()
    if target.is_file() and target.stat().st_size > 0:
        return target
    script = Path(__file__).resolve().parents[3] / "tools" / "export_slide_preview.ps1"
    if not script.is_file():
        raise SlidePreviewError(f"preview exporter missing: {script}")
    shell = shutil.which("pwsh.exe") or shutil.which("pwsh") or shutil.which("powershell.exe")
    if not shell:
        raise SlidePreviewError("PowerShell is unavailable; cannot call PowerPoint preview exporter")
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(script), "-TemplatePath", str(template_path),
        "-SlideIndex", str(slide_index), "-OutputPath", str(target),
        "-Width", "1600", "-Height", "900",
    ]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    with _LOCK:
        if target.is_file() and target.stat().st_size > 0:
            return target
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=75,
                errors='replace',
                check=False, creationflags=creation_flags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SlidePreviewError(f"PowerPoint preview failed: {exc}") from exc
        if completed.returncode != 0 or not target.is_file():
            detail = (completed.stderr or completed.stdout or "unknown PowerPoint error").strip()
            raise SlidePreviewError(f"PowerPoint preview failed: {detail[-800:]}")
    return target
