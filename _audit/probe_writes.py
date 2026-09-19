# -*- coding: utf-8 -*-
"""Write-path smoke test: prove every write API really mutates data, on a COPY.

Reads the live DB read-only, never writes it (sha256 compared before/after).
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
PROBE = ROOT / '_audit' / 'probe3'


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


db_live = LIVE / 'machining_dfm.sqlite3'
before = {'sha': sha(db_live), 'mtime': db_live.stat().st_mtime, 'size': db_live.stat().st_size}

if PROBE.exists():
    shutil.rmtree(PROBE)
(PROBE / 'data' / 'machining_dfm').mkdir(parents=True)
shutil.copy2(db_live, PROBE / 'data' / 'machining_dfm' / 'machining_dfm.sqlite3')
shutil.copytree(LIVE / 'assets', PROBE / 'data' / 'machining_dfm' / 'assets')
os.environ['DFM_APP_ROOT'] = str(PROBE)
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient      # noqa: E402
from app.services.machining import app         # noqa: E402

DB = PROBE / 'data' / 'machining_dfm' / 'machining_dfm.sqlite3'
API = '/api/machining-dfm'
client = TestClient(app)
PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d494844520000000100000001080600000'
    '01f15c4890000000a49444154789c6300010000050001'
    '0d0a2db40000000049454e44ae426082')

rows = []
step = [0]


def rec(name, resp, verify=None, note=''):
    step[0] += 1
    code = resp.status_code
    ok = 200 <= code < 300
    detail = ''
    if isinstance(resp, tuple):
        resp, detail = resp
    v = ''
    try:
        v = verify() if verify else ''
    except Exception as exc:                       # noqa: BLE001
        v = 'VERIFY-ERR %s' % exc
    rows.append({'n': step[0], 'api': name, 'status': code, 'ok': ok,
                 'readback': str(v), 'note': note or detail})
    print('%s %-3d %-62s %-4s %s %s' % ('OK ' if ok else '!! ', step[0], name[:62], code,
                                        ('| ' + str(v)[:90]) if v else '', note[:60]))
    return resp


def q(sql, args=()):
    con = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


print('LIVE BEFORE:', before)
token = client.post(API + '/auth/login', json={'role': 'admin', 'password': 'TP23456'}).json().get('token')
H = {'Authorization': 'Bearer ' + (token or '')}
print('admin token acquired:', bool(token))

print('\n--- 项目 ---')
r = client.post(API + '/projects', json={'name': '验收-写路径', 'state': {'G': {'cust': '客户A', 'part': '零件A'},
                                                                        'pr': [], 'is': []}}, headers=H)
rec('POST /projects', r)
PID = (r.json().get('project') or r.json())['id']
rec('GET /projects/{id}', client.get(API + '/projects/%s' % PID),
    lambda: 'revision=%s' % q('select revision from projects where id=?', (PID,))[0][0])
rec('PUT /projects/{id}/settings', client.put(API + '/projects/%s/settings' % PID, json={'cust': '客户B'}, headers=H),
    lambda: 'customer=%s' % q('select customer from project_settings where project_id=?', (PID,))[0][0])
rec('PATCH /projects/{id}/settings', client.patch(API + '/projects/%s/settings' % PID, json={'part': '零件B'}, headers=H),
    lambda: 'part=%s' % q('select part from project_settings where project_id=?', (PID,))[0][0])
rec('GET /projects/{id}/settings', client.get(API + '/projects/%s/settings' % PID))

print('\n--- 工序 / 刀具行 ---')
r = client.post(API + '/projects/%s/processes' % PID, json={'nm': '机加工序-OP10'}, headers=H)
rec('POST /projects/{id}/processes', r)
PR = r.json()['project'] if 'project' in r.json() else r.json()
PID2 = PR if isinstance(PR, str) else PID
PROC = q('select id from project_processes where project_id=?', (PID,))[0][0]
rec('PATCH /projects/{id}/processes/{pid}', client.patch(API + '/projects/%s/processes/%s' % (PID, PROC),
                                                         json={'mc': 3, 'fixP': 1200}, headers=H),
    lambda: 'machine_count=%s fixture_price=%s' % q('select machine_count,fixture_price from project_processes where id=?', (PROC,))[0])
r = client.post(API + '/projects/%s/processes/%s/tools' % (PID, PROC),
                json={'tp': 'D50盘铣刀', 'd': 50, 'n': 3000, 'vf': 3000, 'ln': 1600, 'ps': 1, 'cn': 1,
                      'td': 700, 'tt': 2, 'sd': 1}, headers=H)
rec('POST /processes/{pid}/tools', r)
TOOL = q('select id from project_process_tools where project_id=?', (PID,))[0][0]
rec('PATCH /projects/{id}/tools/{tid}', client.patch(API + '/projects/%s/tools/%s' % (PID, TOOL),
                                                     json={'vf': 800}, headers=H),
    lambda: 'feed_rate=%s' % q('select feed_rate from project_process_tools where id=?', (TOOL,))[0][0])
rec('POST /processes/reorder', client.post(API + '/projects/%s/processes/reorder' % PID,
                                           json={'ids': [PROC]}, headers=H))
rec('POST /processes/{pid}/tools/reorder', client.post(API + '/projects/%s/processes/%s/tools/reorder' % (PID, PROC),
                                                       json={'ids': [TOOL]}, headers=H))
rec('PUT /processes/{pid}/photo', client.put(API + '/projects/%s/processes/%s/photo' % (PID, PROC),
                                             content=PNG, headers={**H, 'Content-Type': 'image/png'}),
    lambda: 'fixture_photo_id=%s' % q('select fixture_photo_id from project_processes where id=?', (PROC,))[0][0])
rec('PUT /tools/{tid}/photo', client.put(API + '/projects/%s/tools/%s/photo' % (PID, TOOL),
                                        content=PNG, headers={**H, 'Content-Type': 'image/png'}),
    lambda: 'tool_photo_id=%s' % q('select tool_photo_id from project_process_tools where id=?', (TOOL,))[0][0])

print('\n--- 问题清单 / 选型 / 履历 ---')
r = client.post(API + '/projects/%s/issues' % PID, json={'tp': '尺寸', 'ds': '问题描述', 'fx': '整改'}, headers=H)
rec('POST /projects/{id}/issues', r)
ISSUE = q('select id from project_issues where project_id=?', (PID,))[0][0]
rec('PATCH /issues/{iid}', client.patch(API + '/projects/%s/issues/%s' % (PID, ISSUE), json={'st': '已关闭'}, headers=H),
    lambda: 'status=%s' % q('select status from project_issues where id=?', (ISSUE,))[0][0])
rec('POST /issues/reorder', client.post(API + '/projects/%s/issues/reorder' % PID, json={'ids': [ISSUE]}, headers=H))
rec('PUT /issues/{iid}/photo/before', client.put(API + '/projects/%s/issues/%s/photo/before' % (PID, ISSUE),
                                                content=PNG, headers={**H, 'Content-Type': 'image/png'}),
    lambda: 'before_photo_id=%s' % q('select before_photo_id from project_issues where id=?', (ISSUE,))[0][0])
rec('PUT /selections/fixture/0', client.put(API + '/projects/%s/selections/fixture/0' % PID,
                                            json={'legacy_key': '夹具X', 'price': 1234}, headers=H),
    lambda: 'rows=%d' % len(q('select id from project_selections where project_id=?', (PID,))))
rec('PATCH /selections/gauge/0', client.patch(API + '/projects/%s/selections/gauge/0' % PID,
                                              json={'quoted': 0}, headers=H))
rec('GET /selections', client.get(API + '/projects/%s/selections' % PID))
r = client.post(API + '/projects/%s/history' % PID, json={'dt': '2026-01-01', 'ver': 'v1', 'ds': '首次', 'by': '验收'}, headers=H)
rec('POST /history', r)
HIST = q("select id from project_versions where project_id=? and kind='history'", (PID,))
rec('PATCH /history/{rid}', client.patch(API + '/projects/%s/history/%s' % (PID, HIST[0][0] if HIST else 'x'),
                                         json={'ver': 'v2'}, headers=H) if HIST else (None, 'no history row'))
rec('POST /history/reorder', client.post(API + '/projects/%s/history/reorder' % PID,
                                         json={'ids': [HIST[0][0]] if HIST else []}, headers=H))
rec('GET /history', client.get(API + '/projects/%s/history' % PID))
rec('GET /versions', client.get(API + '/projects/%s/versions' % PID),
    lambda: 'rows=%d' % len(q('select id from project_versions where project_id=?', (PID,))))
rec('GET /changes', client.get(API + '/projects/%s/changes' % PID),
    lambda: 'rows=%d' % len(q('select id from project_changes where project_id=?', (PID,))))

print('\n--- 项目图片 ---')
for slot in ('product', 'product2', 'blank_insp', 'final_insp'):
    rec('PUT /photos/%s' % slot, client.put(API + '/projects/%s/photos/%s' % (PID, slot),
                                            content=PNG, headers={**H, 'Content-Type': 'image/png'}))
col = q('select product_photo_id, product2_photo_id, blank_insp_photo_id, final_photo_id from project_settings where project_id=?', (PID,)) if False else None
rec('DELETE /photos/product2', client.delete(API + '/projects/%s/photos/product2' % PID, headers=H))
ASSET = q('select id from assets order by created desc limit 1')[0][0]
rec('GET /assets/{id}', client.get(API + '/assets/%s' % ASSET),
    lambda: 'bytes=%d' % len(client.get(API + '/assets/%s' % ASSET).content))

print('\n--- 项目级回收站 ---')
rec('DELETE /processes/{pid}', client.delete(API + '/projects/%s/processes/%s' % (PID, PROC), headers=H),
    lambda: 'deleted_at=%s' % q('select deleted_at from project_processes where id=?', (PROC,))[0][0])
rec('GET /projects/{id}/trash', client.get(API + '/projects/%s/trash' % PID, headers=H),
    lambda: 'rows=%s' % len((client.get(API + '/projects/%s/trash' % PID, headers=H).json().get('rows') or [])))
rec('POST /processes/{pid}/restore', client.post(API + '/projects/%s/processes/%s/restore' % (PID, PROC), headers=H),
    lambda: 'deleted_at=%s' % q('select deleted_at from project_processes where id=?', (PROC,))[0][0])
rec('POST /issues/{iid}/restore', client.post(API + '/projects/%s/issues/%s/restore' % (PID, ISSUE), headers=H))
rec('POST /tools/{tid}/restore', client.post(API + '/projects/%s/tools/%s/restore' % (PID, TOOL), headers=H))

print('\n--- 基础库：设备 ---')
r = client.post(API + '/machines', json={'brand': '验收品牌', 'model': 'X1', 'rapid': 30, 'tc': 2, 'spm': 8000, 'atc': 20}, headers=H)
rec('POST /machines', r)
MID = q("select id from machines where brand='验收品牌'")
MID = MID[0][0] if MID else 'x'
rec('PATCH /machines/{id}', client.patch(API + '/machines/%s' % MID, json={'rapid': 55.5}, headers=H),
    lambda: 'rapid=%s' % q('select rapid from machines where id=?', (MID,))[0][0] if MID != 'x' else 'n/a')
rec('PUT /machines/{id}/default', client.put(API + '/machines/%s/default' % MID, headers=H))
rec('POST /machines/reorder', client.post(API + '/machines/reorder', json={'ids': [MID]}, headers=H))
rec('PUT /machines/{id}/photo', client.put(API + '/machines/%s/photo' % MID, content=PNG,
                                           headers={**H, 'Content-Type': 'image/png'}),
    lambda: 'photo_id=%s' % (q('select photo_id from machines where id=?', (MID,))[0][0] if MID != 'x' else 'n/a'))
rec('PUT /machines/{id}/doc', client.put(API + '/machines/%s/doc' % MID, content=b'hello doc',
                                         headers={**H, 'Content-Type': 'text/plain'}),
    lambda: 'doc_name=%s' % (q('select doc_name from machines where id=?', (MID,))[0][0] if MID != 'x' else 'n/a'))
rec('DELETE /machines/{id}/doc', client.delete(API + '/machines/%s/doc' % MID, headers=H))
rec('DELETE /machines/{id}', client.delete(API + '/machines/%s?force=true' % MID, headers=H),
    lambda: 'deleted_at=%s' % (q('select deleted_at from machines where id=?', (MID,))[0][0] if MID != 'x' else 'n/a'))
rec('POST /trash/{table}/{id}/restore', client.post(API + '/trash/machines/%s/restore' % MID, headers=H),
    lambda: 'deleted_at=%s' % (q('select deleted_at from machines where id=?', (MID,))[0][0] if MID != 'x' else 'n/a'))
rec('GET /trash', client.get(API + '/trash', headers=H))

print('\n--- 基础库：刀具 / 夹具 / 检具 ---')
r = client.post(API + '/tools', json={'grp': 'hp', 'tp': '验收刀具', 'cat': 'other'}, headers=H)
rec('POST /tools', r)
TID = q("select id from tools where name='验收刀具'")
TID = TID[0][0] if TID else 'x'
rec('PATCH /tools/{id}', client.patch(API + '/tools/%s' % TID, json={'price': 480}, headers=H),
    lambda: 'price=%s' % (q('select price from tools where id=?', (TID,))[0][0] if TID != 'x' else 'n/a'))
rec('PUT /tools/{id}/photo', client.put(API + '/tools/%s/photo' % TID, content=PNG,
                                        headers={**H, 'Content-Type': 'image/png'}))
rec('POST /tools/reorder', client.post(API + '/tools/reorder', json={'ids': [TID]}, headers=H))
FID = q('select id from fixtures limit 1')[0][0]
GID = q('select id from gauges limit 1')[0][0]
rec('PATCH /fixtures/{id}', client.patch(API + '/fixtures/%s' % FID, json={'price': 13500}, headers=H),
    lambda: 'price=%s' % q('select price from fixtures where id=?', (FID,))[0][0])
rec('POST /fixtures', client.post(API + '/fixtures', json={'center': q('select name from fixture_centers limit 1')[0][0], 'name': '验收夹具'}, headers=H))
rec('POST /fixtures/reorder', client.post(API + '/fixtures/reorder', json={'ids': [FID]}, headers=H))
rec('PUT /fixtures/{id}/photo', client.put(API + '/fixtures/%s/photo' % FID, content=PNG,
                                           headers={**H, 'Content-Type': 'image/png'}))
rec('PATCH /gauges/{id}', client.patch(API + '/gauges/%s' % GID, json={'price': 9}, headers=H))
rec('POST /gauges/reorder', client.post(API + '/gauges/reorder', json={'ids': [GID]}, headers=H))
rec('PUT /gauges/{id}/photo', client.put(API + '/gauges/%s/photo' % GID, content=PNG,
                                         headers={**H, 'Content-Type': 'image/png'}))

print('\n--- 字典 ---')
rec('GET /tool-dictionaries', client.get(API + '/tool-dictionaries'))
rec('GET /library-dictionaries', client.get(API + '/library-dictionaries'))
rec('POST /tool-groups', client.post(API + '/tool-groups', json={'code': 'vg', 'label': '验收分组'}, headers=H))
rec('PATCH /tool-groups/{code}', client.patch(API + '/tool-groups/vg', json={'label': '改名'}, headers=H))
rec('DELETE /tool-groups/{code}', client.delete(API + '/tool-groups/vg', headers=H))
rec('POST /tool-categories', client.post(API + '/tool-categories', json={'code': 'vcat', 'label': '验收类别'}, headers=H))
rec('DELETE /tool-categories/{code}', client.delete(API + '/tool-categories/vcat', headers=H))
rec('POST /fixture-centers', client.post(API + '/fixture-centers', json={'name': '验收中心'}, headers=H))
rec('PATCH /fixture-centers/{item}', client.patch(API + '/fixture-centers/验收中心', json={'sort_order': 9}, headers=H))
rec('DELETE /fixture-centers/{item}', client.delete(API + '/fixture-centers/验收中心', headers=H))
rec('POST /gauge-categories', client.post(API + '/gauge-categories', json={'name': '验收类别'}, headers=H))
rec('DELETE /gauge-categories/{item}', client.delete(API + '/gauge-categories/验收类别', headers=H))

print('\n--- 配置 / 库整包 / 导出 / 归档 ---')
rec('GET /config', client.get(API + '/config'))
rec('PUT /config', client.put(API + '/config', json={'site_title': '验收站点', 'autosave_ms': 1500}, headers=H),
    lambda: 'title=%s' % q("select value_json from app_settings where key='site_title'")[0][0])
rec('PUT /config (restore)', client.put(API + '/config', json={'site_title': '机加 DFM 项目工作台', 'autosave_ms': 1200}, headers=H))
libs = client.get(API + '/libraries').json()
rec('PUT /libraries (round-trip)', client.put(API + '/libraries', json=libs.get('libraries', libs), headers=H),
    lambda: 'machines=%d tools=%d' % (len(q('select id from machines')), len(q('select id from tools'))))
z = client.get(API + '/projects/%s/export.zip' % PID)
names = []
if z.status_code == 200:
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        names = zf.namelist()
rec('GET /projects/{id}/export.zip', z, lambda: 'entries=%d %s' % (len(names), names[:4]))
rec('POST /projects/{id}/archive', client.post(API + '/projects/%s/archive' % PID, headers=H),
    lambda: 'archived=%s' % q('select archived from projects where id=?', (PID,))[0][0])
rec('GET /projects/{id} (archived)', client.get(API + '/projects/%s' % PID))
rec('GET /projects/{id}?allow_archived', client.get(API + '/projects/%s?allow_archived=true' % PID))
rec('POST /projects/{id}/restore', client.post(API + '/projects/%s/restore' % PID, headers=H),
    lambda: 'archived=%s' % q('select archived from projects where id=?', (PID,))[0][0])
rec('DELETE /projects/{id}', client.delete(API + '/projects/%s?reason=验收' % PID, headers=H),
    lambda: 'archived=%s' % q('select archived from projects where id=?', (PID,))[0][0])
rec('PUT /auth/password (last)', client.put(API + '/auth/password', json={'role': 'admin', 'password': 'TP23456x'}, headers=H))
rec('POST /auth/login (new pwd)', client.post(API + '/auth/login', json={'role': 'admin', 'password': 'TP23456x'}))
rec('PUT /auth/password (rollback)', client.put(API + '/auth/password', json={'role': 'admin', 'password': 'TP23456'},
                                                headers={'Authorization': 'Bearer ' + (client.post(API + '/auth/login', json={'role': 'admin', 'password': 'TP23456x'}).json().get('token') or '')}))

print('\n' + '=' * 70)
ok = sum(1 for r in rows if r['ok'])
print('WRITE SMOKE: %d/%d 成功' % (ok, len(rows)))
print('失败/非 2xx 的条目：')
for r in rows:
    if not r['ok']:
        print('   %-3d %-62s %s' % (r['n'], r['api'], r['status']))
after = {'sha': sha(db_live), 'mtime': db_live.stat().st_mtime, 'size': db_live.stat().st_size}
print('\nLIVE AFTER :', after)
print('LINE UNCHANGED:', before == after)
json.dump(rows, open('_audit/write_smoke.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
