# -*- coding: utf-8 -*-
"""修完之后按线上那份库跑一遍：4 个修复点逐条验证（全程只动副本）。"""
import hashlib
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path.cwd()
LIVE = ROOT / 'data' / 'machining_dfm'
PROBE = ROOT / '_audit' / 'probe8'
if PROBE.exists():
    shutil.rmtree(PROBE)
(PROBE / 'data' / 'machining_dfm').mkdir(parents=True)
shutil.copy2(LIVE / 'machining_dfm.sqlite3', PROBE / 'data' / 'machining_dfm' / 'machining_dfm.sqlite3')
shutil.copytree(LIVE / 'assets', PROBE / 'data' / 'machining_dfm' / 'assets')
os.environ['DFM_APP_ROOT'] = str(PROBE)
sys.path.insert(0, str(ROOT))

DB = PROBE / 'data' / 'machining_dfm' / 'machining_dfm.sqlite3'
LIVE_DB = LIVE / 'machining_dfm.sqlite3'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


live_before = sha(LIVE_DB)

from fastapi.testclient import TestClient              # noqa: E402
from app.services.machining import app                 # noqa: E402   ← 真正在跑的那个 app

API = '/api/machining-dfm'
client = TestClient(app, raise_server_exceptions=False)
PNG = bytes.fromhex('89504e470d0a1a0a0000000d494844520000000100000001080600000'
                    '01f15c4890000000a49444154789c6300010000050001'
                    '0d0a2db40000000049454e44ae426082')
ok = []

print('== 1. 日志接口鉴权（app/services/machining.py 用真实 app）==')
for path in ('/api/logs/tail', '/api/logs/download'):
    r = client.get(path)
    print('   GET %-22s 无 token -> %s %s' % (path, r.status_code, str(r.json())[:40] if r.headers.get('content-type', '').startswith('application/json') else ''))
    ok.append(r.status_code == 401)
tok = client.post(API + '/auth/login', json={'role': 'admin', 'password': 'TP23456'}).json()['token']
H = {'Authorization': 'Bearer ' + tok}
r = client.get('/api/logs/tail', headers=H)
print('   GET /api/logs/tail      带 admin token -> %s' % r.status_code)
ok.append(r.status_code == 200)

print('\n== 2. 旧归档入口鉴权 ==')
pid = (lambda r: r.get('project', r)['id'])(client.post(API + '/projects', headers=H,
        json={'name': '验收-归档', 'state': {'G': {}, 'pr': [], 'is': []}}).json())
r = client.post(API + '/projects/%s/archive?archived=true' % pid, json={})
print('   无 token -> %s %s' % (r.status_code, r.text[:60]))
ok.append(r.status_code == 401)
r = client.post(API + '/projects/%s/archive?archived=true' % pid, json={}, headers=H)
print('   带 admin token -> %s archived=%s' % (r.status_code, r.json().get('archived')))
ok.append(r.status_code == 200 and r.json().get('archived') is True)
client.post(API + '/projects/%s/archive?archived=false' % pid, json={}, headers=H)

print('\n== 3. 双槽位共用一张图再清空（原来的 500）==')
pid2 = (lambda r: r.get('project', r)['id'])(client.post(API + '/projects', headers=H,
         json={'name': '验收-共用图', 'state': {'G': {}, 'pr': [], 'is': []}}).json())
for slot in ('product', 'product2'):
    assert client.put(API + '/projects/%s/photos/%s' % (pid2, slot), content=PNG,
                      headers={**H, 'Content-Type': 'image/png'}).status_code == 200


def slots(p):
    con = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True)
    try:
        return con.execute('select product_photo_id, product2_photo_id from project_settings where project_id=?', (p,)).fetchone()
    finally:
        con.close()


n_before = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True).execute('select count(*) from assets').fetchone()[0]
before = slots(pid2)
r = client.delete(API + '/projects/%s/photos/product2' % pid2, headers=H)
after = slots(pid2)
n_after = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True).execute('select count(*) from assets').fetchone()[0]
print('   两槽位同图: %s == %s' % (before[0][:8] if before[0] else None, before[1][:8] if before[1] else None))
print('   DELETE /photos/product2 -> %s ; 兄弟槽位仍在=%s ; assets %d->%d'
      % (r.status_code, bool(after[0]), n_before, n_after))
ok.append(r.status_code == 200 and bool(after[0]) and n_after == n_before)

print('\n== 4. 老索引清理（副本库里本来就有 ..._sort）==')


def indexes():
    con = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True)
    try:
        return sorted(r[0] for r in con.execute(
            "select name from sqlite_master where type='index' and tbl_name='machines'"))
    finally:
        con.close()


print('   开库后 machines 索引:')
for name in indexes():
    print('      -', name)
ok.append('idx_machining_dfm_machines_sort' not in indexes())

print('\n== 5. 422 文案 ==')
iid = None
r = client.post(API + '/projects/%s/issues' % pid2, json={'tp': '尺寸', 'ds': 'd'}, headers=H)
con = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True)
iid = con.execute('select id from project_issues where project_id=?', (pid2,)).fetchone()[0]
r = client.patch(API + '/projects/%s/issues/%s' % (pid2, iid), json={'st': '已关闭'}, headers=H)
print('   PATCH 非法状态 -> %s %s' % (r.status_code, r.json().get('detail')))
ok.append(r.status_code == 422 and '（进行中）' not in str(r.json().get('detail')))
r = client.patch(API + '/projects/%s/issues/%s' % (pid2, iid), json={'status': '进行中'}, headers=H)
print('   PATCH 合法状态（表列名）-> %s' % r.status_code)
ok.append(r.status_code == 200)

print('\n== 结论 ==')
print('   5 组检查：%s' % ('全部通过' if all(ok) else '有未通过项 %s' % ok))
print('   线上库 sha256 前 %s -> 后 %s（必须一致）' % (live_before, sha(LIVE_DB)))
print('   %s' % ('线上数据未被改动' if live_before == sha(LIVE_DB) else '！！线上库被改动了'))
