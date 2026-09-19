/* 无头自检：回收站面板（trash_page.js）+ 变更流水时间线（changes_page.js）。
 *
 * 做法与 smoke_machining_page.mjs 一样：用最小 DOM 垫片按 index.html 里的顺序把整页 JS 跑起来。
 * 区别是**接口自己 stub**：
 *   - 读接口（/trash、/projects/{pid}/trash、/projects/{pid}/changes）返回固定的假数据；
 *   - 写接口（恢复）一律拦下、只记账不落库 —— 自检全程不会改线上任何一行；
 *   - 只有 bootstrap 这类 GET 打到真服务（只读）。
 *
 * 四遍（每遍一个干净的虚拟机）：
 *   A 管理员 + 接口正常：入口出现、面板分组与四个字段都在、点恢复发出正确的 POST、行从面板消失、时间线倒序可过滤
 *   B 只有工艺设置令牌：能看不能恢复（没有恢复按钮，硬调也发不出请求）
 *   C /trash 404：入口整块消失、页面无错
 *   D /trash 返回 enabled=false：入口整块消失、页面无错
 *
 * 用法：node tools/check_trash_page.mjs
 */
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const STATIC = join(here, '..', 'static', 'machining_dfm');
const BASE = 'http://127.0.0.1:8002';
const read = name => readFileSync(join(STATIC, name), 'utf8');
const liveFetch = globalThis.fetch;

const problems = [];
const check = (label, ok, extra = '') => {
  if (!ok) problems.push(label + (extra ? ' → ' + extra : ''));
  console.log((ok ? '  ✓ ' : '  ✗ ') + label + (extra ? ' → ' + extra : ''));
};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const rejections = [];
process.on('unhandledRejection', error => { rejections.push(String((error && error.message) || error)); });

// ---------------------------------------------------------------- DOM 垫片
function makeElement(tag = 'div', id = '') {
  const listeners = {};
  const classes = new Set();
  const element = {
    tagName: String(tag).toUpperCase(), id, _html: '', _text: '', value: '', checked: false,
    hidden: false, disabled: false, files: null, type: '', accept: '', style: { cssText: '' },
    dataset: {}, children: [], childNodes: [], parentNode: null, firstChild: null, lastChild: null,
    classList: {
      add: (...names) => names.forEach(n => classes.add(n)),
      remove: (...names) => names.forEach(n => classes.delete(n)),
      toggle: (name, force) => { const on = force === undefined ? !classes.has(name) : !!force; on ? classes.add(name) : classes.delete(name); return on; },
      contains: name => classes.has(name),
    },
    get className() { return [...classes].join(' '); },
    set className(value) { classes.clear(); String(value || '').split(/\s+/).filter(Boolean).forEach(n => classes.add(n)); },
    get innerHTML() { return element._html; },
    set innerHTML(value) { element._html = String(value ?? ''); element.childNodes = []; element.children = []; },
    get textContent() { return element._text; },
    set textContent(value) { element._text = String(value ?? ''); },
    appendChild(child) { element.children.push(child); element.childNodes.push(child); child.parentNode = element; return child; },
    insertBefore(child) { element.children.unshift(child); element.childNodes.unshift(child); child.parentNode = element; return child; },
    removeChild(child) { element.children = element.children.filter(item => item !== child); return child; },
    remove() {}, setAttribute(name, value) { element[name] = value; },
    getAttribute(name) { return element[name] === undefined ? null : element[name]; },
    removeAttribute(name) { delete element[name]; }, hasAttribute(name) { return element[name] !== undefined; },
    addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push(handler); },
    removeEventListener() {}, dispatchEvent(event) { (listeners[event.type] || []).forEach(h => h(event)); return true; },
    click() {}, focus() {}, blur() {}, select() {}, scrollIntoView() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    getElementsByTagName() { return []; }, getElementsByClassName() { return []; },
    closest() { return null; }, contains() { return false; }, cloneNode() { return makeElement(tag, id); },
    after() {}, before() {}, replaceWith() {},
    getContext() { return { fillRect() {}, drawImage() {}, fillStyle: '' }; },
    toDataURL() { return 'data:image/jpeg;base64,AAAA'; },
  };
  return element;
}
function storage(seed = {}) {
  const map = new Map(Object.entries(seed));
  return {
    getItem: key => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: key => map.delete(key),
    clear: () => map.clear(),
    key: index => [...map.keys()][index] ?? null,
    get length() { return map.size; },
  };
}

// ---------------------------------------------------------------- 假数据
const minutesAgo = minutes => new Date(Date.now() - minutes * 60000).toISOString();
// 全局回收站：基础库 + 字典 + 已删除项目（group 与后端 library_trash() 一致）
const GLOBAL_TRASH = [
  { group: '基础库', entity: 'machines', entity_label: '设备库', table: 'machines', record_id: 'm-1',
    title: '兄弟(Brother) S500Z1', deleted_at: minutesAgo(30), deleted_by: 'admin',
    deleted_reason: '设备淘汰', references: 2 },
  { group: '基础库', entity: 'fixtures', entity_label: '夹具库', table: 'fixtures', record_id: 'f-9',
    title: '四轴机加夹具', deleted_at: minutesAgo(120), deleted_by: 'admin',
    deleted_reason: '重复录入', references: 0 },
  { group: '字典', entity: 'fixture_centers', entity_label: '模具中心', table: 'fixture_centers',
    record_id: '9999试验模具中心', title: '9999试验模具中心', deleted_at: minutesAgo(200),
    deleted_by: 'process', deleted_reason: '停用', references: 1 },
  { group: '项目', entity: 'project', entity_label: '项目', table: 'projects', record_id: 'p-archived',
    title: '老项目 · 蓄电池支架', deleted_at: minutesAgo(500), deleted_by: '',
    deleted_reason: '已删除项目（archived=1）', references: 0 },
];
// 本项目回收站：业务行按实体分组（group 与后端 project_trash() 一致）
const PROJECT_TRASH = [
  { group: '工序', entity: 'process', entity_label: '工序', table: 'project_processes', record_id: 'pp-1',
    title: '机加工序-OP10', deleted_at: minutesAgo(10), deleted_by: 'admin',
    deleted_reason: '改工艺删掉', references: 2 },
  { group: '工序刀具行', entity: 'tool', entity_label: '工序刀具行', table: 'project_process_tools',
    record_id: 'pt-1', title: 'D50面铣刀', deleted_at: minutesAgo(15), deleted_by: 'admin',
    deleted_reason: '页面删除', references: 0 },
  { group: '版本履历', entity: 'history', entity_label: '版本履历', table: 'project_versions',
    record_id: 'h-1', title: 'V1.0 初版', deleted_at: minutesAgo(400), deleted_by: 'process',
    deleted_reason: '撤回', references: 0 },
];
// 变更流水：**故意按时间正序给**（真接口是倒序），用来验证页面自己会排序
const CHANGES = [
  { id: 'c-1', sort_order: 1, entity: 'process', action: 'create', label: '新增工序：OP10',
    extra: { fields: ['nm'] }, created: '2026-09-18T08:00:00.123456+00:00', version_revision: 1 },
  { id: 'c-2', sort_order: 2, entity: 'tool', action: 'update', label: '刀具行：转速改成 800',
    extra: { fields: ['vf'], by: 'admin' }, created: '2026-09-18T09:00:00.000001+00:00', version_revision: 2 },
  { id: 'c-3', sort_order: 3, entity: 'project', action: 'save', label: '整份保存：第 3 版',
    extra: { name: '蓄电池支架', revision: 3 }, created: '2026-09-18T10:00:00+00:00', version_revision: 3 },
  { id: 'c-4', sort_order: 4, entity: 'process', action: 'delete', label: '删除工序：OP20',
    extra: { by: 'admin', reason: '页面删除', ids: ['pp-1', 'pp-2'] },
    created: '2026-09-18T11:00:00+00:00', version_revision: 4 },
];

// ---------------------------------------------------------------- 一遍自检
async function runPass(config) {
  const { label, mode = 'ok', adminToken = 'admin-token', processToken = '', projectRecord } = config;
  const elements = new Map();
  const documentStub = {
    readyState: 'complete', title: 'machining', cookie: '',
    documentElement: makeElement('html'), head: makeElement('head'), body: makeElement('body'),
    createElement: tag => makeElement(tag),
    createTextNode: text => ({ textContent: text }),
    createDocumentFragment: () => makeElement('fragment'),
    getElementById: id => { if (!elements.has(id)) elements.set(id, makeElement('div', id)); return elements.get(id); },
    querySelector: selector => {
      const text = String(selector || '');
      if (text.startsWith('#')) return documentStub.getElementById(text.slice(1));
      return makeElement('div', text);
    },
    querySelectorAll: () => [], getElementsByTagName: () => [], getElementsByClassName: () => [],
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
  };
  const messages = [];
  const writeCalls = [];
  const requestLog = [];
  let failRestore = '';
  const jsonResponse = (body, status = 200) => ({
    ok: status >= 200 && status < 300, status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body, text: async () => JSON.stringify(body), blob: async () => new Blob([]),
  });
  const failure = (status, detail) => jsonResponse({ detail }, status);

  const trashReading = () => {
    if (mode === '401' || mode === 'noauth') return failure(401, '未经授权');
    if (mode === '404') return failure(404, 'Not Found');
    if (mode === 'disabled') return jsonResponse({ enabled: false, items: [] });
    return jsonResponse({ enabled: true, items: GLOBAL_TRASH.map(item => ({ ...item })) });
  };
  const projectTrashReading = pid => {
    if (mode === '401' || mode === 'noauth') return failure(401, '未经授权');
    if (mode === '404') return failure(404, 'Not Found');
    if (mode === 'disabled') return jsonResponse({ enabled: false, project_id: pid, items: [] });
    return jsonResponse({ enabled: true, project_id: pid, items: PROJECT_TRASH.map(item => ({ ...item })) });
  };
  const changesReading = url => {
    const entity = /[?&]entity=([^&]*)/.exec(url);
    const wanted = entity ? decodeURIComponent(entity[1]) : '';
    const rows = CHANGES.filter(row => !wanted || row.entity === wanted);
    return jsonResponse({
      table: 'project_changes', enabled: true, count: rows.length, limit: 200,
      entities: ['project', 'settings', 'process', 'tool', 'issue', 'selection', 'history'],
      entity_labels: { project: '项目', settings: '项目信息', process: '工序', tool: '工序刀具行',
        issue: '问题清单', selection: '选型报价', history: '版本履历' },
      action_labels: { create: '新增', update: '修改', delete: '删除', restore: '恢复',
        reorder: '排序调整', photo: '图片', save: '保存' },
      changes: rows.map(row => ({ ...row })),
    });
  };
  const handleWrite = (target, method, init) => {
    const library = /\/trash\/([^/]+)\/([^/]+)\/restore$/.exec(target);
    if (library) {
      if (failRestore) return failure(422, failRestore);
      return jsonResponse({ restored: { table: decodeURIComponent(library[1]), record: { id: decodeURIComponent(library[2]) } } });
    }
    const project = /\/projects\/([^/]+)\/restore$/.exec(target);
    if (project) {
      if (failRestore) return failure(422, failRestore);
      return jsonResponse({ project: { ...(projectRecord || {}), archived: false } });
    }
    const row = /\/projects\/([^/]+)\/(processes|tools|issues|history)\/([^/]+)\/restore$/.exec(target);
    if (row) {
      if (failRestore) return failure(422, failRestore);
      const base = projectRecord || {};
      return jsonResponse({ project: { ...base, revision: Number(base.revision || 0) + 1 } });
    }
    return null;
  };

  const sandbox = {
    console: {
      log: (...args) => messages.push(args.join(' ')),
      warn: (...args) => messages.push('WARN ' + args.join(' ')),
      error: (...args) => messages.push('ERROR ' + args.join(' ')),
    },
    document: documentStub,
    location: { href: BASE + '/machining-dfm', pathname: '/machining-dfm', search: '', hash: '',
      origin: BASE, protocol: 'http:', host: '127.0.0.1:8002', reload() {} },
    navigator: { userAgent: 'node-check-trash', language: 'zh-CN', clipboard: null },
    localStorage: storage(),
    sessionStorage: storage({
      ...(adminToken ? { machiningDfmAdminToken: adminToken } : {}),
      ...(processToken ? { machiningDfmProcessToken: processToken } : {}),
    }),
    alert: message => messages.push('alert: ' + message),
    confirm: () => true, prompt: () => '自检输入',
    setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask,
    requestAnimationFrame: fn => setTimeout(() => fn(Date.now()), 0), cancelAnimationFrame: () => {},
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    open() {}, close() {}, focus() {}, scrollTo() {},
    matchMedia: () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }),
    Image: class { set src(_value) {} },
    FileReader: class { readAsDataURL() {} readAsText() {} },
    Blob: class { constructor(parts, options) { this.parts = parts; this.type = options && options.type; } },
    URL: { createObjectURL: () => 'blob:node/1', revokeObjectURL() {} },
    Headers, Request, Response, URLSearchParams, TextEncoder, TextDecoder, AbortController,
    Event: class { constructor(type) { this.type = type; } },
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
    MutationObserver: class { observe() {} disconnect() {} },
    IntersectionObserver: class { observe() {} disconnect() {} },
    ResizeObserver: class { observe() {} disconnect() {} },
    performance: { now: () => Date.now() },
    structuredClone: value => JSON.parse(JSON.stringify(value)),
    crypto: { randomUUID: () => 'uuid-' + Math.random().toString(16).slice(2) },
    Promise, JSON, Math, Date, Number, String, Boolean, Array, Object, RegExp, Error, TypeError,
    Map, Set, WeakMap, isNaN, parseFloat, parseInt, encodeURIComponent, decodeURIComponent,
    encodeURI, decodeURI, btoa, atob, escape, unescape, Intl,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  sandbox.top = sandbox;
  sandbox.fetch = async (url, init = {}) => {
    const raw = String(url);
    if (/^data:/.test(raw)) {
      return { ok: true, status: 200, headers: new Headers({ 'content-type': 'image/png' }),
        json: async () => ({}), text: async () => '', blob: async () => new Blob([]) };
    }
    const target = raw.startsWith('http') ? raw : BASE + raw;
    const method = String((init && init.method) || 'GET').toUpperCase();
    requestLog.push(method + ' ' + target);
    if (method !== 'GET') {
      writeCalls.push(method + ' ' + target
        + (init.body && typeof init.body === 'string' ? ' ' + init.body.slice(0, 160) : '')
        + ' | Authorization=' + (new Headers(init.headers || {}).get('Authorization') || '(无)'));
      const handled = handleWrite(target, method, init);
      if (handled) return handled;
      // 没预期的写请求：不动线上数据，只回一份同构的空载荷（下面有专门的检查把它们揪出来）
      return jsonResponse({ ok: true, project: projectRecord, removed: { removed_rows: 0 }, usage: [], count: 0 });
    }
    if (/\/api\/machining-dfm\/trash$/.test(target)) return trashReading();
    const projectTrash = /\/api\/machining-dfm\/projects\/([^/]+)\/trash$/.exec(target);
    if (projectTrash) return projectTrashReading(decodeURIComponent(projectTrash[1]));
    if (/\/api\/machining-dfm\/projects\/[^/]+\/changes/.test(target)) return changesReading(target);
    if (/\/api\/machining-dfm\/machines(\?|$)/.test(target)) {
      return jsonResponse({
        machines: [{ id: 'm-1', brand: '兄弟(Brother)', model: 'S500Z1', photo_url: null, doc_url: null }],
        fields: { fields: [{ key: 'brand', label: '品牌', type: 'text', unit: '' },
          { key: 'model', label: '型号', type: 'text', unit: '' }] },
        count: 1, fallback_id: 'm-1',
      });
    }
    // 「已删除项目」列表：线上没有已删项目，这里给一份假的，好把"恢复项目"那条分支走通
    if (/\/api\/machining-dfm\/projects\?archived=true$/.test(target)) {
      return jsonResponse({ projects: [{ ...(projectRecord || {}), archived: true }] });
    }
    // 其余 GET（bootstrap / projects / 集成服务地址…）：只读打到真服务
    return liveFetch(target, { cache: 'no-store', ...init, method: 'GET' });
  };
  const context = vm.createContext(sandbox);
  const loaded = [];
  for (const name of loadFiles()) {
    try {
      vm.runInContext(read(name), context, { filename: name });
      loaded.push(name);
    } catch (error) {
      problems.push(`[${label}] 加载 ${name} 抛异常：${error.message}`);
      console.log(`  ✗ [${label}] 加载 ${name} →`, error.message);
      break;
    }
  }
  const run = expression => vm.runInContext(expression, context);
  let started = false;
  try {
    await run('MachiningDFMHost.start()');
    started = true;
  } catch (error) {
    problems.push(`[${label}] host.start() 抛异常：${error.message}`);
    console.log(`  ✗ [${label}] host.start() 抛异常:`, error.message);
  }
  await sleep(300);
  return { label, run, messages, writeCalls, requestLog, loaded, started, mode,
    setFailRestore: value => { failRestore = value; } };
}

// ---------------------------------------------------------------- index.html 的脚本清单
const html = read('index.html');
const scriptTags = [...html.matchAll(/<script src="\/static\/machining_dfm\/([\w.]+)\?v=([\w.-]+)"/g)];
const scriptOrder = scriptTags.map(match => match[1]);
// pptxgen.bundle.js 与冒烟自检一样跳过（体积大、与本次改动无关），但仍然检查它被页面引用
const loadFiles = () => scriptOrder.filter(name => name !== 'pptxgen.bundle.js');

console.log('=== 静态检查：index.html 与各模块的接线 ===');
const versions = new Set([...scriptTags.map(match => match[2]),
  ...[...html.matchAll(/<link[^>]+href="\/static\/machining_dfm\/[\w.]+\.css\?v=([\w.-]+)"/g)].map(match => match[1])]);
check('index.html 里静态资源版本号统一（project-v1）', versions.size === 1 && versions.has('project-v1'), [...versions].join(', '));
check('index.html 已挂上 trash_page.js / changes_page.js',
  scriptOrder.includes('trash_page.js') && scriptOrder.includes('changes_page.js'), scriptOrder.join(' '));
check('新脚本排在 legacy_app.js 之前（legacy 渲染时要用到它们）',
  scriptOrder.indexOf('trash_page.js') < scriptOrder.indexOf('legacy_app.js')
  && scriptOrder.indexOf('changes_page.js') < scriptOrder.indexOf('legacy_app.js'), '');
check('index.html 引用的脚本文件都在磁盘上',
  scriptOrder.filter(name => !existsSync(join(STATIC, name))).length === 0,
  scriptOrder.filter(name => !existsSync(join(STATIC, name))).join(', '));
const legacy = read('legacy_app.js');
check('legacy_app.js：页签行接上回收站入口', /TrashPage\.tabEntry\(\)/.test(legacy), '');
check('legacy_app.js：版本履历下半部分接上变更流水', /ChangesPage\.section\(\)/.test(legacy), '');
check('legacy_app.js：切到版本履历页签时拉一次流水', /ChangesPage\.enter\(\)/.test(legacy), '');
check('legacy_app.js：不自己拼回收站/流水接口（写死在模块里）',
  !/\/changes/.test(legacy) && !/\/trash/.test(legacy), '');
for (const [file, key] of [['machines.js', "'machines'"], ['tools.js', "'tools'"], ['library_pages.js', 'cfg.endpoint']]) {
  check(`${file}：库页面接上回收站入口`, read(file).includes('TrashPage.button(') && read(file).includes(key), '');
}
for (const file of ['host.js', 'process_page.js', 'issue_page.js', 'selection_page.js', 'history_page.js', 'project_info.js']) {
  check(`${file}：不引用变更流水接口（流水只有 changes_page.js 读）`, !read(file).includes('/changes'), '');
}

// ---------------------------------------------------------------- 项目记录（stub 里 adopt 要用的形状）
let projectRecord = null;
try {
  const response = await liveFetch(BASE + '/api/machining-dfm/bootstrap', { cache: 'no-store' });
  const boot = await response.json();
  projectRecord = boot.project;
  console.log(`\n（已连上 ${BASE}：当前项目 ${projectRecord && projectRecord.id} · v${projectRecord && projectRecord.revision}）`);
} catch (error) {
  console.log(`\n✗ 连不上 ${BASE}（本自检要真 bootstrap 才能验"入口出现/面板渲染"）：${error.message}`);
  problems.push('连不上运行中的服务 ' + BASE + '：' + error.message);
}

// ---------------------------------------------------------------- A：管理员 + 接口正常
if (projectRecord) {
  console.log('\n=== A 管理员登录 + 回收站接口正常 ===');
  const pass = await runPass({ label: 'A', mode: 'ok', adminToken: 'admin-token', processToken: '', projectRecord });
  const { run, writeCalls, requestLog } = pass;
  check('[A] 整页脚本按 index.html 顺序全部加载', pass.loaded.length === loadFiles().length, pass.loaded.join(' '));
  check('[A] host 起来了', pass.started, '');
  check('[A] 回收站接口探到了（enabled=true）', run('TrashPage.available()') === true, String(run('TrashPage.available()')));
  const tabBar = String(run("document.getElementById('tabBar').innerHTML"));
  check('[A] 入口自动出现（没手动 probe）', tabBar.includes('回收站'), tabBar.slice(0, 200));

  // 面板：分组 + 四个字段
  await run("TrashPage.open('all')");
  await sleep(200);
  const panel = String(run("document.getElementById('trashBox').innerHTML"));
  const groups = JSON.parse(run('JSON.stringify(TrashPage._groups().map(function(g){return g.name;}))'));
  check('[A] 面板按 group 分组（基础库/字典/项目/工序/工序刀具行/版本履历）',
    ['基础库', '字典', '项目', '工序', '工序刀具行', '版本履历'].every(name => groups.includes(name)),
    JSON.stringify(groups));
  check('[A] 每行显示 title', panel.includes('兄弟(Brother) S500Z1') && panel.includes('机加工序-OP10'), '');
  check('[A] 每行显示 deleted_by（谁删的）', panel.includes('<td>admin</td>') && panel.includes('<td>process</td>'), '');
  check('[A] 每行显示 deleted_reason（为什么）', panel.includes('设备淘汰') && panel.includes('改工艺删掉'), '');
  check('[A] 每行显示 deleted_at（格式化成人话）', panel.includes('30 分钟前') || panel.includes('1 小时前'),
    panel.includes('30 分钟前') ? '' : '没找到"30 分钟前"');
  check('[A] 每行显示"被 N 个项目引用"', panel.includes('被 2 个项目引用') && panel.includes('被 0 个项目引用'), '');
  check('[A] 管理员才能看到恢复按钮', panel.includes('TrashPage.restore('), '');
  const selectionRow = String(run("TrashPage._rowHtml({table:'project_fixtures',entity:'selection',record_id:'s-1',title:'某夹具',group:'夹具选型'},0)"));
  check('[A] 夹具/检具选型的格子不给恢复按钮，并说明原因',
    !selectionRow.includes('TrashPage.restore(') && selectionRow.includes('没有独立恢复'), selectionRow.slice(0, 200));
  check('[A] 作用域：库页面的入口只看本库（设备库回收站只剩基础库一组）',
    run("(function(){var items=TrashPage._scopes.machines.tables;return JSON.stringify(items);})()") === '["machines"]', '');

  // 恢复基础库行：POST /trash/{table}/{id}/restore
  const items = JSON.parse(run('JSON.stringify(TrashPage._items())'));
  const machineIndex = items.findIndex(item => item.table === 'machines' && item.record_id === 'm-1');
  const before = writeCalls.length;
  await run(`TrashPage.restore(${machineIndex})`);
  await sleep(200);
  const calls = writeCalls.slice(before);
  const machineCall = calls.filter(call => call.includes('/trash/machines/m-1/restore')).pop() || '';
  check('[A] 点恢复发出正确的 POST（基础库行 → /trash/{table}/{id}/restore）',
    machineCall.startsWith('POST') && machineCall.includes('/trash/machines/m-1/restore'), machineCall || calls.join(' | '));
  check('[A] 恢复带上管理员令牌', machineCall.includes('Authorization=Bearer admin-token'), machineCall);
  const afterItems = JSON.parse(run('JSON.stringify(TrashPage._items())'));
  check('[A] 恢复成功后那一行从面板里消失',
    !afterItems.some(item => item.table === 'machines' && item.record_id === 'm-1'),
    JSON.stringify(afterItems.map(item => item.table + '/' + item.record_id)));
  check('[A] 面板提示恢复成功（并已重绘）',
    String(run("document.getElementById('trashBox').innerHTML")).includes('已恢复'), '');

  // 恢复项目业务行：POST /projects/{pid}/{seg}/{id}/restore + host.adopt() 接管读模型
  const rowIndex = afterItems.findIndex(item => item.table === 'project_processes' && item.record_id === 'pp-1');
  const revisionBefore = run('MachiningDFMHost.current().revision');
  const before2 = writeCalls.length;
  await run(`TrashPage.restore(${rowIndex})`);
  await sleep(250);
  const calls2 = writeCalls.slice(before2);
  const rowCall = calls2.filter(call => call.includes('/restore')).pop() || '';
  check('[A] 项目业务行的恢复走模块接口（/projects/{pid}/processes/{id}/restore）',
    rowCall.startsWith('POST') && /\/projects\/[^/]+\/processes\/pp-1\/restore/.test(rowCall), rowCall || calls2.join(' | '));
  check('[A] 恢复后走 host.adopt() 刷新读模型（版本号跟着服务端）',
    Number(run('MachiningDFMHost.current().revision')) === Number(revisionBefore) + 1,
    'v' + revisionBefore + ' → v' + run('MachiningDFMHost.current().revision'));
  const items2 = JSON.parse(run('JSON.stringify(TrashPage._items())'));
  check('[A] 项目业务行也从面板消失',
    !items2.some(item => item.table === 'project_processes' && item.record_id === 'pp-1'),
    JSON.stringify(items2.map(item => item.table)));

  // 恢复失败：后端返回的原因要写在面板里
  pass.setFailRestore('这台设备已经在回收站里了');
  const fixtureIndex = items2.findIndex(item => item.table === 'fixtures');
  const boomBefore = writeCalls.length;
  await run(`TrashPage.restore(${fixtureIndex})`);
  await sleep(150);
  const boomPanel = String(run("document.getElementById('trashBox').innerHTML"));
  check('[A] 恢复失败时把后端给的原因写在面板里',
    boomPanel.includes('恢复失败') && boomPanel.includes('这台设备已经在回收站里了'),
    boomPanel.includes('恢复失败') ? '' : boomPanel.slice(0, 200));
  check('[A] 恢复失败后那一行还留在面板里（不能假装成功）',
    JSON.parse(run('JSON.stringify(TrashPage._items())')).some(item => item.table === 'fixtures'), '');
  check('[A] 失败的恢复只发了一个写请求', writeCalls.length === boomBefore + 1, writeCalls.slice(boomBefore).join(' | '));
  pass.setFailRestore('');

  // 库页面入口
  check('[A] 四个库页面各有回收站入口（button() 出按钮）',
    ['machines', 'tools', 'fixtures', 'gauges'].every(key => run(`TrashPage.button('${key}')`).includes('TrashPage.open(')), '');

  // 变更流水时间线
  console.log('  -- 变更流水时间线 --');
  // 页签序号固定了（legacy_app.js 里 SI=4）：4 问题清单 / 5 版本履历
  const versionTab = 5;
  const changesBefore = requestLog.filter(call => call.includes('/changes')).length;
  run(`sw(${versionTab})`);
  await sleep(250);
  const timeline = String(run("document.getElementById('changesTimeline').innerHTML"));
  const filters = String(run("document.getElementById('changesFilters').innerHTML"));
  const changeCalls = requestLog.filter(call => call.includes('/changes'));
  check('[A] 切到版本履历页签会去读一次流水', changeCalls.length === changesBefore + 1,
    changeCalls.slice(changesBefore).join(' | '));
  const wanted = ['全部', '项目', '项目信息', '工序', '工序刀具行', '问题清单', '选型报价', '版本履历'];
  const missingFilters = wanted.filter(name => !filters.includes('>' + name + '<'));
  check('[A] 顶部一排按 entity 过滤的按钮都在', missingFilters.length === 0, missingFilters.join(', '));
  const order = ['删除工序：OP20', '整份保存：第 3 版', '刀具行：转速改成 800', '新增工序：OP10']
    .map(text => timeline.indexOf(text));
  check('[A] 时间线按时间倒序（新的在前）',
    order.every(index => index >= 0) && order[0] < order[1] && order[1] < order[2] && order[2] < order[3],
    JSON.stringify(order));
  check('[A] label 是主行、extra 折行小字显示',
    timeline.includes('class="chg-label"') && timeline.includes('class="chg-extra"')
    && timeline.includes('操作人：admin') && timeline.includes('涉及行：pp-1、pp-2'), timeline.slice(0, 200));
  check('[A] 时间线是只读的（没有写按钮）',
    !timeline.includes('TrashPage.restore') && !/onclick="ChangesPage\.(?!filter)/.test(timeline), '');
  const writeBefore = writeCalls.length;
  run("ChangesPage.filter('process')");
  await sleep(200);
  const filtered = String(run("document.getElementById('changesTimeline').innerHTML"));
  const filterCall = requestLog.filter(call => call.includes('/changes')).pop() || '';
  check('[A] 点过滤按钮带上 entity=process', filterCall.includes('entity=process'), filterCall);
  check('[A] 过滤后只剩工序的行',
    filtered.includes('新增工序：OP10') && filtered.includes('删除工序：OP20')
    && !filtered.includes('整份保存：第 3 版') && !filtered.includes('刀具行：转速改成 800'), filtered.slice(0, 200));
  check('[A] 过滤只读不写', writeCalls.length === writeBefore, writeCalls.slice(writeBefore).join(' | '));
  run("ChangesPage.filter('history')");
  await sleep(200);
  const empty = String(run("document.getElementById('changesTimeline').innerHTML"));
  check('[A] 空清单给一句人话', empty.includes('变更流水从打开开关那一刻开始记，之前的改动没有流水'), empty.slice(0, 200));
  check('[A] 空清单还标出当前筛选', empty.includes('当前筛选') && empty.includes('版本履历'), '');
  run("ChangesPage.filter('')");
  await sleep(200);
  check('[A] 过滤掉的工作流回到"全部"', String(run("document.getElementById('changesTimeline').innerHTML")).includes('整份保存：第 3 版'), '');

  // 纯重绘不重复打接口（这是刻意设计的：只有切页签/换项目/点过滤才拉流水）
  const renders = requestLog.filter(call => call.includes('/changes')).length;
  run('render();render();render();');
  await sleep(150);
  check('[A] 纯重绘不重复打流水接口',
    requestLog.filter(call => call.includes('/changes')).length === renders,
    requestLog.filter(call => call.includes('/changes')).slice(renders).join(' | '));

  // 页签上换项目：时间线要自己跟着换（不能还显示上一个项目的流水）
  const switched = requestLog.filter(call => call.includes('/changes')).length;
  run("MachiningDFMHost.adopt(Object.assign({},MachiningDFMHost.current(),{id:'other-project',revision:1}),'切到别的项目');");
  await sleep(250);
  const switchCalls = requestLog.filter(call => call.includes('/changes'));
  check('[A] 页签上换项目时时间线自己跟着拉一次',
    switchCalls.length === switched + 1 && switchCalls[switchCalls.length - 1].includes('/projects/other-project/changes'),
    switchCalls.slice(switched).join(' | '));
  await run(`(async function(){var record=await MachiningDFMHost.api('/projects/${projectRecord.id}');`
    + 'MachiningDFMHost.adopt(record,"切回原项目");})()');
  await sleep(250);
  check('[A] 切回原项目后时间线又回到这个项目的流水',
    String(run("document.getElementById('changesTimeline').innerHTML")).includes('整份保存：第 3 版')
    || requestLog.filter(call => call.includes('/changes')).pop().includes(projectRecord.id), '');

  // 自检全过程：没有意外的写请求
  const stray = writeCalls.filter(call => !call.includes('/restore'));
  check('[A] 自检里除了"恢复"没有别的写请求（写接口一律拦下、不落库）', stray.length === 0, stray.join(' | '));
  const errors = pass.messages.filter(message => message.startsWith('ERROR'));
  check('[A] 控制台没有 error', errors.length === 0, errors.join(' | '));
}

// ---------------------------------------------------------------- H：项目删除/恢复按钮走阶段 4 接口
if (projectRecord) {
  console.log('\n=== H 顶部「删除项目」走阶段 4 接口（管理员 + 写流水）===');
  const pass = await runPass({ label: 'H', mode: 'ok', adminToken: 'admin-token', processToken: '', projectRecord });
  const { run, writeCalls, requestLog, messages } = pass;
  const trashProbes = () => requestLog.filter(call => /\/trash$/.test(call)).length;

  // H1 管理员点删除 → DELETE /projects/{id}?reason=（带管理员令牌，不走老 /archive）
  const probesBefore = trashProbes();
  const before = writeCalls.length;
  await run("document.getElementById('serverArchive').onclick()");
  await sleep(300);
  const calls = writeCalls.slice(before);
  const del = calls.filter(call => call.startsWith('DELETE')).pop() || '';
  check('[H] 点「删除项目」发出 DELETE /projects/{id}（不是老的 POST /archive）',
    del.startsWith('DELETE') && del.includes('/projects/' + projectRecord.id) && !del.includes('/archive'),
    del || calls.join(' | '));
  check('[H] 删除带上原因（会写进变更流水与回收站）', /[?&]reason=/.test(del) && decodeURIComponent(del).includes('自检输入'), del);
  check('[H] 删除带上管理员令牌', del.includes('Authorization=Bearer admin-token'), del);
  check('[H] 删除后重新探了一次回收站（入口与面板跟着刷新）', trashProbes() > probesBefore,
    '探了 ' + trashProbes() + ' 次（之前 ' + probesBefore + '）');
  check('[H] 整段只发了这一个写请求', calls.length === 1, calls.join(' | '));
  check('[H] 删除不再碰老接口', !writeCalls.some(call => call.includes('/archive')), writeCalls.join(' | '));

  // H2 「已删除项目」里按钮变成"恢复项目" → POST /projects/{id}/restore
  // 先等自动保存那一次自己跑完：flush() 会把它提前拽出来，而 stub 的假 PUT 响应不是完整项目记录，
  // persist() 会因此抛错、把 onchange 后面的分支打断（写请求仍然被 harness 拦住，不会碰线上）。
  await sleep(1400);
  await run("(function(){var box=document.getElementById('serverShowArchived');box.checked=true;"
    + "box.onchange({target:box});})()");
  await sleep(300);
  check('[H] 切到「已删除项目」后按钮变成"恢复项目"',
    String(run("document.getElementById('serverArchive').textContent")).includes('恢复项目'),
    String(run("document.getElementById('serverArchive').textContent")));
  const before2 = writeCalls.length;
  await run("document.getElementById('serverArchive').onclick()");
  await sleep(300);
  const calls2 = writeCalls.slice(before2);
  const back = calls2.filter(call => call.includes('/restore')).pop() || '';
  check('[H] 恢复项目发出 POST /projects/{id}/restore',
    back.startsWith('POST') && new RegExp('/projects/' + projectRecord.id + '/restore').test(back),
    back || calls2.join(' | '));
  check('[H] 恢复项目也带管理员令牌（口径：恢复只给管理员）',
    back.includes('Authorization=Bearer admin-token'), back);
  check('[H] 恢复后按钮改回"删除项目"',
    String(run("document.getElementById('serverArchive').textContent")).includes('删除项目'),
    String(run("document.getElementById('serverArchive').textContent")));
  check('[H] 控制台没有 error',
    messages.filter(message => message.startsWith('ERROR')).length === 0,
    messages.filter(message => message.startsWith('ERROR')).join(' | '));
}

// ---------------------------------------------------------------- H3：没登录 / 非管理员点删除
if (projectRecord) {
  console.log('\n=== H3 没有管理员身份时点「删除项目」===');
  const pass = await runPass({ label: 'H3', mode: 'ok', adminToken: '', processToken: 'process-token', projectRecord });
  const { run, writeCalls, messages } = pass;
  const before = writeCalls.length;
  await run("document.getElementById('serverArchive').onclick()");
  await sleep(250);
  check('[H3] 非管理员点删除一个写请求都不发（页面自己挡住）', writeCalls.length === before,
    writeCalls.slice(before).join(' | '));
  check('[H3] 挡住时明确要求管理员身份',
    messages.some(message => message.includes('删除项目需要管理员身份')), messages.join(' | '));
  check('[H3] 控制台没有 error', messages.filter(message => message.startsWith('ERROR')).length === 0,
    messages.filter(message => message.startsWith('ERROR')).join(' | '));
}

// ---------------------------------------------------------------- B：只有工艺设置令牌
if (projectRecord) {
  console.log('\n=== B 工艺设置登录（能看不能恢复）===');
  const pass = await runPass({ label: 'B', mode: 'ok', adminToken: '', processToken: 'process-token', projectRecord });
  const { run, writeCalls } = pass;
  check('[B] 工艺设置也能看到回收站入口（读接口给两个角色）',
    run('TrashPage.available()') === true
    && String(run("document.getElementById('tabBar').innerHTML")).includes('回收站'), '');
  check('[B] 认得自己不是管理员', run('TrashPage.isAdmin()') === false, String(run('TrashPage.isAdmin()')));
  await run("TrashPage.open('all')");
  await sleep(200);
  const panel = String(run("document.getElementById('trashBox').innerHTML"));
  check('[B] 面板照样能看到行（title/删除人/原因/时间/引用数）',
    panel.includes('机加工序-OP10') && panel.includes('改工艺删掉') && panel.includes('被 2 个项目引用'), '');
  check('[B] 非管理员看不到恢复按钮（一个都没有）', !panel.includes('TrashPage.restore('), '');
  check('[B] 非管理员那一栏写的是"只有管理员能恢复"', panel.includes('只有管理员能恢复'), '');
  const items = JSON.parse(run('JSON.stringify(TrashPage._items())'));
  const index = items.findIndex(item => item.table === 'machines');
  const before = writeCalls.length;
  await run(`TrashPage.restore(${index})`);
  await sleep(120);
  check('[B] 硬调恢复也发不出写请求（页面自己挡住）', writeCalls.length === before, writeCalls.slice(before).join(' | '));
  check('[B] 挡住时把原因写在面板里',
    String(run("document.getElementById('trashBox').innerHTML")).includes('只有管理员能恢复'), '');
  check('[B] 控制台没有 error', pass.messages.filter(message => message.startsWith('ERROR')).length === 0,
    pass.messages.filter(message => message.startsWith('ERROR')).join(' | '));
}

// ---------------------------------------------------------------- C~F：接口不可用（优雅降级）
const degradeCases = [
  { mode: '401', title: 'C /trash 返回 401（没登录 / 令牌过期）', adminToken: 'bad-token' },
  { mode: '404', title: 'D /trash 返回 404（服务端没有这个接口）', adminToken: 'admin-token' },
  { mode: 'disabled', title: 'E /trash 返回 enabled=false（服务端没开回收站）', adminToken: 'admin-token' },
  { mode: 'noauth', title: 'F 一个字都没登录（连探都不该探）', adminToken: '', processToken: '' },
];
for (const item of degradeCases) {
  if (!projectRecord) break;
  console.log(`\n=== ${item.title} ===`);
  const pass = await runPass({ label: item.mode, mode: item.mode, adminToken: item.adminToken,
    processToken: item.processToken || '', projectRecord });
  const { run, writeCalls, requestLog } = pass;
  const tag = item.mode;
  check(`[${tag}] 判断为"没有回收站"`, run('TrashPage.available()') === false, String(run('TrashPage.available()')));
  const tabBar = String(run("document.getElementById('tabBar').innerHTML"));
  check(`[${tag}] 页签行入口整块消失`, !tabBar.includes('回收站'), tabBar.slice(0, 200));
  check(`[${tag}] 四个库页面入口也消失`,
    ['machines', 'tools', 'fixtures', 'gauges'].every(key => run(`TrashPage.button('${key}')`) === ''), '');
  check(`[${tag}] 项目页照常渲染（没有因为回收站报错）`,
    String(run("(function(){curTab=0;render();return document.getElementById('mainPanels').innerHTML;})()")).length > 1000, '');
  if (item.mode === 'noauth') {
    check(`[${tag}] 没登录就不打回收站接口（不做无谓请求）`,
      requestLog.filter(call => call.includes('/trash')).length === 0,
      requestLog.filter(call => call.includes('/trash')).join(' | '));
  }
  if (item.mode === '401' || item.mode === '404') {
    // 令牌过期/接口不在时，就算面板被硬打开，也只在面板里写一句后端给的原因，不抛异常
    await run("TrashPage.open('all')");
    await sleep(120);
    const panel = String(run("document.getElementById('trashBox').innerHTML"));
    check(`[${tag}] 硬打开面板时只把后端给的原因写在面板里（不抛异常）`,
      panel.includes('回收站读取失败'), panel.slice(0, 200));
  }
  check(`[${tag}] 控制台没有 error`, pass.messages.filter(message => message.startsWith('ERROR')).length === 0,
    pass.messages.filter(message => message.startsWith('ERROR')).join(' | '));
  check(`[${tag}] 没有写请求`, writeCalls.length === 0, writeCalls.join(' | '));
}

// ---------------------------------------------------------------- E：真实接口只读冒烟
// 上面几遍的 /changes 是 stub。这一遍**打真服务**（只读 GET）验一次真实数据的形状：
// 真接口早就有了（阶段 3b），要确认的是"页面拿真数据也能渲染成人话、不冒 undefined/NaN"。
// 回收站那边真接口要登录令牌，这里拿不到，只能验"没令牌时整块隐藏"（C/D 那两遍）。
if (projectRecord) {
  console.log('\n=== G 真实接口只读冒烟（GET /projects/{pid}/changes）===');
  const liveWrites = [];
  const liveOnly = (url, init = {}) => {
    const method = String((init && init.method) || 'GET').toUpperCase();
    if (method !== 'GET') {
      liveWrites.push(method + ' ' + url);
      throw new Error('本自检不许写线上数据：' + method + ' ' + url);
    }
    return liveFetch(url, { cache: 'no-store', ...init, method: 'GET' });
  };
  const elements = new Map();
  const stub = {
    getElementById: id => { if (!elements.has(id)) elements.set(id, makeElement('div', id)); return elements.get(id); },
    createElement: tag => makeElement(tag),
    body: makeElement('body'),
  };
  const sandbox = {
    console: { log() {}, warn() {}, error(...args) { console.log('    [页面 error]', ...args); } },
    document: stub, location: { href: BASE + '/machining-dfm' },
    TR: value => value, setTimeout, clearTimeout, Promise, JSON, Math, Date, Number, String, Boolean,
    Array, Object, RegExp, Error, TypeError, Map, Set, isNaN, parseFloat, parseInt,
    encodeURIComponent, decodeURIComponent, Intl,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.MachiningDFMHost = {
    current: () => ({ id: projectRecord.id, revision: projectRecord.revision }),
    api: async (path, options = {}) => {
      const response = await liveOnly(BASE + '/api/machining-dfm' + path, options);
      if (!response.ok) {
        let detail = '请求失败';
        try { detail = (await response.json()).detail || detail; } catch (error) { /* 保持默认 */ }
        throw new Error(detail);
      }
      return response.json();
    },
  };
  sandbox.fetch = liveOnly;
  const context = vm.createContext(sandbox);
  vm.runInContext(read('changes_page.js'), context, { filename: 'changes_page.js' });
  const run = expression => vm.runInContext(expression, context);
  let liveList = '';
  try {
    const section = String(run('ChangesPage.section()'));
    check('[G] 版本履历下半部分外壳渲染出来（含过滤按钮与时间线容器）',
      section.includes('id="changesFilters"') && section.includes('id="changesTimeline"')
      && section.includes('变更流水'), String(section.length) + ' 字符');
    const rows = await run('ChangesPage.reload()');
    liveList = String(run('ChangesPage._listHtml()'));
    const count = Array.isArray(rows) ? rows.length : -1;
    console.log(`     线上流水 ${count} 条，首行：${liveList.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120)}`);
    check('[G] 真数据渲染成主行 + 小字，且没有 undefined/NaN 泄漏',
      count > 0 && liveList.includes('class="chg-label"') && !/undefined|NaN/.test(liveList),
      count > 0 ? (String(liveList.length) + ' 字符') : '线上流水是空的，无法验证真数据渲染');
    check('[G] 真数据的实体/动作都翻成了中文（entity_labels / action_labels 用上了）',
      liveList.includes('项目'), '');
    check('[G] 只读冒烟没有发出任何写请求', liveWrites.length === 0, liveWrites.join(' | '));
  } catch (error) {
    problems.push('[G] 真实接口只读冒烟抛异常：' + error.message);
    console.log('  ✗ [G] 真实接口只读冒烟抛异常:', error.message);
  }
}

// ---------------------------------------------------------------- 收尾
check('自检全程没有未处理的 Promise 拒绝', rejections.length === 0, rejections.join(' | '));
console.log('\n' + (problems.length ? '发现问题:\n - ' + problems.join('\n - ') : '全部检查通过 ✓'));
process.exitCode = problems.length ? 1 : 0;
