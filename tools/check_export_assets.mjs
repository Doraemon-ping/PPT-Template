/* 无头自检：阶段 5（附件归项目）——把"图片是附件引用、导出时才内联"这条口径钉住。
 *
 * 口径来自 docs/MACHINING_BUSINESS_REFACTOR_PHASE5.md：
 *   - 库里（19 张表）**只存引用**：图片字段是 ``assets.id`` 外键，字节落在
 *     ``data/machining_dfm/assets/<kind>/<sha 前两位>/<sha>.<ext>``，DB 里一个 base64 都没有；
 *   - 读模型（``GET /bootstrap``、``GET /projects/{pid}``）给的是服务端 URL
 *     ``/api/machining-dfm/assets/<id>``，**不是** data URL；
 *   - 导出（JSON 备份 / PPT）前，页面用 legacy_app.js 的 ``inlineSheetImages()``
 *     把这些 URL 就地换成 data URL，保证导出文件离线也能显示图片。
 *
 * 阶段 5 · §7.0（导出改造）之后这里还守两件事：
 *   - 便携单文件 HTML 那一套（``buildPortableHTML`` / ``writeDataFile`` / ``dlPortable`` /
 *     ``exportHTML`` / ``DATA_MARKER`` / ``host.js`` 的 ``window.exportHTML`` 别名）**退休**，
 *     不留半死不活的接线；
 *   - 「数据保存与导出」卡片里的两条导出入口：**导出 JSON**（单文件、图内联，走 ``exportData()``）
 *     与**导出文件包(.zip)**（走服务端 ``GET /projects/{pid}/export.zip``，只读），
 *     并把包内结构（project.json + assets/ 原图 + README.txt、包内相对路径对得上）验一遍。
 *
 * 做法跟 check_trash_page.mjs / smoke_machining_page.mjs 一样：最小 DOM 垫片 + vm 沙箱，
 * 按 index.html 的脚本顺序把整页 JS 跑起来，打印 ``✓ / ✗`` 行。
 *
 * **全程只读**：
 *   - 对运行中的服务只发 GET（写请求拦下、记账、并且绝不放行到真服务）；
 *   - SQLite 用 ``node:sqlite`` 的 ``readOnly: true``（等价 ``sqlite3 file:...?mode=ro``），
 *     启动时会**真试着写一次**来证明这个句柄确实是只读的；
 *   - 沙箱里的"就地内联"只改内存里的读模型；文件包是服务端按需生成的只读响应，不落库。
 *
 * 用法：node tools\check_export_assets.mjs
 */
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { inflateRawSync } from 'node:zlib';
import { DatabaseSync } from 'node:sqlite';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = join(here, '..');
const STATIC = join(ROOT, 'static', 'machining_dfm');
const BASE = 'http://127.0.0.1:8002';
const API = BASE + '/api/machining-dfm';
const ASSET_PREFIX = '/api/machining-dfm/assets/';

const read = name => readFileSync(join(STATIC, name), 'utf8');
const liveFetch = globalThis.fetch;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

const problems = [];
const skips = [];
// 第 2 组里真 GET 回来的附件字节数，第 4 组拿去和 assets.size 对账
const httpSizes = new Map();
// 读模型里所有附件引用的路径（第 3 组逐个验"能不能被内联覆盖"）
let assetPaths = [];
const check = (label, ok, extra = '') => {
  if (!ok) problems.push(label + (extra ? ' → ' + extra : ''));
  console.log((ok ? '  ✓ ' : '  ✗ ') + label + (extra ? ' → ' + extra : ''));
};
// 「按当前实际行为跳过」：既不假装通过，也不把本次自检判红（用户确认前不改后端）
const skip = (label, reason) => {
  skips.push(label + ' → ' + reason);
  console.log('  – 跳过 ' + label + ' → ' + reason);
};
const show = value => {
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  if (text === undefined || text === null) return String(value);
  return text.length > 120 ? text.slice(0, 117) + '…' : text;
};
// 一条附件引用该长的样子：非 data:、长度合理、指向本服务的附件接口
const isAssetRef = value => typeof value === 'string' && value.startsWith(ASSET_PREFIX);

//: 已知的历史死链（2026-09-18 之前存的老版本里指着已经不存在的附件行）。
//: 字节在现有库与所有整库备份里都找不到了（_audit/probe_missing_assets.py 查过），
//: 所以这里按"已知清单"放行 —— 但清单外的任何新死链都会让检查失败（不许再涨）。
const KNOWN_DEAD_ASSETS = new Set([
  '6b9f6df42b9e4dfe804590392fa67fa6', // 第 17、18 版
  '18992028902247a9937792c70800b544', // 第 22 版
  '1199ce56d35b4dc89897280804698b6f', // 第 26 版
  'f1f723b5146549fe9d0c595928143ebb', // 第 30 版
  'b615c97dcad14e8197d40c906b6ff9d8', // 第 34 版
  '35e713887eaa449bb43efed57418ccd2', // 第 38 版
  'c9505b1ce5304845ad57a42e03791e9f', // 第 40 版
]);
const isDataUrl = value => typeof value === 'string' && value.startsWith('data:');
const isFilled = value => value !== null && value !== undefined && value !== '';
const refVerdict = value => {
  if (isDataUrl(value)) return '是 data: 内联（口径要求这里必须是引用）';
  if (!isAssetRef(value)) return '不是 /api/machining-dfm/assets/ 开头的引用';
  if (value.length >= 400) return '长度 ' + value.length + ' 字符（≥ 400，不像引用）';
  return '';
};

const rejections = [];
process.on('unhandledRejection', error => {
  rejections.push(String((error && error.message) || error));
});

// ---------------------------------------------------------------- 读模型小工具
// 把读模型里所有附件 URL 按路径捞出来（路径相对 state，例如 mdb[12].img / G.pI）
function collectAssetPaths(node, { prefix = '', base = 'state', depth = 0, out = [] } = {}) {
  if (depth > 8) return out;
  if (typeof node === 'string') {
    if (node.startsWith(ASSET_PREFIX)) out.push({ path: prefix, value: node });
    return out;
  }
  if (Array.isArray(node)) {
    node.forEach((item, index) => collectAssetPaths(item, { prefix: prefix + '[' + index + ']', base, depth: depth + 1, out }));
    return out;
  }
  if (node && typeof node === 'object') {
    for (const key of Object.keys(node)) {
      collectAssetPaths(node[key], { prefix: prefix ? prefix + '.' + key : key, base, depth: depth + 1, out });
    }
  }
  return out;
}
// 读模型路径 → 页面里的表达式（legacy_app.js 的 applyData 把 state.* 抄进这些全局变量）
const PAGE_ROOT = { mdb: 'MDB', tdb: 'TDB', fdb: 'FDB', idb: 'IDB', pr: 'PR', is: 'IS', vh: 'VH', G: 'G' };
function toPageExpr(relPath) {
  const match = /^([A-Za-z_][A-Za-z0-9_]*)([\s\S]*)$/.exec(relPath);
  if (!match || !Object.prototype.hasOwnProperty.call(PAGE_ROOT, match[1])) return null;
  return PAGE_ROOT[match[1]] + match[2];
}

// ---------------------------------------------------------------- zip 小工具
// 文件包（§7.0）只读自检用：从中央目录拿条目名，再按本地头 + zlib 解出内容。
function zipEntries(buffer) {
  let eocd = -1;
  for (let i = buffer.length - 22; i >= 0 && i >= buffer.length - 66000; i--) {
    if (buffer.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) return null;
  const total = buffer.readUInt16LE(eocd + 10);
  let offset = buffer.readUInt32LE(eocd + 16);
  const entries = [];
  for (let i = 0; i < total; i++) {
    if (buffer.readUInt32LE(offset) !== 0x02014b50) return null;
    const method = buffer.readUInt16LE(offset + 10);
    const compressed = buffer.readUInt32LE(offset + 20);
    const nameLength = buffer.readUInt16LE(offset + 28);
    const extraLength = buffer.readUInt16LE(offset + 30);
    const commentLength = buffer.readUInt16LE(offset + 32);
    const localOffset = buffer.readUInt32LE(offset + 42);
    entries.push({
      name: buffer.toString('utf8', offset + 46, offset + 46 + nameLength),
      method, compressed, localOffset,
    });
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}
function zipRead(buffer, entry) {
  const localName = buffer.readUInt16LE(entry.localOffset + 26);
  const localExtra = buffer.readUInt16LE(entry.localOffset + 28);
  const start = entry.localOffset + 30 + localName + localExtra;
  const raw = buffer.subarray(start, start + entry.compressed);
  if (entry.method === 0) return Buffer.from(raw);
  if (entry.method === 8) return inflateRawSync(raw);
  return Buffer.alloc(0);
}
// 包内 project.json 里的"包内相对路径"（assets/<id>.<ext>）
function collectPackagePaths(node, out = []) {
  if (typeof node === 'string') {
    if (node.startsWith('assets/')) out.push(node);
    return out;
  }
  if (Array.isArray(node)) { node.forEach(item => collectPackagePaths(item, out)); return out; }
  if (node && typeof node === 'object') {
    for (const key of Object.keys(node)) collectPackagePaths(node[key], out);
  }
  return out;
}

// ---------------------------------------------------------------- DOM 垫片
function makeElement(tag = 'div', id = '') {
  const listeners = {};
  const classes = new Set();
  const element = {
    tagName: String(tag).toUpperCase(), id, _html: '', _text: '', value: '', checked: false,
    hidden: false, disabled: false, files: null, type: '', accept: '', min: '', max: '', step: '',
    placeholder: '', title: '', href: '', download: '', src: '', alt: '', name: '', options: [],
    selectedIndex: 0, tabIndex: 0, offsetWidth: 0, offsetHeight: 0, scrollTop: 0, scrollHeight: 0,
    clientWidth: 0, nodeType: 1,
    style: { cssText: '', display: '', setProperty() {}, removeProperty() {} },
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
    get outerHTML() { return element._html; },
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

// ---------------------------------------------------------------- 一遍沙箱
// 返回沙箱句柄；只有 GET 会真的打到运行中的服务。
async function runPage() {
  const elements = new Map();
  const documentStub = {
    readyState: 'complete', title: 'machining', cookie: '',
    documentElement: makeElement('html'), head: makeElement('head'), body: makeElement('body'),
    createElement: tag => makeElement(tag),
    createTextNode: text => ({ textContent: text, nodeType: 3 }),
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
  const requestLog = [];      // 沙箱里发出的每一个请求（方法 + 绝对地址）
  const writeAttempts = [];   // 沙箱里试图发出的非 GET（拦下，绝不落到真服务）
  const blobs = [];           // 页面 new Blob(...) 造出来的东西（导出内容在这里抓）
  const fileReads = [];       // FileReader.readAsDataURL 读过的 blob

  const jsonResponse = (body, status = 200) => ({
    ok: status >= 200 && status < 300, status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body, text: async () => JSON.stringify(body), blob: async () => new Blob([]),
  });

  // FileReader：把真附件的字节真读成 data URL（导出内联的最后一跳就是它）
  class ShimFileReader {
    readAsDataURL(blob) {
      fileReads.push(blob);
      const bytes = blob && typeof blob.arrayBuffer === 'function' ? blob.arrayBuffer() : Promise.resolve(new ArrayBuffer(0));
      bytes.then(buffer => {
        this.result = 'data:' + ((blob && blob.type) || 'application/octet-stream') + ';base64,'
          + Buffer.from(buffer).toString('base64');
        if (this.onload) setTimeout(() => this.onload({ target: { result: this.result } }), 0);
      }).catch(error => { if (this.onerror) setTimeout(() => this.onerror(error), 0); });
    }
    readAsText(blob) { this.readAsDataURL(blob); }
  }
  class ShimBlob {
    constructor(parts, options) {
      this.parts = parts || [];
      this.type = (options && options.type) || '';
      blobs.push(this);
    }
  }

  const sandbox = {
    console: {
      log: (...args) => messages.push(args.join(' ')),
      warn: (...args) => messages.push('WARN ' + args.join(' ')),
      error: (...args) => messages.push('ERROR ' + args.join(' ')),
    },
    document: documentStub,
    location: { href: BASE + '/machining-dfm', pathname: '/machining-dfm', search: '', hash: '',
      origin: BASE, protocol: 'http:', host: '127.0.0.1:8002', reload() {} },
    navigator: { userAgent: 'node-check-export-assets', language: 'zh-CN', clipboard: null },
    localStorage: storage(),
    sessionStorage: storage(),
    alert: message => messages.push('alert: ' + message),
    confirm: () => true, prompt: () => '自检输入',
    setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask,
    requestAnimationFrame: fn => setTimeout(() => fn(Date.now()), 0), cancelAnimationFrame: () => {},
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    open() {}, close() {}, focus() {}, scrollTo() {},
    matchMedia: () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }),
    Image: class { set src(_value) { if (this.onload) setTimeout(() => this.onload(), 0); } },
    FileReader: ShimFileReader,
    Blob: ShimBlob,
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
    if (raw.startsWith('data:')) {
      // 页面拿 data URL 时会直接短路，不该走到网络
      return { ok: true, status: 200, headers: new Headers({ 'content-type': 'image/png' }),
        json: async () => ({}), text: async () => '', blob: async () => new ShimBlob([]) };
    }
    const target = raw.startsWith('http') ? raw : BASE + raw;
    const method = String((init && init.method) || 'GET').toUpperCase();
    requestLog.push(method + ' ' + target);
    if (method !== 'GET') {
      // 写请求：记账 + 拦死，绝不转发到线上
      writeAttempts.push(method + ' ' + target
        + (init.body && typeof init.body === 'string' ? ' ' + init.body.slice(0, 120) : ''));
      return jsonResponse({ ok: true, project: null, count: 0 });
    }
    return liveFetch(target, { ...init, method: 'GET', cache: 'no-store' });
  };

  const context = vm.createContext(sandbox);
  const run = expression => vm.runInContext(expression, context);
  const loaded = [];
  let startError = '';
  for (const name of loadFiles()) {
    try {
      vm.runInContext(read(name), context, { filename: name });
      loaded.push(name);
    } catch (error) {
      startError = '加载 ' + name + ' 抛异常：' + error.message;
      break;
    }
  }
  if (!startError) {
    try {
      await run('MachiningDFMHost.start()');
      await sleep(700);
    } catch (error) {
      startError = 'host.start() 抛异常：' + error.message;
    }
  }
  return { run, messages, requestLog, writeAttempts, blobs, fileReads, loaded, startError,
    resetAssetCache: () => run('_assetCache={}') };
}

// 扫页面读模型里剩余的附件 URL 引用（路径数组的 JSON）
const PAGE_SCAN = `(function(){
  var found=[];
  function walk(v,p,depth){
    if(depth>8)return;
    if(typeof v==='string'){ if(v.indexOf('${ASSET_PREFIX}')===0) found.push(p+' = '+v); return; }
    if(Array.isArray(v)){ for(var i=0;i<v.length;i++) walk(v[i], p+'['+i+']', depth+1); return; }
    if(v&&typeof v==='object'){ for(var k in v) walk(v[k], p?p+'.'+k:k, depth+1); }
  }
  walk({mdb:MDB,tdb:TDB,fdb:FDB,idb:IDB,pr:PR,is:IS,vh:VH,G:G}, '', 0);
  return JSON.stringify(found);
})()`;

// 内联是 17 个并发的"取图 + FileReader"任务，固定 sleep 会截断在半路上；
// 这里轮询到读模型里一处附件 URL 都不剩为止（导出入口不返回 Promise，只能这么等）。
async function waitForInlined(page, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  let rounds = 0;
  while (Date.now() < deadline) {
    rounds += 1;
    if (JSON.parse(page.run(PAGE_SCAN)).length === 0) return { ok: true, rounds };
    await sleep(100);
  }
  return { ok: false, rounds };
}

// ---------------------------------------------------------------- 5 静态检查：index.html 的脚本清单
// （编号 5 但先跑：后面的沙箱要用这里读出来的 index.html 脚本清单）
console.log('=== 5 静态检查：index.html 的脚本清单与导出接线（先跑，沙箱要用这份清单；阶段 4/5 一起守）===');
const html = read('index.html');
const scriptTags = [...html.matchAll(/<script src="\/static\/machining_dfm\/([\w.]+)\?v=([\w.-]+)"/g)];
const scriptOrder = scriptTags.map(match => match[1]);
// pptxgen.bundle.js 与另两个自检一样跳过（477 KB，与本次口径无关），但仍然检查它被页面引用
const loadFiles = () => scriptOrder.filter(name => name !== 'pptxgen.bundle.js');
check('index.html 的脚本清单读出来了', scriptOrder.length >= 10, scriptOrder.length + ' 个');
for (const name of ['trash_page.js', 'changes_page.js', 'pptxgen.bundle.js']) {
  check('index.html 的脚本清单里有 ' + name, scriptOrder.includes(name), scriptOrder.join(' '));
}
check('阶段 4 的两个新脚本排在 legacy_app.js 之前（legacy 渲染时要用）',
  scriptOrder.indexOf('trash_page.js') < scriptOrder.indexOf('legacy_app.js')
  && scriptOrder.indexOf('changes_page.js') < scriptOrder.indexOf('legacy_app.js'), '');
check('index.html 引用的脚本文件都在磁盘上',
  scriptOrder.filter(name => !existsSync(join(STATIC, name))).length === 0,
  scriptOrder.filter(name => !existsSync(join(STATIC, name))).join(', '));
check('index.html 里静态资源版本号仍然统一（project-v1）',
  new Set(scriptTags.map(match => match[2])).size === 1
  && [...new Set(scriptTags.map(match => match[2]))][0] === 'project-v1',
  [...new Set(scriptTags.map(match => match[2]))].join(', '));

// 导出的两条路：JSON 备份（单文件、图内联）与 PPT 都要先 inlineSheetImages()；
// 文件包走服务端（原图字节由服务端发），**不需要**内联，所以它不在这条清单里。
const legacySource = read('legacy_app.js');
const hostSource = read('host.js');
for (const fn of ['exportData', 'exportDFM']) {
  const body = new RegExp('function ' + fn + '\\([^)]*\\)\\{\\s*inlineSheetImages\\(\\)').test(legacySource);
  check('legacy_app.js：' + fn + '() 第一步就是 inlineSheetImages()', body, '');
}
check('legacy_app.js：inlineSheetImages() 覆盖四个库 + 项目四张图 + 工序 cI + 问题 bI/aI',
  /\[MDB,TDB,FDB,IDB\]/.test(legacySource)
  && /\['pI','pf','bInspImg','fInspImg'\]/.test(legacySource)
  && /row\.cI/.test(legacySource) && /row\.bI/.test(legacySource) && /row\.aI/.test(legacySource), '');

// ------------------- 阶段 5 · §7.0：便携单文件 HTML 退休、导出改成两条能兑现的路 -------------------
console.log('  -- §7.0：便携单文件 HTML 退休（函数、调用点、临时接线都不留）--');
for (const fn of ['buildPortableHTML', 'writeDataFile', 'dlPortable', 'exportHTML', 'saveAll', 'saveAs']) {
  check('legacy_app.js 里不再定义 ' + fn + '()（便携单文件那一套已退休）',
    !new RegExp('function ' + fn + '\\s*\\(').test(legacySource), '');
}
check('index.html / legacy_app.js / host.js 里都不再有 <!-- DATA_MARKER --> 这个标记',
  !legacySource.includes('<!-- DATA_MARKER -->') && !html.includes('<!-- DATA_MARKER -->')
  && !hostSource.includes('<!-- DATA_MARKER -->'), '');
check('host.js 不再把 window.exportHTML 指到 exportData（临时接线清理干净，不留名不副实的别名）',
  !hostSource.includes('exportHTML'), '');
check('页面里没有指向退休函数的按钮（onclick="buildPortableHTML()/writeDataFile()/dlPortable()/exportHTML()"）',
  !/onclick="(buildPortableHTML|writeDataFile|dlPortable|exportHTML)\(\)"/.test(legacySource), '');
// 两条导出入口：两张卡片（项目信息 + 数据保存与导出）里都要能点到
const packageButtons = (legacySource.match(/onclick="exportPackage\(\)"/g) || []).length;
const jsonButtons = (legacySource.match(/onclick="exportData\(\)"/g) || []).length;
check('legacy_app.js：「导出文件包(.zip)」入口在两张卡片上都有', packageButtons === 2, packageButtons + ' 个');
check('legacy_app.js：「导出 JSON」入口在两张卡片上都有', jsonButtons === 2, jsonButtons + ' 个');
check('两条导出入口的文案都写明区别（单文件·图内联 / 文件包(.zip)）',
  legacySource.includes('导出 JSON（单文件·图内联）') && legacySource.includes('导出文件包(.zip)'), '');
const packageBody = (/function exportPackage\(\)\{([\s\S]*?)\n\}/.exec(legacySource) || [, ''])[1];
check('exportPackage() 只发一个 GET 打新接口 /projects/{pid}/export.zip（不带 method / body，纯只读）',
  packageBody.includes("'/api/machining-dfm/projects/'") && packageBody.includes("'/export.zip'")
  && packageBody.includes("fetch(url,{cache:'no-store'})") && !/method\s*:/.test(packageBody),
  packageBody ? packageBody.length + ' 字符' : '没找到函数体');

// ---------------------------------------------------------------- 1 读模型里是引用不是 base64
console.log('\n=== 1 读模型（真连 ' + BASE + '，只读）里是附件引用，不是 base64 ===');
let bootstrap = null;
let bootstrapText = '';
let project = null;
let projectText = '';
try {
  const bootResponse = await liveFetch(API + '/bootstrap', { cache: 'no-store' });
  bootstrapText = await bootResponse.text();
  bootstrap = JSON.parse(bootstrapText);
  const pid = bootstrap.project && bootstrap.project.id;
  const projectResponse = await liveFetch(API + '/projects/' + encodeURIComponent(pid), { cache: 'no-store' });
  projectText = await projectResponse.text();
  project = JSON.parse(projectText);
  console.log('  已连上 ' + BASE + '：项目 ' + pid + ' · v' + bootstrap.project.revision
    + ' · bootstrap ' + bootstrapText.length + ' 字符 · projects/{pid} ' + projectText.length + ' 字符');
} catch (error) {
  problems.push('连不上运行中的服务 ' + BASE + '：' + error.message);
  console.log('  ✗ 连不上 ' + BASE + '：' + error.message);
}

if (bootstrap && project) {
  for (const [label, text] of [['bootstrap', bootstrapText], ['projects/{pid}', projectText]]) {
    const inlineHits = text.match(/data:image/g) || [];
    check('[' + label + '] 整份读模型里一个 data:image 都没有（正则扫整份 JSON）',
      inlineHits.length === 0, inlineHits.length + ' 处');
    const base64Hits = text.match(/;base64,/g) || [];
    check('[' + label + '] 整份读模型里一个 ;base64, 都没有', base64Hits.length === 0, base64Hits.length + ' 处');
    check('[' + label + '] 读模型里的附件地址都是相对路径（inlineSheetImages 的 indexOf(...)===0 依赖它）',
      !/https?:\/\/[^"]*\/api\/machining-dfm\/assets\//.test(text), '');
  }

  // 项目四张图（旧键 pI / pf / bInspImg / fInspImg）
  const G = (bootstrap.project.state && bootstrap.project.state.G) || {};
  const PHOTO_SLOTS = [
    ['G.pI（产品图片 · product_photo_id）', 'pI'],
    ['G.pf（产品图片2 · product2_photo_id）', 'pf'],
    ['G.bInspImg（毛坯检具图 · blank_insp_photo_id）', 'bInspImg'],
    ['G.fInspImg（成品检具图 · final_insp_photo_id）', 'fInspImg'],
  ];
  check('四张项目图的槽位都在读模型里（pI / pf / bInspImg / fInspImg）',
    PHOTO_SLOTS.every(([, key]) => key in G), Object.keys(G).filter(k => k in { pI: 1, pf: 1, bInspImg: 1, fInspImg: 1 }).join(', '));
  const filledPhotos = [];
  for (const [label, key] of PHOTO_SLOTS) {
    if (!isFilled(G[key])) {
      console.log('  – ' + label + '：线上为空（' + show(G[key]) + '），无值可验');
      continue;
    }
    filledPhotos.push({ label, key, value: G[key] });
    check(label + ' 是附件引用（非 data: / < 400 字符 / 指向 /assets/）',
      refVerdict(G[key]) === '', show(G[key]) + (refVerdict(G[key]) ? ' ← ' + refVerdict(G[key]) : ''));
  }
  check('四张项目图里至少有一张有值（否则第 2、3 组断言无从下手）',
    filledPhotos.length > 0, filledPhotos.map(item => item.key).join(', ') || '一张都没有');

  // 工序夹具示意图 cI、问题清单 bI/aI
  const processes = (bootstrap.project.state && bootstrap.project.state.pr) || [];
  const issues = (bootstrap.project.state && bootstrap.project.state.is) || [];
  check('pr[] 每行都有 cI 槽位（工序夹具示意图的旧键）',
    processes.length > 0 && processes.every(row => 'cI' in row), processes.length + ' 行');
  check('is[] 每行都有 bI / aI 槽位（问题清单优化前/后的旧键）',
    issues.length > 0 && issues.every(row => 'bI' in row && 'aI' in row), issues.length + ' 行');
  const slotRefs = [];
  processes.forEach((row, index) => { if (isFilled(row.cI)) slotRefs.push({ label: 'pr[' + index + '].cI', value: row.cI }); });
  issues.forEach((row, index) => {
    if (isFilled(row.bI)) slotRefs.push({ label: 'is[' + index + '].bI', value: row.bI });
    if (isFilled(row.aI)) slotRefs.push({ label: 'is[' + index + '].aI', value: row.aI });
  });
  check('pr[].cI / is[].bI / is[].aI 只要有值就必须是附件引用（不许是 data:）',
    slotRefs.every(item => refVerdict(item.value) === ''),
    slotRefs.length ? slotRefs.map(item => item.label + '=' + show(item.value)).join(' | ')
      : '线上这些槽位全是空值，本断言当前为"空集合通过"');
  if (slotRefs.length === 0) {
    skip('pr[].cI / is[].bI / is[].aI 的取值断言（非空集合）',
      '线上 ' + processes.length + ' 道工序的夹具示意图与 ' + issues.length + ' 条问题清单的前/后图当前都是空的，没有真值可验；'
      + '第 3 组会用真实附件地址塞进这三个槽位补测它们的导出内联');
  }
  for (const item of slotRefs) {
    check(item.label + ' 是附件引用（非 data: / < 400 字符 / 指向 /assets/）',
      refVerdict(item.value) === '', show(item.value));
  }

  // 读模型里所有附件 URL
  assetPaths = collectAssetPaths(bootstrap.project.state);
  const assetUrls = [...new Set(assetPaths.map(item => item.value))];
  console.log('  读模型里附件引用 ' + assetPaths.length + ' 处 / ' + assetUrls.length + ' 个不同 id');
  for (const item of assetPaths.slice(0, 4)) console.log('    ' + item.path + ' = ' + item.value);
  if (assetPaths.length > 4) console.log('    …（共 ' + assetPaths.length + ' 处）');
  check('读模型里的附件引用数量 > 0', assetPaths.length > 0, String(assetPaths.length));
  check('读模型里每个附件引用都指向 /api/machining-dfm/assets/<id>',
    assetPaths.every(item => /^\/api\/machining-dfm\/assets\/[A-Za-z0-9]+$/.test(item.value)),
    assetPaths.filter(item => !/^\/api\/machining-dfm\/assets\/[A-Za-z0-9]+$/.test(item.value)).map(item => item.path).join(', '));

  // ---------------------------------------------------------------- 2 附件真的取得到
  console.log('\n=== 2 附件真的取得到（对每个引用发真 GET，只读）===');
  let fetchFailures = 0;
  for (const url of assetUrls) {
    try {
      const response = await liveFetch(BASE + url, { cache: 'no-store' });
      const buffer = Buffer.from(await response.arrayBuffer());
      const type = String(response.headers.get('content-type') || '');
      const ok = response.status === 200 && type.startsWith('image/') && buffer.length > 0;
      if (!ok) fetchFailures += 1;
      httpSizes.set(url, buffer.length);
      if (!ok) console.log('  ✗ ' + url + ' → ' + response.status + ' ' + type + ' ' + buffer.length + ' 字节');
    } catch (error) {
      fetchFailures += 1;
      console.log('  ✗ ' + url + ' → ' + error.message);
    }
  }
  check('读模型里的 ' + assetUrls.length + ' 个附件引用全部取得到（200 + content-type 是图片 + 字节 > 0）',
    fetchFailures === 0 && assetUrls.length > 0, fetchFailures ? fetchFailures + ' 个取不到' : '');
  const sample = filledPhotos.length ? BASE + filledPhotos[0].value : BASE + assetUrls[0];
  const sampleResponse = await liveFetch(sample, { cache: 'no-store' });
  const sampleBytes = Buffer.from(await sampleResponse.arrayBuffer());
  check('抽一个 *_photo_id 对应的 URL 亲眼验一遍：200 + 图片 + 有字节',
    sampleResponse.status === 200
    && String(sampleResponse.headers.get('content-type') || '').startsWith('image/')
    && sampleBytes.length > 0,
    sampleResponse.status + ' · ' + sampleResponse.headers.get('content-type') + ' · ' + sampleBytes.length + ' 字节 · '
      + (filledPhotos.length ? filledPhotos[0].key : assetUrls[0]));
  const missingId = 'deadbeefdeadbeefdeadbeefdeadbeef';
  const missingResponse = await liveFetch(API + '/assets/' + missingId, { cache: 'no-store' });
  check('不存在的附件 id 返回 404（只读 GET，不碰任何写接口）',
    missingResponse.status === 404, 'GET /assets/' + missingId + ' → ' + missingResponse.status);

  // ---------------------------------------------------------------- 3 导出时才内联
  console.log('\n=== 3 导出时才内联（vm 沙箱里真跑 inlineSheetImages()）===');
  const page = await runPage();
  const { run, requestLog, writeAttempts } = page;
  check('整页脚本按 index.html 顺序全部加载', page.loaded.length === loadFiles().length,
    page.loaded.length + '/' + loadFiles().length + (page.startError ? ' | ' + page.startError : ''));
  check('host 起来了（真实 bootstrap）', !page.startError, page.startError);
  if (page.startError) {
    problems.push('沙箱没能把整页跑起来：' + page.startError);
  } else {
    check('inlineSheetImages() 在页面里（导出入口第一步就是它）', run('typeof inlineSheetImages') === 'function', String(run('typeof inlineSheetImages')));
    check('沙箱里的读模型来自真服务（MDB / G 都有内容）',
      Number(run('MDB.length')) > 0 && run('typeof G') === 'object', 'MDB ' + run('MDB.length') + ' 行');
    check('页面读模型里的行数/键与读模型一致（mdb / pr / is）',
      Number(run('MDB.length')) === ((bootstrap.project.state.mdb || []).length)
      && Number(run('PR.length')) === ((bootstrap.project.state.pr || []).length)
      && Number(run('IS.length')) === ((bootstrap.project.state.is || []).length),
      'MDB ' + run('MDB.length') + ' / PR ' + run('PR.length') + ' / IS ' + run('IS.length'));

    // 内联前：页面读模型里应当是 URL，一个 data: 都没有
    const beforeRefs = JSON.parse(run(PAGE_SCAN));
    check('内联前：页面读模型里的图片都是附件 URL（' + beforeRefs.length + ' 处）',
      beforeRefs.length > 0, beforeRefs.slice(0, 3).join(' | '));
    check('页面读模型与读模型一一对上（附件引用数相同：' + assetPaths.length + '）',
      beforeRefs.length === assetPaths.length, beforeRefs.length + ' 处 vs 读模型 ' + assetPaths.length + ' 处');
    const beforeDataUrls = Number(run('(function(){var n=0;function w(v,d){if(d>8)return;if(typeof v==="string"){if(v.indexOf("data:")===0)n++;return}if(Array.isArray(v)){v.forEach(function(x){w(x,d+1)});return}if(v&&typeof v==="object"){for(var k in v)w(v[k],d+1)}}w({mdb:MDB,tdb:TDB,fdb:FDB,idb:IDB,pr:PR,is:IS,vh:VH,G:G},0);return n})()'));
    check('内联前：页面读模型里没有一个 data: 图片（页面上是引用，不是 base64）',
      beforeDataUrls === 0, beforeDataUrls + ' 处');

    // 记住容器对象与"某个带图的行"的下标，用来证明"就地改"（字符串本身是不可变的，
    // 所以只能靠对象身份 + 通过旧引用读回新值来判断，不能拿内联前的字符串比对）
    run('window.__assetProbe={G:G,mdb:MDB,pr:PR,is:IS,idx:(function(){for(var i=0;i<MDB.length;i++)if(MDB[i].img)return i;return -1})()};true');
    const probeIndex = Number(run('window.__assetProbe.idx'));

    // 导出入口先跑：exportData()（JSON 备份）自己会去 inlineSheetImages()
    const blobStart = page.blobs.length;
    const exportStart = requestLog.length;
    const fileReadStart = page.fileReads.length;
    await run('exportData()');
    const inlined = await waitForInlined(page);
    await sleep(200);   // 等 exportData 的 .then（拼 JSON 文件）跑完
    const exportCalls = requestLog.slice(exportStart);

    check('exportData()（JSON 备份）第一步自己就走了附件接口取图（' + exportCalls.length + ' 个请求）',
      exportCalls.length > 0 && exportCalls.every(call => call.startsWith('GET ') && call.includes('/assets/')),
      exportCalls.slice(0, 2).join(' | '));
    check('取图用的是真附件字节（FileReader 真读到了 blob）',
      page.fileReads.length - fileReadStart === exportCalls.length
      && page.fileReads.slice(fileReadStart).every(blob => blob && typeof blob.arrayBuffer === 'function'),
      (page.fileReads.length - fileReadStart) + ' 个 blob / ' + exportCalls.length + ' 个请求');
    const exported = page.blobs.slice(blobStart).filter(blob => String(blob.type).includes('json'));
    check('exportData()（JSON 备份）产出了一份导出文件', exported.length === 1,
      exported.length + ' 个 json blob；' + page.blobs.slice(blobStart).map(blob => blob.type).join(', '));
    const payload = exported.length ? String(exported[0].parts[0]) : '';
    check('导出文件里的图片是内联的 data URL（离线打开也有图）',
      /data:image\/[a-z+]+;base64,/.test(payload), payload ? payload.length + ' 字符' : '没抓到内容');
    check('导出文件里不再残留 ' + ASSET_PREFIX + ' 引用',
      payload.length > 0 && !payload.includes(ASSET_PREFIX),
      payload.includes(ASSET_PREFIX) ? '还残留引用' : '');

    const afterRefs = JSON.parse(run(PAGE_SCAN));
    check('内联后：页面读模型里一处附件 URL 都不剩（导出要用的字段全换成 data:）',
      inlined.ok && afterRefs.length === 0,
      afterRefs.slice(0, 5).join(' | ') || ('等了 ' + inlined.rounds + ' 轮'));
    check('内联是就地改读模型（内联前捕获的同一个容器对象 + 同一个行对象，读回的字段已是 data:）',
      run('window.__assetProbe.G===G&&window.__assetProbe.mdb===MDB&&window.__assetProbe.pr===PR&&window.__assetProbe.is===IS')
      && probeIndex >= 0
      && run('String(window.__assetProbe.mdb[window.__assetProbe.idx].img).indexOf("data:")===0')
      && run('String(G.pI).indexOf("data:")===0'),
      'MDB[' + probeIndex + '].img 现在是 ' + show(String(run('String(MDB[' + probeIndex + '].img)')).slice(0, 40)));
    check('内联出来的确实是图片 data URL（不是空串/占位）',
      /^data:image\/[a-z+]+;base64,[A-Za-z0-9+/=]{100,}$/.test(String(run('G.pI'))),
      show(String(run('G.pI')).slice(0, 48)));
    check('内联只读不写：整个导出流程零写请求（非 GET 一个都没有）',
      writeAttempts.length === 0, writeAttempts.join(' | '));

    // 线上 cI / bI / aI 是空的：塞进真实附件地址来补测这三个槽位
    const probeUrl = filledPhotos.length ? filledPhotos[0].value : chooseRef(project.state);
    run('PR[0].cI=' + JSON.stringify(probeUrl) + ';IS[0].bI=' + JSON.stringify(probeUrl)
      + ';IS[0].aI=' + JSON.stringify(probeUrl) + ';true');
    page.resetAssetCache();
    const slotStart = requestLog.length;
    await run('inlineSheetImages()');
    await sleep(200);
    check('工序夹具示意图 PR[0].cI 走同一套内联（塞真附件地址 → 变 data:）',
      String(run('String(PR[0].cI)')).startsWith('data:'), show(String(run('PR[0].cI')).slice(0, 40)));
    check('问题清单 IS[0].bI / aI 走同一套内联（塞真附件地址 → 变 data:）',
      String(run('String(IS[0].bI)')).startsWith('data:') && String(run('String(IS[0].aI)')).startsWith('data:'),
      show(String(run('IS[0].bI')).slice(0, 40)));
    check('这三个槽位的内联也走附件接口', requestLog.slice(slotStart).some(call => call.includes('/assets/')),
      requestLog.slice(slotStart).join(' | '));
    check('补测期间仍然零写请求', writeAttempts.length === 0, writeAttempts.join(' | '));

    // 「读模型里所有附件字段是否都能被内联覆盖」——读模型里逐个路径验，字段一漏这里就红
    const uncovered = [];
    for (const item of assetPaths) {
      const expression = toPageExpr(item.path);
      if (!expression) { uncovered.push(item.path + '（读模型路径没能翻成页面表达式）'); continue; }
      const value = String(run('(function(){try{return String(' + expression + ')}catch(e){return "__ERR__:"+e.message}})()'));
      if (value.startsWith('data:')) continue;
      if (value.startsWith('__ERR__')) { uncovered.push(item.path + ' → ' + expression + ' ' + value); continue; }
      uncovered.push(item.path + ' → ' + expression + ' = ' + show(value));
    }
    check('读模型里每一条附件引用都在页面里被内联覆盖（漏一个字段这里就红）',
      uncovered.length === 0, uncovered.slice(0, 6).join(' | '));
    check('沙箱全程零写请求（非 GET 一个都没有）', writeAttempts.length === 0,
      writeAttempts.length ? writeAttempts.join(' | ') : '');
  }

  // ---------------------------------------------------------- 3b 文件包导出入口（服务端出包）
  // 换一个干净沙箱，让导出入口成为**第一个**动作：这才验得到"入口自己发 GET"。
  console.log('  -- 3b 文件包导出入口（干净沙箱：入口自己发一个 GET，只读）--');
  const pageB = await runPage();
  if (pageB.startError) {
    problems.push('3b 沙箱没能把整页跑起来：' + pageB.startError);
    check('[3b] host 起来了', false, pageB.startError);
  } else {
    check('[3b] window.exportHTML 不存在了（host.js 的临时接线清理干净）',
      pageB.run('typeof window.exportHTML') === 'undefined', pageB.run('String(window.exportHTML)'));
    check('[3b] 便携单文件那一套在页面里也不存在（buildPortableHTML / writeDataFile / dlPortable）',
      pageB.run('[typeof buildPortableHTML,typeof writeDataFile,typeof dlPortable].join(",")')
        === 'undefined,undefined,undefined',
      pageB.run('[typeof buildPortableHTML,typeof writeDataFile,typeof dlPortable].join(",")'));
    check('[3b] 两个导出入口都是页面上的真函数（exportData / exportPackage）',
      pageB.run('typeof exportData') === 'function' && pageB.run('typeof exportPackage') === 'function', '');
    const pidB = String(pageB.run('(MachiningDFMHost.current()||{}).id||""'));
    check('[3b] 页面知道当前服务端项目 id（文件包要用它拼地址）', pidB.length > 0, pidB);

    const pkgStart = pageB.requestLog.length;
    const writeStart = pageB.writeAttempts.length;
    pageB.run('exportPackage()');
    await sleep(800);      // 等 fetch → blob → 触发下载这一串跑完
    const pkgCalls = pageB.requestLog.slice(pkgStart);
    const expectedCall = 'GET ' + API + '/projects/' + pidB + '/export.zip';
    check('[3b] 点「导出文件包(.zip)」只发一个 GET 到新接口（' + expectedCall + '）',
      pkgCalls.length === 1 && pkgCalls[0] === expectedCall, pkgCalls.join(' | ') || '(一个请求都没发)');
    check('[3b] 文件包导出全程零写请求（非 GET 一个都没有）',
      pageB.writeAttempts.length === writeStart, pageB.writeAttempts.join(' | '));
    check('[3b] 文件包导出不内联图片（原图由服务端发，页面不该为一个图片发 /assets/ 请求）',
      !pkgCalls.some(call => call.includes('/assets/')), pkgCalls.join(' | '));

    // 「导出 JSON」这条入口还是原来的 exportData（先内联、产出单文件 json）
    const blobStartB = pageB.blobs.length;
    await pageB.run('exportData()');
    const inlinedB = await waitForInlined(pageB);
    await sleep(200);
    const jsonBlobs = pageB.blobs.slice(blobStartB).filter(blob => String(blob.type).includes('json'));
    check('[3b] 点「导出 JSON」走 exportData()：先内联再产出一份 .json 备份',
      jsonBlobs.length === 1 && inlinedB.ok
      && /data:image\/[a-z+]+;base64,/.test(String(jsonBlobs[0].parts[0])),
      jsonBlobs.length + ' 个 json blob；内联等了 ' + inlinedB.rounds + ' 轮');
    check('[3b] 两条导出入口加起来仍然零写请求', pageB.writeAttempts.length === writeStart,
      pageB.writeAttempts.join(' | '));
  }

  // ---------------------------------------------------------- 3c 包内结构（直接 GET 真服务，只读）
  console.log('  -- 3c 包内结构（直接 GET 新接口，只读：project.json + 引用到的附件 + README.txt）--');
  const pkgUrl = API + '/projects/' + encodeURIComponent(project.id) + '/export.zip';
  const pkgResponse = await liveFetch(pkgUrl, { cache: 'no-store' });
  const pkgType = String(pkgResponse.headers.get('content-type') || '');
  const disposition = String(pkgResponse.headers.get('content-disposition') || '');
  let pkgDetail = '';
  try { pkgDetail = String(((await pkgResponse.clone().json()) || {}).detail || ''); } catch (error) { pkgDetail = ''; }
  if (pkgResponse.status === 404 && pkgDetail === 'Not Found') {
    // 运行中的进程还是旧代码（没重启）：FastAPI 默认的 "Not Found" 与"项目不存在"的中文 detail 好区分。
    // 这里不假装通过：明说是部署状态，重启服务后同一组检查自动变成真检查（pytest 已对同一接口逐字节验过）。
    skip('文件包接口的包内结构（project.json + assets/ 原图 + README.txt、包内路径对得上、只读）',
      '运行中的服务还是旧代码：GET ' + pkgUrl + ' → 404 的 FastAPI 默认 "Not Found"（老进程里没有这条路由）。'
      + '重启服务后这一组会自动生效；同一接口的形状与字节一致已由 '
      + 'tests/test_machining_export_package.py 在真应用上验过');
  } else {
  check('[3c] GET 文件包接口 → 200 + application/zip',
    pkgResponse.status === 200 && pkgType.startsWith('application/zip'),
    pkgResponse.status + ' ' + pkgType + (pkgDetail ? ' ' + pkgDetail : ''));
  check('[3c] Content-Disposition 是附件下载 + DFM_<项目名>.zip（中文项目名走 filename*）',
    /^attachment; filename="DFM_[^"]*\.zip"; filename\*=UTF-8''DFM_[^;]*\.zip$/.test(disposition), disposition);
  const pkgBuffer = Buffer.from(await pkgResponse.arrayBuffer());
  check('[3c] 包体是真 zip（PK 头）', pkgBuffer.subarray(0, 2).toString('latin1') === 'PK',
    pkgBuffer.length + ' 字节');
  const entries = zipEntries(pkgBuffer);
  check('[3c] zip 中央目录读得出来', !!entries, entries ? entries.length + ' 条' : '解析失败');
  if (entries) {
    const names = new Set(entries.map(entry => entry.name));
    const readModelIds = [...new Set(assetPaths.map(item => item.value.split('/').pop().split('?')[0]))];
    check('[3c] 包里正好是 project.json + README.txt + 本项目引用到的每个附件（不多不少）',
      names.size === readModelIds.length + 2 && names.has('project.json') && names.has('README.txt')
      && readModelIds.every(id => [...names].some(name => name.startsWith('assets/' + id + '.'))),
      [...names].join(', '));
    check('[3c] 包内的附件条目就是读模型里引用到的那些 id（' + readModelIds.length + ' 个）',
      [...names].filter(name => name.startsWith('assets/')).length === readModelIds.length
      && readModelIds.every(id => [...names].some(name => name.startsWith('assets/' + id + '.'))),
      [...names].filter(name => name.startsWith('assets/')).join(', '));
    const readmeEntry = entries.find(entry => entry.name === 'README.txt');
    const readmeText = readmeEntry ? zipRead(pkgBuffer, readmeEntry).toString('utf8') : '';
    check('[3c] README.txt 在包里、能按 UTF-8 解开，并写明"图片在 assets/、由哪个服务导出"',
      readmeText.includes('assets/') && readmeText.includes('machining-dfm-package')
      && readmeText.includes('机加 DFM 项目工作台'),
      readmeText.split('\n')[0] || '(空)');
    const projectEntry = entries.find(entry => entry.name === 'project.json');
    const jsonText = projectEntry ? zipRead(pkgBuffer, projectEntry).toString('utf8') : '';
    let packageJson = null;
    try { packageJson = JSON.parse(jsonText); } catch (error) { packageJson = null; }
    check('[3c] 包里的 project.json 是合法 JSON（与读模型同一份形状 + _export 块）',
      !!packageJson && packageJson.id === project.id
      && packageJson.state && packageJson._export
      && packageJson._export.format === 'machining-dfm-package'
      && packageJson._export.project_id === project.id,
      packageJson ? '顶层 ' + Object.keys(packageJson).length + ' 个键' : '解析失败');
    if (packageJson) {
      const relative = collectPackagePaths(packageJson.state);
      check('[3c] project.json 里的附件字段全是包内相对路径 assets/…（' + relative.length + ' 处，一个 /assets/ 引用都不剩）',
        relative.length === assetPaths.length
        && relative.every(value => /^assets\/[A-Za-z0-9]+\.[a-z0-9]+$/.test(value))
        && !relative.some(value => value.includes(ASSET_PREFIX)),
        relative.slice(0, 3).join(' | '));
      check('[3c] 这些包内相对路径逐个都能在包里找到（包内路径对得上）',
        relative.every(value => names.has(value)),
        relative.filter(value => !names.has(value)).join(', ') || '');
      check('[3c] _export 说明块写明格式/版本/项目/版本号/导出时间/附件个数',
        packageJson._export.version === 1
        && packageJson._export.revision === project.revision
        && String(packageJson._export.exported || '').length >= 10
        && packageJson._export.assets === names.size - 2,
        JSON.stringify(packageJson._export));
    }
  }
  }   // 结束"运行中的服务已有新接口"这一分支
}

function chooseRef(state) {
  const found = collectAssetPaths(state);
  return found.length ? found[0].value : ASSET_PREFIX + 'missing';
}

// ---------------------------------------------------------------- 4 DB 里没有内联图
console.log('\n=== 4 库里只存引用：只读 SQLite 扫 19 张表，没有内联图 ===');
const dataDir = (bootstrap && bootstrap.data_dir) || join(ROOT, 'data', 'machining_dfm');
const dbPath = join(dataDir, 'machining_dfm.sqlite3');
if (!existsSync(dbPath)) {
  problems.push('找不到数据库文件：' + dbPath);
  console.log('  ✗ 找不到数据库文件：' + dbPath);
} else {
  // readOnly:true 等价 sqlite3 的 file:...?mode=ro
  const db = new DatabaseSync(dbPath, { readOnly: true });
  let readOnlyProven = false;
  try {
    db.exec('CREATE TABLE __check_should_fail__(x)');
    console.log('  ! 这个句柄居然能写库 —— 立刻停手');
  } catch (error) {
    readOnlyProven = /readonly|read-only/i.test(String(error.message));
  }
  check('SQLite 句柄确实是只读的（试写被库挡住）', readOnlyProven, readOnlyProven ? 'attempt to write a readonly database' : '试写没被挡住');
  const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all().map(row => row.name);
  console.log('  库：' + dbPath);
  console.log('  表（' + tables.length + ' 张）：' + tables.join(', '));
  for (const name of ['assets', 'projects', 'project_settings', 'project_processes', 'project_issues', 'project_versions']) {
    check('19 张表里有 ' + name, tables.includes(name), '');
  }
  check('表数量与阶段 5 对上的 19 张一致（≥ 19）', tables.length >= 19, tables.length + ' 张');

  let inlineHits = 0;
  const bigCells = [];
  for (const table of tables) {
    const columns = db.prepare('PRAGMA table_info("' + table + '")').all();
    for (const column of columns) {
      let rows;
      try {
        rows = db.prepare('SELECT rowid AS rid, length("' + column.name + '") AS n, "' + column.name + '" AS v FROM "' + table + '"').all();
      } catch (error) {
        console.log('  – 跳过 ' + table + '.' + column.name + '（' + error.message + '）');
        continue;
      }
      for (const row of rows) {
        const length = Number(row.n || 0);
        if (typeof row.v === 'string' && row.v.includes('data:image')) {
          inlineHits += 1;
          console.log('  ✗ ' + table + '.' + column.name + ' rowid=' + row.rid + ' 里有 data:image（' + length + ' 字符）');
        }
        if (length > 4096) bigCells.push({ table, column: column.name, rid: row.rid, length });
      }
    }
  }
  check(tables.length + ' 张表所有文本列扫 data:image → 一个都没有', inlineHits === 0, inlineHits + ' 行');
  const bigTables = [...new Set(bigCells.map(cell => cell.table + '.' + cell.column))];
  console.log('  > 4KB 的文本格子 ' + bigCells.length + ' 个，最长 ' + Math.max(0, ...bigCells.map(cell => cell.length)) + ' 字符');
  check('> 4KB 的文本格子只可能出现在读数模型快照的 project_versions.state_json 里（不是图片 base64）',
    bigTables.every(name => name === 'project_versions.state_json'), bigTables.join(', ') || '(没有)');
  if (bigTables.includes('project_versions.state_json')) {
    console.log('    说明：project_versions.state_json 是"那一次保存时的整份读模型"快照，'
      + '图片槽位在里面仍是 /api/machining-dfm/assets/<id> 引用 —— 它不是内联图，故按快照口径单列；'
      + '下面的 data:image 扫描对它是**包含在内**的（同样 0 命中）。');
    const snapshotWithUrls = db.prepare("SELECT count(*) AS n FROM project_versions WHERE state_json LIKE '%" + ASSET_PREFIX + "%'").get().n;
    const snapshotTotal = db.prepare('SELECT count(*) AS n FROM project_versions').get().n;
    check('版本快照里存的确实是引用（' + snapshotWithUrls + '/' + snapshotTotal + ' 份含 /assets/ URL，0 份含 base64）',
      snapshotWithUrls > 0, snapshotWithUrls + '/' + snapshotTotal);
  }
  // 影子副本的口径：**业务表里已经有行的项目**，state_json 必须停写成 `{}`。
  // （表还是空的项目——比如"另存为"出来的副本还没迁——读模型仍走 state_json，
  //  那是验收报告 2.2 条记着的"双存储并存"缺陷，不是这一条要管的事，所以单列出来提示。）
  const stateJson = db.prepare('SELECT id, state_json, length(state_json) AS n FROM projects').all();
  const businessTables = ['project_processes', 'project_process_tools', 'project_issues',
    'project_fixtures', 'project_gauges'];
  const migrated = [];
  const untouched = [];
  for (const row of stateJson) {
    const hasRows = businessTables.some(table => {
      try {
        return db.prepare('SELECT count(*) AS n FROM "' + table + '" WHERE project_id = ?')
          .get(row.id).n > 0;
      } catch (error) { return false; }
    });
    (hasRows ? migrated : untouched).push(row);
  }
  check('业务表里已经有行的项目：projects.state_json 已停写成 {}（' + migrated.length + ' 个）',
    migrated.length > 0 && migrated.every(row => String(row.state_json).replace(/\s/g, '') === '{}'),
    migrated.map(row => row.id + '=' + JSON.stringify(row.state_json).slice(0, 40)).join(', '));
  if (untouched.length) {
    console.log('    （另 ' + untouched.length + ' 个项目的业务表还是空的，读模型仍走 state_json —— '
      + '就是验收报告 2.2 条那个"双存储并存"：' + untouched.map(row => row.id.slice(0, 8)).join('、') + '）');
  }

  // assets 表：只存引用
  const assetColumns = db.prepare('PRAGMA table_info(assets)').all();
  const assetRows = db.prepare('SELECT id, kind, mime, name, size, sha256, path FROM assets').all();
  console.log('  assets 表 ' + assetRows.length + ' 行 / ' + assetRows.reduce((sum, row) => sum + Number(row.size), 0) + ' 字节');
  check('assets 表只有 id/kind/mime/name/size/sha256/path/created 这些"引用 + 元数据"列',
    assetColumns.map(column => column.name).join(',') === 'id,kind,mime,name,size,sha256,path,created',
    assetColumns.map(column => column.name).join(', '));
  check('assets 表里没有任何 BLOB 列（字节不在库里）',
    assetColumns.every(column => String(column.type).toUpperCase() !== 'BLOB'),
    assetColumns.map(column => column.name + ':' + column.type).join(', '));
  const badPaths = assetRows.filter(row =>
    !new RegExp('^' + row.kind + '/[0-9a-f]{2}/' + row.sha256 + '\\.[a-z0-9]+$').test(String(row.path)));
  check('assets.path 都是 <kind>/<sha 前两位>/<sha>.<ext>（内容寻址）',
    assetRows.length > 0 && badPaths.length === 0, badPaths.map(row => row.path).join(', '));
  check('assets.sha256 与文件名的 sha 一致，且 mime 是图片',
    assetRows.every(row => String(row.path).includes(String(row.sha256)) && String(row.mime).startsWith('image/')), '');

  const missingFiles = [];
  const known = new Set(assetRows.map(row => String(row.path)));
  for (const row of assetRows) {
    const file = join(dataDir, 'assets', ...String(row.path).split('/'));
    if (!existsSync(file)) { missingFiles.push(row.path + '（文件不存在）'); continue; }
    const size = statSync(file).size;
    if (size !== Number(row.size)) missingFiles.push(row.path + '（行里 ' + row.size + '，磁盘 ' + size + '）');
  }
  check('库里每一行附件都能在磁盘 data/machining_dfm/assets 下找到，且字节数一致（有行没文件 0）',
    missingFiles.length === 0, missingFiles.join(', '));
  const assetDir = join(dataDir, 'assets');
  const diskFiles = [];
  const walkDir = directory => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const full = join(directory, entry.name);
      if (entry.isDirectory()) walkDir(full);
      else if (!entry.name.endsWith('.part')) diskFiles.push(full);
    }
  };
  if (existsSync(assetDir)) walkDir(assetDir);
  const orphans = diskFiles.filter(file => !known.has(file.slice(assetDir.length + 1).split('\\').join('/')));
  console.log('  磁盘上的附件文件 ' + diskFiles.length + ' 个 / ' + diskFiles.reduce((sum, file) => sum + statSync(file).size, 0) + ' 字节');
  check('磁盘上的附件文件与 assets 表一一对上（有文件没行 0）',
    orphans.length === 0 && diskFiles.length === assetRows.length,
    orphans.length ? orphans.join(', ') : diskFiles.length + ' vs ' + assetRows.length);

  // 真外键：所有指向 assets(id) 的列，值都不许悬空
  const fkColumns = [];
  for (const table of tables) {
    const ddl = String((db.prepare("SELECT sql FROM sqlite_master WHERE type='table' AND name=?").get(table) || {}).sql || '');
    // 行内写法： "col" TEXT REFERENCES assets(id)
    for (const match of ddl.matchAll(/"(\w+)"\s+TEXT\s+REFERENCES\s+assets\(id\)/g)) fkColumns.push({ table, column: match[1] });
    // 表级写法： FOREIGN KEY(col) REFERENCES assets(id)
    for (const match of ddl.matchAll(/FOREIGN\s+KEY\s*\(\s*"?(\w+)"?\s*\)\s*REFERENCES\s+assets\(id\)/gi)) {
      fkColumns.push({ table, column: match[1] });
    }
  }
  const assetIds = new Set(assetRows.map(row => String(row.id)));
  const danglingRefs = [];
  let refCount = 0;
  for (const { table, column } of fkColumns) {
    const rows = db.prepare('SELECT "' + column + '" AS v FROM "' + table + '" WHERE "' + column + '" IS NOT NULL').all();
    for (const row of rows) {
      refCount += 1;
      if (!assetIds.has(String(row.v))) danglingRefs.push(table + '.' + column + ' → ' + row.v);
    }
  }
  console.log('  指向 assets(id) 的列 ' + fkColumns.length + ' 个：' + fkColumns.map(item => item.table + '.' + item.column).join(', '));
  check('所有指向 assets(id) 的外键列都不悬空（' + refCount + ' 个引用，0 悬空）',
    fkColumns.length > 0 && danglingRefs.length === 0, danglingRefs.join(', '));
  for (const [label, table, column] of [
    ['项目四张图', 'project_settings', 'product_photo_id'],
    ['工序夹具示意图（旧 cI）', 'project_processes', 'fixture_photo_id'],
    ['问题清单优化前（旧 bI）', 'project_issues', 'before_photo_id'],
    ['问题清单优化后（旧 aI）', 'project_issues', 'after_photo_id'],
  ]) {
    check(label + ' 在库里是 ' + table + '.' + column + ' → assets(id) 外键',
      fkColumns.some(item => item.table === table && item.column === column), '');
  }
  const settingsRow = db.prepare('SELECT product_photo_id, product2_photo_id, blank_insp_photo_id, final_insp_photo_id FROM project_settings').all();
  console.log('  project_settings 的四张图外键：' + JSON.stringify(settingsRow));
  check('project_settings 的四张图列的取值都是 assets.id（或 NULL）',
    settingsRow.every(row => Object.values(row).every(value => value === null || assetIds.has(String(value)))), '');

  // 交叉验证：读模型里的 18 个引用，id 全在 assets 表里
  if (bootstrap) {
    const readModelIds = [...new Set(collectAssetPaths(bootstrap.project.state).map(item => item.value.split('/').pop()))];
    const unknown = readModelIds.filter(id => !assetIds.has(id));
    check('读模型里的 ' + readModelIds.length + ' 个附件 id 全部能在 assets 表里找到（悬空 0）',
      unknown.length === 0, unknown.join(', '));
    // 历史版本快照里的附件引用也要算上：快照是"那一次保存时的整份读模型"，
    // 里面的图同样是 assets 行（工具 tools/slim_version_snapshots.py 就是往这里挂引用的）。
    const snapshotIds = new Set();
    for (const row of db.prepare('SELECT state_json FROM project_versions WHERE state_json IS NOT NULL').all()) {
      for (const match of String(row.state_json).matchAll(/\/assets\/([0-9a-zA-Z_-]{8,64})/g)) snapshotIds.add(match[1]);
    }
    const unknownSnapshot = [...snapshotIds].filter(id => !assetIds.has(id));
    const newDead = unknownSnapshot.filter(id => !KNOWN_DEAD_ASSETS.has(id));
    check('历史快照里没有**新**的附件死链（已知的老遗留 ' + KNOWN_DEAD_ASSETS.size + ' 个单独列出）',
      newDead.length === 0, newDead.join(', '));
    if (unknownSnapshot.length) {
      console.log('    ！已知历史死链 ' + unknownSnapshot.length + ' 个：' + unknownSnapshot.join(', '));
      console.log('      原因：老代码"换图"时判定图片还有没有人用，只扫声明了 assets(id) 外键的列，');
      console.log('            而快照里记的是附件 URL（不带外键）→ 老版本里的图被回收成死链，字节已不可恢复。');
      console.log('            这些引用只出现在第 17/18/22/26/30/34/38/40 版（都是 2026-09-18 之前存的老版本）。');
      console.log('      现在 app/machining_library.py::asset_in_snapshots 已把"快照还引用着"算作"有人用"，不再回收。');
    }
    const referenced = new Set([...readModelIds, ...[...snapshotIds].filter(id => assetIds.has(id))]);
    const orphans = assetRows.map(row => String(row.id)).filter(id => !referenced.has(id));
    check('库里每个附件行都有人引用：读模型或历史快照（没有孤儿附件）',
      orphans.length === 0,
      '没人引用：' + orphans.join(', ')
        + '（读模型 ' + readModelIds.length + ' 个、只在历史快照里用到 '
        + [...snapshotIds].filter(id => assetIds.has(id) && !readModelIds.includes(id)).length + ' 个、库里 '
        + assetRows.length + ' 行）');
    check('读模型里的附件引用处数 ≥ 读模型里不同的附件 id 数（同一个附件可被多行共用）',
      assetPaths.length >= readModelIds.length,
      assetPaths.length + ' 处引用 vs ' + readModelIds.length + ' 个附件');
  }

  // 附件下载 URL 与磁盘字节对得上（HTTP 与磁盘同一份字节）
  if (httpSizes.size) {
    const mismatched = [];
    for (const row of assetRows) {
      const size = httpSizes.get(ASSET_PREFIX + row.id);
      if (size !== undefined && size !== Number(row.size)) mismatched.push(row.id + '（HTTP ' + size + ' vs 行 ' + row.size + '）');
    }
    check('附件接口返回的字节数与 assets.size 一致（HTTP 与磁盘同一份字节）',
      mismatched.length === 0, mismatched.join(', '));
  }
  db.close();
}

// ---------------------------------------------------------------- 收尾
check('沙箱里没有未处理的 Promise 拒绝', rejections.length === 0, rejections.join(' | '));

if (skips.length) {
  console.log('\n按当前实际行为跳过（不假装通过，等确认）：');
  for (const item of skips) console.log('  – ' + item);
}
console.log('\n' + (problems.length
  ? '发现问题:\n - ' + problems.join('\n - ')
  : '全部检查通过 ✓'
    + (skips.length ? '（其中 ' + skips.length + ' 条按当前实际行为跳过，见上）' : '')));
process.exitCode = problems.length ? 1 : 0;
