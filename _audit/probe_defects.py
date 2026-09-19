# -*- coding: utf-8 -*-
"""Reproduce the 4 non-2xx write results and capture exact error bodies / tracebacks."""
import io
import json
import os
import shutil
import sqlite3
import sys
import traceback
from pathlib import Path

ROOT = Path.cwd()
LIVE = ROOT / 'data' / 'machining_dfm'
PROBE = ROOT / '_audit' / 'probe4'

if PROBE.exists():
    shutil.rmtree(PROBE)
(PROBE / 'data' / 'machining_dfm').mkdir(parents=True)
shutil.copy2(LIVE / 'machining_dfm.sqlite3', PROBE / 'data' / 'machining_dfm' / 'machining_dfm.sqlite3')
shutil.copytree(LIVE / 'assets', PROBE / 'data' / 'machining_dfm' / 'assets')
os.environ['DFM_APP_ROOT'] = str(PROBE)
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient          # noqa: E402
from app.services.machining import app             # noqa: E402

DB = PROBE / 'data' / 'machining_dfm' / 'machining_dfm.sqlite3'
API = '/api/machining-dfm'
client = TestClient(app)
PNG = bytes.fromhex('89504e470d0a1a0a0000000d494844520000000100000001080600000'
                    '01f15c4890000000a49444154789c6300010000050001'
                    '0d0a2db40000000049454e44ae426082')


def q(sql, args=()):
    con = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


tok = client.post(API + '/auth/login', json={'role': 'admin', 'password': 'TP23456'}).json()['token']
H = {'Authorization': 'Bearer ' + tok}
r = client.post(API + '/projects', json={'name': '复现', 'state': {'G': {}, 'pr': [], 'is': []}}, headers=H)
PID = (r.json().get('project') or r.json())['id']

print('=== A. PATCH /issues/{id}  {"st": "已关闭"} ===')
iss = client.post(API + '/projects/%s/issues' % PID, json={'tp': '尺寸', 'ds': 'd'}, headers=H).json()
IID = (iss.get('project') or iss)['id'] if isinstance(iss, dict) and 'project' in iss else None
rows = q('select id,status from project_issues where project_id=?', (PID,))
IID = rows[0][0]
print('   current status in DB:', rows[0][1])
for body in ({'st': '已关闭'}, {'st': '已解决'}, {'status': '已关闭'}, {'st': '进行中'}, {'ds': '改描述'}):
    resp = client.patch(API + '/projects/%s/issues/%s' % (PID, IID), json=body, headers=H)
    print('   PATCH %-24s -> %s %s' % (json.dumps(body, ensure_ascii=False), resp.status_code, resp.text[:220]))

print('\n=== B. DELETE /projects/{id}/photos/{slot} ===')
for slot in ('product', 'product2', 'blank_insp', 'final_insp'):
    put = client.put(API + '/projects/%s/photos/%s' % (PID, slot), content=PNG,
                     headers={**H, 'Content-Type': 'image/png'})
    dele = client.delete(API + '/projects/%s/photos/%s' % (PID, slot), headers=H)
    print('   %-11s PUT -> %s   DELETE -> %s %s' % (slot, put.status_code, dele.status_code, dele.text[:300]))

print('\n=== B2. traceback for the failing photo delete ===')
client2 = TestClient(app, raise_server_exceptions=True)
try:
    r2 = client2.delete(API + '/projects/%s/photos/product' % PID, headers=H)
    print('   no exception, status', r2.status_code, r2.text[:200])
except Exception:
    traceback.print_exc()

print('\n=== C. reorder routes with the FULL id list vs a partial list ===')
mids = [x[0] for x in q('select id from machines order by sort_order,id')]
tids = [x[0] for x in q('select id from tools order by sort_order,id limit 3')]
allt = [x[0] for x in q('select id from tools order by sort_order,id')]
fids = [x[0] for x in q('select id from fixtures order by sort_order,id limit 3')]
gids = [x[0] for x in q('select id from gauges order by sort_order,id limit 3')]
cases = [
    ('machines/reorder partial', '/machines/reorder', mids[:1]),
    ('machines/reorder full', '/machines/reorder', mids),
    ('tools/reorder partial', '/tools/reorder', tids),
    ('fixtures/reorder partial', '/fixtures/reorder', fids),
    ('gauges/reorder partial', '/gauges/reorder', gids),
]
for label, path, ids in cases:
    resp = client.post(API + path, json={'ids': ids}, headers=H)
    print('   %-26s (n=%d) -> %s %s' % (label, len(ids), resp.status_code, resp.text[:220]))

print('\n=== D. GET /projects/{id}/trash 响应形状（删一道工序之后）===')
proc = client.post(API + '/projects/%s/processes' % PID, json={'nm': 'OP10'}, headers=H)
PROC = q('select id from project_processes where project_id=?', (PID,))[0][0]
client.delete(API + '/projects/%s/processes/%s' % (PID, PROC), headers=H)
tr = client.get(API + '/projects/%s/trash' % PID, headers=H)
print('   status', tr.status_code)
body = tr.json()
print('   top-level keys:', list(body.keys()))
for k, v in body.items():
    if isinstance(v, list):
        print('     %s: %d 条 %s' % (k, len(v), json.dumps(v[:1], ensure_ascii=False)[:220]))
    else:
        print('     %s = %s' % (k, json.dumps(v, ensure_ascii=False)[:160]))
print('   DB soft-deleted process rows:', q('select count(*) from project_processes where deleted_at is not null and project_id=?', (PID,))[0][0])
gt = client.get(API + '/trash', headers=H)
print('   GET /trash keys:', list(gt.json().keys()))
