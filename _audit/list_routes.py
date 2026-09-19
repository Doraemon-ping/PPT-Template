import json, sys, os
sys.path.insert(0, os.getcwd())
from app.services.machining import app


def extract(routes, prefix=''):
    out = []
    for r in routes:
        cand = getattr(r, 'effective_candidates', None)
        if callable(cand):
            p = getattr(getattr(r, 'include_context', None), 'prefix', '') or ''
            out.extend(extract(cand(), prefix + p))
            continue
        route = getattr(r, 'route', None) or getattr(r, 'apiroute', None)
        if route is not None and not hasattr(r, 'methods'):
            p = getattr(getattr(r, 'include_context', None), 'prefix', '') or ''
            out.extend(extract([route], prefix + p))
            continue
        path = getattr(r, 'path', None)
        if path is None:
            continue
        methods = sorted(m for m in (getattr(r, 'methods', []) or []) if m not in ('HEAD', 'OPTIONS'))
        if not methods:
            continue
        ep = getattr(r, 'endpoint', None)
        out.append({
            'path': prefix + path,
            'methods': methods,
            'name': getattr(r, 'name', ''),
            'endpoint': '%s:%s' % (getattr(ep, '__module__', ''), getattr(ep, '__name__', '')),
            'summary': getattr(r, 'summary', '') or '',
        })
    return out


rows = extract(app.routes)
seen = {}
for r in rows:
    key = (tuple(r['methods']), r['path'])
    seen.setdefault(key, []).append(r)
print('TOTAL ROUTES =', len(rows), ' UNIQUE =', len(seen))
by_method = {}
for r in rows:
    for m in r['methods']:
        by_method[m] = by_method.get(m, 0) + 1
print('BY METHOD =', by_method)
dupes = [k for k, v in seen.items() if len(v) > 1]
print('DUP PATH+METHOD =', len(dupes))
for k in dupes:
    print('  DUP', k, [x['endpoint'] for x in seen[k]])
print()
print('%-4s %-76s %s' % ('M', 'PATH', 'ENDPOINT'))
for r in sorted(rows, key=lambda x: (x['path'], x['methods'])):
    print('%-4s %-76s %s' % (','.join(r['methods']), r['path'], r['endpoint']))
with open('_audit/routes.json', 'w', encoding='utf-8') as f:
    json.dump(rows, f, ensure_ascii=False, indent=1)
