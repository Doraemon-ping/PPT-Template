"""机加表单服务的数据源导出 API（/api/ppt-provider/v1）与跨服务链接。

本分支只保留机加部分；压铸侧的同名接口在 hpdc 分支的 provider_api.py 中。
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


def install_machining(app, store_factory):
    router = provider_router()
    from ..native_forms import normalize, DFM_ADAPTER  # noqa: F401

    def check(source_id):
        if source_id != 'machining-dfm':
            raise HTTPException(404, '机加数据源不存在')

    def project_context(state):
        from ..machining_projection import report_runtime
        data, catalog = normalize(report_runtime(state), include_legacy_aliases=False)
        data.pop('runtime', None)
        return data, catalog

    @router.get('/sources')
    def sources(request: Request):
        origin = os.environ.get('MACHINING_PUBLIC_URL', str(request.base_url).rstrip('/'))
        return {'contract_version': '1.0', 'sources': [{'id': 'machining-dfm', 'name': '机加 DFM', 'form_url': origin + '/machining-dfm', 'contract_version': '1.0'}]}

    @router.get('/sources/{source_id}/projects')
    def projects(source_id: str):
        check(source_id)
        return {'projects': store_factory().list()}

    @router.get('/sources/{source_id}/projects/{project_id}/snapshot')
    def get_snapshot(source_id: str, project_id: str, request: Request):
        check(source_id)
        store = store_factory()
        # 附件在库里是磁盘文件 + URL；PPT 需要字节，因此这条路径把设备图片内联成 data URL，
        # 与拆分前的快照逐字段一致（图片槽位 i.* 的绑定不变）。
        record = ({'state': store.defaults(inline_assets=True), 'name': '默认数据', 'revision': 0}
                  if project_id == 'defaults' else store.get(project_id, inline_assets=True))
        data, catalog = project_context(record['state'])
        origin = os.environ.get('MACHINING_PUBLIC_URL', str(request.base_url).rstrip('/'))
        return snapshot(source_id, project_id, record['revision'], record['name'], origin + '/machining-dfm?project_id=' + quote(project_id, safe=''), data, catalog)

    @router.post('/sources/{source_id}/normalize')
    def normalize_data(source_id: str, body: dict):
        check(source_id)
        data = body.get('data', {})
        if 'runtime' in data:
            return project_context(data['runtime']['state'])[0]
        return data

    app.include_router(router)
    install_link(app, 'machining-dfm')
