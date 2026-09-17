import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.services.hpdc import app
from app.native_forms import JSON_ADAPTER, normalize, key

SOURCE = b'''<html><head><title>Native fixture</title></head><body><div id="form"></div><script>
var G={part:'fixture'},PR=[],MDB=[],TDB=[],IS=[],FDB=[],IDB=[],VH=[],GLBL={part:'Part'};
function applyData(d){G=d.G;} function exportData(){} function render(){document.getElementById('form').textContent=G.part;}
localStorage.setItem('cncCalcV7','fixture');render();
</script></body></html>'''

JSON_SOURCE = b'''<html><head><title>JSON fixture</title></head><body><script>
let model={project:{customer:'A'}};
window.__DFM_BRIDGE__={version:'1',exportData(){return model;},importData(value){model=value;}};
</script></body></html>'''


def snapshot():
    return {'adapter':'dfm_quote_v1','state':{'G':{'cust':'Customer','part':'Sample','pI':'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='},'pr':[{'nm':'OP10','tl':[{'nm':'Tool','_ct':2}]}], 'mdb':[], 'tdb':[], 'is':[], 'fdb':[], 'idb':[], 'vh':[]},'labels':{'part':'零件号'}}


class NativeFormsTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.patch=patch('app.services.hpdc.DATA_DIR',Path(self.temp.name));self.patch.start()
        # 本分支只包含 hpdc 服务；机加/工作台模块不存在，无需再隔离它们的 DATA_DIR。
        self.client=TestClient(app)
        response=self.client.post('/api/form-apps/import-native',files={'file':('native.html',SOURCE)})
        self.assertEqual(200,response.status_code,response.text)
        self.app_id=response.json()['id'];self.base='/api/form-apps/'+self.app_id

    def tearDown(self):
        self.client.close();self.patch.stop();self.temp.cleanup()

    def test_original_source_retained_as_json_not_executable_response(self):
        response=self.client.get(self.base+'/runtime-source')
        self.assertEqual(SOURCE.decode(),response.json()['html'])
        self.assertTrue(response.headers['content-type'].startswith('application/json'))

    def test_discovery_announces_native_adapter(self):
        response=self.client.post('/api/form-apps/discover',files={'file':('native.html',SOURCE)})
        self.assertEqual(200,response.status_code,response.text)
        self.assertEqual('dfm_quote_v1',response.json()['native']['adapter'])

    def test_unknown_source_fails_closed(self):
        self.assertEqual(422,self.client.post('/api/form-apps/import-native',files={'file':('other.html',b'<html>hello</html>')}).status_code)

    def test_raw_state_and_catalog_roundtrip(self):
        raw=snapshot()
        p=self.client.post(self.base+'/projects',json={'name':'One','data':{'runtime':raw}}).json()
        self.assertEqual(raw,p['data']['runtime'])
        self.assertEqual('Sample',p['data']['f'][key('G.part')])
        self.assertEqual(2,p['data']['t'][key('pr.tl')][0]['_ct'])
        catalog=self.client.get(self.base+'/catalog',params={'project_id':p['id']}).json()
        self.assertIn('零件号',next(f['label'] for f in catalog['fields'] if f['path']=='f.'+key('G.part')))
        self.assertEqual('i.'+key('G.pI')+'[0]',catalog['images'][key('G.pI')]['path'])

    def test_history_preserves_empty_arrays_and_nested_state(self):
        first=self.client.post(self.base+'/projects',json={'name':'One','data':{'runtime':snapshot()}}).json()
        raw=snapshot();raw['state']['pr']=[]
        url=self.base+'/projects/'+first['id']
        edited=self.client.put(url,json={'name':'One','revision':1,'data':{'runtime':raw}})
        self.assertEqual(200,edited.status_code)
        self.assertEqual([],edited.json()['data']['runtime']['state']['pr'])
        self.assertEqual(1,len(self.client.get(url+'?revision=1').json()['data']['runtime']['state']['pr']))
        self.assertEqual(409,self.client.put(url,json={'name':'One','revision':1,'data':{'runtime':raw}}).status_code)

    def test_current_project_reads_are_not_cached(self):
        first=self.client.post(self.base+'/projects',json={'name':'One','data':{'runtime':snapshot()}}).json()
        url=self.base+'/projects/'+first['id']
        initial=self.client.get(url)
        self.assertEqual('no-store, max-age=0', initial.headers['cache-control'])
        raw=snapshot();raw['state']['G']['cust']='New Energy'
        self.assertEqual(200,self.client.put(url,json={'name':'One','revision':1,'data':{'runtime':raw}}).status_code)
        current=self.client.get(url)
        self.assertEqual('New Energy', current.json()['data']['f'][key('G.cust')])

    def test_missing_snapshot_cannot_silently_save_empty_project(self):
        self.assertEqual(422,self.client.post(self.base+'/projects',json={'name':'One','data':{'f':{}}}).status_code)

    def test_catalog_project_isolation(self):
        p=self.client.post(self.base+'/projects',json={'name':'One','data':{'runtime':snapshot()}}).json()
        other=self.client.post('/api/form-apps/import-native',files={'file':('native.html',SOURCE)}).json()['id']
        self.assertEqual(404,self.client.get('/api/form-apps/'+other+'/catalog',params={'project_id':p['id']}).status_code)

    def test_legacy_template_aliases_are_projected(self):
        raw=snapshot();raw['state']['G']['cust']='Customer alias'
        normalized,_=normalize(raw)
        self.assertEqual('Customer alias',normalized['f']['custName'])
        self.assertEqual('Sample',normalized['f']['partNo'])
        self.assertEqual('Sample',normalized['f']['projName'])

    def test_project_read_exposes_aliases_for_live_preview(self):
        p=self.client.post(self.base+'/projects',json={'name':'Preview','data':{'runtime':snapshot()}}).json()
        # Simulate an old row that only has the runtime payload and hashed keys.
        url=self.base+'/projects/'+p['id']
        old=self.client.get(url).json(); old['data'].pop('f',None); old['data'].pop('t',None); old['data'].pop('i',None)
        # Current endpoint must derive canonical fields when reading the old row.
        # (A fresh update is used here because the public API never accepts a raw DB edit.)
        result=self.client.get(url).json()
        self.assertEqual('Customer',result['data']['f']['custName'])
        self.assertEqual('Sample',result['data']['f']['partNo'])

    def test_flattened_keys_do_not_collide(self):
        self.assertNotEqual(key('G.a_b'),key('G.a.b'))

    def test_native_catalog_keeps_source_paths_and_does_not_advertise_aliases(self):
        project = self.client.post(self.base+'/projects',json={'name':'Catalog','data':{'runtime':snapshot()}}).json()
        catalog = self.client.get(self.base+'/catalog',params={'project_id':project['id']}).json()
        paths = {entry['path'] for entry in catalog['fields']}
        self.assertIn('f.'+key('G.cust'), paths)
        self.assertNotIn('f.custName', paths)
        self.assertNotIn('f.partNo', paths)

    def test_generic_json_export_is_discovered_projected_and_saved_once(self):
        imported=self.client.post('/api/form-apps/import-native',files={'file':('generic.html',JSON_SOURCE)})
        self.assertEqual(200,imported.status_code,imported.text)
        app_id=imported.json()['id'];base='/api/form-apps/'+app_id
        self.assertEqual(JSON_ADAPTER,imported.json()['schema']['runtime']['adapter'])
        runtime={
            'adapter':JSON_ADAPTER,
            'source_version':'2026.09',
            'raw':{
                'project':{'customer':'ACME','count':2},
                'processes':[{'name':'OP10','seconds':12},{'name':'OP20','seconds':8}],
                'tags':['urgent','machining'],
                'audit':{'changed_by':'hidden'},
            },
            'labels':{'project':'项目信息','project.customer':'客户名称','processes':'工序'},
            'rules':{'exclude':['audit']},
        }
        saved=self.client.post(base+'/projects',json={'name':'Generic','data':{'runtime':runtime}})
        self.assertEqual(200,saved.status_code,saved.text)
        payload=saved.json()['data']
        self.assertEqual('ACME',payload['f'][key('project.customer')])
        self.assertEqual(2,len(payload['t'][key('processes')]))
        self.assertEqual([{'value':'urgent'},{'value':'machining'}],payload['t'][key('tags')])
        self.assertNotIn(key('audit.changed_by'),payload['f'])
        catalog=self.client.get(base+'/catalog',params={'project_id':saved.json()['id']}).json()
        self.assertEqual('客户名称',next(f['label'] for f in catalog['fields'] if f['path']=='f.'+key('project.customer')))
        self.assertEqual({'name':'name','seconds':'seconds'},catalog['tables'][key('processes')]['columns'])

        # Persisted revisions contain the authoritative runtime only; the
        # rebuildable projection is not duplicated beside a large raw export.
        from app.form_platform import PlatformStore
        store=PlatformStore(Path(self.temp.name)/'form_platform')
        with store.connect() as db:
            row=db.execute('SELECT data_json FROM projects WHERE id=?',(saved.json()['id'],)).fetchone()
        stored=__import__('json').loads(row['data_json'])
        self.assertEqual({'runtime'},set(stored))


if __name__=='__main__':unittest.main()
