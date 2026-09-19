# -*- coding: utf-8 -*-
"""Probe the machining service in-process against a COPY of the live data.

Never touches data/machining_dfm. Verifies:
  1. the dual-shape project problem (state_json vs tables)
  2. availability of every registered route (schema-driven bodies)
"""
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path.cwd()
LIVE = ROOT / 'data' / 'machining_dfm'
PROBE = ROOT / '_audit' / 'probe2'


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def snapshot_live():
    db = LIVE / 'machining_dfm.sqlite3'
    return {'size': db.stat().st_size, 'mtime': db.stat().st_mtime, 'sha256': sha(db)}


before = snapshot_live()
print('LIVE BEFORE:', before)

if PROBE.exists():
    shutil.rmtree(PROBE)
# NOTE: app/settings.py computes DATA_DIR = DFM_APP_ROOT / 'data', so the store root
# is <DFM_APP_ROOT>/data/machining_dfm.
(PROBE / 'data' / 'machining_dfm').mkdir(parents=True)
shutil.copy2(LIVE / 'machining_dfm.sqlite3', PROBE / 'data' / 'machining_dfm' / 'machining_dfm.sqlite3')
if (LIVE / 'assets').exists():
    shutil.copytree(LIVE / 'assets', PROBE / 'data' / 'machining_dfm' / 'assets')
if (LIVE / 'data').exists():
    shutil.copytree(LIVE / 'data', PROBE / 'data' / 'machining_dfm' / 'data')
os.environ['DFM_APP_ROOT'] = str(PROBE)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient          # noqa: E402
from app.services.machining import app             # noqa: E402

PCOPY = PROBE / 'data' / 'machining_dfm' / 'machining_dfm.sqlite3'


def ids():
    con = sqlite3.connect('file:%s?mode=ro' % PCOPY.as_posix(), uri=True)
    con.row_factory = sqlite3.Row
    out = {
        'projects': [dict(r) for r in con.execute(
            'select id,name,revision,length(state_json) slen,archived from projects')],
        'processes': [r[0] for r in con.execute('select id from project_processes')],
        'tools': [r[0] for r in con.execute('select id from project_process_tools')],
        'issues': [r[0] for r in con.execute('select id from project_issues')],
        'selections': [r[0] for r in con.execute('select id from project_selections')],
        'assets': [r[0] for r in con.execute('select id from assets')],
        'machines': [r[0] for r in con.execute('select id from machines')],
        'library_tools': [r[0] for r in con.execute('select id from tools limit 5')],
        'fixtures': [r[0] for r in con.execute('select id from fixtures limit 5')],
        'gauges': [r[0] for r in con.execute('select id from gauges limit 5')],
        'tool_groups': [r[0] for r in con.execute('select code from tool_groups')],
        'tool_categories': [r[0] for r in con.execute('select code from tool_categories limit 5')],
        'fixture_centers': [r[0] for r in con.execute('select name from fixture_centers')],
        'gauge_categories': [r[0] for r in con.execute('select name from gauge_categories')],
        'versions': [r[0] for r in con.execute("select id from project_versions where kind='save' limit 3")],
    }
    con.close()
    return out


IDS = ids()
print('\nPROJECTS IN COPY:')
for p in IDS['projects']:
    print('   ', p)
MAIN = IDS['projects'][0]['id']
COPY = IDS['projects'][1]['id'] if len(IDS['projects']) > 1 else MAIN

client = TestClient(app)

print('\n' + '=' * 70)
print('PART 1 — DUAL SHAPE (state_json vs tables)')
print('=' * 70)


def state_len(pid):
    r = client.get('/api/machining-dfm/projects/%s' % pid)
    s = r.json().get('state', {})
    return r.status_code, {k: (len(v) if isinstance(v, list) else v) for k, v in s.items()}


for pid, label in ((MAIN, 'MAIN (tables filled)'), (COPY, 'COPY (name ends _副本)')):
    code, shape = state_len(pid)
    prows = client.get('/api/machining-dfm/projects/%s/processes' % pid)
    irows = client.get('/api/machining-dfm/projects/%s/issues' % pid)
    print('\n-- %s  %s' % (label, pid))
    print('   GET /projects/{id}          -> %s  state arrays: %s' % (code, shape))
    print('   GET /projects/{id}/processes-> %s  rows=%s' % (
        prows.status_code, len(prows.json().get('processes', [])) if prows.status_code == 200 else prows.text[:80]))
    print('   GET /projects/{id}/issues   -> %s  rows=%s' % (
        irows.status_code, len(irows.json().get('issues', [])) if irows.status_code == 200 else irows.text[:80]))
    print('   read model flags: process_table=%s issue_table=%s' % (
        client.get('/api/machining-dfm/projects/%s' % pid).json().get('process_table'),
        client.get('/api/machining-dfm/projects/%s' % pid).json().get('issue_table')))

print('\n-- what the FE row-level editor does on the COPY (0 table rows, 2 legacy processes):')
dup = client.post('/api/machining-dfm/projects/%s/processes' % COPY,
                  json={'nm': '探针新增工序', 'mc': 1},
                  headers={'Authorization': 'Bearer ' + (os.environ.get('PROBE_TOKEN') or '')})
print('   POST /projects/{copy}/processes -> %s %s' % (dup.status_code, str(dup.text)[:120]))
code, shape = state_len(COPY)
prows = client.get('/api/machining-dfm/projects/%s/processes' % COPY)
print('   after that write: GET /projects/{copy}   -> %s state.pr=%s' % (code, shape.get('pr')))
print('   after that write: GET /projects/{copy}/processes -> %s rows=%s' % (
    prows.status_code, len(prows.json().get('processes', []))))

print('\n-- POST /projects (新建/另存为) on the copy of live data:')
newp = client.post('/api/machining-dfm/projects', json={'name': '探针-新建项目', 'state': {'G': {'part': 'X'}, 'pr': [{'nm': 'OP10', 'tl': [{'id': 'T01', 'tp': 'D10'}]}], 'is': []}})
print('   -> %s %s' % (newp.status_code, str(newp.text)[:200]))
if newp.status_code in (200, 201):
    payload = newp.json()
    nid = (payload.get('project') or payload)['id']
    con = sqlite3.connect('file:%s?mode=ro' % PCOPY.as_posix(), uri=True)
    srow = con.execute('select length(state_json) from projects where id=?', (nid,)).fetchone()[0]
    npr = con.execute('select count(*) from project_processes where project_id=?', (nid,)).fetchone()[0]
    ntl = con.execute('select count(*) from project_process_tools where project_id=?', (nid,)).fetchone()[0]
    con.close()
    print('   new project: state_json=%d bytes, project_processes=%d rows, project_process_tools=%d rows' % (srow, npr, ntl))

print('\n' + '=' * 70)
print('PART 2 — ROUTE AVAILABILITY SWEEP (all 127 routes, copy data)')
print('=' * 70)

spec = app.openapi()
routes = json.load(open('_audit/routes.json', encoding='utf-8'))


def synth(schema, name='', depth=0):
    """Build a minimal valid body from an OpenAPI schema."""
    if not isinstance(schema, dict) or depth > 3:
        return None
    if 'anyOf' in schema or 'oneOf' in schema:
        for opt in schema['anyOf'] + schema.get('oneOf', []):
            if opt.get('type') != 'null':
                return synth(opt, name, depth + 1)
    t = schema.get('type')
    if t == 'object' or 'properties' in schema:
        req = schema.get('required', [])
        out = {}
        for key, sub in (schema.get('properties') or {}).items():
            if key not in req:
                continue
            out[key] = synth(sub, key, depth + 1)
        return out
    if t == 'array':
        return []
    if t == 'integer':
        return 1
    if t == 'number':
        return 1.0
    if t == 'boolean':
        return False
    if t == 'string':
        low = name.lower()
        if low in ('by', 'operator'):
            return 'probe'
        if 'reason' in low:
            return '探针'
        if low in ('id', 'project_id', 'process_id', 'tool_id', 'issue_id', 'machine_id', 'row_id'):
            return None
        if 'name' in low:
            return '探针'
        return 'probe'
    return None


def fill(path, params):
    p = path
    for key in list(params):
        p = p.replace('{%s}' % key, str(params[key]))
    return p


def param_value(name, spec_):
    if name in ('project_id',):
        return MAIN
    if name in ('process_id',):
        return IDS['processes'][0] if IDS['processes'] else 'x'
    if name in ('tool_id', 'row_id'):
        return 'x'
    if name == 'issue_id':
        return IDS['issues'][0] if IDS['issues'] else 'x'
    if name == 'machine_id':
        return IDS['machines'][0]
    if name == 'asset_id':
        return IDS['assets'][0]
    if name == 'code':
        return IDS['tool_groups'][0]
    if name == 'item':
        return IDS['fixture_centers'][0]
    if name == 'kind':
        return 'fixture'
    if name == 'slot':
        return 'pI'
    if name == 'table':
        return 'machines'
    if name == 'record_id':
        return 'x'
    if name == 'source_id':
        return 'machining-dfm'
    return 'x'


results = []
for r in sorted(routes, key=lambda x: x['path']):
    path = r['path']
    op = spec.get('paths', {}).get(path, {})
    for method in r['methods']:
        if path in ('/docs', '/redoc', '/openapi.json', '/docs/oauth2-redirect', '/static'):
            continue
        info = op.get(method.lower(), {})
        params = {p['name']: param_value(p['name'], p) for p in info.get('parameters', []) if p.get('in') == 'path'}
        url = fill(path, params)
        body = None
        if method in ('POST', 'PUT', 'PATCH'):
            schema = ((info.get('requestBody') or {}).get('content') or {}).get('application/json', {}).get('schema')
            body = synth(schema) if schema else None
            if isinstance(body, dict):
                for k, v in list(body.items()):
                    if v is None and k in ('project_id',):
                        body[k] = MAIN
                    if v is None and k.endswith('_id'):
                        body[k] = IDS['library_tools'][0]
        try:
            resp = client.request(method, url, json=body) if body is not None else client.request(method, url)
            code, text = resp.status_code, resp.text[:120].replace('\n', ' ')
        except Exception as exc:                      # noqa: BLE001
            code, text = 'EXC', '%s: %s' % (type(exc).__name__, exc)[:120]
        results.append((method, url, code, text))
        flag = 'OK ' if isinstance(code, int) and 200 <= code < 300 else ('!! ' if code == 'EXC' or (isinstance(code, int) and code >= 500) else '   ')
        print('%s%-6s %-72s %-4s %s' % (flag, method, url, code, text[:90]))

print('\nSUMMARY OF SWEEP')
import collections
print(collections.Counter(c for _, _, c, _ in results))
print('\n5xx / exceptions:')
for m, u, c, t in results:
    if c == 'EXC' or (isinstance(c, int) and c >= 500):
        print('  !!', m, u, c, t)

after = snapshot_live()
print('\nLIVE AFTER :', after)
print('LIVE UNCHANGED:', before == after)
json.dump([{'method': m, 'url': u, 'status': c, 'body': t} for m, u, c, t in results],
          open('_audit/sweep_results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
