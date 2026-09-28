# -*- coding: utf-8 -*-
import io
import unittest
from pathlib import Path
from urllib.parse import quote

from pptx import Presentation

from app.demo import demo_state

try:
    from fastapi.testclient import TestClient
    from app.main import app
except ModuleNotFoundError:  # Local bundled test runtime may omit web dependencies.
    TestClient = None
    app = None

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "templates" / "DFM_Template_Placeholder_Demo.pptx"
TABLE = ROOT / "templates" / "DFM_Template_Table_Demo.pptx"


@unittest.skipUnless(TestClient is not None, "FastAPI/httpx test dependencies are not installed")
class TemplateImportBindAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.payload = demo_state()

    def test_upload_scan_inspect_bind_generate_delete_flow(self):
        payload_id = "apitest-demo"
        # 1) 上传
        with open(DEMO, "rb") as fp:
            response = self.client.post(
                f"/api/templates/upload?template_id={payload_id}&version=9",
                files={"file": ("demo.pptx", fp,
                                "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
            )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(payload_id, response.json()["template"]["template_id"])
        self.assertEqual(3, response.json()["slide_count"])

        # 2) 列表包含新模板
        listed = {t["template_id"] for t in self.client.get("/api/templates").json()["templates"]}
        self.assertIn(payload_id, listed)

        # 3) 扫描
        scan = self.client.post("/api/template/scan", json={"template": payload_id})
        self.assertEqual(200, scan.status_code)
        self.assertEqual(16, scan.json()["placeholder_count"])

        # 4) 形状清单
        inspect = self.client.post("/api/template/inspect", json={"template": payload_id})
        self.assertEqual(200, inspect.status_code)
        shapes = inspect.json()["slides"][0]["shapes"]
        self.assertTrue(any(s["shape_name"] == "COVER_PART_NUMBER" for s in shapes))

        # 5) 显式绑定生成
        gen = self.client.post("/api/template/generate", json={
            "template": payload_id,
            "output_mode": "deck",
            "slides": [{
                "source": 1,
                "bindings": {"COVER_PART_NUMBER": {"type": "text", "source": "f.partNo"}},
            }],
            "data": self.payload,
        })
        self.assertEqual(200, gen.status_code, gen.text)
        self.assertEqual("1", gen.headers["x-dfm-bindings-applied"])
        prs = Presentation(io.BytesIO(gen.content))
        self.assertEqual("TP-HPDC-2026-0087", prs.slides[0].shapes[0].text.strip())

        # 6) 删除
        deleted = self.client.delete(f"/api/templates/{payload_id}")
        self.assertEqual(200, deleted.status_code)

    def test_upload_rejects_non_pptx(self):
        response = self.client.post(
            "/api/templates/upload?template_id=badfile",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        self.assertEqual(415, response.status_code)

    def test_upload_rejects_invalid_zip(self):
        response = self.client.post(
            "/api/templates/upload?template_id=broken",
            files={"file": ("broken.pptx", b"not a zip at all", "application/octet-stream")},
        )
        self.assertEqual(422, response.status_code)

    def test_upload_chinese_filename_derives_safe_template_id(self):
        """回归：中文文件名模板曾一律 409 invalid template id。

        前端把「去掉结尾 .pptx 的文件名」作为 template_id 传入；中文会被规范化成
        前导 '-'，而注册表要求 id 以字母或数字开头，于是所有中文名模板都无法上传。
        """
        name = "高压项目DFM交流模板A12版_中文_2025-09-30.pptx  -  已修复.pptx"
        # 前端只去掉结尾的 .pptx，内层 .pptx 留在 id 里（真实报错中的形式）
        sent_id = name[: -len(".pptx")]
        with open(DEMO, "rb") as fp:
            response = self.client.post(
                "/api/templates/upload?template_id=" + quote(sent_id),
                files={"file": (name, fp, "application/octet-stream")},
            )
        self.assertEqual(200, response.status_code, response.text)
        template_id = response.json()["template"]["template_id"]
        self.assertRegex(template_id, r"^dfm-a12-2025-09-30-pptx(-\d+)?$")
        self.assertEqual(200, self.client.delete(f"/api/templates/{template_id}").status_code)

    def test_upload_derives_safe_id_from_chinese_filename(self):
        """未指定 template_id 时也从中文文件名派生合法 id，无 ASCII 时哈希兜底。"""
        for filename, pattern in [
            ("高压项目DFM交流模板A12版.pptx", r"^dfm-a12(-\d+)?$"),
            ("高压项目.pptx", r"^template-[0-9a-f]{10}(-\d+)?$"),
        ]:
            with self.subTest(filename=filename):
                with open(DEMO, "rb") as fp:
                    response = self.client.post(
                        "/api/templates/upload",
                        files={"file": (filename, fp, "application/octet-stream")},
                    )
                self.assertEqual(200, response.status_code, response.text)
                template_id = response.json()["template"]["template_id"]
                self.assertRegex(template_id, pattern)
                self.client.delete(f"/api/templates/{template_id}")

    def test_workbench_page_served(self):
        response = self.client.get("/template-editor")
        self.assertEqual(200, response.status_code)
        self.assertIn("DFM 模板可视化绑定", response.text)
        self.assertIn("btnGenerate", response.text)

    def test_table_demo_scan_recognises_cell_placeholders(self):
        scan = self.client.post("/api/template/scan", json={"template": "table-demo"})
        self.assertEqual(200, scan.status_code)
        self.assertIn("f.partNo", scan.json()["placeholder_paths"])


if __name__ == "__main__":
    unittest.main()
