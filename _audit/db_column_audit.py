# -*- coding: utf-8 -*-
"""Column-level deadness audit + JSON payload inspection (read-only)."""
import sqlite3, json, subprocess, os, re, collections

DB = 'data/machining_dfm/machining_dfm.sqlite3'
con = sqlite3.connect('file:' + DB + '?mode=ro', uri=True)
con.row_factory = sqlite3.Row

SRC = []
for root, dirs, fs in os.walk('app'):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', 'resources', 'assets')]
    SRC += [os.path.join(root, f) for f in fs if f.endswith('.py')]
for root, dirs, fs in os.walk('static/machining_dfm'):
    SRC += [os.path.join(root, f) for f in fs if f.endswith(('.js', '.html'))]
BLOB = {}
for p in SRC:
    try:
        BLOB[p] = open(p, encoding='utf-8', errors='replace').read()
    except Exception:
        pass

tables = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")
          if not r[0].startswith('sqlite_')]

print('### CONSTANT / UNUSED COLUMNS  (constant = every row equals the same value incl. NULL)')
dead = []
for t in tables:
    n = con.execute('select count(*) from "%s"' % t).fetchone()[0]
    for r in con.execute('PRAGMA table_info("%s")' % t):
        c, dflt = r[1], r[4]
        if n == 0:
            continue
        distinct = con.execute('select count(distinct "%s") from "%s"' % (c, t)).fetchone()[0]
        nul = con.execute('select count(*) from "%s" where "%s" is null' % (t, c)).fetchone()[0]
        val = con.execute('select "%s" from "%s" limit 1' % (c, t)).fetchone()[0]
        if distinct <= 1:
            # is the column name referenced in source at all?
            hits = sum(len(re.findall(r'\b' + re.escape(c) + r'\b', txt)) for txt in BLOB.values())
            flag = 'DEAD' if hits == 0 else ('CONST' if hits else 'DEAD')
            dead.append((t, c, flag, hits, nul, n, val))
            print('  %-6s %-26s %-24s distinct=%d null=%d/%d src_refs=%d firstval=%r'
                  % (flag, t, c, distinct, nul, n, hits, (str(val)[:30] if val is not None else None)))

print('\n### 2. project_settings.extra_json CONTENT')
for r in con.execute('select project_id, extra_json from project_settings'):
    print(' project', r['project_id'])
    print('  ', r['extra_json'][:1200])

print('\n### 3. project_changes.extra_json + label SAMPLES')
for r in con.execute('select entity, action, label, extra_json from project_changes order by sort_order limit 12'):
    print('  %-10s %-8s %-34s %s' % (r['entity'], r['action'], r['label'][:34], r['extra_json']))
print('  distinct extra_json key sets:',
      collections.Counter(tuple(sorted(json.loads(r[0]).keys())) for r in con.execute('select extra_json from project_changes')))

print('\n### 4. LOGICAL-DELETE COLUMN USAGE')
for t in tables:
    cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % t)]
    if 'deleted_at' not in cols:
        continue
    tot = con.execute('select count(*) from "%s"' % t).fetchone()[0]
    dl = con.execute('select count(*) from "%s" where deleted_at is not null' % t).fetchone()[0]
    print('  %-26s rows=%-5d soft-deleted=%d' % (t, tot, dl))

print('\n### 5. LIBRARY LINKAGE / SNAPSHOT POPULATION')
for col in ('tool_id', 'handle_id', 'accessory_id'):
    n = con.execute('select count(*) from project_process_tools where "%s" is not null' % col).fetchone()[0]
    print('  project_process_tools.%s not-null = %d / 25' % (col, n))
for col in ('machine_id', 'fixture_photo_id'):
    n = con.execute('select count(*) from project_processes where "%s" is not null' % col).fetchone()[0]
    print('  project_processes.%s not-null = %d / 2' % (col, n))
for col in ('fixture_id', 'gauge_id', 'fixture_center', 'gauge_category'):
    n = con.execute('select count(*) from project_selections where "%s" is not null' % col).fetchone()[0]
    print('  project_selections.%s not-null = %d / 9' % (col, n))
print('  project_selections by kind:',
      [dict(r) for r in con.execute('select kind, count(*) n, sum(quoted) q from project_selections group by kind')])
print('  project_process_tools rows with tool_group set:',
      con.execute("select count(*) from project_process_tools where tool_group<>''").fetchone()[0])
print('  tools by tool_group:', [dict(r) for r in con.execute('select tool_group, count(*) n from tools group by tool_group')])
print('  tools.category values not in tool_categories:',
      con.execute('select count(*) from tools t left join tool_categories c on c.code=t.category where c.code is null').fetchone()[0])
print('  fixtures.center not in fixture_centers:',
      con.execute('select count(*) from fixtures f left join fixture_centers c on c.name=f.center where c.name is null').fetchone()[0])
print('  gauges.category not in gauge_categories:',
      con.execute('select count(*) from gauges g left join gauge_categories c on c.name=g.category where c.name is null').fetchone()[0])

print('\n### 6. assets CONTENT')
for r in con.execute('select id, kind, mime, name, size, substr(sha256,1,12) sha, path from assets'):
    print('  %-10s %-14s %-24s %-8s %s' % (r['id'], r['kind'], r['mime'], r['size'], r['path']))
print('  assets by kind:', [dict(r) for r in con.execute('select kind, count(*) n from assets group by kind')])

print('\n### 7. app_settings KEYS')
for r in con.execute('select key, value_json from app_settings'):
    print('  %-34s %s' % (r['key'], r['value_json'][:80]))

print('\n### 8. project row revision vs table truth')
for r in con.execute('select id, name, revision, length(state_json) slen from projects'):
    pid = r['id']
    npr = con.execute('select count(*) from project_processes where project_id=?', (pid,)).fetchone()[0]
    ntool = con.execute('select count(*) from project_process_tools where project_id=?', (pid,)).fetchone()[0]
    nis = con.execute('select count(*) from project_issues where project_id=?', (pid,)).fetchone()[0]
    nver = con.execute('select count(*) from project_versions where project_id=?', (pid,)).fetchone()[0]
    nsel = con.execute('select count(*) from project_selections where project_id=?', (pid,)).fetchone()[0]
    nchg = con.execute('select count(*) from project_changes where project_id=?', (pid,)).fetchone()[0]
    print('  %s rev=%-3d state_json=%-5d processes=%d tools=%d issues=%d selections=%d versions=%d changes=%d'
          % (pid[:8], r['revision'], r['slen'], npr, ntool, nis, nsel, nver, nchg))
