# -*- coding: utf-8 -*-
"""Match every registered route against real call sites in frontend/tests/tools/docs.

Strategy: for each source line, extract string literals and tokenise them by '/'.
A route matches a line when the route's non-parameter tokens appear as a CONTIGUOUS
subsequence of that line's token stream (after dropping a known API base prefix that the
file defines elsewhere, e.g. `const API='/api/machining-dfm'`).
"""
import json, os, re, collections

routes = json.load(open('_audit/routes.json', encoding='utf-8'))
LIT = re.compile(r"""'([^'\n]*)'|"([^"\n]*)"|`([^`\n]*)`""")
BASES = ['/api/machining-dfm', '/api/ppt-provider/v1', '/api/integration', '/api/logs', '/api']

SRC = collections.defaultdict(list)
for root, dirs, fs in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('.git', '.venv', 'node_modules', '__pycache__',
                                            '_audit', 'data', 'output', 'release', 'packaging',
                                            'template_previews', 'exact_style_previews',
                                            'pilot_output_previews', '1-基础数据', 'templates', 'scripts')]
    for f in fs:
        if f.endswith(('.js', '.mjs', '.py', '.md', '.html', '.cjs')) and 'pptxgen.bundle' not in f:
            SRC[os.path.join(root, f).replace('.\\', '')] = None


def toks_from_line(line):
    """token stream of one source line, honouring concatenation order"""
    out = []
    for m in LIT.finditer(line):
        s = next(g for g in m.groups() if g is not None)
        for part in s.split('/'):
            part = part.strip()
            if not part:
                continue
            # expression fragments / params / query strings are wildcards
            if part.startswith('{') or '${' in part or part.startswith('?') or ' ' in part:
                out.append(('PARAM', part))
            elif re.fullmatch(r'[A-Za-z0-9_\-.~%]+', part):
                out.append(('LIT', part))
            else:
                out.append(('PARAM', part))
    return out


def route_tokens(path):
    out = []
    for part in path.split('/'):
        if not part:
            continue
        if part.startswith('{'):
            out.append(('PARAM', part))
        else:
            out.append(('LIT', part))
    return out


def lits_only(toks):
    return [v for k, v in toks if k == 'LIT']


def contiguous(hay, needle):
    if not needle:
        return False
    n = len(needle)
    for i in range(len(hay) - n + 1):
        if hay[i:i + n] == needle:
            return True
    return False


file_lines = {}
file_has_base = collections.defaultdict(set)
for path in SRC:
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except Exception:
        continue
    lines = text.splitlines()
    file_lines[path] = lines
    for b in BASES:
        if b in text:
            file_has_base[path].add(b)

results = {}
for r in routes:
    rt = route_tokens(r['path'])
    variants = []
    for base in BASES:
        bt = lits_only(route_tokens(base))
        lt = lits_only(rt)
        if lt[:len(bt)] == bt:
            variants.append(lt[len(bt):])
    variants.append(lits_only(rt))
    variants = [v for v in variants if v]
    hits = []
    for path, lines in file_lines.items():
        base_ok = bool(file_has_base.get(path)) or path.endswith(('.md', '.mjs'))
        for i in range(len(lines)):
            # window of up to 3 consecutive lines: page modules build paths across lines
            for w in (1, 2, 3):
                if i + w > len(lines):
                    continue
                chunk = ' '.join(lines[i:i + w])
                if not any(k in chunk for k in ('/api/', 'fetch', 'api(', 'client.', 'http', "'/", '"/')):
                    continue
                hay = lits_only(toks_from_line(chunk))
                for v in variants:
                    if not base_ok and len(v) == len(lits_only(route_tokens(r['path']))):
                        continue
                    if contiguous(hay, v):
                        hits.append((path, i + 1, chunk.strip()[:220]))
                        break
                else:
                    continue
                break
    results[(tuple(r['methods']), r['path'])] = hits

def bucket(path):
    p = path.replace('\\', '/').lstrip('./')
    if p.startswith('static/machining_dfm'):
        return 'FE'
    if p.startswith('tests/'):
        return 'TESTS'
    if p.startswith('tools/'):
        return 'TOOLS'
    if p.startswith('docs/') or p.endswith('.md'):
        return 'DOCS'
    if p.startswith('app/'):
        return 'APP'
    return 'OTHER'

print('%-4s %-74s %-6s %s' % ('M', 'PATH', 'CLASS', 'CALLERS'))
summary = collections.Counter()
for r in sorted(routes, key=lambda x: x['path']):
    key = (tuple(r['methods']), r['path'])
    hits = results[key]
    b = collections.Counter(bucket(p) for p, i, l in hits)
    if b.get('FE'):
        cls = 'FE-used'
    elif b.get('TESTS'):
        cls = 'test-only'
    elif b.get('TOOLS'):
        cls = 'tool-only'
    elif b.get('DOCS'):
        cls = 'docs-only'
    elif b.get('APP'):
        cls = 'app-only'
    else:
        cls = 'NO-REF'
    summary[cls] += 1
    ev = '; '.join('%s:%d' % (p, i) for p, i, l in hits[:4])
    print('%-4s %-74s %-8s %s' % (','.join(r['methods']), r['path'], cls, ev[:170]))

print()
print('SUMMARY:', dict(summary))
print()
print('### DETAIL FOR NO-REF / app-only ROUTES')
for r in sorted(routes, key=lambda x: x['path']):
    key = (tuple(r['methods']), r['path'])
    hits = results[key]
    b = collections.Counter(bucket(p) for p, i, l in hits)
    if not b.get('FE') and not b.get('TESTS') and not b.get('TOOLS') and not b.get('DOCS'):
        print('---', ','.join(r['methods']), r['path'], 'endpoint=', r['endpoint'])
        for p, i, l in hits:
            print('     %s:%d  %s' % (p, i, l))

json.dump({'%s %s' % (','.join(r['methods']), r['path']): results[(tuple(r['methods']), r['path'])]
           for r in routes}, open('_audit/usage_raw.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
