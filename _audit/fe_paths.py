import os, re, json, collections

FRAG = re.compile(r"""['"`](/[A-Za-z0-9_\-\{\}\$\./]*)['"`]""")
TEMPL = re.compile(r"""['"`](\$\{[^}]*\}|/)[^'"`]*['"`]""")

files = []
for root, dirs, fs in os.walk('static/machining_dfm'):
    for f in fs:
        if f.endswith(('.js', '.html', '.css')):
            files.append(os.path.join(root, f))

allfrag = collections.Counter()
per = {}
for path in sorted(files):
    txt = open(path, encoding='utf-8', errors='replace').read()
    frags = sorted(set(m.group(1) for m in FRAG.finditer(txt)))
    per[path] = frags
    for f in frags:
        allfrag[f] += 1

print('=== ALL DISTINCT PATH FRAGMENTS IN FRONTEND ===')
for f, n in sorted(allfrag.items()):
    print('%-60s %d' % (f, n))

print()
print('=== fetch / api CALL SITES (line context) ===')
callre = re.compile(r"(fetch\(|api\(|req\(|http\()")
for path in sorted(files):
    lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    hits = [(i + 1, l.strip()) for i, l in enumerate(lines) if callre.search(l)]
    if hits:
        print('--- %s (%d)' % (path, len(hits)))
        for i, l in hits:
            print('  %5d  %s' % (i, l[:200]))
