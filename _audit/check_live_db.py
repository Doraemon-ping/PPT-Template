# -*- coding: utf-8 -*-
"""重启后线上库体检（只读）：老索引是否清掉、外键与完整性是否正常。"""
import os
import sqlite3

P = 'data/machining_dfm/machining_dfm.sqlite3'
con = sqlite3.connect('file:%s?mode=ro' % P.replace('\\', '/'), uri=True)
idx = sorted(r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='machines'"))
print('machines 索引（重启开库后）：')
for name in idx:
    print('   -', name)
print('老命名 ..._sort 已清掉：', 'idx_machining_dfm_machines_sort' not in idx)
print('foreign_key_check：', con.execute('PRAGMA foreign_key_check').fetchall())
print('integrity_check：', con.execute('PRAGMA integrity_check').fetchone()[0])
print('表数：', con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
print('库大小：', os.path.getsize(P), '字节')
con.close()
