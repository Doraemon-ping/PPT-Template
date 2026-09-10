# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.report.ppt import slide_preview


class SlidePreviewTests(unittest.TestCase):
    def test_stale_worker_is_recreated_before_falling_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = root / "sample.pptx"
            template.write_bytes(b"pptx")
            worker_script = root / "preview_worker.ps1"
            worker_script.write_text("# test", encoding="utf-8")
            exporter = root / "export_slide_preview.ps1"
            exporter.write_text("# test", encoding="utf-8")
            calls = []

            class Worker:
                def __init__(self, *_args):
                    self.shell = "pwsh.exe"
                    calls.append("created")

                def render(self, *_args):
                    calls.append("render")
                    if calls.count("render") == 1:
                        raise slide_preview.SlidePreviewError("[WinError 6] handle is invalid")
                    output = _args[2]
                    output.write_bytes(b"png")

                def close(self):
                    calls.append("closed")

            old_worker = slide_preview._WORKER
            slide_preview._WORKER = None
            try:
                with patch.object(slide_preview, "_WORKER_SCRIPT", worker_script), \
                     patch("app.report.ppt.slide_preview.shutil.which", return_value="pwsh.exe"), \
                     patch("app.report.ppt.slide_preview._PersistentPowerPointRenderer", Worker), \
                     patch.object(slide_preview.Path, "resolve", autospec=True, side_effect=lambda value: value):
                    output = slide_preview.render_slide_preview(template, 1, root / "cache")
            finally:
                slide_preview._shutdown_worker()
                slide_preview._WORKER = old_worker
            self.assertTrue(output.is_file())
            self.assertEqual(["created", "render", "closed", "created", "render", "closed"], calls)
