import sqlite3, os, json

p = 'data/machining_dfm/machining_dfm.sqlite3'
print('exists', os.path.exists(p), os.path.getsize(p))
c = sqlite3.connect('file:' + p + '?mode=ro', uri=True)
c.row_factory = sqlite3.Row

tables = [r[0] for r in c.execute("select name from sqlite_master where type='table' order by name")]
print('TABLE COUNT =', len(tables))
print()
for t in tables:
    n = c.execute('select count(*) from "%s"' % t).fetchone()[0]
    print('=' * 78)
    print('TABLE %s  rows=%d' % (t, n))
    sql = c.execute("select sql from sqlite_master where type='table' and name=?", (t,)).fetchone()[0]
    print(sql)
    idx = [r[0] for r in c.execute("select sql from sqlite_master where type='index' and tbl_name=? and sql is not null", (t,))]
    for i in idx:
        print('  IDX', i)
