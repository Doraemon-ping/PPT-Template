# -*- coding: utf-8 -*-
"""Pin down the DELETE /projects/{id}/photos/{slot} 500."""
import os
import shutil
import sqlite3
import sys
import traceback
from pathlib import Path

ROOT = Path.cwd()
LIVE = ROOT / 'data' / 'machining_dfm'
PROBE = ROOT / '_audit' / 'probe5'
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
OTHER = bytes.fromhex('89504e470d0a1a0a0000000d494844520000000100000001080200000'
                      '0907753de0000000c49444154789c6360000002000154a24f5f'
                      '0000000049454e44ae426082')


def q(sql, args=()):
    con = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


tok = client.post(API + '/auth/login', json={'role': 'admin', 'password': 'TP23456'}).json()['token']
H = {'Authorization': 'Bearer ' + tok}
PID = (lambda r: (r.get('project') or r)['id'])(client.post(
    API + '/projects', json={'name': '共享附件复现', 'state': {'G': {}, 'pr': [], 'is': []}}, headers=H).json())

print('CASE 1 — 同一张图上传到两个槽位，再删其中一个（内容寻址 → 同一个 asset）')
for slot in ('product', 'product2'):
    r = client.put(API + '/projects/%s/photos/%s' % (PID, slot), content=PNG,
                   headers={**H, 'Content-Type': 'image/png'})
    print('   PUT %-9s -> %s' % (slot, r.status_code))
ids = q('select product_photo_id, product2_photo_id from project_settings where project_id=?', (PID,))[0]
print('   product_photo_id =', ids[0])
print('   product2_photo_id=', ids[1], '  ← 同一个 asset id:', ids[0] == ids[1])
print('   assets 行数 =', q('select count(*) from assets')[0][0])
r = client.delete(API + '/projects/%s/photos/product2' % PID, headers=H)
print('   DELETE /photos/product2 -> %s %s' % (r.status_code, r.text[:400]))
print('   删后 settings:', q('select product_photo_id, product2_photo_id from project_settings where project_id=?', (PID,))[0])
print('   删后 assets 行数 =', q('select count(*) from assets')[0][0])

print('\nCASE 2 — 两个槽位用不同的图，再删其中一个（对照组）')
PID2 = (lambda r: (r.get('project') or r)['id'])(client.post(
    API + '/projects', json={'name': '不同附件', 'state': {'G': {}, 'pr': [], 'is': []}}, headers=H).json())
client.put(API + '/projects/%s/photos/product' % PID2, content=PNG, headers={**H, 'Content-Type': 'image/png'})
client.put(API + '/projects/%s/photos/product2' % PID2, content=OTHER, headers={**H, 'Content-Type': 'image/png'})
print('   ids:', q('select product_photo_id, product2_photo_id from project_settings where project_id=?', (PID2,))[0])
r = client.delete(API + '/projects/%s/photos/product2' % PID2, headers=H)
print('   DELETE /photos/product2 -> %s %s' % (r.status_code, r.text[:200]))

print('\nCASE 3 — 三连：同图三槽位，逐个删')
PID3 = (lambda r: (r.get('project') or r)['id'])(client.post(
    API + '/projects', json={'name': '三槽位', 'state': {'G': {}, 'pr': [], 'is': []}}, headers=H).json())
for slot in ('product', 'product2', 'blank_insp'):
    client.put(API + '/projects/%s/photos/%s' % (PID3, slot), content=PNG, headers={**H, 'Content-Type': 'image/png'})
for slot in ('product2', 'blank_insp', 'product'):
    r = client.delete(API + '/projects/%s/photos/%s' % (PID3, slot), headers=H)
    print('   DELETE %-11s -> %s %s' % (slot, r.status_code, r.text[:200]))

print('\n=== 直接调用 store，抓 traceback ===')
from app.machining_dfm import MachiningDFMStore                         # noqa: E402
from app.core.config import BASE_DIR, DATA_DIR                            # noqa: E402
store = MachiningDFMStore(DATA_DIR / 'machining_dfm', BASE_DIR / 'app/resources/machining_dfm_seed')
PID4 = (lambda r: (r.get('project') or r)['id'])(client.post(
    API + '/projects', json={'name': 'traceback', 'state': {'G': {}, 'pr': [], 'is': []}}, headers=H).json())
for slot in ('product', 'product2'):
    client.put(API + '/projects/%s/photos/%s' % (PID4, slot), content=PNG, headers={**H, 'Content-Type': 'image/png'})
try:
    store.clear_project_photo(PID4, 'product2')
    print('   clear_project_photo OK')
except Exception:
    traceback.print_exc()

print('\n=== 服务端日志里这一条 500 的原文 ===')
log = PROBE / 'data' / 'machining_dfm' / 'logs' / 'server.log'
if log.exists():
    text = log.read_text(encoding='utf-8', errors='replace').splitlines()
    for line in text[-40:]:
        if '500' in line or 'Error' in line or 'Traceback' in line or 'assets' in line:
            print('   ', line[:220])
