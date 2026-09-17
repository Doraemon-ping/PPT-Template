"""Standalone machining form. Run: uvicorn app.services.machining:app --port 8002."""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from ..settings import BASE_DIR, DATA_DIR, STATIC_DIR
from ..machining_dfm import MachiningDFMStore, router_for
from .provider_api import install_machining

def store():
    return MachiningDFMStore(DATA_DIR / 'machining_dfm', BASE_DIR / 'app/resources/machining_dfm_seed.json')

app = FastAPI(title='机加 DFM 表单服务', version='2.0')
from .observability import install as install_logging
LOG_FILE = install_logging(app, 'machining_dfm')
app.include_router(router_for(store, STATIC_DIR))
install_machining(app, store)

@app.get('/')
def home():
    return RedirectResponse('/machining-dfm')

@app.get('/health')
def health():
    return {'service': 'machining', 'contract_version': '1.0'}

app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')
