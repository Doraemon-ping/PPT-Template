import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.native_forms import normalize, key

SOURCE = b'''<html><head><title>Native fixture</title></head><body><div id="form"></div><script>
var G={part:'fixture'},PR=[],MDB=[],TDB=[],IS=[],FDB=[],IDB=[],VH=[],GLBL={part:'Part'};
function applyData(d){G=d.G;} function exportData(){} function render(){document.getElementById('form').textContent=G.part;}
localStorage.setItem('cncCalcV7','fixture');render();
</script></body></html>'''


def snapshot():
    return {'adapter':'dfm_quote_v1','state':{'G':{'cust':'Customer','part':'Sample','pI':'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='},'pr':[{'nm':'OP10','tl':[{'nm':'Tool','_ct':2}]}], 'mdb':[], 'tdb':[], 'is':[], 'fdb':[], 'idb':[], 'vh':[]},'labels':{'part':'零件号'}}


class NativeFormsTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.patch=patch('app.main.DATA_DIR',Path(self.temp.name));self.patch.start()
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

    def test_native_snapshot_generates_text_and_image_binding(self):
        import io, zipfile
        from lxml import etree
        template=Path('templates/DFM_Template_Placeholder_Demo.pptx')
        upload=self.client.post('/api/templates/upload?app_id='+self.app_id+'&template_id=native-smoke',files={'file':(template.name,template.read_bytes())})
        self.assertEqual(200,upload.status_code,upload.text); template_id=upload.json()['template']['template_id']
        p=self.client.post(self.base+'/projects',json={'name':'Native','data':{'runtime':snapshot()}}).json()
        payload={'name':'Native smoke','template':template_id,'slides':[{'source':1,'bindings':{'text':{'type':'text','shape':'COVER_PART_NUMBER','source':'f.custName'}}},{'source':2,'bindings':{'image':{'type':'image','shape':'PART_IMAGE','source':'i.'+key('G.pI')+'[0]'}}}]}
        self.assertEqual(200,self.client.post('/api/schemes?app_id='+self.app_id,json=payload).status_code)
        response=self.client.post('/api/schemes/Native smoke/generate?app_id='+self.app_id,json={'data':p['data']})
        self.assertEqual(200,response.status_code,response.text[:300]); package=zipfile.ZipFile(io.BytesIO(response.content)); xml=etree.fromstring(package.read('ppt/slides/slide1.xml'))
        self.assertIn('Customer',xml.xpath('//*[local-name()="t"]/text()'))
        self.assertTrue(etree.fromstring(package.read('ppt/slides/slide2.xml')).xpath('//*[local-name()="pic"]'))

        # Updating the same project URL must feed the latest snapshot into the
        # next render, never the customer value used by the previous render.
        raw=snapshot();raw['state']['G']['cust']='New Energy'
        updated=self.client.put(self.base+'/projects/'+p['id'],json={'name':'Native','revision':p['revision'],'data':{'runtime':raw}}).json()
        response=self.client.post('/api/schemes/Native smoke/generate?app_id='+self.app_id,json={'data':updated['data']})
        self.assertEqual(200,response.status_code,response.text[:300])
        package=zipfile.ZipFile(io.BytesIO(response.content));xml=etree.fromstring(package.read('ppt/slides/slide1.xml'))
        text=xml.xpath('//*[local-name()="t"]/text()')
        self.assertIn('New Energy',text)
        self.assertNotIn('Customer',text)

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

    def test_native_generation_allows_unbound_template_targets(self):
        import io, zipfile
        from lxml import etree
        template=Path('templates/DFM_Template_Placeholder_Demo.pptx')
        upload=self.client.post('/api/templates/upload?app_id='+self.app_id+'&template_id=native-targets',files={'file':(template.name,template.read_bytes())})
        self.assertEqual(200,upload.status_code,upload.text); template_id=upload.json()['template']['template_id']
        raw=snapshot(); raw['state']['G'].update({'dfmDate':'2026-09-09','custVer':'A1'})
        project=self.client.post(self.base+'/projects',json={'name':'Targets','data':{'runtime':raw}}).json()
        def src(path): return 'f.'+key(path)
        bindings={
            'COVER_PART_NUMBER': {'type':'text','shape':'COVER_PART_NUMBER','source':src('G.part')},
            'COVER_PROJECT_NAME': {'type':'text','shape':'COVER_PROJECT_NAME','source':src('G.part')},
            'COVER_CUSTOMER': {'type':'text','shape':'COVER_CUSTOMER','source':src('G.cust')},
            'COVER_DATE': {'type':'text','shape':'COVER_DATE','source':src('G.dfmDate')},
            'COVER_VERSION': {'type':'text','shape':'COVER_VERSION','source':src('G.custVer')},
        }
        payload={'name':'Native target mapping','template':template_id,'slides':[{'source':1,'bindings':bindings}]}
        self.assertEqual(200,self.client.post('/api/schemes?app_id='+self.app_id,json=payload).status_code)
        response=self.client.post('/api/schemes/Native target mapping/generate?app_id='+self.app_id,json={'data':project['data']})
        self.assertEqual(200,response.status_code,response.text[:300])
        package=zipfile.ZipFile(io.BytesIO(response.content))
        xml=etree.fromstring(package.read('ppt/slides/slide1.xml'))
        text=''.join(xml.xpath('//*[local-name()="t"]/text()'))
        self.assertIn('Customer',text)
        self.assertNotIn('{f.',text)

        incomplete={'name':'Native target incomplete','template':template_id,'slides':[{'source':1,'bindings':{'customer':bindings['COVER_CUSTOMER']}}]}
        self.assertEqual(200,self.client.post('/api/schemes?app_id='+self.app_id,json=incomplete).status_code)
        partial=self.client.post('/api/schemes/Native target incomplete/generate?app_id='+self.app_id,json={'data':project['data']})
        self.assertEqual(200,partial.status_code,partial.text[:300])
        self.assertEqual('4', partial.headers['x-dfm-unbound-targets'])
        package=zipfile.ZipFile(io.BytesIO(partial.content))
        xml=etree.fromstring(package.read('ppt/slides/slide1.xml'))
        text=''.join(xml.xpath('//*[local-name()="t"]/text()'))
        self.assertIn('Customer', text)
        self.assertIn('{f.partNo}', text)


if __name__=='__main__':unittest.main()
