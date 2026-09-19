# -*- coding: utf-8 -*-
"""Final numbers for the acceptance report (read-only)."""
import sqlite3, json, os

DB = 'data/machining_dfm/machining_dfm.sqlite3'
con = sqlite3.connect('file:' + DB + '?mode=ro', uri=True)
con.row_factory = sqlite3.Row
print('DB size = %d bytes' % os.path.getsize(DB))
tables = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
print('tables =', len(tables))
for t in tables:
    n = con.execute('select count(*) from "%s"' % t).fetchone()[0]
    print('  %-24s %d' % (t, n))
print()
print('FK constraints =', sum(len(list(con.execute('PRAGMA foreign_key_list("%s")' % t))) for t in tables))
print('foreign_key_check =', con.execute('PRAGMA foreign_key_check').fetchall())
print('integrity_check =', con.execute('PRAGMA integrity_check').fetchone()[0])
print()
tot = 0
print('JSON 体积：')
for t, c in (('projects', 'state_json'), ('project_versions', 'state_json'), ('project_versions', 'extra_json'),
             ('project_settings', 'extra_json'), ('project_issues', 'extra_json'), ('project_changes', 'extra_json'),
             ('project_processes', 'count_json'), ('project_processes', 'machine_snapshot')):
    n, b, mx = con.execute('select count(*), coalesce(sum(length(%s)),0), coalesce(max(length(%s)),0) from %s' % (c, c, t)).fetchone()
    tot += b
    print('  %-18s %-16s rows=%-4d bytes=%-8d max=%d' % (t, c, n, b, mx))
print('  合计 = %d bytes' % tot)
print()
print('项目形态：')
for r in con.execute('select id,name,revision,length(state_json) slen from projects'):
    pid = r['id']
    npr = con.execute('select count(*) from project_processes where project_id=?', (pid,)).fetchone()[0]
    ntl = con.execute('select count(*) from project_process_tools where project_id=?', (pid,)).fetchone()[0]
    nis = con.execute('select count(*) from project_issues where project_id=?', (pid,)).fetchone()[0]
    nvh = con.execute("select count(*) from project_versions where project_id=? and kind='history'", (pid,)).fetchone()[0]
    nsv = con.execute("select count(*) from project_versions where project_id=? and kind='save'", (pid,)).fetchone()[0]
    print('  %s rev=%-3d state_json=%-6d 表行(工序=%d 刀具=%d 问题=%d) 履历行=%d 保存版本=%d'
          % (r['id'][:8], r['revision'], r['slen'], npr, ntl, nis, nvh, nsv))
print()
print('索引（重复/冗余检查）：')
import collections
d = collections.defaultdict(list)
for r in con.execute("select name,tbl_name,sql from sqlite_master where type='index' and sql is not null"):
    d[r['tbl_name']].append((r['name'], ' '.join(r['sql'].split())))
for t, items in sorted(d.items()):
    cols = collections.Counter()
    for name, sql in items:
        # extract column tuple
        import re
        m = re.search(r'\((.*)\)\s*$', sql)
        cols[m.group(1) if m else sql] += 1
    dup = [c for c, n in cols.items() if n > 1]
    if dup:
        print('  !! %s 有重复索引定义: %s' % (t, dup))
        for name, sql in items:
            print('       %s' % sql)
print()
print('空转/全空列（样本）：')
for t, c in (('project_process_tools', 'tool_price_snapshot'), ('project_process_tools', 'tool_life_snapshot'),
             ('project_selections', 'price_snapshot'), ('project_selections', 'name_snapshot'),
             ('tools', 'price'), ('tools', 'life_minutes'), ('tools', 'length'),
             ('machines', 'price'), ('machines', 'doc_id'), ('machines', 'doc_name'),
             ('fixtures', 'photo_id'), ('gauges', 'photo_id'), ('fixtures', 'process_days'),
             ('gauges', 'design_days'), ('gauges', 'process_days'), ('fixtures', 'remark')):
    nz = con.execute('select count(*) from "%s" where "%s" is not null and "%s" not in ("",0,0.0)' % (t, c, c)).fetchone()[0]
    n = con.execute('select count(*) from "%s"' % t).fetchone()[0]
    print('  %-22s %-24s 有值=%d/%d' % (t, c, nz, n))
print()
print('逻辑删除列使用情况：')
for t in tables:
    cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % t)]
    if 'deleted_at' in cols:
        nz = con.execute('select count(*) from "%s" where deleted_at is not null' % t).fetchone()[0]
        n = con.execute('select count(*) from "%s"' % t).fetchone()[0]
        print('  %-22s 已删行=%d/%d' % (t, nz, n))
print()
print('附件：')
print('  assets =', con.execute('select count(*) from assets').fetchone()[0],
      ' 总字节 =', con.execute('select sum(size) from assets').fetchone()[0])
print('  附件引用列非空数：')
for t, cols in (('project_settings', ('product_photo_id', 'product2_photo_id', 'blank_insp_photo_id', 'final_insp_photo_id')),
                ('project_processes', ('fixture_photo_id',)), ('project_process_tools', ('tool_photo_id',)),
                ('project_issues', ('before_photo_id', 'after_photo_id')), ('machines', ('photo_id', 'doc_id')),
                ('tools', ('photo_id',)), ('fixtures', ('photo_id',)), ('gauges', ('photo_id',))):
    for c in cols:
        nz = con.execute('select count(*) from "%s" where "%s" is not null' % (t, c)).fetchone()[0]
        if nz:
            print('    %-20s %-20s %d' % (t, c, nz))
print()
print('最新 project_changes：')
for r in con.execute('select entity,action,label,created from project_changes order by created desc limit 3'):
    print('   ', dict(r))
