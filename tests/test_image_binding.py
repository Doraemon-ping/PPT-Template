# -*- coding: utf-8 -*-
import base64
import io
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from app.report.ppt.openxml import ImageBindingFiller, OoxmlPackage
from app.report.ppt.openxml.image_binding import decode_image_bytes, is_image_reference, is_image_url

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "templates" / "DFM_Template_Placeholder_Demo.pptx"


def _make_png(color=(255, 0, 0), size=(64, 48)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def _part_bytes(source, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(source if isinstance(source, bytes) else source.read_bytes())) as archive:
        return archive.read(name)


class ImageBindingFillerTests(unittest.TestCase):
    def test_replaces_picture_media_in_place(self):
        package = OoxmlPackage(DEMO)
        before = package.read("ppt/media/image1.png")
        result = ImageBindingFiller().fill(package, 2, "PART_IMAGE", _make_png())
        self.assertTrue(result.replaced_in_place)
        self.assertEqual("ppt/media/image1.png", result.media_part)
        self.assertEqual((64, 48), (result.image_width_px, result.image_height_px))
        self.assertNotEqual(before, package.read("ppt/media/image1.png"))

    def test_unbound_parts_remain_byte_identical(self):
        theme_before = _part_bytes(DEMO, "ppt/theme/theme1.xml")
        package = OoxmlPackage(DEMO)
        ImageBindingFiller().fill(package, 2, "PART_IMAGE", _make_png())
        self.assertEqual(theme_before, package.read("ppt/theme/theme1.xml"))

    def test_missing_picture_shape_raises(self):
        package = OoxmlPackage(DEMO)
        with self.assertRaises(Exception):
            ImageBindingFiller().fill(package, 2, "NO_SUCH_PICTURE", _make_png())

    def test_invalid_image_bytes_raise(self):
        package = OoxmlPackage(DEMO)
        with self.assertRaises(Exception):
            ImageBindingFiller().fill(package, 2, "PART_IMAGE", b"not-an-image")

    def test_decode_data_uri(self):
        raw = _make_png()
        uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        self.assertEqual(raw, decode_image_bytes(uri))

    def test_plain_text_is_rejected_with_clear_message(self):
        """把文本字段（如公司名称）绑到图片对象时给出明确提示，而不是文件不存在。"""
        with self.assertRaises(Exception) as ctx:
            decode_image_bytes("TUOPU · 压铸工艺部")
        message = str(ctx.exception)
        self.assertIn("不是图片", message)
        self.assertIn("data:", message)

    def test_broken_data_uri_is_rejected(self):
        with self.assertRaises(Exception) as ctx:
            decode_image_bytes("data:image/png;base64,!!not-base64!!")
        self.assertIn("解码失败", str(ctx.exception))

    def test_http_image_url_is_downloaded_and_cached(self):
        """接口接入的图片字段是 http 地址，服务端渲染时必须自己去下载。"""
        raw = _make_png()
        hits = []

        class ImageApi(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/assets/photo.png":
                    hits.append(self.path)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                else:
                    self.send_error(404)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), ImageApi)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/assets/photo.png"

        self.assertEqual(raw, decode_image_bytes(url))
        # 同一地址再取一次走缓存，不重复下载
        self.assertEqual(raw, decode_image_bytes(url))
        self.assertEqual(1, len(hits))

        # 图片能真正填进图片对象
        package = OoxmlPackage(DEMO)
        result = ImageBindingFiller().fill(package, 2, "PART_IMAGE", url)
        self.assertEqual((64, 48), (result.image_width_px, result.image_height_px))

        with self.assertRaises(Exception) as ctx:
            decode_image_bytes(f"http://127.0.0.1:{server.server_port}/assets/missing.png")
        self.assertIn("下载失败", str(ctx.exception))

    def test_image_reference_detection_covers_http_and_data(self):
        raw = _make_png()
        data_uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        self.assertTrue(is_image_reference(data_uri))
        self.assertTrue(is_image_reference("https://example.com/a/b/photo.png"))
        self.assertTrue(is_image_reference("http://127.0.0.1:8002/api/machining-dfm/assets/abc.JPG?raw=1"))
        self.assertTrue(is_image_reference(raw))
        self.assertFalse(is_image_reference("TUOPU · 压铸工艺部"))
        self.assertFalse(is_image_reference("https://example.com/report.json"))
        self.assertFalse(is_image_reference(None))
        self.assertTrue(is_image_url("http://127.0.0.1:8002/api/machining-dfm/assets/abc.webp"))
        self.assertFalse(is_image_url("/api/machining-dfm/assets/abc.png"))


if __name__ == "__main__":
    unittest.main()
