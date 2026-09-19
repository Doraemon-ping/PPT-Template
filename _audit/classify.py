# -*- coding: utf-8 -*-
"""Final API classification for the machining branch.

Base = machine match from usage_match.py (usage_raw.json) + manual corrections that the
generic matcher cannot see (documented per route). Prints the final table + the
'no frontend caller' list.
"""
import json
import os
import re
from pathlib import Path

routes = json.load(open('_audit/routes.json', encoding='utf-8'))
raw = json.load(open('_audit/usage_raw.json', encoding='utf-8'))


def bucket(p):
    p = p.replace('\\', '/').lstrip('./')
    if p.startswith('static/machining_dfm'):
        return 'FE'
    if p.startswith('tests/'):
        return 'TESTS'
    if p.startswith('tools/'):
        return 'TOOLS'
    if p.endswith('.md') or p.startswith('docs/'):
        return 'DOCS'
    if p.startswith('app/'):
        return 'APP'
    return 'OTHER'


# ---------------------------------------------------------------- manual corrections
# Each entry: (methods, path) -> (forced_frontend: bool, evidence, reason)
CORR = {}


def corr(path, methods, is_fe, ev, why):
    CORR[(methods, path)] = (is_fe, ev, why)


FE_LIB = 'static/machining_dfm/library_pages.js:78/259/297 + fixtures.js:17 + gauges.js:18'
for m, p in (('GET', '/api/machining-dfm/fixtures'), ('POST', '/api/machining-dfm/fixtures'),
             ('PATCH', '/api/machining-dfm/fixtures/{row_id}'), ('DELETE', '/api/machining-dfm/fixtures/{row_id}'),
             ('PUT', '/api/machining-dfm/fixtures/{row_id}/photo'), ('DELETE', '/api/machining-dfm/fixtures/{row_id}/photo'),
             ('GET', '/api/machining-dfm/gauges'), ('POST', '/api/machining-dfm/gauges'),
             ('PATCH', '/api/machining-dfm/gauges/{row_id}'), ('DELETE', '/api/machining-dfm/gauges/{row_id}'),
             ('PUT', '/api/machining-dfm/gauges/{row_id}/photo'), ('DELETE', '/api/machining-dfm/gauges/{row_id}/photo'),
             ('GET', '/api/machining-dfm/fixture-centers'), ('POST', '/api/machining-dfm/fixture-centers'),
             ('PATCH', '/api/machining-dfm/fixture-centers/{item}'), ('DELETE', '/api/machining-dfm/fixture-centers/{item}'),
             ('GET', '/api/machining-dfm/gauge-categories'), ('POST', '/api/machining-dfm/gauge-categories'),
             ('PATCH', '/api/machining-dfm/gauge-categories/{item}'), ('DELETE', '/api/machining-dfm/gauge-categories/{item}')):
    corr(p, m, True, FE_LIB, '库页面用 cfg.endpoint/cfg.dictionary 拼路径，matcher 看不到')

for m, p in (('PUT', '/api/machining-dfm/machines/{machine_id}/photo'), ('DELETE', '/api/machining-dfm/machines/{machine_id}/photo'),
             ('PUT', '/api/machining-dfm/machines/{machine_id}/doc'), ('DELETE', '/api/machining-dfm/machines/{machine_id}/doc')):
    corr(p, m, True, 'static/machining_dfm/machines.js:229/274/282（kind 变量拼路径）', 'kind 是变量，matcher 看不到字面量')

for m, seg in (('POST', 'processes'), ('POST', 'tools'), ('POST', 'issues'), ('POST', 'history')):
    corr('/api/machining-dfm/projects/{project_id}/%s/{rid}/restore' % seg, m, True,
         'static/machining_dfm/trash_page.js:27/257-261（ROW_SEGMENTS 拼路径）', '回收站面板按段名拼恢复路径')

corr('/api/machining-dfm/projects/{project_id}/processes/{process_id}/restore', 'POST', True,
     'static/machining_dfm/trash_page.js:27 ROW_SEGMENTS.process', '同上')
corr('/api/machining-dfm/projects/{project_id}/issues/{issue_id}/restore', 'POST', True,
     'static/machining_dfm/issue_page.js:177-178 + trash_page.js:27', '问题清单页与回收站都能恢复')
corr('/api/machining-dfm/projects/{project_id}/history/{record_id}/restore', 'POST', True,
     'static/machining_dfm/trash_page.js:27 ROW_SEGMENTS.history', '同上')
corr('/api/machining-dfm/projects/{project_id}/processes/{process_id}/tools/{tool_id}/restore', 'POST', True,
     'static/machining_dfm/trash_page.js:27 ROW_SEGMENTS.tool', '同上')
corr('/api/machining-dfm/projects/{project_id}/tools/{tool_id}/restore', 'POST', True,
     'static/machining_dfm/trash_page.js:27 ROW_SEGMENTS.tool', '同上')
corr('/api/machining-dfm/projects/{project_id}/issues/{issue_id}/photo/{slot}', 'PUT', True,
     'static/machining_dfm/issue_page.js:195-198（slot 变量）', 'slot 是变量')
corr('/api/machining-dfm/projects/{project_id}/issues/{issue_id}/photo/{slot}', 'DELETE', True,
     'static/machining_dfm/issue_page.js:195-198', 'slot 是变量')
corr('/api/machining-dfm/projects/{project_id}/photos/{slot}', 'PUT', True,
     'static/machining_dfm/project_info.js:195（slot 变量）', 'slot 是变量')
corr('/api/machining-dfm/projects/{project_id}/photos/{slot}', 'DELETE', True,
     'static/machining_dfm/project_info.js:239', 'slot 是变量')
corr('/api/machining-dfm/projects/{project_id}/selections/{kind}/{slot}', 'PUT', True,
     'static/machining_dfm/selection_page.js:98/120（kind/slot 变量）', 'kind/slot 是变量')
corr('/api/machining-dfm/projects/{project_id}/selections/{kind}/{slot}', 'DELETE', True,
     'static/machining_dfm/selection_page.js:98/120', 'kind/slot 是变量')
corr('/api/machining-dfm/projects/{project_id}/selections/{kind}/{slot}', 'PATCH', True,
     'static/machining_dfm/selection_page.js:98/120', 'kind/slot 是变量')
corr('/api/machining-dfm/projects/{project_id}/trash', 'GET', True, 'static/machining_dfm/trash_page.js:230', 'matcher 已命中')
corr('/api/integration/workbench-link', 'GET', True, 'static/machining_dfm/host.js:46', 'matcher 只看到 docs')

# Routes the matcher over-claimed (evidence is only a doc test fixture / wrong window)
OVERCLAIM = {
    ('GET', '/api/machining-dfm/bootstrap'): False,
}

final = []
for r in routes:
    key = (tuple(r['methods']), r['path'])
    hits = raw.get('%s %s' % (','.join(r['methods']), r['path']), [])
    buckets = {}
    for p, i, line in hits:
        buckets.setdefault(bucket(p), []).append((p, i, line))
    override = None
    for m in r['methods']:
        c = CORR.get((m, r['path']))
        if c and c[0]:
            override = c
    fe = bool(buckets.get('FE')) or bool(override)
    final.append({
        'methods': r['methods'], 'path': r['path'], 'endpoint': r['endpoint'],
        'fe': fe,
        'fe_ev': ([e for e in (buckets.get('FE') or [])][:2] or ([(override[1], 0, override[2])] if override else [])),
        'tests': buckets.get('TESTS', [])[:2], 'tools': buckets.get('TOOLS', [])[:2],
        'docs': buckets.get('DOCS', [])[:1], 'app': buckets.get('APP', [])[:1],
        'override_reason': override[2] if override else '',
    })

fe_used = [f for f in final if f['fe']]
no_fe = [f for f in final if not f['fe']]

print('总路由 %d；前端可达 %d；前端不可达 %d' % (len(final), len(fe_used), len(no_fe)))
print('\n=== 前端不可达的路由（按有无其它调用方分组）===')
groups = {'test-only': [], 'tools-only': [], 'docs-only': [], 'app-only': [], 'no-caller': []}
for f in no_fe:
    if f['tests']:
        groups['test-only'].append(f)
    elif f['tools']:
        groups['tools-only'].append(f)
    elif f['docs']:
        groups['docs-only'].append(f)
    elif f['app']:
        groups['app-only'].append(f)
    else:
        groups['no-caller'].append(f)
for g, items in groups.items():
    print('\n-- %s (%d)' % (g, len(items)))
    for f in items:
        ev = ''
        for k in ('tests', 'tools', 'docs', 'app'):
            if f[k]:
                ev = '%s:%s' % (f[k][0][0], f[k][0][1])
                break
        print('   %-6s %-74s %s' % (','.join(f['methods']), f['path'], ev))

json.dump({'total': len(final), 'fe_used': len(fe_used), 'no_fe': len(no_fe),
           'no_fe_rows': no_fe, 'groups': {k: len(v) for k, v in groups.items()}},
          open('_audit/api_classification.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
