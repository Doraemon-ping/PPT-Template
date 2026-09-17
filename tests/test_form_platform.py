import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from lxml import etree

from app.form_platform import PlatformStore, discover_html, validate_schema
from app.services.hpdc import app
from app.report.ppt.openxml.package_editor import OoxmlPackage

FIXTURE = Path(__file__).parent / 'fixtures' / 'inspection_form.html'


class DiscoveryTests(unittest.TestCase):
    def test_legacy_app_table_is_migrated_for_soft_delete(self):
        with TemporaryDirectory() as temp:
            db=Path(temp)/'platform.sqlite3'
            connection=sqlite3.connect(db)
            try:
                connection.execute('CREATE TABLE apps(id TEXT PRIMARY KEY,name TEXT NOT NULL,schema_json TEXT NOT NULL,warnings_json TEXT NOT NULL,html BLOB,created TEXT NOT NULL)')
                connection.execute('INSERT INTO apps VALUES(?,?,?,?,?,?)',('old','Old','{}','[]',None,'2026-01-01'))
                connection.commit()
            finally:
                connection.close()
            store=PlatformStore(temp)
            with store.connect() as connection:
                row=connection.execute('SELECT archived FROM apps WHERE id="old"').fetchone()
            self.assertEqual(0,row['archived'])

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
        self.patch = patch('app.services.hpdc.DATA_DIR', Path(self.temp.name))
        self.patch.start()
        # 本分支只包含 hpdc 服务；机加/工作台模块不存在，无需再隔离它们的 DATA_DIR。
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

    def test_imported_application_soft_delete_and_restore_preserves_projects(self):
        project=self.create()
        active={item['id'] for item in self.client.get('/api/form-apps').json()['apps']}
        self.assertIn(self.a,active)
        deleted=self.client.post(f'/api/form-apps/{self.a}/archive')
        self.assertEqual(200,deleted.status_code,deleted.text)
        self.assertNotIn(self.a,{item['id'] for item in self.client.get('/api/form-apps').json()['apps']})
        archived=self.client.get('/api/form-apps?archived=true').json()['apps']
        self.assertEqual([self.a],[item['id'] for item in archived if item['id']==self.a])
        self.assertEqual(410,self.client.get(f'/api/form-apps/{self.a}').status_code)
        restored=self.client.post(f'/api/form-apps/{self.a}/archive?archived=false')
        self.assertEqual(200,restored.status_code,restored.text)
        self.assertEqual(project['id'],self.client.get(f'/api/form-apps/{self.a}/projects').json()['projects'][0]['id'])
        self.assertEqual(422,self.client.post('/api/form-apps/dfm/archive').status_code)

    def test_catalog_images_expose_editor_binding_paths(self):
        result=self.client.get(f'/api/form-apps/{self.a}/catalog').json()
        self.assertEqual('i.photo[0]',result['images']['photo']['path'])
        self.assertTrue(all(isinstance(f['path'],str) for f in result['fields']))

    def test_invalid_schema_returns_validation_error(self):
        for schema in ({'fields':[None]}, {'fields':[{'key':[]}]}, {'fields':[{'key':'a','label':'A','type':'select','options':['bad']}]}):
            self.assertEqual(422,self.client.post('/api/form-apps',json={'name':'Invalid','schema':schema}).status_code)
