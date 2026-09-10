# -*- coding: utf-8 -*-
"""Render an exact slide preview through desktop PowerPoint and cache it."""
import atexit
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path


class SlidePreviewError(RuntimeError):
    pass


_LOCK = threading.Lock()
_WORKER_SCRIPT = Path(__file__).resolve().parents[3] / "tools" / "preview_worker.ps1"
_WORKER = None


class _WorkerUnavailable(RuntimeError):
    """The persistent renderer died before returning a job result."""


class _PersistentPowerPointRenderer:
    def __init__(self, shell: str, script: Path):
        self.shell = shell
        self.script = script
        self.process = None
        self.responses = None
        self.reader = None

    def _start(self):
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                [self.shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(self.script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
        except OSError as exc:
            raise _WorkerUnavailable(str(exc)) from exc
        response_queue = queue.Queue()
        self.responses = response_queue
        process = self.process

        def read_responses():
            try:
                for line in process.stdout:
                    response_queue.put(line)
            finally:
                response_queue.put(None)

        self.reader = threading.Thread(target=read_responses, name="dfm-preview-worker-reader", daemon=True)
        self.reader.start()

    def close(self):
        process, self.process = self.process, None
        self.responses = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

    def render(self, template_path: Path, slide_index: int, output_path: Path, width: int, height: int):
        if self.process is None or self.process.poll() is not None:
            self.close()
            self._start()
        job = json.dumps({
            "TemplatePath": str(template_path),
            "SlideIndex": int(slide_index),
            "OutputPath": str(output_path),
            "Width": int(width),
            "Height": int(height),
        }, ensure_ascii=True, separators=(",", ":"))
        try:
            self.process.stdin.write(job + "\n")
            self.process.stdin.flush()
            line = self.responses.get(timeout=75)
        except (OSError, queue.Empty, AttributeError) as exc:
            self.close()
            raise _WorkerUnavailable(f"persistent PowerPoint renderer stopped: {exc}") from exc
        if line is None:
            self.close()
            raise _WorkerUnavailable("persistent PowerPoint renderer exited without a result")
        try:
            result = json.loads(line)
        except json.JSONDecodeError as exc:
            self.close()
            raise _WorkerUnavailable(f"invalid persistent renderer response: {line!r}") from exc
        if not result.get("ok"):
            raise SlidePreviewError(result.get("error") or "PowerPoint preview failed")
        if not output_path.is_file():
            raise SlidePreviewError(f"PowerPoint did not create preview: {output_path}")


def _shutdown_worker():
    global _WORKER
    if _WORKER is not None:
        _WORKER.close()
        _WORKER = None


atexit.register(_shutdown_worker)


def _run_one_shot_export(command: list[str], creation_flags: int, target: Path) -> None:
    """Run the compatibility exporter, retrying one stale Windows process handle.

    A PowerPoint COM host can occasionally disappear while PowerShell is being
    started or torn down.  Windows reports that situation as ``WinError 6``.
    The first process is no longer usable, but a fresh process generally is, so
    retry once before reporting the preview as unavailable.
    """
    last_error = None
    for attempt in range(2):
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=75,
                errors="replace", check=False, creationflags=creation_flags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            if attempt == 0:
                continue
            raise SlidePreviewError(f"PowerPoint preview failed: {exc}") from exc
        if completed.returncode == 0 and target.is_file() and target.stat().st_size > 0:
            return
        detail = (completed.stderr or completed.stdout or "unknown PowerPoint error").strip()
        last_error = detail[-800:]
        if attempt == 0:
            continue
    raise SlidePreviewError(f"PowerPoint preview failed: {last_error}")


def render_slide_preview(
    template_path: Path,
    slide_index: int,
    cache_root: Path,
    *,
    width: int = 1280,
    height: int = 720,
) -> Path:
    """Render one slide through PowerPoint, reusing the disk cache when possible.

    The editor displays the image inside a 16:9 canvas, so 1280×720 is enough
    for object selection while avoiding the larger 1600×900 export cost.  The
    dimensions are part of the cache fingerprint so callers can request a
    different size without receiving an older image.
    """
    template_path = Path(template_path).resolve()
    if not template_path.is_file():
        raise SlidePreviewError(f"template file missing: {template_path}")
    if slide_index < 1:
        raise SlidePreviewError(f"slide index out of range: {slide_index}")
    stat = template_path.stat()
    fingerprint = f"{stat.st_size}-{stat.st_mtime_ns}-{int(width)}x{int(height)}"
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
        "-Width", str(int(width)), "-Height", str(int(height)),
    ]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    with _LOCK:
        if target.is_file() and target.stat().st_size > 0:
            return target
        global _WORKER
        if _WORKER_SCRIPT.is_file():
            # A queued renderer can retain a dead COM connection after Office
            # updates, an interactive PowerPoint exit, or a broken pipe.  Tear
            # it down and give a newly-created worker one clean retry.  If that
            # still fails, use the isolated exporter instead of failing the
            # editor's original-page preview immediately.
            for worker_attempt in range(2):
                try:
                    if _WORKER is None or _WORKER.shell != shell:
                        _shutdown_worker()
                        _WORKER = _PersistentPowerPointRenderer(shell, _WORKER_SCRIPT)
                    _WORKER.render(template_path, slide_index, target, int(width), int(height))
                    return target
                except (_WorkerUnavailable, SlidePreviewError):
                    _shutdown_worker()
                    if worker_attempt == 0:
                        continue
        _run_one_shot_export(command, creation_flags, target)
    return target
