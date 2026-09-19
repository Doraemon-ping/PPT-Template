# -*- coding: utf-8 -*-
"""Read-only structural audit of the live machining DFM database."""
import sqlite3, json, collections, re, sys

DB = 'data/machining_dfm/machining_dfm.sqlite3'
con = sqlite3.connect('file:' + DB + '?mode=ro', uri=True)
con.row_factory = sqlite3.Row
con.execute('PRAGMA foreign_keys=ON')

tables = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")
          if not r[0].startswith('sqlite_')]
print('### TABLES:', len(tables))

# ---------- 1. JSON-ish columns content ----------
print('\n### 1. JSON / TEXT-JSON COLUMN CONTENT')
jsonish = re.compile(r'^\s*[\[{]')
for t in tables:
    cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % t)]
    for c in cols:
        if c in ('state_json', 'extra_json', 'count_json', 'machine_snapshot') or c.endswith('_json'):
            rows = con.execute('select "%s" as v from "%s"' % (c, t)).fetchall()
            vals = [r['v'] for r in rows]
            nonempty = [v for v in vals if v not in (None, '', '{}', '[]')]
            keys = collections.Counter()
            shapes = collections.Counter()
            bad = 0
            for v in nonempty:
                try:
                    o = json.loads(v)
                except Exception:
                    bad += 1
                    continue
                shapes[type(o).__name__] += 1
                if isinstance(o, dict):
                    for k in o:
                        keys[k] += 1
            lens = [len(v) for v in nonempty] or [0]
            print('%-22s %-18s rows=%-4d json-ish=%-4d unparsable=%d avg=%.0f max=%d shapes=%s'
                  % (t, c, len(vals), len(nonempty), bad, sum(lens) / len(lens), max(lens), dict(shapes)))
            if keys:
                print('        keys:', ', '.join('%s×%d' % (k, n) for k, n in keys.most_common(14)))

# ---------- 2. non-atomic text columns (potential repeating groups) ----------
print('\n### 2. NON-ATOMIC TEXT COLUMNS (separator heuristics)')
SEP = re.compile(r'[,;、，\n|]')
for t in tables:
    cols = [(r[1], r[2]) for r in con.execute('PRAGMA table_info("%s")' % t)]
    for name, typ in cols:
        if (typ or '').upper() not in ('TEXT', ''):
            continue
        if name.endswith('_json') or name in ('state_json', 'extra_json', 'count_json', 'machine_snapshot'):
            continue
        rows = con.execute('select "%s" as v from "%s" where "%s" is not null and "%s"<>""' % (name, t, name, name)).fetchall()
        if not rows:
            continue
        multi = sum(1 for r in rows if SEP.search(str(r['v'])))
        if multi:
            ex = [str(r['v'])[:60] for r in rows if SEP.search(str(r['v']))][:2]
            print('%-22s %-18s nonempty=%-5d with-separator=%-5d ex=%s' % (t, name, len(rows), multi, ex))

# ---------- 3. snapshots / duplicated business values ----------
print('\n### 3. SNAPSHOT COLUMNS (duplicated-from-library values)')
snapcols = []
for t in tables:
    for r in con.execute('PRAGMA table_info("%s")' % t):
        if 'snapshot' in r[1] or r[1].startswith(('tool_price', 'tool_life', 'handle_price',
                                                  'accessory_price', 'name_snapshot', 'drawing_snapshot')):
            snapcols.append((t, r[1]))
for t, c in snapcols:
    nz = con.execute('select count(*) from "%s" where "%s" is not null and "%s" not in ("", "{}", "0", "0.0")' % (t, c, c)).fetchone()[0]
    tot = con.execute('select count(*) from "%s"' % t).fetchone()[0]
    print('  %-26s %-26s non-trivial=%d/%d' % (t, c, nz, tot))

# ---------- 4. project_versions kinds ----------
print('\n### 4. project_versions BY KIND')
for r in con.execute('select kind, count(*) n, sum(length(state_json)) bytes, max(length(state_json)) mx from project_versions group by kind'):
    print('  kind=%-8s n=%-4d state_json_bytes=%-8s max=%s' % (r['kind'], r['n'], r['bytes'], r['mx']))

# ---------- 5. empty / near-empty tables & projects.state_json ----------
print('\n### 5. EMPTY TABLES / DEAD-ISH CONTENT')
for t in tables:
    n = con.execute('select count(*) from "%s"' % t).fetchone()[0]
    if n == 0:
        print('  EMPTY:', t)
print('  projects.state_json values:',
      [r[0] for r in con.execute('select state_json from projects')])
print('  projects rows:', [dict(r) for r in con.execute('select id,name,revision,state_json,archived from projects')])

# ---------- 6. indexes: duplicates & unused ----------
print('\n### 6. INDEX INVENTORY')
idx = collections.defaultdict(list)
for r in con.execute("select name, tbl_name, sql from sqlite_master where type='index'"):
    idx[r['tbl_name']].append((r['name'], r['sql']))
for t in sorted(idx):
    print(' ', t)
    for name, sql in idx[t]:
        print('     ', name, '::', (sql or '(auto)').replace('\n', ' '))

# ---------- 7. foreign keys + integrity ----------
print('\n### 7. FOREIGN KEYS')
fkc = 0
for t in tables:
    fks = list(con.execute('PRAGMA foreign_key_list("%s")' % t))
    if fks:
        fkc += len(fks)
        for f in fks:
            print('  %-26s %-22s -> %-22s %-22s on_delete=%s' % (t, f['from'], f['table'], f['to'], f['on_delete']))
print('  total FK constraints =', fkc)
print('  foreign_key_check:', con.execute('PRAGMA foreign_key_check').fetchall())
print('  integrity_check:', con.execute('PRAGMA integrity_check').fetchone()[0])

# ---------- 8. PK / uniqueness sanity ----------
print('\n### 8. PRIMARY KEYS')
for t in tables:
    pk = [r[1] for r in con.execute('PRAGMA table_info("%s")' % t) if r[5]]
    print('  %-26s PK=%s' % (t, pk))
