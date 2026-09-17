"""PPT-owned connector registry, HTTP client, drafts and storage migration.

No form store or calculation imports are allowed in this module.
"""
import json
import os
import re
import shutil
import sqlite3
import threading
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..settings import DATA_DIR
from ..integration_contract import Snapshot, ReportContext

scope = ContextVar('ppt_source', default='dfm')
request_origin = ContextVar('ppt_request_origin', default='http://127.0.0.1:8000')
_migration_lock = threading.Lock()

def valid_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
        raise HTTPException(404, '数据源标识无效')
    return value

def storage_root(source_id):
    source_id = valid_id(source_id)
    target = DATA_DIR / 'ppt_workbench' / 'sources' / source_id
    # Copy once, keep originals as rollback copies. Never reset an existing target.
    with _migration_lock:
        marker = target / '.migrated-v1'
        if not marker.exists():
            target.mkdir(parents=True, exist_ok=True)
            if source_id == 'dfm':
                legacy = DATA_DIR
            elif source_id == 'machining-dfm':
                legacy = DATA_DIR / 'machining_dfm' / 'data'
            else:
                legacy = DATA_DIR / 'form_platform' / 'applications' / source_id / 'data'
            for name in ('templates', 'schemes'):
                if (legacy / name).is_dir():
                    for file in (legacy / name).rglob('*'):
                        relative = file.relative_to(legacy / name)
                        dest = target / name / relative
                        if file.is_file() and not dest.exists():
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(file, dest)
            marker.write_text('Original files preserved; migration v1\n', encoding='utf-8')
    return target

def safe_filename(data):
    fields = data.get('f', data)
    name = str(fields.get('partNo') or fields.get('partName') or fields.get('projName') or 'Report')
    return 'DFM_' + re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)[:100] + '.pptx'

class ProviderHub:
    def __init__(self):
        self.local_apps = {}

    def connections(self):
        path = Path(os.environ.get('PPT_CONNECTIONS_FILE', DATA_DIR / 'ppt_workbench' / 'connections.json'))
        if path.exists():
            items = json.loads(path.read_text(encoding='utf-8'))['connections']
        else:
            items = [
                {'id': 'hpdc', 'base_url': os.environ.get('HPDC_PROVIDER_URL', 'http://127.0.0.1:8001')},
                {'id': 'machining', 'base_url': os.environ.get('MACHINING_PROVIDER_URL', 'http://127.0.0.1:8002')},
            ]
        return items

    async def call(self, connection, path, method='GET', body=None):
        base = connection['base_url'].rstrip('/')
        if not base.startswith(('http://', 'https://')):
            raise HTTPException(502, '数据源必须使用 HTTP 或 HTTPS 地址')
        local = self.local_apps.get(connection['id'])
        if local:
            base = request_origin.get()
        headers = {}
        if connection.get('token_env'):
            token = os.environ.get(connection['token_env'], '')
            if token:
                headers['Authorization'] = 'Bearer ' + token
        transport = httpx.ASGITransport(app=local) if local else None
        try:
            async with httpx.AsyncClient(base_url=base, transport=transport, timeout=30, follow_redirects=False, trust_env=False) as client:
                result = await client.request(method, '/api/ppt-provider/v1' + path, json=body, headers=headers)
            if result.status_code >= 400:
                try:
                    detail = result.json().get('detail', '数据源返回错误')
                except (ValueError, AttributeError):
                    detail = '数据源返回非 JSON 错误响应'
                raise HTTPException(result.status_code, detail)
            try:
                payload = result.json()
                if not isinstance(payload, dict):
                    raise ValueError('Expected an object')
                return payload
            except ValueError as exc:
                raise HTTPException(502, '数据源返回了无效的 JSON 对象') from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"数据源 {connection['id']} 无法连接，请启动对应表单服务") from exc

    async def sources(self, include_archived=False):
        import asyncio
        connections = self.connections()
        results = await asyncio.gather(*(self.call(c, '/sources') for c in connections), return_exceptions=True)
        items, errors, seen = [], [], set()
        for connection, result in zip(connections, results):
            if isinstance(result, Exception):
                errors.append({'connection': connection['id'], 'detail': getattr(result, 'detail', str(result))})
                continue
            for source in result.get('sources', []):
                valid_id(source['id'])
                if source['id'] in seen:
                    raise HTTPException(409, '多个连接使用了相同的数据源标识：' + source['id'])
                seen.add(source['id'])
                if source.get('archived') and not include_archived:
                    continue
                items.append({**source, 'connection_id': connection['id']})
        return {'sources': items, 'errors': errors}

    async def resolve(self, source_id):
        valid_id(source_id)
        listing = await self.sources(include_archived=True)
        source = next((s for s in listing['sources'] if s['id'] == source_id), None)
        if source is None:
            raise HTTPException(502 if listing['errors'] else 404, '数据源不可用或不存在：' + source_id)
        if source.get('archived'):
            raise HTTPException(410, '数据源已删除，请在所属表单服务恢复')
        connection = next(c for c in self.connections() if c['id'] == source['connection_id'])
        return connection, source

    async def source_call(self, source_id, suffix, method='GET', body=None):
        connection, _ = await self.resolve(source_id)
        return await self.call(connection, '/sources/' + quote(source_id, safe='') + suffix, method, body)

    async def snapshot(self, source_id, project_id):
        data = await self.source_call(source_id, '/projects/' + quote(project_id, safe='') + '/snapshot')
        try:
            value = Snapshot.model_validate(data).model_dump()
            if value['source_id'] != source_id or value['project_id'] != project_id:
                raise ValueError('快照项目标识不匹配')
        except ValueError as exc:
            raise HTTPException(502, '数据源返回了无效的 v1 快照') from exc
        value['data']['_ppt_context_version'] = 1
        return value

hub = ProviderHub()

def draft_db():
    root = DATA_DIR / 'ppt_workbench'
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / 'workbench.sqlite3', timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS drafts(source_id TEXT,draft_key TEXT,revision INTEGER,payload TEXT,PRIMARY KEY(source_id,draft_key))')
    db.execute('CREATE TABLE IF NOT EXISTS migrations(name TEXT PRIMARY KEY)')
    legacy = DATA_DIR / 'form_platform' / 'platform.sqlite3'
    if legacy.exists() and not db.execute("SELECT 1 FROM migrations WHERE name='legacy-drafts'").fetchone():
        with sqlite3.connect(legacy) as old:
            if old.execute("SELECT 1 FROM sqlite_master WHERE name='drafts'").fetchone():
                db.executemany('INSERT OR IGNORE INTO drafts VALUES(?,?,?,?)', old.execute('SELECT app_id,draft_key,revision,payload FROM drafts').fetchall())
        db.execute("INSERT OR IGNORE INTO migrations VALUES('legacy-drafts')")
    db.commit()
    return db

def install_api(app):
    @app.middleware('http')
    async def source_scope(request: Request, call_next):
        source_id = request.query_params.get('app_id', 'dfm')
        token = scope.set(source_id)
        origin_token = request_origin.set(str(request.base_url).rstrip('/'))
        try:
            if request.url.path.startswith(('/api/template', '/api/schemes')):
                await hub.resolve(source_id)
                # Legacy callers are normalized by the owning form API.
                # Modern workbench snapshots already carry calculated context.
                if request.method == 'POST' and request.headers.get('content-type', '').startswith('application/json'):
                    payload = await request.json()
                    if isinstance(payload, dict) and 'data' in payload:
                        data = payload['data']
                        if data.get('_ppt_context_version') != 1:
                            definition = payload
                            if request.url.path.startswith('/api/schemes/') and request.url.path.endswith('/generate'):
                                from ..report.ppt.scheme_service import SchemeService, SchemeError
                                name = request.url.path[len('/api/schemes/'):-len('/generate')]
                                try:
                                    definition = SchemeService(DATA_DIR.parent, storage_root=storage_root(source_id)/'schemes').get(name)
                                except SchemeError as exc:
                                    raise HTTPException(404, '方案不存在') from exc
                            paths = set()
                            def collect(value):
                                if isinstance(value, dict):
                                    if isinstance(value.get('source'), str):
                                        paths.add(value['source'])
                                    for child in value.values():
                                        collect(child)
                                elif isinstance(value, list):
                                    for child in value:
                                        collect(child)
                                elif isinstance(value, str):
                                    paths.update(re.findall(r'\{([A-Za-z_][A-Za-z0-9_.\[\]-]*)\}', value))
                            collect(definition)
                            data = await hub.source_call(source_id, '/normalize', 'POST', {'data': data, 'binding_sources': sorted(paths)})
                        payload['data'] = {**ReportContext.model_validate(data).model_dump(), '_ppt_context_version': 1}
                        request._body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            response = await call_next(request)
            return response
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({'detail': '请求或数据源格式无效：' + str(exc)}, status_code=422)
        finally:
            scope.reset(token)
            request_origin.reset(origin_token)

    @app.get('/')
    def home():
        return RedirectResponse('/ppt')

    @app.get('/health')
    def health():
        return {'service': 'ppt-workbench', 'contract_version': '1.0'}

    @app.get('/api/ppt/sources')
    async def sources():
        return await hub.sources()

    @app.get('/api/ppt/sources/{source_id}')
    async def source(source_id: str):
        return (await hub.resolve(source_id))[1]

    @app.get('/api/ppt/sources/{source_id}/projects')
    async def projects(source_id: str):
        return await hub.source_call(source_id, '/projects')

    @app.get('/api/ppt/sources/{source_id}/projects/{project_id}/snapshot')
    async def snapshot_api(source_id: str, project_id: str):
        return await hub.snapshot(source_id, project_id)

    @app.get('/api/ppt/sources/{source_id}/drafts/{draft_key}')
    async def get_draft(source_id: str, draft_key: str):
        await hub.resolve(source_id)
        db = draft_db()
        try:
            row = db.execute('SELECT revision,payload FROM drafts WHERE source_id=? AND draft_key=?', (source_id,draft_key)).fetchone()
            return {'revision': row['revision'], 'payload': json.loads(row['payload'])} if row else {'revision': 0, 'payload': None}
        finally:
            db.close()

    @app.put('/api/ppt/sources/{source_id}/drafts/{draft_key}')
    async def save_draft(source_id: str, draft_key: str, body: dict):
        await hub.resolve(source_id)
        payload = json.dumps(body.get('payload'), ensure_ascii=False)
        if len(payload.encode()) > 4*1024*1024:
            raise HTTPException(413, '工作台草稿过大')
        db = draft_db()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT revision FROM drafts WHERE source_id=? AND draft_key=?', (source_id,draft_key)).fetchone()
                rev = row['revision'] if row else 0
                if body.get('revision') != rev:
                    raise HTTPException(409, '其他窗口已修改此工作台，请重新载入')
                db.execute('INSERT OR REPLACE INTO drafts VALUES(?,?,?,?)', (source_id,draft_key,rev+1,payload))
            return {'revision': rev+1}
        finally:
            db.close()
