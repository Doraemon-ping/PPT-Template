import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from lxml import etree

from app.form_platform import discover_html, validate_schema
from app.main import app
from app.report.ppt.openxml.package_editor import OoxmlPackage
from tests.test_table_pagination import fixture

FIXTURE = Path(__file__).parent / 'fixtures' / 'inspection_form.html'


class DiscoveryTests(unittest.TestCase):
    def test_controls_labels_defaults_and_repeat_table(self):
        result = discover_html(FIXTURE.read_bytes())
        schema = validate_schema(result['schema'])
        fields = {f['key']: f for f in schema['fields']}
        self.assertEqual('设备编号', fields['partNo']['label'])
        self.assertEqual('image', fields['photo']['type'])
        self.assertEqual(True, fields['confirmed']['default'])
        self.assertEqual('ok', fields['result']['default'])
        self.assertEqual(7, len(fields))
        self.assertEqual([{'col_1':'油位','col_2':'正常'}, {'col_1':'温控','col_2':'正常'}], schema['tables'][0]['default'])
        self.assertTrue(result['warnings'])

    def test_declarative_javascript_without_execution(self):
        raw = b"<html><title>Example</title><script>var fields=[{k:'device', t:'Device',type:'text',def:'A'}, {k:'items',t:'Items',type:'table',cols:[{k:'value',t:'Value',type:'number'}],rows:[{value:2}]}]; throw new Error('never execute');</script></html>"
        result = discover_html(raw)
        self.assertEqual('device', result['schema']['fields'][0]['key'])
        self.assertEqual('items', result['schema']['tables'][0]['key'])

    def test_unknown_dynamic_html_requires_review_not_fake_success(self):
        result = discover_html(b'<html><title>JS</title><script>fetch("/fields").then(render)</script></html>')
        self.assertEqual([], result['schema']['fields'])
        self.assertTrue(result['warnings'])

    def test_duplicate_and_prototype_keys_rejected(self):
        from fastapi import HTTPException
        for fields in ([{'key':'__proto__','label':'Bad','type':'text'}], [{'key':'a','label':'A','type':'text'}]*2):
            with self.assertRaises(HTTPException): validate_schema({'fields':fields,'tables':[]})


class FormPlatformAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.patch = patch('app.main.DATA_DIR', Path(self.temp.name))
        self.patch.start()
        self.client = TestClient(app)
        self.schema = discover_html(FIXTURE.read_bytes())['schema']
        self.a = self.client.post('/api/form-apps', json={'name':'Inspection','schema':self.schema}).json()['id']
        self.b = self.client.post('/api/form-apps', json={'name':'Other','schema':self.schema}).json()['id']

    def tearDown(self):
        self.client.close(); self.patch.stop(); self.temp.cleanup()

    def create(self, name='Project', data=None):
        r = self.client.post(f'/api/form-apps/{self.a}/projects',json={'name':name,'data':data or {'f':{'partNo':'EQ-002'}}})
        self.assertEqual(200,r.status_code,r.text)
        return r.json()

    def test_named_projects_never_overwrite_on_create(self):
        a,b = self.create(),self.create()
        self.assertNotEqual(a['id'],b['id'])
        self.assertEqual(2,len(self.client.get(f'/api/form-apps/{self.a}/projects').json()['projects']))

    def test_revisions_conflict_and_restore_are_preserved(self):
        p=self.create();url=f'/api/form-apps/{self.a}/projects/{p["id"]}'
        changed={'name':'Edited','revision':1,'data':{'f':{'partNo':'EQ-003'}}}
        self.assertEqual(2,self.client.put(url,json=changed).json()['revision'])
        self.assertEqual(409,self.client.put(url,json=changed).status_code)
        original=self.client.get(url+'?revision=1').json()
        self.assertEqual('EQ-002',original['data']['f']['partNo'])
        restored=self.client.put(url,json={'name':original['name'],'revision':2,'data':original['data']}).json()
        self.assertEqual(3,restored['revision'])
        self.assertEqual(3,len(self.client.get(url+'/versions').json()['versions']))

    def test_project_and_draft_application_isolation(self):
        p=self.create()
        self.assertEqual(404,self.client.get(f'/api/form-apps/{self.b}/projects/{p["id"]}').status_code)
        url=f'/api/form-apps/{self.a}/drafts/templates'
        self.assertEqual(200,self.client.put(url,json={'revision':0,'payload':{'deck':[{'source':1}]}}).status_code)
        self.assertEqual(409,self.client.put(url,json={'revision':0,'payload':{}}).status_code)
        self.assertIsNone(self.client.get(f'/api/form-apps/{self.b}/drafts/templates').json()['payload'])

    def test_archiving_is_recoverable(self):
        p=self.create();url=f'/api/form-apps/{self.a}/projects/{p["id"]}'
        self.client.post(url+'/archive')
        self.assertEqual([],self.client.get(f'/api/form-apps/{self.a}/projects').json()['projects'])
        self.assertEqual(1,len(self.client.get(f'/api/form-apps/{self.a}/projects?archived=true').json()['projects']))
        self.client.post(url+'/archive?archived=false')
        self.assertEqual(1,len(self.client.get(f'/api/form-apps/{self.a}/projects').json()['projects']))

    def test_template_upload_and_scheme_do_not_leak_across_apps(self):
        for scope in (self.a,self.b): self.assertEqual([],self.client.get('/api/templates?app_id='+scope).json()['templates'])
        response=self.client.post('/api/templates/upload?app_id='+self.a+'&template_id=inspection',files={'file':('inspection.pptx',fixture())})
        self.assertEqual(200,response.status_code,response.text)
        self.assertEqual([],self.client.get('/api/templates?app_id='+self.b).json()['templates'])
        slides=[{'source':1,'bindings':{'cell':{'type':'table_cell','shape':'DATA','source':'f.partNo','options':{'row':1,'column':0}}}}]
        payload={'name':'Report','template':'inspection','slides':slides}
        self.assertEqual(200,self.client.post('/api/schemes?app_id='+self.a,json=payload).status_code)
        self.assertEqual([],self.client.get('/api/schemes?app_id='+self.b).json()['schemes'])
        with patch('app.report.ppt.template_engine.compute_all',side_effect=AssertionError('DFM adapter must not execute')):
            result=self.client.post('/api/schemes/Report/generate?app_id='+self.a,json={'data':{'f':{'partNo':'EQ-901'}}})
        self.assertEqual(200,result.status_code,result.text[:100] if result.status_code!=200 else '')
        package=OoxmlPackage(result.content)
        root=etree.fromstring(package.read(next(iter(package.slide_parts().values()))))
        self.assertIn('EQ-901',root.xpath('//*[local-name()="t"]/text()'))
        self.assertEqual(404,self.client.post('/api/template/inspect?app_id='+self.b,json={'template':'inspection'}).status_code)

    def test_same_filename_import_keeps_first_template(self):
        url='/api/templates/upload?app_id='+self.a+'&template_id=inspection'
        first=self.client.post(url,files={'file':('inspection.pptx',fixture())}).json()['template']
        second=self.client.post(url,files={'file':('inspection.pptx',fixture())}).json()['template']
        self.assertNotEqual(first['template_id'],second['template_id'])
        self.assertEqual(2,len(self.client.get('/api/templates?app_id='+self.a).json()['templates']))

    def test_invalid_scope_cannot_fall_back_to_dfm(self):
        self.assertEqual(404,self.client.get('/api/templates?app_id=../dfm').status_code)

    def test_catalog_images_expose_editor_binding_paths(self):
        result=self.client.get(f'/api/form-apps/{self.a}/catalog').json()
        self.assertEqual('i.photo[0]',result['images']['photo']['path'])
        self.assertTrue(all(isinstance(f['path'],str) for f in result['fields']))

    def test_invalid_schema_returns_validation_error(self):
        for schema in ({'fields':[None]}, {'fields':[{'key':[]}]}, {'fields':[{'key':'a','label':'A','type':'select','options':['bad']}]}):
            self.assertEqual(422,self.client.post('/api/form-apps',json={'name':'Invalid','schema':schema}).status_code)

    def test_scope_does_not_leak_between_requests(self):
        self.client.get('/api/templates?app_id='+self.a)
        self.assertIn('demo',[t['template_id'] for t in self.client.get('/api/templates').json()['templates']])


if __name__=='__main__': unittest.main()
