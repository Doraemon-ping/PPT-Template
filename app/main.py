"""HTTP gateway for three independently runnable services."""
from urllib.parse import parse_qs
from fastapi import FastAPI
from .services import hpdc, machining, workbench
from .services.workbench_core import hub

# ASGI HTTP uses the same JSON contract as independent HTTP deployment.
hub.local_apps.update(hpdc=hpdc.app, machining=machining.app)
hpdc.app.state.workbench_url = ''
machining.app.state.workbench_url = ''

class Gateway:
    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        query = parse_qs(scope.get('query_string', b'').decode())
        if path.startswith(('/api/templates', '/api/template/', '/api/schemes', '/api/ppt/sources')) or path in {'/template-editor', '/ppt'}:
            target = workbench.app
        elif path.startswith(('/machining-dfm', '/api/machining-dfm')):
            target = machining.app
        elif path == '/api/integration/workbench-link' and query.get('app_id') == ['machining-dfm']:
            target = machining.app
        else:
            target = hpdc.app
        await target(scope, receive, send)

app = FastAPI(title='DFM 与 PPT 服务入口', version='2.0')

@app.get('/health')
def health():
    return {'service': 'gateway', 'services': ['hpdc', 'machining', 'ppt-workbench']}

app.mount('/', Gateway())

def run():
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000)

if __name__ == '__main__':
    run()
