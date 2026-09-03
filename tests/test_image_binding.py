# -*- coding: utf-8 -*-
import base64
import io
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from app.report.ppt.openxml import ImageBindingFiller, OoxmlPackage
from app.report.ppt.openxml.image_binding import decode_image_bytes

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


if __name__ == "__main__":
    unittest.main()
