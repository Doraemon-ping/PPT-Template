# -*- coding: utf-8 -*-
"""对账：改造前的备份库里业务数组 vs 现在的表 —— 有没有搬家搬丢的。"""
import glob
import json
import os
import sqlite3

LIVE = 'data/machining_dfm/machining_dfm.sqlite3'


def summarize(path, label):
    try:
        con = sqlite3.connect('file:%s?mode=ro' % path.replace('\\', '/'), uri=True)
        con.row_factory = sqlite3.Row
        tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        out = {'label': label, 'size': os.path.getsize(path), 'tables': len(tabs)}
        if 'projects' in tabs:
            for r in con.execute('select id,name,revision,state_json from projects'):
                state = json.loads(r['state_json'] or '{}')
                arrays = {k: (len(v) if isinstance(v, list) else type(v).__name__)
                          for k, v in state.items() if isinstance(v, (list, dict))}
                out.setdefault('projects', []).append(
                    {'id': r['id'][:8], 'name': (r['name'] or '')[:28], 'rev': r['revision'], 'arrays': arrays})
        if 'revisions' in tabs:
            out['revisions'] = con.execute('select count(*) from revisions').fetchone()[0]
            mx = con.execute('select max(revision) from revisions').fetchone()[0]
            out['revision_max'] = mx
        if 'project_versions' in tabs:
            out['project_versions'] = [dict(x) for x in con.execute(
                'select kind, count(*) n from project_versions group by kind')]
        for t in ('project_processes', 'project_process_tools', 'project_issues',
                  'project_selections', 'project_changes', 'assets'):
            if t in tabs:
                out[t] = con.execute('select count(*) from "%s"' % t).fetchone()[0]
        if 'equipment' in tabs:
            out['equipment_legacy'] = con.execute('select count(*) from equipment').fetchone()[0]
        con.close()
        return out
    except Exception as exc:                       # noqa: BLE001
        return {'label': label, 'error': str(exc)[:120]}


print('===== 线上现状 =====')
print(json.dumps(summarize(LIVE, 'LIVE'), ensure_ascii=False, indent=1))

backups = sorted(glob.glob('data/machining_dfm/backups/**/*.sqlite3', recursive=True))
print('\n===== 备份（改造前/改造中）%d 个 =====' % len(backups))
for b in backups:
    s = summarize(b, os.path.basename(b))
    print('\n--', os.path.basename(b), ' (%d KB)' % (s.get('size', 0) // 1024))
    for p in s.get('projects', []):
        print('   项目 %s rev=%-3s 数组: %s' % (p['id'], p['rev'], p['arrays']))
    for k in ('revisions', 'revision_max', 'project_versions', 'project_processes', 'project_process_tools',
              'project_issues', 'project_selections', 'project_changes', 'assets', 'equipment_legacy'):
        if k in s:
            print('   %-20s %s' % (k, s[k]))
    if 'error' in s:
        print('   ERROR', s['error'])

print('\n===== 线上 project_versions 明细（kind 分布 + 是否有历史履历行）=====')
con = sqlite3.connect('file:%s?mode=ro' % LIVE, uri=True)
con.row_factory = sqlite3.Row
for r in con.execute('select project_id, kind, count(*) n, min(revision) mn, max(revision) mx from project_versions group by project_id, kind'):
    print('   ', dict(r))
print('   revisions 表是否还在:', con.execute("select count(*) from sqlite_master where name='revisions'").fetchone()[0])
print('   projects.state_json 现状:')
for r in con.execute('select id,name,length(state_json) slen,state_json from projects'):
    print('      %s %s len=%d %s' % (r['id'][:8], r['name'][:30], r['slen'], r['state_json'][:120]))
