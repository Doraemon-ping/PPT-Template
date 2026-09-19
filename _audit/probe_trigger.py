# -*- coding: utf-8 -*-
"""Exact trigger matrix for the shared-asset FK 500 on photo delete."""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path.cwd()
LIVE = ROOT / 'data' / 'machining_dfm'
PROBE = ROOT / '_audit' / 'probe6'
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
client = TestClient(app, raise_server_exceptions=False)
PNG = bytes.fromhex('89504e470d0a1a0a0000000d494844520000000100000001080600000'
                    '01f15c4890000000a49444154789c6300010000050001'
                    '0d0a2db40000000049454e44ae426082')
PNG2 = bytes.fromhex('89504e470d0a1a0a0000000d494844520000000100000001080200000'
                     '0907753de0000000c49444154789c6360000002000154a24f5f'
                     '0000000049454e44ae426082')
COLS = ('product_photo_id', 'product2_photo_id', 'blank_insp_photo_id', 'final_insp_photo_id')


def q(sql, args=()):
    con = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


tok = client.post(API + '/auth/login', json={'role': 'admin', 'password': 'TP23456'}).json()['token']
H = {'Authorization': 'Bearer ' + tok}


def new_project(name):
    r = client.post(API + '/projects', json={'name': name, 'state': {'G': {}, 'pr': [], 'is': []}}, headers=H)
    return (r.json().get('project') or r.json())['id']


def slots(pid):
    row = q('select %s from project_settings where project_id=?' % ','.join(COLS), (pid,))
    return dict(zip(COLS, row[0])) if row else {}


def scenario(title, uploads, delete_slot):
    pid = new_project(title)
    for slot, data in uploads:
        r = client.put(API + '/projects/%s/photos/%s' % (pid, slot), content=data,
                       headers={**H, 'Content-Type': 'image/png'})
        assert r.status_code == 200, (slot, r.status_code, r.text[:200])
    before = slots(pid)
    n_assets = q('select count(*) from assets')[0][0]
    same = len({v for v in before.values() if v})
    print('\n-- %s' % title)
    print('   上传槽位 %-28s → 不同 asset 数=%d  %s' % ([s for s, _ in uploads], same,
                                                    {k[:9]: (v[:8] if v else None) for k, v in before.items() if v}))
    r = client.delete(API + '/projects/%s/photos/%s' % (pid, delete_slot), headers=H)
    after = slots(pid)
    print('   DELETE /photos/%-11s -> %s %s' % (delete_slot, r.status_code, r.text[:150]))
    print('   槽位值: ' + ', '.join('%s=%s' % (k[:9], (str(v)[:8] if v else '-')) for k, v in after.items()))
    print('   assets 行数 %d -> %d' % (n_assets, q('select count(*) from assets')[0][0]))


scenario('A：product 与 product2 同图，删 product2', [('product', PNG), ('product2', PNG)], 'product2')
scenario('B：product 与 product2 同图，删 product', [('product', PNG), ('product2', PNG)], 'product')
scenario('C：product/product2/blank_insp 同图，删 product2',
         [('product', PNG), ('product2', PNG), ('blank_insp', PNG)], 'product2')
scenario('D：product/product2 不同图，删 product2', [('product', PNG), ('product2', PNG2)], 'product2')
scenario('E：两个不同项目各用同图，删本项目 product',
         [('product', PNG)], 'product')

print('\n-- F：跨项目共用 + 同项目双槽位（完整触发条件）')
p1 = new_project('F1')
p2 = new_project('F2')
for pid in (p1, p2):
    for slot in ('product', 'product2'):
        client.put(API + '/projects/%s/photos/%s' % (pid, slot), content=PNG,
                   headers={**H, 'Content-Type': 'image/png'})
print('   p1 槽位:', {k[:9]: (v[:8] if v else '-') for k, v in slots(p1).items() if v})
print('   p2 槽位:', {k[:9]: (v[:8] if v else '-') for k, v in slots(p2).items() if v})
for pid, label in ((p1, 'p1'), (p2, 'p2')):
    r = client.delete(API + '/projects/%s/photos/product' % pid, headers=H)
    print('   DELETE %s/photos/product -> %s %s' % (label, r.status_code, r.text[:130]))
    print('      %s 槽位: %s' % (label, {k[:9]: (v[:8] if v else '-') for k, v in slots(pid).items() if v}))
