"""压铸表单服务的数据源导出 API（/api/ppt-provider/v1）与跨服务链接。

本分支只保留压铸部分；机加侧的同名接口在 machining 分支的 provider_api.py 中。
"""
import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..integration_contract import snapshot


def provider_router():
    def authenticate(authorization: str | None = Header(None)):
        import hmac
        expected = os.environ.get('PPT_PROVIDER_TOKEN')
        if expected and not hmac.compare_digest(authorization or '', 'Bearer ' + expected):
            raise HTTPException(401, '数据源接口凭证无效')
    return APIRouter(prefix='/api/ppt-provider/v1', dependencies=[Depends(authenticate)])


def install_link(app, source_id):
    @app.get('/api/integration/services')
    def service_links(request: Request):
        unified = getattr(request.app.state, 'workbench_url', None) == ''
        return {'hpdc': '/forms' if unified else os.environ.get('HPDC_PUBLIC_URL', 'http://127.0.0.1:8001').rstrip('/') + '/forms',
                'machining': '/machining-dfm' if unified else os.environ.get('MACHINING_PUBLIC_URL', 'http://127.0.0.1:8002').rstrip('/') + '/machining-dfm'}

    @app.get('/api/integration/workbench-link')
    def workbench_link(request: Request, project_id: str = '', app_id: str | None = None):
        base = getattr(request.app.state, 'workbench_url', None)
        if base is None:
            base = os.environ.get('PPT_WORKBENCH_URL', 'http://127.0.0.1:8003')
        source = app_id or source_id
        return {'url': base.rstrip('/') + '/template-editor?app_id=' + quote(source, safe='') +
                ('&project_id=' + quote(project_id, safe='') if project_id else '')}

    # 表单页「按方案生成」是同源 HTTP 客户端：转发到独立的 PPT 工作台服务，
    # 不共享方案文件，也不导入渲染器。
    async def proxy(request: Request):
        import httpx
        from fastapi.responses import Response
        base = os.environ.get('PPT_WORKBENCH_URL', 'http://127.0.0.1:8003').rstrip('/')
        query = dict(request.query_params)
        query.setdefault('app_id', source_id)
        try:
            async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
                result = await client.request(request.method, base + request.url.path, params=query,
                    content=await request.body(), headers={'Content-Type': request.headers.get('Content-Type', 'application/json')})
            headers = {k: v for k, v in result.headers.items() if k.lower().startswith('x-dfm-') or k.lower() in {'content-type', 'content-disposition'}}
            return Response(result.content, status_code=result.status_code, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(502, 'PPT 工作台无法连接，请启动工作台服务') from exc
    app.add_api_route('/api/schemes', proxy, methods=['GET', 'POST'])
    app.add_api_route('/api/schemes/{scheme_path:path}', proxy, methods=['GET', 'POST', 'DELETE'])


def install_hpdc(app, store_factory, static_dir, demo_factory, legacy_factory):
    router = provider_router()
    from ..form_platform import FORM_SCOPE
    from ..provider_context import build_legacy_context
    from ..native_forms import normalize
    import json

    def catalog_for(source_id, data):
        store = store_factory()
        application = store.application(source_id)
        if source_id == 'dfm':
            text = (static_dir / 'dfm_catalog.js').read_text(encoding='utf-8')
            catalog = json.loads(text[text.index('{'):text.rfind('}') + 1])
            from ..provider_context import FORMULA_FIELDS
            catalog['fields'].extend({'path': path, 'label': label, 'module': '计算结果', 'group': '公式显示'} for path, label in FORMULA_FIELDS.items())
            # Historical PPT context uses scalar verdicts, not nested objects.
            catalog['fields'].extend({'path': 'calc_results.' + key, 'label': label, 'module': '计算结果', 'group': '工艺结论'} for key, label in catalog.get('results', {}).items())
            catalog['results'] = {}
            return catalog
        if application['schema'].get('runtime'):
            return normalize(data['runtime'], include_legacy_aliases=False)[1]
        from ..form_platform import catalog
        return catalog(application['schema'])

    def project_data(source_id, project_id):
        store = store_factory()
        application = store.application(source_id)
        if project_id in {'defaults', 'demo', 'legacy'}:
            if source_id == 'dfm':
                data = legacy_factory() if project_id == 'legacy' else demo_factory()
            else:
                from ..form_platform import defaults
                with store.connect() as db:
                    latest = db.execute('SELECT id FROM projects WHERE app_id=? AND archived=0 ORDER BY updated DESC LIMIT 1', (source_id,)).fetchone()
                if latest and application['schema'].get('runtime'):
                    data = store.project(source_id, latest['id'])['data']
                elif application['schema'].get('runtime'):
                    raise HTTPException(409, '请先在表单中保存一个项目')
                else:
                    data = defaults(application['schema'])
            return {'name': '默认数据', 'revision': 0, 'data': data}
        with store.connect() as db:
            row = db.execute('SELECT archived FROM projects WHERE app_id=? AND id=?', (source_id, project_id)).fetchone()
        if row and row['archived']:
            raise HTTPException(410, '项目已删除，请先恢复')
        return store.project(source_id, project_id)

    @router.get('/sources')
    def sources(request: Request):
        origin = os.environ.get('HPDC_PUBLIC_URL', str(request.base_url).rstrip('/'))
        store = store_factory()
        with store.connect() as db:
            extra = [dict(r) for r in db.execute('SELECT id,name,archived FROM apps')]
        return {'contract_version': '1.0', 'sources': [
            {'id': 'dfm', 'name': '压铸 DFM', 'form_url': origin + '/', 'contract_version': '1.0'},
            *[{**row, 'form_url': origin + '/forms?app_id=' + row['id'], 'contract_version': '1.0'} for row in extra],
        ]}

    @router.get('/sources/{source_id}/projects')
    def projects(source_id: str):
        store = store_factory(); store.application(source_id)
        with store.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT id,name,revision,updated FROM projects WHERE app_id=? AND archived=0 ORDER BY updated DESC', (source_id,))]
        return {'projects': rows}

    @router.post('/sources/{source_id}/normalize')
    def normalize_data(source_id: str, body: dict):
        store_factory().application(source_id)
        token = FORM_SCOPE.set(source_id)
        try:
            return build_legacy_context(body.get('data', {}), binding_sources=body.get('binding_sources'))
        finally:
            FORM_SCOPE.reset(token)

    @router.get('/sources/{source_id}/projects/{project_id}/snapshot')
    def get_snapshot(source_id: str, project_id: str, request: Request):
        record = project_data(source_id, project_id)
        origin = os.environ.get('HPDC_PUBLIC_URL', str(request.base_url).rstrip('/'))
        url = origin + ('/?project_id=' if source_id == 'dfm' else '/forms?app_id=' + source_id + '&project=') + quote(project_id, safe='')
        if project_id in {'defaults', 'demo', 'legacy'}:
            url = origin + ('/' if source_id == 'dfm' else '/forms?app_id=' + source_id)
        return snapshot(source_id, project_id, record['revision'], record['name'], url,
                        normalize_data(source_id, {'data': record['data']}), catalog_for(source_id, record['data']))

    app.include_router(router)
    install_link(app, 'dfm')
    install_report_bridge(app, 'dfm')


def install_report_bridge(app, source_id):
    """表单服务侧的 PPT 生成入口：同源转发到独立工作台，不导入渲染器。

    - GET  /api/report/options   : 工作台地址与该数据源的生成入口（页面/脚本对接用）
    - GET  /api/report/sources   : 转发工作台 /api/ppt/contract（数据源清单与契约版本）
    - POST /api/report/generate  : {project_id, scheme | template+slides, output_mode, missing}
                                   转发到工作台 POST /api/ppt/generate 并回传 pptx
    """
    import os

    import httpx
    from fastapi.responses import Response
    from pydantic import BaseModel

    class ReportGenerateRequest(BaseModel):
        project_id: str
        scheme: str | None = None
        template: str | None = None
        slides: list[dict] = []
        output_mode: str = 'deck'
        missing: str = 'keep'

    def workbench_base():
        return os.environ.get('PPT_WORKBENCH_URL', 'http://127.0.0.1:8003').rstrip('/')

    @app.get('/api/report/options')
    def report_options():
        base = workbench_base()
        return {
            'source_id': source_id,
            'workbench_url': base,
            'generate': {'method': 'POST', 'path': '/api/report/generate',
                         'body': ['project_id', 'scheme 或 template+slides', 'output_mode', 'missing']},
            'contract': base + '/api/ppt/contract',
            'catalog': base + '/api/ppt/sources/' + source_id + '/projects/{project_id}/catalog',
        }

    @app.get('/api/report/sources')
    async def report_sources():
        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                result = await client.get(workbench_base() + '/api/ppt/contract')
        except httpx.HTTPError as exc:
            raise HTTPException(502, 'PPT 工作台无法连接，请启动工作台服务') from exc
        if result.status_code != 200:
            raise HTTPException(result.status_code, result.text[:300])
        return result.json()

    @app.post('/api/report/generate')
    async def report_generate(req: ReportGenerateRequest):
        body = {'source_id': source_id, **req.model_dump()}
        try:
            async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
                result = await client.post(workbench_base() + '/api/ppt/generate', json=body)
        except httpx.HTTPError as exc:
            raise HTTPException(502, 'PPT 工作台无法连接，请启动工作台服务') from exc
        headers = {k: v for k, v in result.headers.items()
                   if k.lower().startswith('x-dfm-') or k.lower() in {'content-type', 'content-disposition'}}
        return Response(result.content, status_code=result.status_code, headers=headers)
