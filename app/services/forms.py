"""Adapters for original HTML applications. HTML is never executed on the server."""
import hashlib
import re
from fastapi import HTTPException
from lxml import html

DFM_ADAPTER = 'dfm_quote_v1'
JSON_ADAPTER = 'json_export_v1'
# Backwards-compatible name used by older callers/tests.
ADAPTER = DFM_ADAPTER
ROOT_LABELS = {'G': '项目信息', 'pr': '工序', 'mdb': '设备库', 'tdb': '刀具库', 'is': '问题清单', 'fdb': '夹具库', 'idb': '检具库', 'vh': '版本履历'}
LABELS = {'cust':'客户', 'part':'零件号', 'len':'长度', 'wid':'宽度', 'hgt':'高度', 'wgt':'重量', 'pI':'产品图片', 'pf':'产品图片2', 'nm':'名称', 'name':'名称', 'img':'图片', 'tl':'刀具明细', 'price':'价格', 'dt':'日期', 'ds':'描述', 'by':'负责人', 'ver':'版本', 'custVer':'客户版本', 'dfmDate':'DFM日期', 'bInspImg':'毛坯检具图片', 'fInspImg':'成品检具图片', '_ct':'切削时间', '_vc':'切削速度', '_vf':'进给速度', '_fz':'每转进给', 'type':'类型', 'drw':'图号'}
LABELS.update({'computed':'原表单计算结果','processes':'工序计算汇总','cut_seconds':'切削时间(s)','noncut_seconds':'非切削时间(s)','cycle_seconds':'节拍(s)','monthly_capacity':'月产能(件)','total_seconds':'总节拍(s)','parent_index':'所属工序序号'})
# These names are retained only for an explicit, opt-in migration of old DFM
# schemes.  They must never be added to a newly imported form's catalog: a PPT
# placeholder is a target slot, not a universal business-field vocabulary.
DFM_FIELD_ALIASES = {
    'cust': ('custName',), 'part': ('projName', 'partName', 'partNo'), 'custVer': ('version', 'custVer'),
    'dfmDate': ('dfmDate',), 'prj': ('projType',), 'len': ('dimL',), 'wid': ('dimW',),
    'hgt': ('dimH',), 'wgt': ('wFinish', 'wCast'),
}
DFM_IMAGE_ALIASES = {'pI': ('plImg3d',), 'pf': ('plImg2d',), 'bInspImg': ('insImg',), 'fInspImg': ('dcImg',)}
DFM_TABLE_ALIASES = {'pr': 'mech', 'is': 'issues', 'vh': 'dfmHist'}
DFM_LABELS = {'custName':'客户名称','partName':'零件名称','partNo':'零件号','version':'版本号','dfmDate':'日期','projType':'项目类型','dimL':'产品尺寸 L','dimW':'产品尺寸 W','dimH':'产品尺寸 H','wFinish':'成品重量','wCast':'毛坯重量（铸件）','plImg3d':'产品 3D 图片','plImg2d':'产品 2D 图片','insImg':'检具图片','dcImg':'设计图片','mech':'机加工艺','issues':'问题清单','dfmHist':'版本履历'}


def decode_source(raw):
    if not raw or len(raw) > 8*1024*1024:
        raise HTTPException(422, '请选择 8 MB 以内的 HTML 文件')
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise HTTPException(422, '请将 HTML 另存为 UTF-8')


def detect_adapter(source):
    if all(re.search(p, source) for p in (r'function\s+applyData\s*\(', r'function\s+exportData\s*\(', r'function\s+render\s*\(', r'cncCalcV7', r'\bMDB\b', r'\bPR\b', r'\bGLBL\b')):
        return DFM_ADAPTER
    # Generic applications opt in with a tiny stable contract.  For existing
    # tools, matching export/import functions are also accepted so adding a
    # bridge object is not mandatory.  Runtime validation still fails closed
    # when exportData does not return JSON-compatible data.
    if re.search(r'__DFM_BRIDGE__', source):
        return JSON_ADAPTER
    has_export = re.search(r'(?:function\s+exportData\s*\(|exportData\s*[:=]\s*(?:async\s*)?(?:function|\(?[^=;]*\)?\s*=>))', source)
    has_import = re.search(r'(?:function\s+(?:importData|applyData|loadData)\s*\(|(?:importData|applyData|loadData)\s*[:=]\s*(?:async\s*)?(?:function|\(?[^=;]*\)?\s*=>))', source)
    return JSON_ADAPTER if has_export and has_import else None


def describe(raw):
    source = decode_source(raw)
    root = html.fromstring(source)
    return {'adapter': detect_adapter(source), 'name': ''.join(root.xpath('//title/text()'))[:100] or '原样 HTML 应用'}


def key(path):
    # Length-safe identifiers without collisions between dotted and underscored paths.
    return re.sub(r'[^A-Za-z0-9_]', '_', path)[:55] + '_' + hashlib.sha256(path.encode()).hexdigest()[:10]


def normalize(runtime, *, include_legacy_aliases=True):
    """Dispatch a native snapshot to its source-specific normalizer."""
    if not isinstance(runtime, dict):
        raise HTTPException(422, '原样表单数据桥接格式无效')
    adapter = runtime.get('adapter')
    if adapter == JSON_ADAPTER:
        return normalize_json_export(runtime)
    if adapter == DFM_ADAPTER:
        return _normalize_dfm(runtime, include_legacy_aliases=include_legacy_aliases)
    raise HTTPException(422, f'不支持的数据适配器：{adapter or "未指定"}')


def _normalization_result(runtime):
    return (
        {'f': {}, 't': {}, 'i': {}, 'runtime': runtime},
        {'fields': [], 'tables': {}, 'images': {}, 'derived': {}, 'results': {}},
    )


def _path_allowed(path, rules):
    """Apply optional prefix include/exclude rules without requiring a schema."""
    def matches(prefix):
        return path == prefix or path.startswith(prefix + '.') or path.startswith(prefix + '[')

    include = rules.get('include', []) if isinstance(rules, dict) else []
    exclude = rules.get('exclude', []) if isinstance(rules, dict) else []
    include = [p for p in include if isinstance(p, str) and p]
    exclude = [p for p in exclude if isinstance(p, str) and p]
    if any(matches(p) for p in exclude):
        return False
    # Parents of included paths must remain traversable.
    return not include or any(matches(p) or p.startswith(path + '.') or p.startswith(path + '[') for p in include)


def normalize_json_export(runtime):
    """Build a rebuildable PPT projection from an arbitrary exported JSON tree.

    ``runtime.raw`` remains authoritative.  Scalar values, object arrays and
    data-URL images are projected automatically using collision-safe keys.
    Optional ``labels`` and ``rules`` only affect the generated catalog and can
    evolve independently from the source data.
    """
    if runtime.get('adapter') != JSON_ADAPTER or 'raw' not in runtime:
        raise HTTPException(422, '通用 JSON 快照缺少 raw 数据')
    raw = runtime['raw']
    if not isinstance(raw, (dict, list)):
        raise HTTPException(422, '导出的 JSON 顶层必须是对象或数组')
    labels = runtime.get('labels') if isinstance(runtime.get('labels'), dict) else {}
    rules = runtime.get('rules') if isinstance(runtime.get('rules'), dict) else {}
    result, catalog = _normalization_result(runtime)
    count = 0

    def label_for(path, leaf):
        value = labels.get(path, labels.get(leaf, leaf))
        return str(value)[:160] if isinstance(value, (str, int, float)) else leaf

    def meta(path, leaf):
        root = path.split('.', 1)[0].split('[', 1)[0]
        return {
            'label': label_for(path, leaf),
            'module': label_for(root, root),
            'group': 'JSON 导出数据',
            'source_path': path,
        }

    def scalar(value):
        return value is None or isinstance(value, (str, int, float, bool))

    def visit(value, path, depth=0):
        nonlocal count
        count += 1
        if count > 150000 or depth > 24:
            raise HTTPException(422, '导出的 JSON 层级或字段数量过大；请用 rules.include/exclude 缩小投影范围')
        if not _path_allowed(path, rules):
            return
        leaf = path.rsplit('.', 1)[-1]
        if leaf in {'__proto__', 'prototype', 'constructor'}:
            return
        field_key = key(path)
        item_meta = meta(path, leaf)
        if isinstance(value, dict):
            for name, child in value.items():
                if isinstance(name, str) and name not in {'__proto__', 'prototype', 'constructor'}:
                    visit(child, f'{path}.{name}' if path else name, depth + 1)
            return
        if isinstance(value, list):
            # Arrays become one table rather than thousands of indexed fields.
            # This keeps large exports usable and makes bindings stable when
            # rows are inserted, deleted or reordered.
            if all(isinstance(row, dict) for row in value):
                columns = {}
                for row in value:
                    for name, child in row.items():
                        if isinstance(name, str) and name not in {'__proto__', 'prototype', 'constructor'} and scalar(child):
                            columns[name] = label_for(f'{path}[*].{name}', name)
                result['t'][field_key] = value
                catalog['tables'][field_key] = {**item_meta, 'columns': columns}
                nested = sorted({name for row in value for name, child in row.items() if isinstance(name, str) and isinstance(child, list)})
                for name in nested:
                    children = []
                    for index, row in enumerate(value, 1):
                        for child in row.get(name, []):
                            if isinstance(child, dict):
                                children.append({**child, 'parent_index': index})
                    if children:
                        visit(children, f'{path}[*].{name}', depth + 1)
                for index, row in enumerate(value, 1):
                    for name, child in row.items():
                        if isinstance(child, str) and child.startswith('data:image/'):
                            visit(child, f'{path}[{index}].{name}', depth + 1)
            elif all(scalar(row) for row in value):
                rows = [{'value': row} for row in value]
                result['t'][field_key] = rows
                catalog['tables'][field_key] = {**item_meta, 'columns': {'value': '值'}}
            else:
                for index, child in enumerate(value, 1):
                    visit(child, f'{path}[{index}]', depth + 1)
            return
        if isinstance(value, str) and value.startswith('data:image/'):
            result['i'][field_key] = [value]
            catalog['images'][field_key] = {**item_meta, 'path': f'i.{field_key}[0]'}
        elif scalar(value):
            # Other data URLs (documents, archives, etc.) stay in raw only.
            if isinstance(value, str) and value.startswith('data:'):
                return
            result['f'][field_key] = value
            catalog['fields'].append({**item_meta, 'path': f'f.{field_key}'})

    if isinstance(raw, dict):
        for name, child in raw.items():
            if isinstance(name, str) and name not in {'__proto__', 'prototype', 'constructor'}:
                visit(child, name)
    else:
        visit(raw, 'root')
    return result, catalog


def _normalize_dfm(runtime, *, include_legacy_aliases=True):
    """Project an original HTML snapshot into the generic PPT data scopes.

    Platform catalog/context calls deliberately keep source-specific,
    collision-safe paths (``f.<stable-key>`` / ``i.<stable-key>`` /
    ``t.<stable-key>``).  The template editor then stores an explicit
    target-shape -> source-path binding. ``include_legacy_aliases`` exists only
    for a one-off migration of historical DFM schemes; platform calls pass
    ``False``. Its compatibility default remains enabled for older direct
    callers and can be disabled explicitly.
    """
    if runtime.get('adapter') != DFM_ADAPTER or not isinstance(runtime.get('state'), dict):
        raise HTTPException(422, '原样表单数据桥接格式无效')
    state = runtime['state']
    if not isinstance(state.get('G'), dict) or any(not isinstance(state.get(k), list) for k in ROOT_LABELS if k != 'G'):
        raise HTTPException(422, '原样表单快照缺少项目或数据库/明细数组，请重新读取页面')
    supplied = runtime.get('labels', {})
    labels = {**LABELS, **{k: v[:160] for k, v in supplied.items() if isinstance(k, str) and isinstance(v, str)}} if isinstance(supplied, dict) else LABELS
    result, catalog = _normalization_result(runtime)
    count = 0

    def caption(path):
        return ' / '.join(ROOT_LABELS.get(p, labels.get(p, p)) for p in path.split('.'))

    def visit(value, path, depth=0):
        nonlocal count
        count += 1
        if count > 100000 or depth > 16:
            raise HTTPException(422, '原样表单数据层级或字段数量过大')
        leaf = path.rsplit('.', 1)[-1]
        if leaf in {'__proto__', 'prototype', 'constructor', '_vSnap'}:
            return
        field_key = key(path)
        meta = {'label': caption(path), 'module': ROOT_LABELS.get(path.split('.')[0], '原表单'), 'group': '原样表单参数', 'source_path': path}
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(k, str): visit(v, path+'.'+k, depth+1)
        elif isinstance(value, list):
            # Preserve nested row values for repeat pages; flattened nested lists also
            # appear in the catalog with parent_index for cross-reference.
            if all(isinstance(r, dict) for r in value):
                columns = {}
                for row in value:
                    for k, v in row.items():
                        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k) and k not in {'__proto__','constructor','prototype','_vSnap'} and not isinstance(v, (list, dict)):
                            columns[k] = labels.get(k, k)
                result['t'][field_key] = value
                catalog['tables'][field_key] = {**meta, 'columns': columns}
                children = sorted({k for r in value for k,v in r.items() if isinstance(v,list)})
                for child in children:
                    rows = [{**item, 'parent_index': n+1} for n,r in enumerate(value) for item in r.get(child,[]) if isinstance(item,dict)]
                    if rows: visit(rows, path+'.'+child, depth+1)
                # Individual image slots include row position for direct page binding.
                for n,row in enumerate(value):
                    for k,v in row.items():
                        if isinstance(v,str) and v.startswith('data:image/'):
                            visit(v, path+'.'+str(n+1)+'.'+k, depth+1)
            else:
                for n, v in enumerate(value): visit(v, path+'.'+str(n+1), depth+1)
        elif isinstance(value,str) and value.startswith('data:image/') or value is None and leaf in {'pI','pf','img','bInspImg','fInspImg'}:
            result['i'][field_key] = [value] if value else []
            catalog['images'][field_key] = {**meta, 'path':'i.'+field_key+'[0]'}
        elif value is None or isinstance(value, (str,int,float,bool)):
            # Opaque document attachments stay in the raw snapshot, not text fields.
            if isinstance(value,str) and value.startswith('data:'): return
            result['f'][field_key] = value
            catalog['fields'].append({**meta, 'path':'f.'+field_key})

    for root in ROOT_LABELS:
        visit(state[root], root)
    if include_legacy_aliases:
        # Migration-only projection for schemes created before the generic
        # template binding workflow.  Production catalog/context calls leave
        # this disabled so unrelated HTML applications cannot inherit DFM
        # business names.
        g = state['G']
        for source, aliases in DFM_FIELD_ALIASES.items():
            if source not in g: continue
            for alias in aliases:
                result['f'].setdefault(alias, g[source])
                if not any(x.get('path') == 'f.' + alias for x in catalog['fields']):
                    catalog['fields'].append({'label': DFM_LABELS.get(alias, alias), 'module': '兼容 DFM 参数（迁移）', 'group': '项目信息', 'path': 'f.' + alias, 'source_path': f'G.{source}'})
        for source, aliases in DFM_IMAGE_ALIASES.items():
            if source not in g: continue
            value = g.get(source)
            for alias in aliases:
                result['i'].setdefault(alias, [value] if value else [])
                catalog['images'].setdefault(alias, {'label': DFM_LABELS.get(alias, alias), 'module': '兼容 DFM 参数（迁移）', 'group': '产品图片', 'path': 'i.' + alias + '[0]', 'source_path': f'G.{source}'})
        for source, alias in DFM_TABLE_ALIASES.items():
            if source not in state: continue
            rows = state[source]
            result['t'].setdefault(alias, rows)
            if alias not in catalog['tables']:
                columns = {}
                for row in rows:
                    if isinstance(row, dict):
                        for col, value in row.items():
                            if not isinstance(value, (list, dict)) and col not in {'_vSnap'}: columns.setdefault(col, LABELS.get(col, col))
                catalog['tables'][alias] = {'label': DFM_LABELS.get(alias, alias), 'module': '兼容 DFM 参数（迁移）', 'group': DFM_LABELS.get(alias, alias), 'columns': columns, 'source_path': f'{source}'}
    if isinstance(runtime.get('computed'),dict):
        visit(runtime['computed'], 'computed')
    return result, catalog
