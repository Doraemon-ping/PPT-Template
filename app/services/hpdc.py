import json
import os
import re
import uuid
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from ..settings import BASE_DIR, APP_ROOT, DATA_DIR, STATIC_DIR
from ..calc import compute_all
from ..demo import demo_state
from ..ppt import build_pptx, safe_filename
from ..form_platform import PlatformStore, router_for
app = FastAPI(title='压铸 DFM 表单服务', version='2.0')
from .observability import install as install_logging
LOG_FILE = install_logging(app, 'hpdc')
PROJECT_FILE = DATA_DIR / 'project.json'
def _platform():
    return PlatformStore(DATA_DIR / 'form_platform')
app.include_router(router_for(_platform, STATIC_DIR))
class CalcRequest(BaseModel):
    f: dict = {}
    t: dict = {}
    apply_machine: bool = False


class PptRequest(BaseModel):
    f: dict = {}
    t: dict = {}
    i: dict = {}


class SaveRequest(BaseModel):
    f: dict = {}
    t: dict = {}
    i: dict = {}


@app.get('/forms')
def form_center():
    return FileResponse(STATIC_DIR / 'form_center.html')


@app.post('/api/form-apps/dfm/import-legacy-project')
def import_legacy_project():
    if not PROJECT_FILE.exists():
        raise HTTPException(404, '没有旧版服务器项目')
    data = json.loads(PROJECT_FILE.read_text(encoding='utf-8'))
    return _platform().save_project('dfm', '旧版项目 · ' + (data.get('f', {}).get('projName') or 'DFM'), data)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/calc")
def api_calc(req: CalcRequest):
    return compute_all(req.f, apply_machine=req.apply_machine)


@app.post("/api/ppt")
def api_ppt(req: PptRequest):
    try:
        buf = build_pptx(req.f, req.t, req.i)
        fname = safe_filename(req.f)
        cd = 'attachment; filename="DFM.pptx"; filename*=UTF-8\'\'' + quote(fname)
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": cd},
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"PPT 生成失败：{e}") from e


# 说明：旧版命名形状引擎预览（原 /api/ppt/preview-v2）已随三服务拆分移至
# workbench（PPT 工作台）服务；本服务只保留传统 47 页 /api/ppt 导出。


@app.get("/api/demo")
def api_demo():
    return demo_state()


@app.get("/api/project/load")
def api_project_load():
    if PROJECT_FILE.exists():
        try:
            with open(PROJECT_FILE, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            pass
    return {"f": {}, "t": {}, "i": {}}


@app.post("/api/project/save")
def api_project_save(req: SaveRequest):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = {"f": req.f, "t": req.t, "i": req.i}
        record = _platform().save_project('dfm', req.f.get('projName') or req.f.get('partNo') or 'DFM 项目', data)
        return {"ok": True, "project": record, "hint": "已保存为新项目，可在表单中心管理"}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"保存失败：{e}") from e

from .provider_api import install_hpdc
install_hpdc(app, _platform, STATIC_DIR, demo_state, api_project_load)

@app.get('/health')
def health():
    return {'service': 'hpdc', 'contract_version': '1.0'}

app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')

