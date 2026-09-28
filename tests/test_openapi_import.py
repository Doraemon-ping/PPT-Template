import asyncio
import tempfile
import unittest
from pathlib import Path

from app.db.connector_database import ConnectorDatabase
from app.db.connector_database import get_connector_database
from app.services.openapi_importer import load_openapi_document, preview_openapi_import
from app.services.workbench import app
from fastapi.testclient import TestClient


OPENAPI_YAML = """
openapi: 3.0.3
info:
  title: 质量报告 API
  version: '1.2'
servers:
  - url: https://quality.example/api/{version}
    variables:
      version:
        default: v1
security:
  - ApiKey: []
components:
  securitySchemes:
    ApiKey:
      type: apiKey
      in: header
      name: X-API-Key
  schemas:
    Report:
      type: object
      properties:
        projectName:
          type: string
        issues:
          type: array
          items:
            type: object
            properties:
              problem_name:
                type: string
              image:
                type: string
                format: uri
paths:
  /reports/{project_id}:
    get:
      summary: 项目问题
      parameters:
        - name: project_id
          in: path
          required: true
          schema: {type: string}
        - name: page_size
          in: query
          schema: {type: integer, default: 50}
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Report'
    delete:
      summary: 删除报告
      responses:
        '204': {description: deleted}
"""


class OpenApiImporterTests(unittest.TestCase):
    def test_preview_reads_yaml_ref_parameters_auth_and_fields(self):
        document, document_hash = asyncio.run(load_openapi_document(spec_text=OPENAPI_YAML, spec_url=None))
        preview = preview_openapi_import(document, document_hash)

        self.assertEqual("质量报告 API", preview["title"])
        self.assertEqual("https://quality.example/api/v1", preview["base_url"])
        self.assertIn("api_key", [item["auth_type"] for item in preview["auth_options"]])
        self.assertEqual(1, len(preview["operations"]))
        operation = preview["operations"][0]
        self.assertEqual("GET /reports/{project_id}", operation["id"])
        by_name = {item["name"]: item for item in operation["parameters"]}
        self.assertEqual("input", by_name["project_id"]["source_type"])
        self.assertEqual("fixed", by_name["page_size"]["source_type"])
        self.assertEqual(50, by_name["page_size"]["default_value"])
        targets = {item["target_field"] for item in operation["mappings"]}
        self.assertIn("project_name", targets)
        self.assertIn("issues", targets)
        self.assertTrue(preview["ignored_operations"])

    def test_atomic_import_rolls_back_when_a_later_endpoint_conflicts(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db = ConnectorDatabase(Path(temp_dir.name) / "openapi.sqlite3")
        operations = [
            {"name": "重复接口", "path": "/a", "method": "GET", "parameters": [], "mappings": []},
            {"name": "重复接口", "path": "/b", "method": "GET", "parameters": [], "mappings": []},
        ]
        with self.assertRaises(Exception):
            db.import_openapi({
                "name": "导入来源", "system_name": "OPENAPI-TEST", "base_url": "https://example.test",
                "auth_type": "none", "auth_config": {}, "timeout": 30,
            }, operations)
        self.assertEqual([], db.list_connections())


class OpenApiImportApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = ConnectorDatabase(Path(self.temp_dir.name) / "openapi-api.sqlite3")
        app.dependency_overrides[get_connector_database] = lambda: self.db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_preview_is_read_only_and_commit_creates_workspace_source(self):
        preview_response = self.client.post(
            "/api/connectors/imports/openapi/preview", json={"spec_text": OPENAPI_YAML},
        )
        self.assertEqual(200, preview_response.status_code, preview_response.text)
        preview = preview_response.json()
        self.assertEqual([], self.db.list_connections())
        workspace = self.db.create_workspace({"name": "导入测试"})

        committed = self.client.post("/api/connectors/imports/openapi/commit", json={
            "spec_text": OPENAPI_YAML,
            "document_hash": preview["document_hash"],
            "name": "质量报告",
            "auth_type": "api_key",
            "auth_config": {"key": "test-only"},
            "selected_operations": ["GET /reports/{project_id}"],
            "workspace_id": workspace["id"],
        })
        self.assertEqual(201, committed.status_code, committed.text)
        result = committed.json()
        self.assertEqual(1, len(result["endpoints"]))
        endpoint = self.db.get_endpoint(result["endpoints"][0]["id"])
        self.assertEqual("GET", endpoint.method)
        self.assertEqual(2, len(self.db.list_parameters(endpoint.id)))
        self.assertGreaterEqual(len(self.db.list_mappings(endpoint.id)), 2)
        detail = self.db.get_workspace(workspace["id"])
        self.assertEqual(result["connection"]["id"], detail["sources"][0]["id"])
