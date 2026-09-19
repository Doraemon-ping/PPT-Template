# -*- coding: utf-8 -*-
"""按行号打印 legacy_app.js 片段（长行截断），用于精确定位要改的地方。"""
import sys

PATH = 'static/machining_dfm/legacy_app.js'
LINES = open(PATH, encoding='utf-8').read().split('\n')

start = int(sys.argv[1])
end = int(sys.argv[2])
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 1200
for number in range(start, end + 1):
    text = LINES[number - 1]
    mark = '*' if len(text) > limit else ' '
    print('%s%4d (%5d) %s' % (mark, number, len(text), text[:limit]))
