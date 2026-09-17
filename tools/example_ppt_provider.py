"""Independent example: uvicorn tools.example_ppt_provider:app --port 8010.

No imports from app: new projects only implement this HTTP/JSON contract.
"""
from fastapi import FastAPI, HTTPException

app = FastAPI(title='Example PPT data provider')
PREFIX = '/api/ppt-provider/v1'

@app.get('/health')
def health():
    return {'service': 'example'}

@app.get(PREFIX + '/sources')
def sources():
    return {'contract_version': '1.0', 'sources': [
        {'id': 'inspection', 'name': '质量检验（接入示例）', 'form_url': 'http://127.0.0.1:8010/docs', 'contract_version': '1.0'}]}

@app.get(PREFIX + '/sources/{source_id}/projects')
def projects(source_id: str):
    if source_id != 'inspection':
        raise HTTPException(404, 'Source not found')
    return {'projects': [{'id': 'sample', 'name': '检验样例', 'revision': 1}]}

@app.get(PREFIX + '/sources/{source_id}/projects/{project_id}/snapshot')
def snapshot(source_id: str, project_id: str):
    projects(source_id)
    if project_id not in ('sample', 'defaults'):
        raise HTTPException(404, 'Project not found')
    return {'contract_version': '1.0', 'source_id': source_id, 'project_id': project_id,
        'name': '检验样例', 'revision': 1, 'form_url': 'http://127.0.0.1:8010/docs',
        'data': {'f': {'part': 'INSPECT-001', 'status': '合格'}, 't': {'checks': [{'item': '直径', 'value': 20.01}]}, 'i': {}},
        'catalog': {'fields': [
            {'path': 'f.part', 'label': '零件号', 'module': '检验', 'group': '基本信息'},
            {'path': 'f.status', 'label': '检验结论', 'module': '检验', 'group': '基本信息'}],
            'tables': {'checks': {'label': '检验明细', 'module': '检验', 'group': '尺寸', 'columns': {'item': '项目', 'value': '实测值'}}},
            'images': {}, 'derived': {}, 'results': {}}}
