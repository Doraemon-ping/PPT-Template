# -*- coding: utf-8 -*-
"""服务端日志与错误返回的测试。

覆盖三件事：
1. 每个响应带 X-Request-Id，便于与服务端日志对应；
2. 未处理异常返回 JSON（含 detail 与 request_id），而不是纯文本 500；
3. 异常与访问记录确实写入 data/logs/server.log。
"""
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient
    from app.services import hpdc as main_module
    from app.services.hpdc import app
except ModuleNotFoundError:  # 精简测试环境可能缺少 web 依赖
    TestClient = None
    main_module = None
    app = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(TestClient is not None, "FastAPI/httpx test dependencies are not installed")
class LoggingAndErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_response_carries_request_id(self):
        response = self.client.get('/api/demo')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get('X-Request-Id'))

    def test_logs_tail_endpoint(self):
        response = self.client.get('/api/logs/tail?lines=20')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('file', payload)
        self.assertIsInstance(payload['lines'], list)
        self.assertTrue(str(payload['file']).endswith('server.log'))

    def test_unhandled_exception_returns_json_detail_and_logs(self):
        log_path = Path(main_module.LOG_FILE)
        with mock.patch.object(main_module, 'compute_all', side_effect=RuntimeError('模拟计算故障')):
            response = self.client.post('/api/calc', json={'f': {}, 't': {}})
        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertIn('模拟计算故障', payload['detail'])
        self.assertTrue(payload.get('request_id'))
        self.assertEqual(payload.get('request_id'), response.headers.get('X-Request-Id'))

        self.assertTrue(log_path.is_file(), f'日志文件未生成: {log_path}')
        content = log_path.read_text(encoding='utf-8', errors='replace')
        self.assertIn('模拟计算故障', content)
        self.assertIn('未处理异常', content)

    def test_http_error_detail_is_preserved(self):
        response = self.client.post('/api/template/scan', json={'template': '不存在的模板'})
        self.assertEqual(response.status_code, 404)
        self.assertIn('detail', response.json())


if __name__ == '__main__':
    unittest.main()
