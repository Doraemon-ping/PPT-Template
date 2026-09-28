import asyncio
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from app.core.exceptions import ApiRequestError, ApiResponseError
from app.db.connector_database import ConnectorDatabase
from app.models import FieldMapping
from app.services.api_executor import ApiExecutor
from app.services.mapping_service import MappingService
from app.services.response_parser import ResponseParser
from app.services.connector_ux import count_records, discover_fields
from app.services.connector_binding import build_workspace_binding_context
from app.services.dataset_service import DatasetService


class ConnectorTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = ConnectorDatabase(Path(self.temp_dir.name) / "connectors.sqlite3")
        self.connection = self.db.create_connection({
            "name": "DFM系统A",
            "system_name": "DFM-A",
            "base_url": "https://external.example/api",
            "auth_type": "none",
            "auth_config": {},
            "timeout": 10,
            "status": "active",
        })
        self.endpoint = self.db.create_endpoint({
            "connection_id": self.connection.id,
            "name": "问题列表",
            "path": "/reports/{id}/issues",
            "method": "GET",
            "headers": {"X-Client": "ppt-workbench"},
            "query_params": {},
            "body_template": None,
            "description": "",
            "status": "active",
        })
        self.db.create_parameter({
            "endpoint_id": self.endpoint.id,
            "name": "id",
            "location": "path",
            "source_type": "input",
            "source_key": "report_id",
            "default_value": None,
        })
        self.db.create_parameter({
            "endpoint_id": self.endpoint.id,
            "name": "severity",
            "location": "query",
            "source_type": "input",
            "source_key": "filters.severity",
            "default_value": "all",
        })

    def test_parameter_configuration_builds_path_and_query(self):
        request = ApiExecutor(self.db).build_request(
            self.endpoint.id,
            {"report_id": "R 001/2", "filters": {"severity": "high"}},
        )
        self.assertEqual("https://external.example/api/reports/R%20001%2F2/issues", request.url)
        self.assertEqual("high", request.query["severity"])
        self.assertEqual("ppt-workbench", request.headers["X-Client"])

    def test_executor_returns_200_response(self):
        def handler(request: httpx.Request):
            self.assertEqual("/api/reports/001/issues", request.url.path)
            self.assertEqual("high", request.url.params["severity"])
            return httpx.Response(200, json={"data": {"issues": []}})

        executor = ApiExecutor(self.db, transport=httpx.MockTransport(handler))
        response = asyncio.run(executor.execute(
            self.endpoint.id,
            {"report_id": "001", "filters": {"severity": "high"}},
        ))
        self.assertEqual(200, response.status_code)

    def test_executor_maps_400_and_500_to_request_error(self):
        for upstream_status in (400, 500):
            with self.subTest(upstream_status=upstream_status):
                transport = httpx.MockTransport(
                    lambda _request, code=upstream_status: httpx.Response(code, json={"error": "failed"})
                )
                with self.assertRaises(ApiRequestError) as raised:
                    asyncio.run(ApiExecutor(self.db, transport=transport).execute(
                        self.endpoint.id, {"report_id": "001"},
                    ))
                self.assertEqual(upstream_status, raised.exception.details["upstream_status"])

    def test_jsonpath_extracts_array_values(self):
        payload = {"data": {"issues": [{"name": "test"}, {"name": "second"}]}}
        self.assertEqual(
            ["test", "second"],
            ResponseParser.extract(payload, "$.data.issues[*].name"),
        )

    def test_jsonpath_can_pick_one_item_out_of_an_array(self):
        """接口返回一组数据时，要能只取其中一条：下标、过滤器、切片都要支持。"""
        payload = {"machines": [{"name": "设备1", "qty": 3}, {"name": "设备2", "qty": 5}]}
        # 下标：取第 1 条 → MappingService 会得到单个值（不是列表）
        self.assertEqual(["设备1"], ResponseParser.extract(payload, "$.machines[0].name"))
        self.assertEqual([5], ResponseParser.extract(payload, "$.machines[1].qty"))
        single = MappingService().map(payload, [
            FieldMapping(id=1, endpoint_id=1, source_path="$.machines[0].name",
                         target_field="fields.first_machine", transform_type="none", transform_config={}),
        ])
        self.assertEqual("设备1", single["fields"]["first_machine"])
        # 过滤器与切片走 jsonpath_ng.ext（基础解析器会直接词法报错）
        self.assertEqual(["设备2"], ResponseParser.extract(payload, '$.machines[?(@.qty>4)].name'))
        self.assertEqual(["设备2"], ResponseParser.extract(payload, "$.machines[1:].name"))
        wildcard = MappingService().map(payload, [
            FieldMapping(id=2, endpoint_id=1, source_path="$.machines[*].name",
                         target_field="tables.machines", transform_type="none", transform_config={}),
        ])
        self.assertEqual(["设备1", "设备2"], wildcard["tables"]["machines"])
        with self.assertRaises(ApiResponseError):
            ResponseParser.extract(payload, "$.machines[?(@.name=)]")

    def test_mapping_supports_none_and_enum_transform(self):
        title = self.db.create_mapping({
            "endpoint_id": self.endpoint.id,
            "source_path": "$.problemName",
            "target_field": "title",
            "transform_type": "none",
            "transform_config": {},
        })
        severity = self.db.create_mapping({
            "endpoint_id": self.endpoint.id,
            "source_path": "$.severity",
            "target_field": "metadata.severity",
            "transform_type": "enum",
            "transform_config": {"mapping": {"H": "高", "L": "低"}, "default": "未知"},
        })
        result = MappingService().map(
            {"problemName": "拔模角不足", "severity": "H"},
            [title, severity],
        )
        self.assertEqual({"title": "拔模角不足", "metadata": {"severity": "高"}}, result)

    def test_mapping_resolves_relative_image_urls_when_configured(self):
        image = self.db.create_mapping({
            "endpoint_id": self.endpoint.id,
            "source_path": "$.image",
            "target_field": "image",
            "transform_type": "none",
            "transform_config": {"url_base": "https://source.example/api"},
        })
        result = MappingService().map({"image": "/assets/a.png"}, [image])
        self.assertEqual("https://source.example/assets/a.png", result["image"])

    def test_table_url_resolution_keeps_text_and_foreign_keys(self):
        rows = self.db.create_mapping({
            "endpoint_id": self.endpoint.id,
            "source_path": "$.rows[*]",
            "target_field": "tables.rows",
            "transform_type": "none",
            "transform_config": {"url_base": "http://127.0.0.1:8002"},
        })
        result = MappingService().map({
            "rows": [{
                "id": "row-1",
                "process_id": "process-1",
                "name": "OP10",
                "photo_url": "/api/assets/image-1",
            }]
        }, [rows])
        row = result["tables"]["rows"][0]
        self.assertEqual("row-1", row["id"])
        self.assertEqual("process-1", row["process_id"])
        self.assertEqual("OP10", row["name"])
        self.assertEqual("http://127.0.0.1:8002/api/assets/image-1", row["photo_url"])

    def test_binding_context_exposes_fields_tables_and_images(self):
        mappings = [
            self.db.create_mapping({
                "endpoint_id": self.endpoint.id,
                "source_path": "$.name",
                "target_field": "project.name",
                "transform_type": "none",
                "transform_config": {"display_name": "项目名称", "module": "项目信息"},
            }),
            self.db.create_mapping({
                "endpoint_id": self.endpoint.id,
                "source_path": "$.issues[*]",
                "target_field": "tables.issues",
                "transform_type": "none",
                "transform_config": {
                    "display_name": "问题清单",
                    "column_labels": {"title": "问题标题"},
                },
            }),
            self.db.create_mapping({
                "endpoint_id": self.endpoint.id,
                "source_path": "$.image",
                "target_field": "images.product",
                "transform_type": "none",
                "transform_config": {"display_name": "产品图片"},
            }),
        ]
        data, catalog = build_workspace_binding_context({
            "project": {"name": "蓄电池支架"},
            "tables": {"issues": [{"title": "孔径偏差"}]},
            "images": {"product": "https://example.test/product.png"},
        }, mappings)
        self.assertEqual("蓄电池支架", data["f"]["project"]["name"])
        self.assertEqual("孔径偏差", data["t"]["issues"][0]["title"])
        self.assertEqual(["https://example.test/product.png"], data["i"]["product"])
        self.assertEqual("问题标题", catalog["tables"]["issues"]["columns"]["title"])

    def test_binding_context_accepts_wizard_targets_without_table_prefix(self):
        """普通模式向导写的是 processes / issues / product_image，也要能当整表/图片绑定。

        否则工作空间里"工序/问题"只会变成一个装数组的普通字段，整表填入根本选不到。
        """
        mappings = [
            self.db.create_mapping({
                "endpoint_id": self.endpoint.id,
                "source_path": "$.state.pr[*]",
                "target_field": "processes",
                "transform_type": "none",
                "transform_config": {"display_name": "工序清单", "module": "工艺数据", "group": "工序",
                                     "column_labels": {"nm": "工序名称"}},
            }),
            self.db.create_mapping({
                "endpoint_id": self.endpoint.id,
                "source_path": "$.state.is[*]",
                "target_field": "issues",
                "transform_type": "none",
                "transform_config": {"display_name": "问题清单", "module": "质量数据", "group": "问题"},
            }),
            self.db.create_mapping({
                "endpoint_id": self.endpoint.id,
                "source_path": "$.state.G.pI",
                "target_field": "product_image",
                "transform_type": "none",
                "transform_config": {"display_name": "产品图片", "module": "项目图片",
                                     "url_base": "http://127.0.0.1:8002"},
            }),
            self.db.create_mapping({
                "endpoint_id": self.endpoint.id,
                "source_path": "$.state.G.cust",
                "target_field": "customer",
                "transform_type": "none",
                "transform_config": {"display_name": "客户"},
            }),
        ]
        data, catalog = build_workspace_binding_context({
            "processes": [{"nm": "机加工序-OP10", "machine_model": "S700Z2N"}],
            "issues": [{"ds": "孔径偏差"}],
            "product_image": "http://127.0.0.1:8002/api/machining-dfm/assets/f95d0a5f",
            "customer": "赛力斯 SERES",
        }, mappings)
        self.assertEqual("机加工序-OP10", data["t"]["processes"][0]["nm"])
        self.assertEqual("孔径偏差", data["t"]["issues"][0]["ds"])
        self.assertEqual(["http://127.0.0.1:8002/api/machining-dfm/assets/f95d0a5f"], data["i"]["product_image"])
        self.assertEqual("赛力斯 SERES", data["f"]["customer"])
        self.assertEqual("工序名称", catalog["tables"]["processes"]["columns"]["nm"])
        # 被当成整表/图片的 Dataset 键不再同时变成同名字段
        self.assertNotIn("processes", data["f"])
        self.assertNotIn("product_image", data["f"])
        self.assertNotIn("f.processes", [item["path"] for item in catalog["fields"]])

    def test_discovery_uses_conservative_defaults_and_keeps_object_collections(self):
        fields = discover_fields({
            "id": "P-1",
            "name": "机加项目",
            "issue_table": True,
            "state": {
                "pr": [{"id": "OP10", "name": "粗加工", "tools": [{"name": "T1"}]}],
                "is": [{"problem_name": "孔径偏差", "status": "进行中"}],
                "G": {"pI": "/assets/product-image"},
            },
        })
        by_path = {field["source_path"]: field for field in fields}
        self.assertEqual("project_name", by_path["$.name"]["recommended_target"])
        self.assertTrue(by_path["$.name"]["selected"])
        self.assertIsNone(by_path["$.issue_table"]["recommended_target"])
        self.assertFalse(by_path["$.state.pr[*].id"]["selected"])
        self.assertEqual("processes", by_path["$.state.pr[*]"]["recommended_target"])
        self.assertTrue(by_path["$.state.pr[*]"]["selected"])
        self.assertEqual("issues", by_path["$.state.is[*]"]["recommended_target"])
        self.assertTrue(by_path["$.state.is[*]"]["selected"])
        self.assertEqual("image", by_path["$.state.G.pI"]["value_type"])
        self.assertEqual("product_image", by_path["$.state.G.pI"]["recommended_target"])
        self.assertLess(sum(1 for field in fields if field["selected"]), len(fields))
        self.assertEqual(1, count_records({"nested": {"rows": [{"id": 1}]}}))
        self.assertEqual(3, count_records({"nested": {"rows": [1, 2, 3]}}))

    def test_migration_is_idempotent_and_foreign_keys_cascade(self):
        ConnectorDatabase(self.db.path)
        with closing(self.db.connect()) as connection:
            migrations = connection.execute("SELECT COUNT(*) FROM connector_schema_migrations").fetchone()[0]
        self.assertEqual(6, migrations)
        self.db.delete_connection(self.connection.id)
        with closing(self.db.connect()) as connection:
            count = connection.execute("SELECT COUNT(*) FROM api_endpoints").fetchone()[0]
        self.assertEqual(0, count)


try:
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock, patch

    from app.db.connector_database import get_connector_database
    from app.services.workbench import app
except ModuleNotFoundError:
    TestClient = None


@unittest.skipUnless(TestClient is not None, "FastAPI/httpx test dependencies are not installed")
class ConnectorApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = ConnectorDatabase(Path(self.temp_dir.name) / "api.sqlite3")
        app.dependency_overrides[get_connector_database] = lambda: self.db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_crud_execute_and_dataset_read_flow(self):
        connection = self.client.post("/api/connectors/connections", json={
            "name": "质量系统", "system_name": "QMS-A", "base_url": "https://qms.example/api",
        })
        self.assertEqual(201, connection.status_code, connection.text)
        connection_id = connection.json()["id"]
        endpoint = self.client.post("/api/connectors/endpoints", json={
            "connection_id": connection_id, "name": "问题", "path": "/issues/{id}", "method": "GET",
        })
        self.assertEqual(201, endpoint.status_code, endpoint.text)
        endpoint_id = endpoint.json()["id"]

        parameter = self.client.post("/api/connectors/parameters", json={
            "endpoint_id": endpoint_id, "name": "id", "location": "path",
            "source_type": "input", "source_key": "issue_id",
        })
        self.assertEqual(201, parameter.status_code, parameter.text)
        mapping = self.client.post("/api/connectors/mappings", json={
            "endpoint_id": endpoint_id, "source_path": "$.problemName", "target_field": "title",
        })
        self.assertEqual(201, mapping.status_code, mapping.text)

        fake_response = httpx.Response(
            200,
            json={"problemName": "拔模角不足"},
            request=httpx.Request("GET", "https://qms.example/api/issues/1"),
        )
        with patch("app.api.connectors.ApiExecutor.execute", new=AsyncMock(return_value=fake_response)):
            executed = self.client.post("/api/connectors/test", json={
                "endpoint_id": endpoint_id, "parameters": {"issue_id": "1"},
            })
        self.assertEqual(200, executed.status_code, executed.text)
        dataset = executed.json()
        self.assertEqual("QMS-A", dataset["source"])
        self.assertEqual({"title": "拔模角不足"}, dataset["data"])

        loaded = self.client.get(f"/api/connectors/datasets/{dataset['id']}")
        self.assertEqual(200, loaded.status_code, loaded.text)
        self.assertEqual(dataset, loaded.json())

    def test_real_http_full_configuration_to_dataset_flow(self):
        class ExternalApi(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/v1/reports/001/issues?severity=high":
                    self.send_error(404)
                    return
                payload = json.dumps({"data": {"issues": [{"name": "真实接入问题"}]}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), ExternalApi)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        connection_id = self.client.post("/api/connectors/connections", json={
            "name": "外部测试系统", "system_name": "EXT-TEST",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
        }).json()["id"]
        endpoint_id = self.client.post("/api/connectors/endpoints", json={
            "connection_id": connection_id, "name": "问题列表",
            "path": "/reports/{id}/issues", "method": "GET",
        }).json()["id"]
        for parameter in (
            {"name": "id", "location": "path", "source_type": "input", "source_key": "report_id"},
            {"name": "severity", "location": "query", "source_type": "input", "source_key": "severity"},
        ):
            response = self.client.post("/api/connectors/parameters", json={"endpoint_id": endpoint_id, **parameter})
            self.assertEqual(201, response.status_code, response.text)
        response = self.client.post("/api/connectors/mappings", json={
            "endpoint_id": endpoint_id,
            "source_path": "$.data.issues[*].name",
            "target_field": "issue_titles",
        })
        self.assertEqual(201, response.status_code, response.text)

        executed = self.client.post("/api/connectors/test", json={
            "endpoint_id": endpoint_id,
            "parameters": {"report_id": "001", "severity": "high"},
        })
        self.assertEqual(200, executed.status_code, executed.text)
        self.assertEqual(["真实接入问题"], executed.json()["data"]["issue_titles"])

        sources = self.client.get("/api/connectors/sources")
        self.assertEqual(200, sources.status_code, sources.text)
        summary = sources.json()["items"][0]
        self.assertEqual("normal", summary["status"])
        self.assertEqual(1, summary["record_count"])
        self.assertIsNotNone(summary["last_success_at"])

    def test_endpoint_discovery_lists_every_optional_field_without_writing_a_dataset(self):
        """「4 字段」读取可选参数：列出接口返回的全部字段、标出已映射，且不产生 Dataset。"""

        class DiscoveryApi(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/v1/reports/001/settings":
                    self.send_error(404)
                    return
                payload = json.dumps({
                    "settings": {"cust": "赛力斯 SERES", "hpd": 22.0},
                    "issues": [
                        {"title": "尺寸超差", "level": 1},
                        {"title": "毛刺", "level": 2},
                    ],
                }, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), DiscoveryApi)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        connection_id = self.client.post("/api/connectors/connections", json={
            "name": "发现测试系统", "system_name": "DISC-TEST",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
        }).json()["id"]
        endpoint_id = self.client.post("/api/connectors/endpoints", json={
            "connection_id": connection_id, "name": "项目设置",
            "path": "/reports/{id}/settings", "method": "GET",
        }).json()["id"]
        created_parameter = self.client.post("/api/connectors/parameters", json={
            "endpoint_id": endpoint_id, "name": "id", "location": "path",
            "source_type": "fixed", "default_value": "001",
        })
        self.assertEqual(201, created_parameter.status_code, created_parameter.text)
        created_mapping = self.client.post("/api/connectors/mappings", json={
            "endpoint_id": endpoint_id,
            "source_path": "$.settings.cust",
            "target_field": "fields.customer",
        })
        self.assertEqual(201, created_mapping.status_code, created_mapping.text)

        discovered = self.client.post(f"/api/connectors/endpoints/{endpoint_id}/discover", json={})
        self.assertEqual(200, discovered.status_code, discovered.text)
        body = discovered.json()
        paths = [field["source_path"] for field in body["fields"]]
        # 未被映射的字段也必须列出来，用户才能发现漏配的参数
        self.assertIn("$.settings.hpd", paths)
        self.assertIn("$.issues[*].title", paths)
        self.assertEqual(["$.settings.cust"], body["mapped_paths"])
        self.assertEqual(2, body["record_count"])
        # 每个字段都带分组、类型和示例值，前端才能按分组展示并给出映射方法
        for field in body["fields"]:
            self.assertTrue(field["group"])
            self.assertIn(field["value_type"], {"text", "number", "boolean", "image", "collection"})
            self.assertIn("sample", field)
        self.assertTrue(any(item["key"] == "customer" for item in body["targets"]))
        collections = [field for field in body["fields"] if field["value_type"] == "collection"]
        self.assertEqual(["$.issues[*]"], [field["source_path"] for field in collections])
        # 配置页要用原始返回渲染预览（文字值 / 图片地址 / 表格行）
        self.assertEqual(2, len(body["raw"]["issues"]))
        self.assertFalse(body["raw_truncated"])

        # 只读：读取可选参数不写入 Dataset
        datasets = self.client.get("/api/connectors/datasets")
        self.assertEqual(200, datasets.status_code)
        self.assertEqual([], datasets.json()["items"])

        missing = self.client.post("/api/connectors/endpoints/99999/discover", json={})
        self.assertEqual(404, missing.status_code)

    def test_wizard_inspects_json_and_recommends_user_friendly_fields(self):
        class PreviewApi(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/preview?project_id=P-001":
                    self.send_error(404)
                    return
                payload = json.dumps({
                    "projectName": "新能源外壳",
                    "issues": [{
                        "problem_name": "拔模角不足",
                        "level": "High",
                        "image": "issue-001.png",
                    }],
                }, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), PreviewApi)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        response = self.client.post("/api/connectors/wizard/inspect", json={
            "name": "供应商DFM系统",
            "url": f"http://127.0.0.1:{server.server_port}/preview",
            "project_id": "P-001",
        })
        self.assertEqual(200, response.status_code, response.text)
        result = response.json()
        self.assertEqual(1, result["record_count"])
        by_name = {item["external_name"]: item for item in result["fields"]}
        self.assertEqual("project_name", by_name["projectName"]["recommended_target"])
        self.assertEqual("issue_title", by_name["problem_name"]["recommended_target"])
        self.assertEqual("severity", by_name["level"]["recommended_target"])
        self.assertEqual("issue_image", by_name["image"]["recommended_target"])
        self.assertEqual("$.issues[*].problem_name", by_name["problem_name"]["source_path"])
        self.assertEqual("query", result["configuration"]["parameter"]["location"])

    def test_wizard_hides_authentication_exception_behind_friendly_message(self):
        class UnauthorizedApi(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(401)
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), UnauthorizedApi)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        response = self.client.post("/api/connectors/wizard/inspect", json={
            "name": "需认证系统",
            "url": f"http://127.0.0.1:{server.server_port}/preview",
        })
        self.assertEqual(502, response.status_code, response.text)
        detail = response.json()["detail"]
        self.assertEqual("认证失败，请检查 API Key 是否正确", detail["message"])
        self.assertIn("technical_detail", detail)

    def test_workspace_groups_its_data_sources_and_ppt_templates(self):
        workspace = self.client.post("/api/connectors/workspaces", json={
            "name": "注塑 DFM 周报",
            "description": "供应商问题周报",
        })
        self.assertEqual(201, workspace.status_code, workspace.text)
        workspace_id = workspace.json()["id"]
        connection = self.client.post("/api/connectors/connections", json={
            "name": "供应商 DFM", "system_name": "DFM-WORKSPACE",
            "base_url": "https://supplier.example/api",
        })
        self.assertEqual(201, connection.status_code, connection.text)
        connection_id = connection.json()["id"]
        endpoint_id = self.client.post("/api/connectors/endpoints", json={
            "connection_id": connection_id,
            "name": "问题列表",
            "path": "/issues",
            "method": "GET",
        }).json()["id"]
        mapping = self.client.post("/api/connectors/mappings", json={
            "endpoint_id": endpoint_id,
            "source_path": "$.problemName",
            "target_field": "issue_title",
            "transform_config": {"display_name": "缺陷名称"},
        })
        self.assertEqual(201, mapping.status_code, mapping.text)

        attached_source = self.client.post(
            f"/api/connectors/workspaces/{workspace_id}/sources",
            json={"connection_id": connection_id},
        )
        self.assertEqual(200, attached_source.status_code, attached_source.text)
        self.db.record_source_status(connection_id, status="normal", record_count=1)
        DatasetService(self.db).create(source="DFM-WORKSPACE", data={"rows": [{"id": 1}, {"id": 2}]})
        attached_template = self.client.post(
            f"/api/connectors/workspaces/{workspace_id}/templates",
            json={
                "template_id": "supplier-weekly",
                "source_name": "供应商周报模板.pptx",
                "slide_count": 12,
                "size": 2048,
            },
        )
        self.assertEqual(200, attached_template.status_code, attached_template.text)

        detail = self.client.get(f"/api/connectors/workspaces/{workspace_id}")
        self.assertEqual(200, detail.status_code, detail.text)
        payload = detail.json()
        self.assertFalse(payload["ready"])
        self.assertEqual("needs_binding", payload["setup_status"])
        self.assertFalse(payload["templates"][0]["bindable"])
        self.assertEqual("供应商 DFM", payload["sources"][0]["name"])
        self.assertEqual("供应商周报模板.pptx", payload["templates"][0]["source_name"])
        context = self.client.get(
            f"/api/connectors/workspaces/{workspace_id}/templates/supplier-weekly/binding-context"
        )
        self.assertEqual(200, context.status_code, context.text)
        self.assertEqual("DFM-WORKSPACE", context.json()["dataset"]["source"])
        saved_binding = self.client.put(
            f"/api/connectors/workspaces/{workspace_id}/templates/supplier-weekly/binding",
            json={
                "revision": 0,
                "payload": {
                    "template": "supplier-weekly",
                    "baseTemplate": "supplier-weekly",
                    "deck": [{
                        "source": 1,
                        "bindings": {"title": {"type": "text", "source": "f.rows", "shape": "标题"}},
                    }],
                },
            },
        )
        self.assertEqual(200, saved_binding.status_code, saved_binding.text)
        self.assertEqual(1, saved_binding.json()["binding_count"])
        self.assertTrue(self.client.get(f"/api/connectors/workspaces/{workspace_id}").json()["ready"])
        conflict = self.client.put(
            f"/api/connectors/workspaces/{workspace_id}/templates/supplier-weekly/binding",
            json={"revision": 0, "payload": {}},
        )
        self.assertEqual(409, conflict.status_code, conflict.text)
        rebound = self.client.post(
            f"/api/connectors/workspaces/{workspace_id}/templates",
            json={
                "template_id": "supplier-weekly",
                "source_name": "供应商周报模板.pptx",
                "slide_count": 12,
                "size": 2048,
                "placeholder_count": 3,
            },
        )
        self.assertEqual(200, rebound.status_code, rebound.text)
        self.assertTrue(rebound.json()["ready"])
        self.assertEqual("ready", rebound.json()["setup_status"])
        scoped_sources = self.client.get(f"/api/connectors/sources?workspace_id={workspace_id}")
        self.assertEqual(1, len(scoped_sources.json()["items"]))
        self.assertEqual(2, scoped_sources.json()["items"][0]["record_count"])
        self.assertEqual(
            "缺陷名称",
            scoped_sources.json()["items"][0]["display_labels"]["issue_title"],
        )

    def test_workspace_binding_context_combines_multiple_systems_without_cross_mapping(self):
        workspace_id = self.client.post("/api/connectors/workspaces", json={
            "name": "多系统质量报告", "description": "MES + QMS",
        }).json()["id"]

        def add_source(name, system_name, target, value):
            connection_id = self.client.post("/api/connectors/connections", json={
                "name": name, "system_name": system_name, "base_url": "https://example.test",
            }).json()["id"]
            endpoint_id = self.client.post("/api/connectors/endpoints", json={
                "connection_id": connection_id, "name": "项目详情", "path": "/project", "method": "GET",
            }).json()["id"]
            self.client.post("/api/connectors/mappings", json={
                "endpoint_id": endpoint_id, "source_path": "$.value", "target_field": target,
                "transform_config": {"display_name": name + "字段"},
            })
            self.client.post(
                f"/api/connectors/workspaces/{workspace_id}/sources",
                json={"connection_id": connection_id},
            )
            DatasetService(self.db).create(
                source=system_name, data={target: value}, connection_id=connection_id,
                endpoint_id=endpoint_id,
            )
            self.db.record_source_status(connection_id, status="normal", record_count=1)
            return connection_id, endpoint_id

        mes_connection, _ = add_source("MES", "MES-A", "customer", "MES 客户")
        qms_connection, _ = add_source("QMS", "QMS-A", "customer", "QMS 客户")
        self.client.post(f"/api/connectors/workspaces/{workspace_id}/templates", json={
            "template_id": "multi-system", "source_name": "多系统模板.pptx", "slide_count": 1,
        })

        response = self.client.get(
            f"/api/connectors/workspaces/{workspace_id}/templates/multi-system/binding-context"
        )
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual(2, len(payload["datasets"]))
        self.assertEqual("2 个系统接口", payload["dataset"]["source"])
        self.assertEqual("MES 客户", payload["data"]["f"]["customer"])
        self.assertEqual(
            "MES 客户",
            payload["data"]["f"]["_systems"][f"source_{mes_connection}"]["customer"],
        )
        self.assertEqual(
            "QMS 客户",
            payload["data"]["f"]["_systems"][f"source_{qms_connection}"]["customer"],
        )
        paths = {item["path"] for item in payload["catalog"]["fields"]}
        self.assertIn(f"f._systems.source_{mes_connection}.customer", paths)
        self.assertIn(f"f._systems.source_{qms_connection}.customer", paths)

    def test_workspace_is_not_ready_when_one_of_multiple_sources_failed(self):
        workspace_id = self.client.post("/api/connectors/workspaces", json={"name": "状态校验"}).json()["id"]
        for index, status_value in enumerate(("normal", "failed"), 1):
            connection_id = self.client.post("/api/connectors/connections", json={
                "name": f"系统 {index}", "system_name": f"SYS-{index}",
                "base_url": "https://example.test",
            }).json()["id"]
            self.client.post(f"/api/connectors/workspaces/{workspace_id}/sources", json={
                "connection_id": connection_id,
            })
            self.db.record_source_status(connection_id, status=status_value, record_count=1)
        detail = self.client.get(f"/api/connectors/workspaces/{workspace_id}").json()
        self.assertEqual("source_error", detail["setup_status"])
        self.assertFalse(detail["ready"])

    def test_workspace_refresh_runs_every_attached_endpoint_and_keeps_provenance(self):
        workspace_id = self.client.post("/api/connectors/workspaces", json={"name": "刷新校验"}).json()["id"]
        endpoint_ids = []
        for index in (1, 2):
            connection_id = self.client.post("/api/connectors/connections", json={
                "name": f"系统 {index}", "system_name": f"REFRESH-{index}",
                "base_url": "https://example.test",
            }).json()["id"]
            endpoint_id = self.client.post("/api/connectors/endpoints", json={
                "connection_id": connection_id, "name": f"接口 {index}",
                "path": "/data", "method": "GET",
            }).json()["id"]
            endpoint_ids.append(endpoint_id)
            self.client.post("/api/connectors/mappings", json={
                "endpoint_id": endpoint_id, "source_path": "$.value",
                "target_field": f"value_{index}",
            })
            self.client.post(f"/api/connectors/workspaces/{workspace_id}/sources", json={
                "connection_id": connection_id,
            })

        with patch("app.api.connectors.ApiExecutor.execute", new=AsyncMock(
            return_value=httpx.Response(200, json={"value": "fresh"})
        )):
            response = self.client.post(f"/api/connectors/workspaces/{workspace_id}/refresh")
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(2, response.json()["refreshed"])
        self.assertEqual(0, response.json()["failed"])
        datasets = self.db.list_datasets(limit=10)
        self.assertEqual(set(endpoint_ids), {item.endpoint_id for item in datasets})
        self.assertTrue(all(item.connection_id for item in datasets))

    def test_connector_console_is_the_empty_home_page(self):
        page = self.client.get("/ppt")
        self.assertEqual(200, page.status_code)
        self.assertIn("先创建一个工作空间", page.text)
        self.assertIn('id="workspaceListView"', page.text)
        self.assertIn('id="workspaceDetailView"', page.text)
        self.assertIn('id="templateFile"', page.text)
        self.assertIn('id="customTargetName"', page.text)
        self.assertIn('id="addCustomTarget"', page.text)
        self.assertIn('id="fieldSearch"', page.text)
        self.assertIn('id="selectRecommended"', page.text)
        self.assertIn('id="journeyBinding"', page.text)
        self.assertIn('id="newSource"', page.text)
        self.assertIn('id="normalView"', page.text)
        self.assertIn('class="shell advanced-view hidden" id="advancedView"', page.text)
        self.assertIn("选择数据来源", page.text)
        self.assertIn('id="connectionForm"', page.text)
        self.assertNotIn("/api/ppt/sources", page.text)
        script = self.client.get("/static/api_connectors.js")
        self.assertEqual(200, script.status_code)
        self.assertIn("/api/connectors/test", script.text)
        self.assertIn("data-bind-template", script.text)
        editor = self.client.get("/template-editor?workspace_id=1&template=example")
        self.assertEqual(200, editor.status_code)
        self.assertIn("WORKSPACE_ID", editor.text)
        self.assertIn("binding-context", editor.text)

    def test_advanced_settings_fields_ship_help_and_examples(self):
        """高级设置页每个 JSON 配置都要有填写说明和示例入口，用户不必猜字段含义。"""
        page = self.client.get("/ppt")
        self.assertEqual(200, page.status_code)
        html = page.text
        for field in (
            "authConfig",
            "endpointHeaders",
            "endpointQuery",
            "endpointBody",
            "parameterDefault",
            "pickerEnum",
            "pickerColumns",
            "runtimeParameters",
            "runtimeContext",
        ):
            with self.subTest(field=field):
                self.assertIn('id="%s"' % field, html)
                self.assertIn('data-example="%s"' % field, html)
        self.assertIn("高级认证配置", html)
        self.assertIn("高级请求配置", html)
        self.assertIn("field-help", html)
        # 手写 JSONPath 的独立表单已移除，映射只能在字段配置面板里维护
        self.assertNotIn('id="mappingForm"', html)
        self.assertNotIn('id="transformConfig"', html)
        script = self.client.get("/static/api_connectors.js")
        self.assertEqual(200, script.status_code)
        self.assertIn("[data-example]", script.text)
        self.assertIn("syncExampleButtons", script.text)

    def test_parameters_can_be_edited_from_the_advanced_view(self):
        """参数列表必须能编辑（回填 + 更新），而不是只能删掉重建。"""
        page = self.client.get("/ppt")
        self.assertEqual(200, page.status_code)
        self.assertIn('id="saveParameter"', page.text)
        self.assertIn('id="cancelParameterEdit"', page.text)
        script = self.client.get("/static/api_connectors.js")
        self.assertEqual(200, script.status_code)
        self.assertIn("data-edit-parameter", script.text)
        self.assertIn("function editParameter(", script.text)
        self.assertIn("function resetParameterForm(", script.text)
        self.assertIn("method:editing?'PATCH':'POST'", script.text)
        self.assertIn("参数已更新", script.text)

    def test_mapping_picker_configures_one_field_at_a_time(self):
        """字段配置是「选参数 → 分组/类型/预览 → 保存 → 下一个」的引导流程。"""
        page = self.client.get("/ppt")
        self.assertEqual(200, page.status_code)
        for marker in (
            'id="pickerList"',
            'id="pickerConfig"',
            'id="pickerTypeChoice"',
            'id="pickerPreview"',
            'id="pickerSave"',
            'id="pickerSaveStay"',
            'id="pickerGroup"',
            'id="pickerSourcePath"',
            'id="pickerProgress"',
            'id="pickerExtra"',
            'id="pickerEnum"',
            'id="pickerColumns"',
            'id="pickerIndex"',
            'data-pick-type="fields"',
            'data-pick-type="images"',
            'data-pick-type="tables"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, page.text)
        script = self.client.get("/static/api_connectors.js")
        self.assertEqual(200, script.status_code)
        for marker in (
            "function savePickerField(",
            "function selectNextUnconfigured(",
            "function previewTable(",
            "function previewImage(",
            "function previewText(",
            "function resolveJsonPath(",
            "function pickerEntries(",
            "function selectMappingInPicker(",
            "data-open-mapping",
            "'/discover'",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script.text)

    def test_preview_payload_is_capped(self):
        """预览数据过大时不回传，避免把大响应塞进浏览器。"""
        from app.api.connectors import preview_payload

        self.assertEqual({"a": [1, 2]}, preview_payload({"a": [1, 2]}))
        self.assertIsNone(preview_payload(None))
        self.assertIsNone(preview_payload("x" * 500_000))

    def test_workspace_cards_use_the_avatar_card_layout(self):
        """工作空间卡与数据来源卡使用统一的头像式卡片布局。"""
        page = self.client.get("/ppt")
        self.assertEqual(200, page.status_code)
        self.assertIn(".workspace-avatar{", page.text)
        self.assertIn(".workspace-card-title{", page.text)
        self.assertIn(".asset-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr)", page.text)
        self.assertIn("repeat(auto-fit,minmax(280px,1fr))", page.text)
        script = self.client.get("/static/api_connectors.js")
        self.assertIn('class="workspace-avatar"', script.text)
        self.assertIn('class="workspace-card-title"', script.text)
        self.assertIn("填入示例", script.text)


if __name__ == "__main__":
    unittest.main()
