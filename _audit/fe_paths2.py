# -*- coding: utf-8 -*-
"""Print every path-looking expression in the frontend page modules, in order."""
import os, re, glob

FILES = sorted(glob.glob('static/machining_dfm/*.js'))
EXPR = re.compile(r"(['\"`][^'\"`\n]*['\"`]\s*\+?\s*(?:encodeURIComponent\([^)]*\)\s*\+?\s*)?)+")
PATHY = re.compile(r"^['\"`]/")

for f in FILES:
    base = os.path.basename(f)
    if base in ('pptxgen.bundle.js',):
        continue
    lines = open(f, encoding='utf-8').read().splitlines()
    out = []
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith('*') or s.startswith('//') or s.startswith('/*'):
            continue
        # collect string literals that look like path fragments
        frags = re.findall(r"'([^'\n]*)'", line) + re.findall(r'"([^"\n]*)"', line)
        pathy = [x for x in frags if x.startswith('/') or x in ('/photo', 'photo', 'photo/', '/restore', '/default', '/reorder', '/doc')]
        if any(x for x in frags if PATHY.match(x)) or re.search(r"api\(|call\(|request\(|write\(|uploadBinary|API\s*\+", line):
            if pathy or re.search(r"api\(|call\(|request\(|write\(|uploadBinary", line):
                out.append((i, s[:200]))
    if out:
        print('=' * 30, f)
        for i, s in out:
            print('%5d  %s' % (i, s))
