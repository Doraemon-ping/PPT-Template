"""Form applications, HTML discovery and versioned server-side project storage."""
import hashlib
import json
import re
import sqlite3
import uuid
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from lxml import html
from pydantic import BaseModel, Field

FORM_SCOPE = ContextVar('form_scope', default='dfm')
KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,79}$')
RESERVED = {'__proto__', 'constructor', 'prototype'}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def clean_key(value, prefix='field'):
    text = re.sub(r'[^A-Za-z0-9_]', '_', value or '').strip('_')
    if not text or not text[0].isalpha():
        text = prefix + '_' + hashlib.sha256((value or prefix).encode()).hexdigest()[:8]
    return text[:70]


def validate_schema(schema):
    fields, tables = schema.get('fields', []), schema.get('tables', [])
    if not isinstance(fields, list) or not isinstance(tables, list) or len(fields) > 1000 or len(tables) > 100:
        raise HTTPException(422, '字段或明细表数量无效')
    if not fields and not tables:
        raise HTTPException(422, '至少保留一个字段或明细表；可以手动补充未识别的字段')
    seen = set()
    allowed = {'text', 'textarea', 'number', 'date', 'datetime-local', 'email', 'checkbox', 'select', 'image'}
    for entry in fields + tables:
        if not isinstance(entry, dict):
            raise HTTPException(422, '字段定义必须为对象')
        key = entry.get('key', '')
        if not isinstance(key, str) or not KEY.fullmatch(key) or key in seen or key in RESERVED:
            raise HTTPException(422, f'字段标识无效或重复：{key}')
        seen.add(key)
        if not str(entry.get('label', '')).strip():
            raise HTTPException(422, f'请填写字段名称：{key}')
    for entry in fields:
        if entry.get('type') not in allowed:
            raise HTTPException(422, f'不支持的字段类型：{entry.get("type")}')
    for table in tables:
        cols = table.get('columns', [])
        if not isinstance(cols, list) or not cols or len(cols) > 100 or any(not isinstance(c, dict) for c in cols):
            raise HTTPException(422, '明细表需要 1–100 列')
        keys = [c.get('key', '') for c in cols]
        if any(not isinstance(k, str) for k in keys) or len(keys) != len(set(keys)) or any(not KEY.fullmatch(k) or k in RESERVED for k in keys):
            raise HTTPException(422, '明细表列标识重复或无效')
        if any(c.get('type', 'text') not in allowed - {'image'} for c in cols):
            raise HTTPException(422, '明细表列类型无效')
        rows = table.get('default', [])
        if not isinstance(rows, list) or len(rows) > 500 or any(not isinstance(r, dict) for r in rows):
            raise HTTPException(422, '明细表默认数据必须为不超过 500 行的对象列表')
    for entry in fields + [c for t in tables for c in t['columns']]:
        options = entry.get('options', [])
        if not isinstance(options, list) or len(options) > 2000 or any(not isinstance(o, dict) or not isinstance(o.get('label'), str) or not isinstance(o.get('value'), (str, int, float, bool)) for o in options):
            raise HTTPException(422, '选择项必须包含名称和简单值')
    return {'fields': fields, 'tables': tables}


def discover_html(raw):
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise HTTPException(422, '请选择 8 MB 以内的 HTML 文件')
    decoded = None
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    if decoded is None:
        raise HTTPException(422, '无法识别文件编码，请另存为 UTF-8 HTML')
    root = html.fromstring(decoded)
    title = ' '.join(root.xpath('//title/text()')) or '导入的表单'
    warnings = []
    schema = {'fields': [], 'tables': []}
    labels = {n.get('for'): ' '.join(n.text_content().split()) for n in root.xpath('//label[@for]')}
    used = set()

    def unique(value, prefix):
        key = clean_key(value, prefix)
        base, i = key, 2
        while key in used:
            key = f'{base}_{i}'; i += 1
        used.add(key)
        return key

    def field(node, key, label=None):
        kind = node.get('type', 'text').lower() if node.tag == 'input' else node.tag
        if kind == 'file':
            kind = 'image'
            if 'image' not in node.get('accept', ''):
                warnings.append(f'「{label or key}」附件控件按图片槽位导入；其他附件需另行适配。')
        if kind not in {'text', 'textarea', 'number', 'date', 'datetime-local', 'email', 'checkbox', 'select', 'image'}:
            kind = 'text'
        wrapping = node.xpath('ancestor::label[1]')
        caption = label or labels.get(node.get('id')) or node.get('aria-label') or (wrapping[0].text_content().strip() if wrapping else '') or node.get('placeholder') or node.get('name') or node.get('id') or key
        groups = node.xpath('ancestor::fieldset[1]/legend')
        default = node.get('value', '')
        if kind == 'textarea': default = node.text_content()
        if kind == 'checkbox': default = node.get('checked') is not None
        result = {'key': key, 'label': caption[:160], 'type': kind, 'group': groups[0].text_content().strip() if groups else '基本信息', 'required': node.get('required') is not None, 'default': default, 'source': node.get('name') or node.get('id') or ''}
        if kind == 'select':
            result['options'] = [{'value': o.get('value', o.text_content()), 'label': o.text_content().strip()} for o in node.findall('.//option')]
            selected = node.xpath('.//option[@selected]') or node.findall('.//option')[:1]
            result['default'] = selected[0].get('value', selected[0].text_content()) if selected else ''
        return result

    table_controls = set()
    for n, table in enumerate(root.xpath('//table')):
        controls = table.xpath('.//input|.//select|.//textarea')
        headers = table.xpath('.//tr[1]/th|.//thead/tr[1]/td')
        if not headers or not controls:
            continue
        cols = []
        row_nodes = table.xpath('.//tbody/tr') or table.xpath('.//tr[position()>1]')
        for col, header in enumerate(headers):
            candidates = table.xpath(f'.//tr/td[{col+1}]//input|.//tr/td[{col+1}]//select|.//tr/td[{col+1}]//textarea')
            if not candidates:
                continue
            c = candidates[0]
            key = 'col_' + str(col + 1)
            item = field(c, key, header.text_content().strip() or f'第 {col+1} 列')
            if item['type'] == 'image':
                warnings.append('明细表内图片需在字段确认中单独添加图片槽位。')
                continue
            item['_index'] = col
            cols.append(item)
        if not cols:
            continue
        values = []
        for row in row_nodes:
            values.append({c['key']: (field(nodes[0], c['key'])['default'] if (nodes := row.xpath(f'./td[{c["_index"]+1}]//input|./td[{c["_index"]+1}]//select|./td[{c["_index"]+1}]//textarea')) else '') for c in cols})
        for c in cols: c.pop('_index', None)
        caption = table.xpath('./caption')
        schema['tables'].append({'key': unique(table.get('id') or f'table_{n+1}', 'table'), 'label': caption[0].text_content().strip() if caption else table.get('aria-label', f'明细表 {n+1}'), 'columns': cols, 'default': values[:500]})
        table_controls.update(controls)
    radios = {}
    for n, node in enumerate(root.xpath('//input|//select|//textarea')):
        if node in table_controls or node.get('type', '').lower() in {'hidden', 'submit', 'button', 'reset', 'password'}:
            continue
        name = node.get('name') or node.get('id') or f'field_{n+1}'
        if node.get('type') == 'radio':
            if name not in radios:
                item = field(node, unique(name, 'field'), labels.get(node.get('name')) or name)
                item.update(type='select', options=[], default='')
                radios[name] = item; schema['fields'].append(item)
            item = radios[name]
            item['options'].append({'value': node.get('value', ''), 'label': labels.get(node.get('id')) or node.get('value', '')})
            if node.get('checked') is not None: item['default'] = node.get('value', '')
        else:
            schema['fields'].append(field(node, unique(name, 'field')))
    from .html_literals import declared_fields
    declared = []
    for script in root.xpath('//script'):
        declared.extend(declared_fields(script.text or ''))
    for f in declared:
        source = str(f.get('k') or f.get('key'))
        if source in used: continue
        kind = {'images': 'image'}.get(f['type'], f['type'])
        if kind not in {'text','textarea','number','date','email','checkbox','select','image','table'}: continue
        key = unique(source, 'field')
        label = str(f.get('t') or f.get('label') or source)
        def convert(c):
            options = c.get('opt') or c.get('options') or []
            return {'key': clean_key(str(c.get('k') or c.get('key'))), 'label': str(c.get('t') or c.get('label') or c.get('k') or c.get('key')), 'type': {'images':'image'}.get(c.get('type','text'),c.get('type','text')), 'default': c.get('def', c.get('default','')), 'group':'识别的动态表单字段', 'options': [o if isinstance(o,dict) and 'label' in o and 'value' in o else {'label': str(o), 'value': str(o)} for o in options]}
        if kind == 'table':
            cols = [convert(c) for c in f.get('cols', f.get('columns', [])) if c.get('k') or c.get('key')]
            if cols: schema['tables'].append({'key':key,'label':label,'columns':cols,'default':f.get('rows',[])})
        else:
            item = convert(f); item['key']=key; schema['fields'].append(item)
    if declared:
        warnings.append('已静态读取脚本中的声明式字段配置。函数生成、变量拼接和远程加载的字段仍需核对；未执行脚本。')
    if root.xpath('//script'):
        warnings.append('检测到脚本：已识别静态表单控件；动态生成的控件、计算公式及联动逻辑需要检查或补充。导入页面不会执行原脚本。')
    if not schema['fields'] and not schema['tables']:
        warnings.append('未发现可填写控件。该 HTML 可能由 JavaScript 渲染；请手动添加字段，或导入渲染后包含 input/select/textarea 的 HTML。')
    return {'name': title[:100], 'schema': schema, 'warnings': list(dict.fromkeys(warnings))}


def catalog(schema):
    result = {'fields': [], 'tables': {}, 'images': {}, 'derived': {}, 'results': {}}
    for f in schema['fields']:
        entry = {'label': f['label'], 'module': '表单数据', 'group': f.get('group') or '基本信息'}
        if f['type'] == 'image': result['images'][f['key']] = {**entry, 'path': 'i.' + f['key'] + '[0]'}
        else: result['fields'].append({**entry, 'path': 'f.' + f['key']})
    for t in schema['tables']:
        result['tables'][t['key']] = {'label': t['label'], 'module': '明细数据', 'group': t['label'], 'columns': {c['key']: c['label'] for c in t['columns']}}
    return result


def defaults(schema):
    return {'f': {f['key']: f.get('default', '') for f in schema['fields'] if f['type'] != 'image'}, 'i': {f['key']: [] for f in schema['fields'] if f['type'] == 'image'}, 't': {t['key']: t.get('default', []) for t in schema['tables']}}


class PlatformStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'platform.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS apps(id TEXT PRIMARY KEY,name TEXT NOT NULL,schema_json TEXT NOT NULL,warnings_json TEXT NOT NULL,html BLOB,created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,app_id TEXT NOT NULL,name TEXT NOT NULL,revision INTEGER NOT NULL,data_json TEXT NOT NULL,updated TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS revisions(project_id TEXT NOT NULL,revision INTEGER NOT NULL,name TEXT NOT NULL,data_json TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(project_id,revision));
                CREATE TABLE IF NOT EXISTS drafts(app_id TEXT NOT NULL,draft_key TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(app_id,draft_key));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def application(self, app_id):
        if app_id == 'dfm': return {'id': 'dfm', 'name': '高压压铸 DFM', 'builtin': True}
        with self.connect() as db:
            r = db.execute('SELECT id,name,schema_json,warnings_json,created FROM apps WHERE id=?', (app_id,)).fetchone()
        if not r: raise HTTPException(404, '表单应用不存在')
        return {'id': r['id'], 'name': r['name'], 'schema': json.loads(r['schema_json']), 'warnings': json.loads(r['warnings_json']), 'created': r['created'], 'builtin': False}

    def project(self, app_id, project_id, revision=None):
        with self.connect() as db:
            row = db.execute('SELECT * FROM projects WHERE app_id=? AND id=?', (app_id, project_id)).fetchone()
            if not row: raise HTTPException(404, '当前表单应用中没有该项目')
            if revision is not None:
                row = db.execute('SELECT *,project_id AS id FROM revisions WHERE project_id=? AND revision=?', (project_id, revision)).fetchone()
                if not row: raise HTTPException(404, '版本不存在')
            payload = json.loads(row['data_json'])
            application = self.application(app_id)
            if application.get('schema', {}).get('runtime') and isinstance(payload.get('runtime'), dict):
                from .native_forms import normalize
                projected, _ = normalize(payload['runtime'], include_legacy_aliases=False)
                for key in ('f', 't', 'i'):
                    # The runtime snapshot is authoritative.  Returning an
                    # old persisted alias projection here would make a PPT
                    # placeholder appear bound without an explicit template
                    # mapping.
                    payload[key] = dict(projected[key])
                # Keep read compatibility for old clients that display the
                # former DFM names.  The template engine ignores these names
                # unless a saved scheme explicitly references one, and the
                # catalog never advertises them as universal fields.
                legacy, _ = normalize(payload['runtime'], include_legacy_aliases=True)
                for key in ('f', 't', 'i'):
                    payload[key].update({name: value for name, value in legacy[key].items() if name not in projected[key]})
            return {'id': project_id, 'name': row['name'], 'revision': row['revision'], 'data': payload}

    def save_project(self, app_id, name, data, project_id=None, revision=None):
        application = self.application(app_id)
        if application.get('schema', {}).get('runtime'):
            from .native_forms import normalize
            data, _ = normalize(data.get('runtime'), include_legacy_aliases=False)
        if not name.strip(): raise HTTPException(422, '请输入项目名称')
        if any(not isinstance(data.get(k, {}), dict) for k in ('f','t','i')):
            raise HTTPException(422, '项目数据 f/t/i 必须为对象')
        payload = json.dumps({k: data.get(k, {}) for k in (('f', 't', 'i', 'runtime') if application.get('schema', {}).get('runtime') else ('f', 't', 'i'))}, ensure_ascii=False, allow_nan=False)
        if len(payload.encode()) > 80 * 1024 * 1024: raise HTTPException(413, '项目数据超过 80 MB')
        now = stamp()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if project_id:
                old = db.execute('SELECT revision FROM projects WHERE id=? AND app_id=? AND archived=0', (project_id, app_id)).fetchone()
                if not old: raise HTTPException(404, '项目不存在或已归档')
                if revision != old['revision']: raise HTTPException(409, '该项目已被其他窗口更新。请重新载入，或另存为新项目，避免覆盖修改。')
                next_revision = revision + 1
                db.execute('UPDATE projects SET name=?,revision=?,data_json=?,updated=? WHERE id=?', (name, next_revision, payload, now, project_id))
            else:
                project_id, next_revision = uuid.uuid4().hex, 1
                db.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,0)', (project_id, app_id, name, next_revision, payload, now))
            db.execute('INSERT INTO revisions VALUES(?,?,?,?,?)', (project_id, next_revision, name, payload, now))
        return self.project(app_id, project_id)


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    schema_: dict = Field(alias='schema')
    warnings: list[str] = []


class ProjectSave(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    data: dict
    revision: int | None = None


def router_for(get_store, static_dir):
    router = APIRouter()

    @router.get('/api/form-apps')
    def list_apps():
        store = get_store()
        with store.connect() as db:
            items = [dict(r) for r in db.execute('SELECT id,name,created FROM apps ORDER BY created DESC')]
        return {'apps': [store.application('dfm')] + items}

    @router.post('/api/form-apps/discover')
    async def discover(file: UploadFile):
        if not (file.filename or '').lower().endswith(('.html', '.htm')): raise HTTPException(415, '请选择 HTML 文件')
        raw = await file.read(8 * 1024 * 1024 + 1)
        from .native_forms import describe
        native = describe(raw)
        result = discover_html(raw)
        result['native'] = native
        return result

    @router.post('/api/form-apps/import-native')
    async def import_native(file: UploadFile):
        from .native_forms import describe, decode_source
        if not (file.filename or '').lower().endswith(('.html', '.htm')):
            raise HTTPException(415, '请选择 HTML 文件')
        raw = await file.read(8*1024*1024+1)
        info = describe(raw)
        if not info['adapter']:
            raise HTTPException(422, '此 HTML 尚无原样数据桥接适配器，不能保证项目保存；请使用简单表单模式或添加适配器')
        schema = {'fields': [], 'tables': [], 'runtime': {'adapter':info['adapter']}}
        key = uuid.uuid4().hex
        store = get_store()
        with store.connect() as db:
            db.execute('INSERT INTO apps VALUES(?,?,?,?,?,?)', (key, (file.filename or info['name']).rsplit('.',1)[0][:100], json.dumps(schema), json.dumps(['原样运行模式：原脚本在隔离框架中运行，项目数据通过桥接保存。']), decode_source(raw), stamp()))
        return store.application(key)

    @router.get('/api/form-apps/{app_id}/runtime-source')
    def runtime_source(app_id: str):
        store = get_store()
        application = store.application(app_id)
        if not application.get('schema', {}).get('runtime'):
            raise HTTPException(404, '当前应用不是原样运行模式')
        with store.connect() as db:
            row = db.execute('SELECT html FROM apps WHERE id=?', (app_id,)).fetchone()
        return {'html': row['html'], 'adapter': application['schema']['runtime']['adapter']}

    @router.post('/api/form-apps')
    def create_app(req: ApplicationCreate):
        if not req.name.strip():
            raise HTTPException(422, '请填写表单应用名称')
        schema = validate_schema(req.schema_)
        key = uuid.uuid4().hex
        store = get_store()
        with store.connect() as db:
            db.execute('INSERT INTO apps VALUES(?,?,?,?,?,?)', (key, req.name.strip(), json.dumps(schema, ensure_ascii=False), json.dumps(req.warnings, ensure_ascii=False), None, stamp()))
        return store.application(key)

    @router.get('/api/form-apps/{app_id}')
    def get_app(app_id: str):
        return get_store().application(app_id)

    @router.get('/api/form-apps/{app_id}/catalog')
    def get_catalog(app_id: str, project_id: str | None = None):
        application = get_store().application(app_id)
        if app_id == 'dfm':
            source = (static_dir / 'dfm_catalog.js').read_text(encoding='utf-8')
            return json.loads(source[source.index('{'):source.rfind('}')+1])
        if application['schema'].get('runtime'):
            store = get_store()
            if project_id:
                snapshot = store.project(app_id, project_id)['data']
            else:
                with store.connect() as db:
                    row = db.execute('SELECT data_json FROM projects WHERE app_id=? AND archived=0 ORDER BY updated DESC LIMIT 1', (app_id,)).fetchone()
                snapshot = json.loads(row['data_json']) if row else None
            if snapshot:
                from .native_forms import normalize
                return normalize(snapshot.get('runtime'), include_legacy_aliases=False)[1]
        return catalog(application['schema'])

    @router.get('/api/form-apps/{app_id}/defaults')
    def get_defaults(app_id: str):
        application = get_store().application(app_id)
        if app_id == 'dfm':
            from .demo import demo_state
            return demo_state()
        return defaults(application['schema'])

    @router.get('/api/form-apps/{app_id}/projects')
    def list_projects(app_id: str, archived: bool = False):
        store = get_store(); store.application(app_id)
        with store.connect() as db:
            return {'projects': [dict(r) for r in db.execute('SELECT id,name,revision,updated,archived FROM projects WHERE app_id=? AND archived=? ORDER BY updated DESC', (app_id, int(archived)))]}

    @router.post('/api/form-apps/{app_id}/projects')
    def create_project(app_id: str, req: ProjectSave):
        return get_store().save_project(app_id, req.name, req.data)

    @router.get('/api/form-apps/{app_id}/drafts/{draft_key}')
    def get_draft(app_id: str, draft_key: str):
        store = get_store(); store.application(app_id)
        with store.connect() as db:
            row = db.execute('SELECT revision,payload FROM drafts WHERE app_id=? AND draft_key=?', (app_id,draft_key)).fetchone()
        return {'revision': row['revision'], 'payload': json.loads(row['payload'])} if row else {'revision': 0, 'payload': None}

    @router.put('/api/form-apps/{app_id}/drafts/{draft_key}')
    def save_draft(app_id: str, draft_key: str, body: dict):
        store = get_store(); store.application(app_id)
        payload = json.dumps(body.get('payload'), ensure_ascii=False)
        if len(payload) > 4*1024*1024: raise HTTPException(413, '工作台草稿过大，请保存方案')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM drafts WHERE app_id=? AND draft_key=?', (app_id,draft_key)).fetchone()
            revision = row['revision'] if row else 0
            if body.get('revision') != revision: raise HTTPException(409, '其他窗口已修改此工作台，请刷新载入或先另存为方案')
            db.execute('INSERT OR REPLACE INTO drafts VALUES(?,?,?,?)', (app_id,draft_key,revision+1,payload))
        return {'revision': revision+1}

    @router.get('/api/form-apps/{app_id}/projects/{project_id}')
    def get_project(app_id: str, project_id: str, response: Response, revision: int | None = None):
        # A project URL stays stable across revisions.  It must never be served
        # from browser/proxy cache or the PPT workbench can render an older
        # snapshot than the form that the user just saved.
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        return get_store().project(app_id, project_id, revision)

    @router.put('/api/form-apps/{app_id}/projects/{project_id}')
    def update_project(app_id: str, project_id: str, req: ProjectSave):
        return get_store().save_project(app_id, req.name, req.data, project_id, req.revision)

    @router.get('/api/form-apps/{app_id}/projects/{project_id}/versions')
    def versions(app_id: str, project_id: str):
        store = get_store(); store.project(app_id, project_id)
        with store.connect() as db:
            return {'versions': [dict(r) for r in db.execute('SELECT revision,name,created FROM revisions WHERE project_id=? ORDER BY revision DESC', (project_id,))]}

    @router.post('/api/form-apps/{app_id}/projects/{project_id}/archive')
    def archive(app_id: str, project_id: str, archived: bool = True):
        store = get_store(); store.project(app_id, project_id)
        with store.connect() as db:
            db.execute('UPDATE projects SET archived=? WHERE id=? AND app_id=?', (int(archived), project_id, app_id))
        return {'ok': True}

    @router.get('/api/form-apps/{app_id}/projects/{project_id}/export')
    def export(app_id: str, project_id: str):
        project = get_store().project(app_id, project_id)
        return Response(json.dumps(project, ensure_ascii=False), media_type='application/json', headers={'Content-Disposition': 'attachment; filename="project.json"'})

    return router
