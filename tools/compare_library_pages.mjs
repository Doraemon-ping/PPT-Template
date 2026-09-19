/* 结构性对比：旧渲染器（改造前 legacy_app.js 备份）与新模块的夹具库/检具库页面输出。
 * 用法：node tools/compare_library_pages.mjs
 * 旧文件优先取 $TEMP/legacy_app.backup.js，其次 git HEAD 里的版本，都没有就跳过。
 */
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { execSync } from 'node:child_process';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const STATIC = join(here, '..', 'static', 'machining_dfm');
const BASE = 'http://127.0.0.1:8002';

function oldSource() {
  const candidates = [process.env.TEMP && join(process.env.TEMP, 'legacy_app.backup.js'), join(here, 'legacy_app.old.js')];
  for (const path of candidates) if (path && existsSync(path)) return { path, source: readFileSync(path, 'utf8') };
  // 兜底：拿 git 里最后一次提交的版本（改造前的页面就是那一版）
  try {
    const source = execSync('git show HEAD:static/machining_dfm/legacy_app.js', { cwd: join(here, '..'), encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
    if (source && source.length) return { path: 'git HEAD:static/machining_dfm/legacy_app.js', source };
  } catch (error) {
    return null;
  }
  return null;
}

function makeElement(tag = 'div', id = '') {
  const classes = new Set();
  const element = {
    tagName: String(tag).toUpperCase(), id, _html: '', _text: '', value: '', checked: false, hidden: false,
    style: { cssText: '', display: '', setProperty() {} }, dataset: {}, children: [], childNodes: [], parentNode: null,
    classList: { add: (...n) => n.forEach(x => classes.add(x)), remove: (...n) => n.forEach(x => classes.delete(x)), toggle: () => false, contains: n => classes.has(n) },
    get className() { return [...classes].join(' '); },
    set className(v) { classes.clear(); String(v || '').split(/\s+/).filter(Boolean).forEach(n => classes.add(n)); },
    get innerHTML() { return element._html; }, set innerHTML(v) { element._html = String(v ?? ''); },
    get textContent() { return element._text; }, set textContent(v) { element._text = String(v ?? ''); },
    get outerHTML() { return element._html; },
    appendChild(c) { element.children.push(c); return c; }, insertBefore(c) { return c; }, removeChild(c) { return c; },
    remove() {}, setAttribute(k, v) { element[k] = v; }, getAttribute(k) { return element[k] ?? null; },
    removeAttribute(k) { delete element[k]; }, hasAttribute(k) { return element[k] !== undefined; },
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    click() {}, focus() {}, blur() {}, querySelector() { return null; }, querySelectorAll() { return []; },
    getElementsByTagName() { return []; }, getContext() { return { fillRect() {}, drawImage() {} }; },
  };
  return element;
}

function buildContext() {
  const elements = new Map();
  const documentStub = {
    readyState: 'complete', title: 't', documentElement: makeElement('html'), head: makeElement('head'), body: makeElement('body'),
    createElement: tag => makeElement(tag), createTextNode: t => ({ textContent: t }),
    getElementById: id => { if (!elements.has(id)) elements.set(id, makeElement('div', id)); return elements.get(id); },
    querySelector: s => (String(s).startsWith('#') ? documentStub.getElementById(String(s).slice(1)) : makeElement('div')),
    querySelectorAll: () => [], getElementsByTagName: () => [], addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
  };
  const store = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), clear: () => m.clear(), key: i => [...m.keys()][i] ?? null, get length() { return m.size; } }; };
  const sandbox = {
    console, document: documentStub,
    location: { href: BASE + '/machining-dfm', pathname: '/machining-dfm', search: '', hash: '', origin: BASE, reload() {} },
    navigator: { userAgent: 'node' }, localStorage: store(), sessionStorage: store(),
    alert() {}, confirm: () => true, prompt: () => 'x',
    setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask, requestAnimationFrame: fn => setTimeout(fn, 0), cancelAnimationFrame() {},
    getComputedStyle: () => ({ getPropertyValue: () => '' }), matchMedia: () => ({ matches: false, addEventListener() {} }),
    Image: class {}, FileReader: class { readAsDataURL() {} }, Blob: class {}, URL: { createObjectURL: () => 'blob:1', revokeObjectURL() {} },
    Headers, Request, Response, URLSearchParams, TextEncoder, TextDecoder, AbortController,
    Event: class { constructor(t) { this.type = t; } }, MutationObserver: class { observe() {} disconnect() {} },
    performance: { now: () => Date.now() }, structuredClone: v => JSON.parse(JSON.stringify(v)), crypto: { randomUUID: () => 'u' },
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; }, open() {}, close() {}, focus() {}, scrollTo() {},
    fetch: async url => {
      const target = String(url).startsWith('http') ? String(url) : BASE + String(url);
      const response = await fetch(target);
      return response;
    },
    Promise, JSON, Math, Date, Number, String, Boolean, Array, Object, RegExp, Error, TypeError, Map, Set, isNaN, parseFloat, parseInt,
    encodeURIComponent, decodeURIComponent, encodeURI, decodeURI, btoa, atob, Intl,
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.self = sandbox;
  const context = vm.createContext(sandbox);
  return { context, run: expression => vm.runInContext(expression, context), elements };
}

async function renderWith(legacyJs, label) {
  const { context, run } = buildContext();
  for (const name of ['host.js', 'machines.js', 'tools.js', 'library_pages.js', 'fixtures.js', 'gauges.js']) {
    vm.runInContext(readFileSync(join(STATIC, name), 'utf8'), context, { filename: name });
  }
  vm.runInContext(legacyJs, context, { filename: 'legacy_app_' + label + '.js' });
  await run('MachiningDFMHost.start()');
  await new Promise(resolve => setTimeout(resolve, 900));
  run('adUnl=true;dbUnl=true;checkAdm=function(){return true;};');
  // 等夹具/检具模块自己 load 完（新页面首次渲染会异步取字段表与字典）
  await new Promise(resolve => setTimeout(resolve, 900));
  const fixtures = run('bFixDB()');
  const gauges = run('bInspDB()');
  return { fixtures: String(fixtures || ''), gauges: String(gauges || ''), run };
}

function analyse(html) {
  const headers = [...html.matchAll(/<th>(.*?)<\/th>/g)].map(m => m[1].replace(/<[^>]+>/g, '').trim());
  const buttons = [...html.matchAll(/<button[^>]*>([\s\S]*?)<\/button>/g)].map(m => m[1].replace(/<[^>]+>/g, '').trim()).filter(Boolean);
  return {
    length: html.length,
    headers,
    uniqueHeaders: [...new Set(headers)],
    tableCount: (html.match(/<table>/g) || []).length,
    cardHeadings: [...html.matchAll(/<h3>([\s\S]*?)<\/h3>/g)].map(m => m[1].replace(/<[^>]+>/g, '').trim().slice(0, 40)),
    inputCount: (html.match(/<input/g) || []).length,
    buttonLabels: [...new Set(buttons)].slice(0, 14),
    hasNote: html.includes('class="note"'),
  };
}

const oldFile = oldSource();
if (!oldFile) {
  console.error('找不到改造前的 legacy_app.js 备份，跳过对比');
  process.exit(0);
}
console.log('旧文件:', oldFile.path);

let oldJs = oldFile.source;
// 旧文件里没有新模块，bFixDB/bInspDB 会走老渲染分支：把依赖的新脚本顺序保持一致即可
const before = await renderWith(oldJs, 'old');
const after = await renderWith(readFileSync(join(STATIC, 'legacy_app.js'), 'utf8'), 'new');

for (const [key, title] of [['fixtures', '夹具库'], ['gauges', '检具库']]) {
  console.log(`\n===== ${title} =====`);
  const a = analyse(before[key]);
  const b = analyse(after[key]);
  console.log('改造前:', JSON.stringify(a, null, 1));
  console.log('改造后:', JSON.stringify(b, null, 1));
  console.log('表头是否一致:', JSON.stringify(a.uniqueHeaders) === JSON.stringify(b.uniqueHeaders));
  console.log('按钮:', JSON.stringify(a.buttonLabels), '→', JSON.stringify(b.buttonLabels));
}
