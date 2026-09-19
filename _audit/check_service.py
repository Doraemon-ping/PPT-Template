# -*- coding: utf-8 -*-
"""重启后按真实 HTTP 打一遍：确认新代码已生效、服务可用（只读 + 一个假 id 的鉴权探测）。"""
import json
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:8002'


def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, data, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def brief(raw: bytes) -> str:
    return raw[:60].decode('utf-8', 'replace')


print('== 1. 基本可用性 ==')
for method, path in (('GET', '/health'), ('GET', '/machining-dfm'),
                     ('GET', '/api/machining-dfm/projects?archived=false'),
                     ('GET', '/api/machining-dfm/config'),
                     ('GET', '/api/integration/services')):
    status, _ = call(method, path)
    print('   %-4s %-48s -> %s' % (method, path, status))

print('\n== 2. 本次修复是否已生效（新代码才有的 401）==')
status, body = call('GET', '/api/logs/tail')
print('   GET  /api/logs/tail                       无 token -> %s %s' % (status, brief(body)))
status_dl, _ = call('GET', '/api/logs/download')
print('   GET  /api/logs/download                   无 token -> %s' % status_dl)
status_ar, body_ar = call('POST', '/api/machining-dfm/projects/__nope__/archive?archived=true', body={})
print('   POST .../projects/__nope__/archive        无 token -> %s %s' % (status_ar, brief(body_ar)))

login_status, raw = call('POST', '/api/machining-dfm/auth/login', body={'role': 'admin', 'password': 'TP23456'})
token = json.loads(raw)['token']
print('   管理员登录 -> %s' % login_status)
status, _ = call('GET', '/api/logs/tail', token=token)
print('   GET  /api/logs/tail                       带 admin token -> %s' % status)
status, body = call('POST', '/api/machining-dfm/projects/__nope__/archive?archived=true', token=token, body={})
print('   POST .../projects/__nope__/archive        带 admin token -> %s（假 id，必须是 404）%s'
      % (status, brief(body)))

print('\n== 3. 线上数据与读模型 ==')
status, raw = call('GET', '/api/machining-dfm/projects?archived=false', token=token)
print('   项目列表 -> %s' % status)
for item in json.loads(raw)['projects']:
    print('      - %s rev=%s %s' % (item['id'][:8], item['revision'], str(item.get('name', ''))[:34]))
status, raw = call('GET', '/api/machining-dfm/projects/b1f786630dc24006a9839f3a7f8fa3f1', token=token)
print('   主项目读模型 -> %s（%d 字节）' % (status, len(raw)))
