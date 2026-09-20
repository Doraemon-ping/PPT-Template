# -*- coding: utf-8 -*-
"""Is the same-row multi-attachment FK bug present elsewhere (issues before/after, machines photo/doc)?"""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path.cwd()
LIVE = ROOT / 'data' / 'machining_dfm'
PROBE = ROOT / '_audit' / 'probe7'
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


def q(sql, args=()):
    con = sqlite3.connect('file:%s?mode=ro' % DB.as_posix(), uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


tok = client.post(API + '/auth/login', json={'role': 'admin', 'password': 'TP23456'}).json()['token']
H = {'Authorization': 'Bearer ' + tok}
pid = (lambda r: (r.get('project') or r)['id'])(client.post(
    API + '/projects', json={'name': '问题清单附件', 'state': {'G': {}, 'pr': [], 'is': []}}, headers=H).json())
r = client.post(API + '/projects/%s/issues' % pid, json={'tp': '尺寸', 'ds': 'd'}, headers=H)
print('POST /issues 返回体字节数 = %d（键：%s）' % (len(r.content), list(r.json().keys())[:8]))
iid = q('select id from project_issues where project_id=?', (pid,))[0][0]

print('\n行级写入的返回体大小（每次改一个格子都回整份读模型？）：')
t0 = q('select id from project_process_tools where project_id=(select id from projects where name=?)', ('问题清单附件',))
pr = client.post(API + '/projects/%s/processes' % pid, json={'nm': 'OP10'}, headers=H)
print('   POST /processes        -> %d bytes' % len(pr.content))
proc = q('select id from project_processes where project_id=?', (pid,))[0][0]
pt = client.patch(API + '/projects/%s/processes/%s' % (pid, proc), json={'mc': 3}, headers=H)
print('   PATCH /processes/{id}  -> %d bytes' % len(pt.content))
t = client.post(API + '/projects/%s/processes/%s/tools' % (pid, proc), json={'tp': 'D10', 'd': 10}, headers=H)
print('   POST .../tools         -> %d bytes' % len(t.content))
g = client.get(API + '/projects/%s' % pid)
print('   GET /projects/{id}     -> %d bytes' % len(g.content))
b = client.get(API + '/bootstrap')
print('   GET /bootstrap         -> %d bytes' % len(b.content))

print('问题清单 before/after 用同一张图：')
for slot in ('before', 'after'):
    r = client.put(API + '/projects/%s/issues/%s/photo/%s' % (pid, iid, slot), content=PNG,
                   headers={**H, 'Content-Type': 'image/png'})
    print('   PUT %-7s -> %s %s' % (slot, r.status_code, r.text[:120]))
print('   槽位:', q('select before_photo_id, after_photo_id from project_issues where id=?', (iid,))[0])
r = client.delete(API + '/projects/%s/issues/%s/photo/before' % (pid, iid), headers=H)
print('   DELETE before -> %s %s' % (r.status_code, r.text[:200]))
print('   槽位:', q('select before_photo_id, after_photo_id from project_issues where id=?', (iid,))[0])

print('\n设备 photo 与 doc 用同一份字节（kind 不同，预期不共用）：')
mid = q('select id from machines limit 1')[0][0]
for path, ctype in (('/machines/%s/photo' % mid, 'image/png'), ('/machines/%s/doc' % mid, 'text/plain')):
    r = client.put(API + path, content=PNG, headers={**H, 'Content-Type': ctype})
    print('   PUT %-28s -> %s' % (path, r.status_code))
print('   槽位:', q('select photo_id, doc_id from machines where id=?', (mid,))[0])
r = client.delete(API + '/machines/%s/photo' % mid, headers=H)
print('   DELETE photo -> %s %s' % (r.status_code, r.text[:150]))
r = client.delete(API + '/machines/%s/doc' % mid, headers=H)
print('   DELETE doc   -> %s %s' % (r.status_code, r.text[:150]))

print('\nassets 表上以 kind 去重的键（同一 kind 才会共用同一行）：')
print('   ', q('select kind, count(*) from assets group by kind'))
print('\n各附件列的 kind 定义：')
import re
# 2026-09 分层重构后路径：app/machining_project.py → app/domains/project.py
src = open('app/domains/project.py', encoding='utf-8').read()
for m in re.finditer(r'AttachmentSpec\(([^)]*)\)', src, re.S):
    print('   ', ' '.join(m.group(1).split())[:150])
# app/machining_issue.py → app/domains/issue.py
src2 = open('app/domains/issue.py', encoding='utf-8').read()
for m in re.finditer(r'AttachmentSpec\(([^)]*)\)', src2, re.S):
    print('   issue:', ' '.join(m.group(1).split())[:150])
