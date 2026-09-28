import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.a13 import project_state
from app.calc import compute_all


class A13HtmlToolTests(unittest.TestCase):
    def test_root_uses_a13_and_loads_fastapi_bridge(self):
        response = TestClient(app).get('/')
        self.assertEqual(200, response.status_code)
        self.assertIn('· A13版</title>', response.text)
        self.assertIn('/static/a13_platform.js', response.text)
        self.assertIn('id="btnServerSave"', response.text)

    def test_a13_route_and_version_identity(self):
        response = TestClient(app).get('/a13')
        self.assertEqual(200, response.status_code)
        self.assertIn('· A13版</title>', response.text)
        self.assertIn("var LS_KEY = 'hpdc_dfm_project_a13'", response.text)
        self.assertIn("高压压铸 DFM 报告（A13版）", response.text)

    def test_a13_keeps_non_destructive_a12_migration(self):
        response = TestClient(app).get('/a13')
        self.assertIn("var LEGACY_LS_KEY = 'hpdc_dfm_project_a12'", response.text)
        self.assertIn('localStorage.getItem(LEGACY_LS_KEY)', response.text)
        self.assertNotIn('localStorage.removeItem(LEGACY_LS_KEY)', response.text)

    def test_rich_state_is_projected_for_ppt_workbench(self):
        state = project_state({
            'f': {'partNo': 'A13-1'}, 't': {'issues': []}, 'i': {},
            'mach': {'list': [{'brand': 'Custom', 'model': '9000', 'ton': 9000, 'lock': 90000}]},
            'v': {'f08Def': {'defects': [{'img': 1, 'type': '缩孔', 'severity': '高', 'verdict': 'ok'}]}},
            'quote': {'meta': {'customer': 'Customer'}, 'sheet': [
                {'key': 'mold', 'cat': '硬模', 'desc': '模具', 'unit': 100, 'qty': 2}
            ]},
        })
        self.assertEqual('Customer', state['f']['quoteCustomer'])
        self.assertEqual(226.0, state['f']['quoteGrossTotal'])
        self.assertEqual(200.0, state['t']['quoteSheet'][0]['total'])
        self.assertEqual('缩孔', state['t']['visionDefects'][0]['type'])
        self.assertEqual('Custom', state['t']['machineLibrary'][0]['brand'])

    def test_custom_a13_machine_library_drives_calculation(self):
        machine = {'brand':'Custom','model':'C1','ton':9999,'lock':99990,'open':1000,
                   'moldMin':500,'moldMax':1800,'tie':'1600×1600','tieDia':220,
                   'injForce':1000,'injStroke':1200,'punch':[100],'v0':7,
                   'ejForce':800,'ejStroke':300,'plate':'1900×1900'}
        result = compute_all({'machineId':'Custom C1'}, machines=[machine])
        self.assertIn('Custom C1', result['results']['rMachine']['html'])
        self.assertIn('9999', result['results']['rMachList']['html'])


if __name__ == '__main__':
    unittest.main()
