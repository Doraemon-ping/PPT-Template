# -*- coding: utf-8 -*-
"""Compare seed JSON library rows against live DB rows to detect data loss on import."""
import json, sqlite3, collections

SEED = 'app/resources/machining_dfm_seed/%s.json'
DB = 'data/machining_dfm/machining_dfm.sqlite3'
con = sqlite3.connect('file:' + DB + '?mode=ro', uri=True)
con.row_factory = sqlite3.Row

for name, table in (('machines', 'machines'), ('tools', 'tools'), ('fixtures', 'fixtures'), ('gauges', 'gauges')):
    d = json.load(open(SEED % name, encoding='utf-8'))
    if isinstance(d, dict):
        rows = next(v for v in d.values() if isinstance(v, list))
    else:
        rows = d
    print('== %-9s seed rows=%-4d db rows=%d' % (name, len(rows), con.execute('select count(*) from "%s"' % table).fetchone()[0]))
    seedkeys = collections.Counter()
    for r in rows:
        for k in r:
            seedkeys[k] += 1
    print('   seed keys:', ', '.join('%s(%d)' % (k, n) for k, n in seedkeys.most_common()))
    dbcols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % table)]
    print('   db cols  :', ', '.join(dbcols))
    for k in seedkeys:
        if k not in dbcols:
            print('   !! seed key not in DB columns:', k)
    # value population in db
    for c in dbcols:
        if c in ('created', 'updated', 'deleted_at', 'deleted_by', 'deleted_reason', 'sort_order', 'id'):
            continue
        nz = con.execute('select count(*) from "%s" where "%s" is not null and "%s" not in ("",0,0.0)' % (table, c, c)).fetchone()[0]
        tot = con.execute('select count(*) from "%s"' % table).fetchone()[0]
        print('   DB %-22s populated=%d/%d' % (c, nz, tot))
    print('   seed sample:', json.dumps(rows[0], ensure_ascii=False)[:220])
    if len(rows) > 1:
        print('   seed sample2:', json.dumps(rows[1], ensure_ascii=False)[:220])
