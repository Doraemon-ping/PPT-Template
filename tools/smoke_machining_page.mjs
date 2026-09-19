/* 真·前端冒烟自检：用最小 DOM 垫片把整页 JS 按 index.html 的顺序跑起来，
 * 直连运行中的服务（只读：写请求被拦下，不会改线上数据），逐个页签渲染并抓异常。
 * 用法：node tools/smoke_machining_page.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const STATIC = join(here, '..', 'static', 'machining_dfm');
const BASE = 'http://127.0.0.1:8002';

// ---------------------------------------------------------------- DOM 垫片
function makeElement(tag = 'div', id = '') {
  const listeners = {};
  const classes = new Set();
  const element = {
    tagName: String(tag).toUpperCase(),
    id,
    _html: '',
    _text: '',
    value: '',
    checked: false,
    hidden: false,
    disabled: false,
    files: null,
    type: '',
    accept: '',
    min: '',
    max: '',
    step: '',
    placeholder: '',
    title: '',
    href: '',
    download: '',
    src: '',
    alt: '',
    name: '',
    options: [],
    selectedIndex: 0,
    tabIndex: 0,
    offsetWidth: 0,
    offsetHeight: 0,
    scrollTop: 0,
    scrollHeight: 0,
    clientWidth: 0,
    style: { cssText: '', display: '', setProperty() {}, removeProperty() {} },
    dataset: {},
    children: [],
    childNodes: [],
    parentNode: null,
    firstChild: null,
    lastChild: null,
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
    remove() {},
    setAttribute(name, value) { element[name] = value; },
    getAttribute(name) { return element[name] === undefined ? null : element[name]; },
    removeAttribute(name) { delete element[name]; },
    hasAttribute(name) { return element[name] !== undefined; },
    addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push(handler); },
    removeEventListener() {},
    dispatchEvent(event) { (listeners[event.type] || []).forEach(handler => handler(event)); return true; },
    click() {},
    focus() {},
    blur() {},
    select() {},
    scrollIntoView() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getElementsByTagName() { return []; },
    getElementsByClassName() { return []; },
    closest() { return null; },
    contains() { return false; },
    cloneNode() { return makeElement(tag, id); },
    after() {},
    before() {},
    replaceWith() {},
    getContext() { return { fillRect() {}, drawImage() {}, fillStyle: '' }; },
    toDataURL() { return 'data:image/jpeg;base64,AAAA'; },
  };
  return element;
}

const elements = new Map();
const documentListeners = {};
const documentStub = {
  readyState: 'complete',
  title: 'machining',
  cookie: '',
  documentElement: makeElement('html'),
  head: makeElement('head'),
  body: makeElement('body'),
  createElement: tag => makeElement(tag),
  createTextNode: text => ({ textContent: text }),
  createDocumentFragment: () => makeElement('fragment'),
  getElementById: id => { if (!elements.has(id)) elements.set(id, makeElement('div', id)); return elements.get(id); },
  querySelector: selector => {
    const text = String(selector || '');
    if (text.startsWith('#')) return documentStub.getElementById(text.slice(1));
    return makeElement('div', text);
  },
  querySelectorAll: () => [],
  getElementsByTagName: () => [],
  getElementsByClassName: () => [],
  addEventListener(type, handler) { (documentListeners[type] = documentListeners[type] || []).push(handler); },
  removeEventListener() {},
  dispatchEvent() { return true; },
};

// window 级别的事件接口（host.js 会挂 beforeunload）
documentStub.defaultView = null;

function storage() {
  const map = new Map();
  return {
    getItem: key => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: key => map.delete(key),
    clear: () => map.clear(),
    key: index => [...map.keys()][index] ?? null,
    get length() { return map.size; },
  };
}

const problems = [];
const messages = [];
// 真正连网的 fetch 单独存一份：**只准 GET**。写请求一律在下面被拦下来，
// 万一将来有人改坏了拦截逻辑，这里会直接抛错，而不是悄悄写进线上库。
const liveFetch = globalThis.fetch;
let liveWrites = 0;
const guardedFetch = (url, init = {}) => {
  const method = String((init && init.method) || 'GET').toUpperCase();
  if (method !== 'GET') {
    liveWrites += 1;
    throw new Error('自检脚本试图向线上发写请求（已阻止）：' + method + ' ' + url);
  }
  return liveFetch(url, init);
};
const sandbox = {
  console: { log: (...args) => messages.push(args.join(' ')), warn: (...args) => messages.push('WARN ' + args.join(' ')), error: (...args) => messages.push('ERROR ' + args.join(' ')) },
  document: documentStub,
  location: { href: BASE + '/machining-dfm', pathname: '/machining-dfm', search: '', hash: '', origin: BASE, protocol: 'http:', host: '127.0.0.1:8002', reload() {} },
  navigator: { userAgent: 'node-smoke', language: 'zh-CN', clipboard: null },
  localStorage: storage(),
  sessionStorage: storage(),
  alert: message => messages.push('alert: ' + message),
  confirm: () => true,
  prompt: () => '自检输入',
  setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask,
  requestAnimationFrame: fn => setTimeout(() => fn(Date.now()), 0),
  cancelAnimationFrame: () => {},
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent() { return true; },
  open() {},
  close() {},
  focus() {},
  scrollTo() {},
  matchMedia: () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }),
  Image: class { set src(_value) { if (this.onload) setTimeout(() => this.onload(), 0); } },
  FileReader: class { readAsDataURL() { if (this.onload) setTimeout(() => this.onload({ target: { result: 'data:image/png;base64,AAAA' } }), 0); } readAsText() { this.readAsDataURL(); } },
  Blob: class { constructor(parts, options) { this.parts = parts; this.type = options && options.type; } },
  URL: { createObjectURL: () => 'blob:node/1', revokeObjectURL() {} },
  Headers,
  Request,
  Response,
  URLSearchParams,
  TextEncoder,
  TextDecoder,
  AbortController,
  Event: class { constructor(type) { this.type = type; } },
  CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
  MutationObserver: class { observe() {} disconnect() {} },
  IntersectionObserver: class { observe() {} disconnect() {} },
  ResizeObserver: class { observe() {} disconnect() {} },
  performance: { now: () => Date.now() },
  structuredClone: value => JSON.parse(JSON.stringify(value)),
  crypto: { randomUUID: () => 'uuid-' + Math.random().toString(16).slice(2) },
  fetch: guardedFetch,
  Promise, JSON, Math, Date, Number, String, Boolean, Array, Object, RegExp, Error, TypeError, Map, Set, WeakMap, isNaN, parseFloat, parseInt, encodeURIComponent, decodeURIComponent, encodeURI, decodeURI, btoa, atob,
  escape, unescape,
  Intl,
  __node: true,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;
sandbox.top = sandbox;

const context = vm.createContext(sandbox);

// 直连服务的 fetch：GET 放行；写请求拦下（返回成功但不动线上数据）
const writeCalls = [];
// 所有请求（含 GET）：查"页面有没有碰某个接口"用（阶段 3b 的变更流水就是靠这个证明页面不写也不读）
const requestLog = [];
const projectCache = new Map();
const jsonResponse = body => ({ ok: true, status: 200, headers: new Headers({ 'content-type': 'application/json' }), json: async () => body, text: async () => JSON.stringify(body), blob: async () => new Blob([]) });

// 工序落表（1b）：线上开关还是关的，这里按真实接口的形状造一份"表里的行"，
// 让前端行级保存的路径能真正跑完（行 id 用合成 id，用来验证"按行 id 写、不是按下标写"）。
// 行级写会把结果同时写回这份"表"和项目记录里的 pr[]——像真服务那样，
// 这样"行级保存之后不会再有整份保存"这条才检验得出来。
const processRows = new Map();
// 与线上一致：默认**开关关着**；测试里调 __enableProcessTable() 才打开
let processTableEnabled = false;
sandbox.__enableProcessTable = () => {
  processTableEnabled = true;
  for (const record of projectCache.values()) record.process_table = true;
  return true;
};
async function projectRecord(projectId) {
  if (!projectCache.has(projectId)) {
    const response = await guardedFetch(BASE + '/api/machining-dfm/projects/' + projectId);
    const record = await response.json();
    record.process_table = processTableEnabled;
    record.issue_table = issueTableEnabled;
    projectCache.set(projectId, record);
  }
  return projectCache.get(projectId);
}
function legacyTool(row) {
  return {
    id: row.code, tp: row.tp, ds: row.ds, d: row.d, n: row.n, vf: row.vf, ln: row.ln,
    ps: row.ps, cn: row.cn, bg: !!row.bg, td: row.td, fi: row.fi || null, tt: row.tt,
    sd: row.sd, cat: row.cat, hld: row.hld, acc: row.acc,
  };
}
// 把"表"同步回读模型（compose 的简化版：派生值这里不重算，交给页面算）
function syncLegacy(projectId) {
  const listing = processRows.get(projectId);
  const record = projectCache.get(projectId);
  if (!listing || !record) return;
  record.state.pr = listing.processes
    .filter(row => !row.deleted_at)
    .map(row => ({
      nm: row.nm, mc: row.mc, cI: row.cI || null, nc: row.nc, tl: (row.tools || []).map(legacyTool),
      fixP: row.fixP || 0, eqP: row.eqP || 0, mid: row.mid || '', mi: -1,
    }));
}
async function processListing(projectId) {
  if (processRows.has(projectId)) return processRows.get(projectId);
  const record = await projectRecord(projectId);
  const processes = (record.state.pr || []).map((process, pi) => ({
    id: 'p-' + pi,
    sort_order: pi,
    project_id: projectId,
    nm: process.nm,
    mc: process.mc,
    mid: process.mid,
    fixP: process.fixP,
    eqP: process.eqP,
    nc: process.nc,
    cI: process.cI || null,
    machine_snapshot: {},
    tools: (process.tl || []).map((tool, i) => ({
      id: 't-' + pi + '-' + i,
      process_id: 'p-' + pi,
      sort_order: i,
      code: tool.id,
      tp: tool.tp,
      cat: tool.cat,
      ds: tool.ds,
      d: tool.d,
      n: tool.n,
      vf: tool.vf,
      ln: tool.ln,
      ps: tool.ps,
      cn: tool.cn,
      bg: tool.bg ? 1 : 0,
      td: tool.td,
      tt: tool.tt,
      sd: tool.sd,
      hld: tool.hld,
      acc: tool.acc,
      fi: tool.fi || null,
      tool_id: '',
      tool_grp: '',
      tool_price: 0,
      tool_life: 0,
      hld_id: '',
      hld_price: 0,
      acc_id: '',
      acc_price: 0,
    })),
  }));
  const listing = { processes, deleted_processes: [], deleted_tools: [], fields: { nc_keys: ['cc', 'co', 'mc_', 'sc', 'ac', 'it'] } };
  processRows.set(projectId, listing);
  syncLegacy(projectId);
  return listing;
}
// ---------------- 问题清单落表（2a）：同样造一份"表里的行" ----------------
const issueRows = new Map();
// 与线上一致：默认**开关关着**（工序与问题清单都是）；测试里调 __enableIssueTable() 才打开
let issueTableEnabled = false;
sandbox.__enableIssueTable = () => {
  issueTableEnabled = true;
  for (const record of projectCache.values()) record.issue_table = true;
  return true;
};
// 把"表"同步回读模型：pr 由外键现算当前工序名（简化的 compose）
function syncLegacyIssues(projectId) {
  const listing = issueRows.get(projectId);
  const record = projectCache.get(projectId);
  if (!listing || !record) return;
  const names = {};
  for (const process of listing.processes || []) names[process.id] = process.name;
  record.state.is = listing.issues.map(row => ({
    tp: row.tp, pr: names[row.process_id] || row.prName || '', ds: row.ds, fx: row.fx,
    cr: row.cr, st: row.st, bI: row.bI || null, aI: row.aI || null,
  }));
}
async function issueListing(projectId) {
  const processes = (await processListing(projectId)).processes
    .map(row => ({ id: row.id, name: row.nm, sort_order: row.sort_order }));
  if (!issueRows.has(projectId)) {
    const record = await projectRecord(projectId);
    const issues = (record.state.is || []).map((issue, i) => ({
      id: 'i-' + i,
      project_id: projectId,
      process_id: (processes.filter(p => p.name === issue.pr)[0] || {}).id || null,
      sort_order: i,
      tp: issue.tp,
      ds: issue.ds,
      fx: issue.fx,
      cr: issue.cr,
      st: issue.st,
      prName: issue.pr || '',
      bI: issue.bI || null,
      aI: issue.aI || null,
    }));
    issueRows.set(projectId, { issues, deleted_issues: [], processes, fields: { statuses: ['进行中', '已完成'] } });
    syncLegacyIssues(projectId);
  }
  const listing = issueRows.get(projectId);
  listing.processes = processes;
  return listing;
}
async function applyIssueWrite(projectId, path, method, payload) {
  const listing = await issueListing(projectId);
  const match = path.match(/^\/issues(?:\/([^/]+))?(?:\/(restore))?(?:\/photo\/(\w+))?$/);
  if (!match) return null;
  const [, issueId, restoreSegment, photoSlot] = match;
  const row = listing.issues.filter(item => item.id === issueId)[0];
  if (photoSlot && row) {
    const key = photoSlot === 'before' ? 'bI' : 'aI';
    row[key] = method === 'DELETE' ? null : '/api/machining-dfm/assets/smoke';
  } else if (restoreSegment && row) {
    row.deleted_at = null;
    listing.issues.push(row);
    listing.deleted_issues = listing.deleted_issues.filter(item => item !== row);
  } else if (method === 'DELETE' && row) {
    row.deleted_at = new Date().toISOString();
    listing.deleted_issues.push(row);
    listing.issues = listing.issues.filter(item => item !== row);
  } else if (method === 'POST') {
    listing.issues.push(Object.assign({
      id: 'i-' + (listing.issues.length + listing.deleted_issues.length),
      project_id: projectId, process_id: null, sort_order: listing.issues.length,
      tp: '尺寸', ds: '', fx: '', cr: '', st: '进行中', prName: '', bI: null, aI: null,
    }, payload));
  } else if (row) {
    Object.assign(row, payload);
    if ('process_id' in payload) {
      row.prName = (listing.processes.filter(p => p.id === payload.process_id)[0] || {}).name || '';
    }
  }
  syncLegacyIssues(projectId);
  const record = JSON.parse(JSON.stringify(projectCache.get(projectId)));
  record.process_table = processTableEnabled;
  record.issue_table = issueTableEnabled;
  record.revision = (record.revision || 0) + 1;
  return jsonResponse({ project: record });
}

// ---------------- 选型报价落表（2b）：造一份"格子里的行" ----------------
// 与线上一致：默认开关关着；测试里调 __enableSelectionTable() 才打开。
// 一个类别一格：夹具 4 格（模具中心）、检具 5 格（检具类别），未选型的格子也有行。
const selectionRows = new Map();
let selectionTableEnabled = false;
const FIXTURE_CENTERS = ['1025减震模具中心', '1059轻合金模具中心', '1929底盘模具中心', '8107结构件模具中心'];
const GAUGE_CATEGORIES = ['毛坯检具', '成品机械检具', '成品总成检具', '成品电子检具', '测量支架'];
sandbox.__enableSelectionTable = () => {
  selectionTableEnabled = true;
  for (const record of projectCache.values()) record.selection_table = true;
  return true;
};
sandbox.__selectionTableEnabled = () => selectionTableEnabled;
// 把"表"同步回读模型：四个数组由类别现算（未选型的格子是 ""/1）
function syncLegacySelections(projectId) {
  const listing = selectionRows.get(projectId);
  const record = projectCache.get(projectId);
  if (!listing || !record) return;
  const G = record.state.G || (record.state.G = {});
  const build = (kind, names, arrayKey, quoteKey) => {
    const values = names.map(() => '');
    const quotes = names.map(() => 1);
    for (const row of listing.rows) {
      if (row.kind !== kind) continue;
      const index = names.indexOf(row.category);
      if (index < 0) continue;              // 类别已不在字典里：这一格不输出（行留着当历史）
      values[index] = row.legacy_key || '';
      quotes[index] = row.quoted ? 1 : 0;
    }
    G[arrayKey] = values;
    G[quoteKey] = quotes;
  };
  build('fixture', FIXTURE_CENTERS, 'fixQ', 'fixQC');
  build('gauge', GAUGE_CATEGORIES, 'insp', 'inspQ');
}
async function selectionListing(projectId) {
  const record = await projectRecord(projectId);
  if (!selectionRows.has(projectId)) {
    const G = record.state.G || {};
    const rows = [];
    FIXTURE_CENTERS.forEach((category, i) => rows.push({
      id: 'sel-f-' + i, kind: 'fixture', category, slot: i,
      legacy_key: (G.fixQ || [])[i] || '', quoted: ((G.fixQC || [])[i] === 0 ? 0 : 1),
      fixture_id: null, gauge_id: null, price: null,
    }));
    GAUGE_CATEGORIES.forEach((category, i) => rows.push({
      id: 'sel-g-' + i, kind: 'gauge', category, slot: i,
      legacy_key: (G.insp || [])[i] || '', quoted: ((G.inspQ || [])[i] === 0 ? 0 : 1),
      fixture_id: null, gauge_id: null, price: null,
    }));
    selectionRows.set(projectId, { rows });
    syncLegacySelections(projectId);
  }
  const listing = selectionRows.get(projectId);
  return { rows: listing.rows, arrays: (() => {
    const G = projectCache.get(projectId).state.G || {};
    return { fixQ: G.fixQ || [], fixQC: G.fixQC || [], insp: G.insp || [], inspQ: G.inspQ || [] };
  })() };
}
// 一类选型一个接口（夹具 /fixtures、检具 /gauges）：格子顺序就是类别字典顺序
async function selectionKindListing(projectId, kind) {
  const listing = await selectionListing(projectId);
  const names = kind === 'fixture' ? FIXTURE_CENTERS : GAUGE_CATEGORIES;
  const label = kind === 'fixture' ? '夹具' : '检具';
  const slots = names.map((category, i) => {
    const row = listing.rows.filter(item => item.kind === kind && item.slot === i)[0] || {};
    const quoted = row.quoted === 0 ? 0 : 1;
    const price = row.price == null ? 0 : row.price;
    return {
      slot: i, category, kind, label, value: row.legacy_key || '', quoted,
      bound: !!(row.fixture_id || row.gauge_id), price,
      fixture_id: row.fixture_id || null, gauge_id: row.gauge_id || null,
      id: row.id || '', name: (row.legacy_key || '').split('|').pop() || '',
    };
  });
  return {
    enabled: true, kind, label, table: kind === 'fixture' ? 'project_fixtures' : 'project_gauges',
    slots, categories: names, rows: listing.rows.filter(item => item.kind === kind),
    total: {
      quoted: slots.filter(item => item.quoted).length,
      price: slots.reduce((sum, item) => sum + (item.quoted ? item.price : 0), 0),
    },
    arrays: listing.arrays,
  };
}
// 与真接口同一套坐标：(哪一类, 格子下标)；空串 = 清空（行保留、只解绑）
async function applySelectionWrite(projectId, path, method, payload) {
  const match = path.match(/^\/(fixtures|gauges)\/(\d+)$/);
  if (!match) return null;
  const kind = match[1] === 'fixtures' ? 'fixture' : 'gauge';
  const listing = await selectionListing(projectId);
  const slot = Number(match[2]);
  const row = listing.rows.filter(item => item.kind === kind && item.slot === slot)[0];
  if (!row) {
    return jsonResponse({ detail: '这一格不在类别字典里（夹具第 ' + slot + ' 格）' }, 422);
  }
  if (method === 'DELETE') {
    row.legacy_key = ''; row.fixture_id = null; row.gauge_id = null; row.price = null;
  } else if ('quoted' in payload) {
    row.quoted = payload.quoted ? 1 : 0;
  } else {
    row.legacy_key = String(payload.legacy_key || '');
    // 简化版的"唯一才绑"：冒烟用的库里就一条同名夹具
    if (row.legacy_key.indexOf('两点式拉杆四轴机加夹具') >= 0) {
      row.fixture_id = 'fx-1'; row.price = 16000;
    }
  }
  syncLegacySelections(projectId);
  const record = JSON.parse(JSON.stringify(projectCache.get(projectId)));
  record.process_table = processTableEnabled;
  record.issue_table = issueTableEnabled;
  record.selection_table = selectionTableEnabled;
  record.revision = (record.revision || 0) + 1;
  return jsonResponse({ project: record });
}

// ---------------- 版本履历落表（3a）：造一份"履历行" ----------------
// 与线上一致：默认开关关着；测试里调 __enableHistoryTable() 才打开。
// 行数 = 页面上 vh[] 的条数（迁移工具干的就是这件事），四个键 + 一个稳定 id。
const historyRows = new Map();
let historyTableEnabled = false;
sandbox.__enableHistoryTable = () => {
  historyTableEnabled = true;
  for (const record of projectCache.values()) record.history_table = true;
  return true;
};
sandbox.__historyTableEnabled = () => historyTableEnabled;
// 造两行履历：写进"服务端记录"里（页面 adopt 之后 VH 就有了），线上真项目此刻 vh 是空的
sandbox.__seedHistory = (projectId) => {
  const record = projectCache.get(projectId);
  if (!record) return null;
  record.state.vh = [
    { dt: '2026-01-05', ver: 'V1.0', ds: '初版发布', by: '张三' },
    { dt: '2026-02-11', ver: 'V1.1', ds: '改结构', by: '李四' },
  ];
  record.history_table = historyTableEnabled;
  return JSON.parse(JSON.stringify(record));
};
// 把"表"同步回读模型：vh[] 由行现算（键序与页面上 addVH() 一致）
function syncLegacyHistory(projectId) {
  const listing = historyRows.get(projectId);
  const record = projectCache.get(projectId);
  if (!listing || !record) return;
  record.state.vh = listing.rows.filter(row => !row.deleted_at).map(row => ({
    dt: row.dt || '', ver: row.ver || '', ds: row.ds || '', by: row.by || '',
  }));
}
async function historyListing(projectId) {
  const record = await projectRecord(projectId);
  if (!historyRows.has(projectId)) {
    // 第一次访问：把页面上现有的 vh[] 原样搬成行（id 与真服务一致：<项目 id>-h<下标>）
    const rows = (record.state.vh || []).map((item, index) => ({
      id: projectId + '-h' + index, index, sort_order: index,
      dt: item.dt || '', ver: item.ver || '', ds: item.ds || '', by: item.by || '',
      revision: null, extra: {}, deleted_at: null, deleted_by: '', deleted_reason: '',
      created: '', updated: '',
    }));
    historyRows.set(projectId, { rows });
    syncLegacyHistory(projectId);
  }
  const listing = historyRows.get(projectId);
  const live = listing.rows.filter(row => !row.deleted_at);
  const deleted = listing.rows.filter(row => row.deleted_at);
  return {
    table: 'project_versions', enabled: true, kind: 'history',
    keys: ['dt', 'ver', 'ds', 'by'], materialized: true,
    count: live.length, live_count: live.length, recycle_count: deleted.length,
    history: live.map((row, index) => ({ ...row, index })),
    // 只有这个冒烟用的假服务端会用到：写请求改的就是这一份行（真服务端在 SQL 里改）
    rows: listing.rows,
  };
}
// 与真接口同一套坐标：行 id（页面每次写入都先 GET 一次清单，用下标换 id）
async function applyHistoryWrite(projectId, path, method, payload) {
  const match = path.match(/^\/history(?:\/([^/?]+))?(?:\/(restore))?$/);
  if (!match) return null;
  const listing = await historyListing(projectId);
  const [, recordId, restoreSegment] = match;
  const respond = () => {
    syncLegacyHistory(projectId);
    const record = JSON.parse(JSON.stringify(projectCache.get(projectId)));
    record.process_table = processTableEnabled;
    record.issue_table = issueTableEnabled;
    record.selection_table = selectionTableEnabled;
    record.history_table = historyTableEnabled;
    record.revision = (record.revision || 0) + 1;
    projectCache.set(projectId, record);
    return jsonResponse({ project: record });
  };
  if (recordId === undefined) {
    // POST /history —— 新增一行（缺的键补空串，与真服务一样）
    listing.rows.push({
      id: projectId + '-h' + listing.rows.length, sort_order: listing.rows.length,
      dt: payload.dt || '', ver: payload.ver || '', ds: payload.ds || '', by: payload.by || '',
      revision: null, extra: {}, deleted_at: null, deleted_by: '', deleted_reason: '',
      created: '', updated: '',
    });
    return respond();
  }
  const row = listing.rows.filter(item => item.id === decodeURIComponent(recordId))[0];
  if (!row) return jsonResponse({ detail: '版本履历记录不存在，可能已被删除' }, 404);
  if (restoreSegment === 'restore') {
    row.deleted_at = null; row.deleted_by = ''; row.deleted_reason = '';
    return respond();
  }
  if (method === 'DELETE') {
    row.deleted_at = new Date().toISOString();
    row.deleted_by = 'smoke'; row.deleted_reason = '页面删除';
    return respond();
  }
  // PATCH：只认四个格子（其余键进 extra，不丢）
  for (const key of ['dt', 'ver', 'ds', 'by']) {
    if (key in payload) row[key] = String(payload[key] == null ? '' : payload[key]);
  }
  for (const [key, value] of Object.entries(payload)) {
    if (['dt', 'ver', 'ds', 'by', 'id', 'index', 'revision', 'kind'].includes(key)) continue;
    row.extra[key] = value;
  }
  return respond();
}

// 行级写：按行 id 落到"表"里，再同步回 pr[]，返回改完的项目记录
async function applyProcessWrite(projectId, path, method, payload) {
  const listing = await processListing(projectId);
  // 两类路由：工序下的（/processes/…）与项目级的刀具行（/tools/{id}）
  const toolOnly = path.match(/^\/tools\/([^/]+)(?:\/(photo))?$/);
  const underProcess = path.match(/^\/processes(?:\/([^/]+))?(?:\/(tools)(?:\/([^/]+))?)?(?:\/(photo))?$/);
  if (!toolOnly && !underProcess) return null;
  let processId = '', toolsSegment = '', toolId = '', photoSegment = '';
  if (toolOnly) {
    toolId = toolOnly[1];
    photoSegment = toolOnly[2] || '';
  } else {
    [, processId, toolsSegment, toolId, photoSegment] = underProcess;
  }
  const findProcess = id => listing.processes.filter(row => row.id === id)[0];
  const findTool = (id) => {
    for (const process of listing.processes) {
      const hit = (process.tools || []).filter(row => row.id === id)[0];
      if (hit) return hit;
    }
    return null;
  };
  if (toolOnly) {
    const tool = findTool(toolId);
    if (!tool) return null;
    if (photoSegment) tool.fi = method === 'DELETE' ? null : '/api/machining-dfm/assets/smoke';
    else if (method === 'DELETE') {
      // 逻辑删除：从列表里移走，进回收站（真服务就是这样）
      for (const process of listing.processes) {
        if ((process.tools || []).indexOf(tool) < 0) continue;
        process.tools = process.tools.filter(row => row !== tool);
      }
      tool.deleted_at = new Date().toISOString();
      listing.deleted_tools.push(tool);
    } else Object.assign(tool, payload);
  } else if (!processId) {
    // POST /processes —— 新增工序
    listing.processes.push({
      id: 'p-' + listing.processes.length, sort_order: listing.processes.length, project_id: projectId,
      nm: payload.nm || '新工序', mc: payload.mc || 1, mid: payload.mid || '', fixP: 0, eqP: 0,
      nc: payload.nc || {}, cI: null, machine_snapshot: {}, tools: [],
    });
  } else if (toolsSegment === 'tools' && !toolId) {
    const process = findProcess(processId);
    if (process) {
      process.tools = process.tools || [];
      process.tools.push({ id: 't-' + processId + '-' + process.tools.length, process_id: processId, sort_order: process.tools.length, ...payload });
    }
  } else if (toolsSegment === 'tools' && toolId) {
    const tool = findTool(toolId);
    if (tool) Object.assign(tool, payload);
  } else if (photoSegment) {
    const process = findProcess(processId);
    if (process) process.cI = method === 'DELETE' ? null : '/api/machining-dfm/assets/smoke';
  } else if (method === 'DELETE') {
    const process = findProcess(processId);
    if (process) {
      process.deleted_at = new Date().toISOString();
      listing.deleted_processes.push(process);
      listing.processes = listing.processes.filter(row => row !== process);
    }
  } else {
    const process = findProcess(processId);
    if (process) Object.assign(process, payload);
  }
  syncLegacy(projectId);
  const record = JSON.parse(JSON.stringify(projectCache.get(projectId)));
  record.process_table = processTableEnabled;
  record.revision = (record.revision || 0) + 1;
  return jsonResponse({ project: record });
}

// 工序设备选择：PUT 挂一台设备 / DELETE 清空。真服务会校验"设备真在库里"（不然 422），
// 这里同样校验——设备清单从真服务读（machines.js 读的是同一份）。
let machineCache = null;
async function machineList() {
  if (!machineCache) {
    const response = await guardedFetch(BASE + '/api/machining-dfm/machines');
    const data = await response.json();
    machineCache = data.machines || data.rows || [];
  }
  return machineCache;
}
async function applyMachineWrite(projectId, processId, method, payload) {
  const listing = await processListing(projectId);
  const process = listing.processes.filter(row => row.id === processId)[0];
  if (!process) return jsonResponse({ detail: '这道工序不在了' }, 404);
  const wanted = String((payload && (payload.machine_id || payload.mid)) || '').trim();
  if (method === 'DELETE' || !wanted) {
    process.mid = ''; process.machine_snapshot = {}; process.eqP = 0;
  } else {
    const machine = (await machineList()).filter(row => String(row.id) === wanted)[0];
    if (!machine) return jsonResponse({ detail: '设备库里没有这条记录：' + wanted }, 422);
    process.mid = wanted;
    process.machine_snapshot = { ...machine };
    // 与真服务一致：设备库有价就顺手同步这道工序的设备费
    if (Number(machine.price) > 0) process.eqP = Number(machine.price);
  }
  syncLegacy(projectId);
  const record = JSON.parse(JSON.stringify(projectCache.get(projectId)));
  record.process_table = processTableEnabled;
  record.revision = (record.revision || 0) + 1;
  return jsonResponse({ project: record });
}

sandbox.fetch = async (url, init = {}) => {
  // data URL（页面粘贴图片走这里）：直接解成 Blob，别拿去打真服务
  const raw = String(url);
  if (/^data:/.test(raw)) {
    const match = raw.match(/^data:([^;,]*)(;base64)?,([\s\S]*)$/);
    const mime = (match && match[1]) || 'application/octet-stream';
    const bytes = (match && match[2])
      ? Buffer.from(match[3], 'base64')
      : Buffer.from(decodeURIComponent((match && match[3]) || ''), 'utf8');
    return { ok: true, status: 200, headers: new Headers({ 'content-type': mime }),
      blob: async () => new Blob([bytes], { type: mime }), json: async () => ({}), text: async () => '' };
  }
  const target = raw.startsWith('http') ? raw : BASE + raw;
  const method = (init.method || 'GET').toUpperCase();
  requestLog.push(method + ' ' + target);
  // 工序列表：返回造的"表里的行"（真服务此刻还是 409）
  const listMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/processes(\?|$)/);
  if (method === 'GET' && listMatch) return jsonResponse(await processListing(listMatch[1]));
  // 问题清单列表：同一个道理
  const issueListMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/issues(\?|$)/);
  if (method === 'GET' && issueListMatch) return jsonResponse(await issueListing(issueListMatch[1]));
  // 选型（拆表后两类各一套接口）：夹具 /fixtures、检具 /gauges
  const selectionKindMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/(fixtures|gauges)(\?|$)/);
  if (method === 'GET' && selectionKindMatch) {
    return jsonResponse(await selectionKindListing(selectionKindMatch[1],
      selectionKindMatch[2] === 'fixtures' ? 'fixture' : 'gauge'));
  }
  // 老的多态接口（两类一起给）：留着，页面已经不调了
  const selectionListMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/selections(\?|$)/);
  if (method === 'GET' && selectionListMatch) return jsonResponse(await selectionListing(selectionListMatch[1]));
  // 版本履历列表：同一个道理
  const historyListMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/history(\?|$)/);
  if (method === 'GET' && historyListMatch) return jsonResponse(await historyListing(historyListMatch[1]));
  if (method !== 'GET') {
    writeCalls.push(method + ' ' + target + (init.body && typeof init.body === 'string' ? ' ' + init.body.slice(0, 160) : ''));
    const payload = init.body && typeof init.body === 'string' ? JSON.parse(init.body) : {};
    // 相对路径（给各个写处理器用）：去掉域名/前缀/**查询串**。
    // 查询串一定要去掉：逻辑删除的 reason/by 是 query（`?reason=页面删除`），带着它正则就匹配不上，
    // 表现是"请求发出去了、但没人处理"——真跑起来会以为接口坏了，所以这里踩过一次就写死。
    const relative = target.replace(/^.*\/api\/machining-dfm/, '')
      .replace(/^\/projects\/[^/]+/, '').split('?')[0];
    // 版本履历：行级保存 → 落到造的"表"里
    const historyMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/history(\/|$)/);
    if (historyMatch) {
      const result = await applyHistoryWrite(historyMatch[1], relative, method, payload);
      if (result) return result;
    }
    // 选型（拆表后两类各一套接口）：按格子行级保存 → 落到造的"表"里
    const selectionMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/(fixtures|gauges)(\/|$)/);
    if (selectionMatch) {
      const result = await applySelectionWrite(selectionMatch[1], relative, method, payload);
      if (result) return result;
    }
    // 工序设备选择：PUT 挂设备 / DELETE 清空（行级，作用在这道工序上）
    const machineMatch = target.match(
      /\/api\/machining-dfm\/projects\/([^/]+)\/processes\/([^/]+)\/machine$/);
    if (machineMatch) {
      const result = await applyMachineWrite(machineMatch[1], machineMatch[2], method, payload);
      if (result) return result;
    }
    // 问题清单：行级保存 → 落到造的"表"里
    const issueMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/issues(\/|$)/);
    if (issueMatch) {
      const result = await applyIssueWrite(issueMatch[1], relative, method, payload);
      if (result) return result;
    }
    // 工序/刀具行：行级保存 → 真正落到造的"表"里，再回一份改完之后的项目记录
    const rowMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/(processes|tools)(\/|$)/);
    if (rowMatch) {
      const result = await applyProcessWrite(rowMatch[1], relative, method, payload);
      if (result) return result;
    }
    // 整份保存（旧路径，问题清单/版本履历还走它）
    const putMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)$/);
    if (putMatch && method === 'PUT') {
      const record = JSON.parse(JSON.stringify(await projectRecord(putMatch[1])));
      record.name = payload.name || record.name;
      record.state = payload.state || record.state;
      record.process_table = processTableEnabled;
      record.issue_table = issueTableEnabled;
      record.selection_table = selectionTableEnabled;
      record.revision = (record.revision || 0) + 1;
      projectCache.set(putMatch[1], record);
      return jsonResponse(record);
    }
    // 项目信息：按真实接口的形状回一份"改完之后"的项目记录（只改内存，不动线上数据）
    const settingsMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/settings$/);
    const photoMatch = target.match(/\/api\/machining-dfm\/projects\/([^/]+)\/photos\/([\w]+)$/);
    if (settingsMatch || photoMatch) {
      const projectId = (settingsMatch || photoMatch)[1];
      const base = await projectRecord(projectId);
      const record = JSON.parse(JSON.stringify(base));
      if (settingsMatch) {
        Object.assign(record.state.G, payload);
      } else {
        record.state.G[photoMatch[2] === 'product' ? 'pI' : 'pf'] = method === 'DELETE' ? null : '/api/machining-dfm/assets/smoke';
      }
      record.process_table = processTableEnabled;
      record.issue_table = issueTableEnabled;
      record.selection_table = selectionTableEnabled;
      record.revision = (record.revision || 0) + 1;
      projectCache.set(projectId, record);
      return jsonResponse({ project: record });
    }
    // 写请求不动线上数据，但返回和真实接口同构的载荷，好让成功分支真正跑完
    const body = {
      ok: true,
      row: { name: '自检类别', builtin: false, source: 'manual' },
      machine: { id: 'self-test', brand: '自检', model: 'SMOKE' },
      tool: { id: 'self-test', tp: '自检刀具' },
      fixture: { id: 'self-test' },
      gauge: { id: 'self-test' },
      removed: { removed_rows: 0 },
      usage: [],
      count: 0,
    };
    return jsonResponse(body);
  }
  // 只有 GET 会走到这里（非 GET 全部在上面被拦下并返回假数据）
  return guardedFetch(target, { ...init, method: 'GET' });
};

// ---------------------------------------------------------------- 按 index.html 顺序加载
const files = ['host.js', 'machines.js', 'tools.js', 'library_pages.js', 'fixtures.js', 'gauges.js', 'project_info.js', 'process_page.js', 'issue_page.js', 'selection_page.js', 'history_page.js', 'legacy_app.js'];
for (const name of files) {
  const source = readFileSync(join(STATIC, name), 'utf8');
  try {
    vm.runInContext(source, context, { filename: name });
    console.log('✓ 加载', name);
  } catch (error) {
    problems.push(`加载 ${name} 抛异常：${error.message}`);
    console.log('✗ 加载', name, '→', error.message);
    break;
  }
}

const run = expression => vm.runInContext(expression, context);
const check = (label, ok, extra = '') => {
  if (!ok) problems.push(label + (extra ? ' → ' + extra : ''));
  console.log((ok ? '  ✓ ' : '  ✗ ') + label + (extra ? ' → ' + extra : ''));
};

console.log('\n=== 启动 host（真实 bootstrap）===');
try {
  await run('MachiningDFMHost.start()');
  await new Promise(resolve => setTimeout(resolve, 800));
  const state = run('JSON.stringify({tab:curTab, pr:PR.length, mdb:MDB.length, tdb:TDB.length, fdb:FDB.length, idb:IDB.length, fcnX:(G.fcnX||[]).length, icnX:(G.icnX||[]).length, status:document.getElementById("serverSaveStatus").textContent})');
  console.log('  运行状态:', state);
  const parsed = JSON.parse(state);
  check('bootstrap 载入设备库', parsed.mdb > 0, String(parsed.mdb));
  check('bootstrap 载入夹具库', parsed.fdb > 0, String(parsed.fdb));
  check('bootstrap 载入检具库', parsed.idb > 0, String(parsed.idb));
} catch (error) {
  problems.push('host.start() 抛异常：' + error.message + '\n' + error.stack);
  console.log('  ✗ host.start() 抛异常:', error.message);
}

console.log('\n=== 逐个页签渲染 ===');
// 权限门只做检查用：这里没有浏览器 session 里的管理员令牌，直接放行（不影响渲染逻辑本身）
run('adUnl=true;dbUnl=true;checkAdm=function(){return true;};checkPwd=function(){return true;};');
// 页签序号现在是**固定的**（legacy_app.js 里 SI=4）：0 项目信息 / 1 工序 / 2 夹具选型 /
// 3 检具选型 / 4 问题清单 / 5 版本履历 / 6 工艺设置 / 7 设备库 / 8 刀具库 / 9 夹具库 / 10 检具库
const tabs = [
  ['工艺设置', '6', 'bSettings'],
  ['设备库', '7', 'bMachDB'],
  ['刀具库', '8', 'bToolDB'],
  ['夹具库', '9', 'bFixDB'],
  ['检具库', '10', 'bInspDB'],
];
for (const [label, expression, fn] of tabs) {
  try {
    console.log('    调试:', run(`'curTab='+curTab+' adUnl='+adUnl+' dbUnl='+dbUnl+' PR='+PR.length+' | bFixDB 返回 '+typeof (typeof bFixDB==='function'?bFixDB():null)+' 长度 '+(function(){try{return String(bFixDB()||'').length}catch(e){return 'ERR '+e.message}})()`));
    const html = run(`(function(){curTab=${expression};render();return document.getElementById('mainPanels').innerHTML;})()`);
    const text = String(html || '');
    check(`${label} 渲染`, text.length > 200, `${text.length} 字符`);
    const junk = ['undefined', 'NaN', '[object Object]'].filter(token => text.includes(token));
    check(`${label} 无 undefined/NaN 泄漏`, junk.length === 0, junk.join(', '));
    if (junk.length) {
      const index = text.indexOf(junk[0]);
      console.log('     泄漏片段:', text.slice(Math.max(0, index - 120), index + 120).replace(/\s+/g, ' '));
    }
    if (label === '夹具库' || label === '检具库') {
      const cards = (text.match(/<h3>/g) || []).length;
      console.log(`     卡片数 ${cards}，含表格 ${text.includes('<table')}，含输入框 ${text.includes('<input')}`);
    }
  } catch (error) {
    problems.push(`${label} 渲染抛异常：${error.message}`);
    console.log(`  ✗ ${label} 渲染抛异常:`, error.message);
  }
  await new Promise(resolve => setTimeout(resolve, 400));
}

console.log('\n=== 页签渲染后再次 render()（模拟自动保存/重渲染）===');
try {
  run('curTab=9;render();');
  await new Promise(resolve => setTimeout(resolve, 300));
  check('重复渲染夹具库', true);
} catch (error) {
  problems.push('重复渲染抛异常：' + error.message);
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 项目信息页（业务数据重构第一部分）===');
try {
  const html = String(run("(function(){curTab=0;render();return document.getElementById('mainPanels').innerHTML;})()"));
  check('项目信息页渲染', html.length > 1500, html.length + ' 字符');
  const wanted = ['客户名称', '零件名称', '项目类型', '客户版本', 'DFM完成时间', '日可动时间', '可动率', '流程图显示', '产品图片'];
  const missing = wanted.filter(text => !html.includes(text));
  check('项目信息页字段齐全', missing.length === 0, missing.join(', '));
  check('项目信息字段走新 id（旧 gs* 输入框不再出现）', html.includes('id="pi_cust"') && !html.includes('id="gs0"'), '');
  const junk = ['undefined', 'NaN', '[object Object]'].filter(token => html.includes(token));
  check('项目信息页无 undefined/NaN 泄漏', junk.length === 0, junk.join(', '));
  console.log('     卡片数:', (html.match(/class="card"/g) || []).length, '| 输入框:', (html.match(/<input/g) || []).length);
} catch (error) {
  problems.push('项目信息页渲染抛异常：' + error.message);
  console.log('  ✗ 项目信息页渲染抛异常:', error.message);
}

console.log('\n=== 项目信息页：改一个字段 → 落库 + 换画面 ===');
try {
  const before = writeCalls.length;
  await run("(async()=>{ await ProjectInfoPage.saveField('hpd', { value: '12', classList: { toggle: function(){} } }); })()");
  await new Promise(resolve => setTimeout(resolve, 400));
  const calls = writeCalls.slice(before);
  check('saveField 发出 PATCH /settings', calls.some(call => call.includes('PATCH') && call.includes('/settings')), calls.join(' | '));
  const payloadCall = calls.filter(call => call.includes('/settings')).pop() || '';
  check('PATCH 载荷是单字段（行级保存）', payloadCall.includes('"hpd":12'), payloadCall.slice(0, 140));
  const notice = String(run("document.getElementById('piStatus').textContent"));
  check('保存后状态栏提示', notice.includes('已保存'), notice);
  const version = run('MachiningDFMHost.current().revision');
  check('保存后版本号递增（每次保存都留版本）', Number(version) > 1, 'v' + version);
  const html = String(run("document.getElementById('mainPanels').innerHTML"));
  check('保存后界面按新版本重绘', html.includes('· v' + version), '');
  const general = run('JSON.stringify({hpd:G.hpd,cust:G.cust,part:G.part})');
  console.log('     内存里的项目信息:', general);
} catch (error) {
  problems.push('项目信息保存抛异常：' + error.message);
  console.log('  ✗ 项目信息保存抛异常:', error.message);
}

console.log('\n=== 工序落表（1b）：开关关着时行为一字不变 ===');
// 线上此刻就是"开关关着"：任何工序改动都只能改内存、不许发行级写请求
try {
  check('ProcessPage 已加载', run('typeof ProcessPage') === 'object', run('typeof ProcessPage'));
  check('线上（未迁移）开关是关的', run('ProcessPage.enabled()') === false, String(run('ProcessPage.enabled()')));
  const before = writeCalls.length;
  const originalVf = run('PR[0].tl[0].vf');
  await run("sN(0,0,'vf',777)");
  await new Promise(resolve => setTimeout(resolve, 200));
  check('开关关着：改字段只动内存', run('PR[0].tl[0].vf') === 777, String(run('PR[0].tl[0].vf')));
  check('开关关着：没有行级写请求', writeCalls.length === before, writeCalls.slice(before).join(' | '));
  run(`PR[0].tl[0].vf=${JSON.stringify(originalVf)};`);
} catch (error) {
  problems.push('工序开关关闭态检查抛异常：' + error.message);
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 工序落表（1b）：开关打开后 → 行级保存 ===');
try {
  run("__enableProcessTable();MachiningDFMHost.current().process_table=true;render();");
  await new Promise(resolve => setTimeout(resolve, 200));
  check('ProcessPage.enabled() 跟随服务端开关', run('ProcessPage.enabled()') === true, String(run('ProcessPage.enabled()')));

  // 1) 刀具数字字段：PATCH 到"这一行"（按行 id，不是按下标）
  let before = writeCalls.length;
  await run("sN(0,0,'vf',800)");
  await new Promise(resolve => setTimeout(resolve, 400));
  let calls = writeCalls.slice(before);
  const toolPatch = calls.filter(call => call.startsWith('PATCH')).pop() || '';
  check('刀具数字字段 → PATCH 到行 id', toolPatch.includes('/tools/t-0-0 '), toolPatch);
  check('载荷是单字段（行级保存）', toolPatch.includes('"vf":800'), toolPatch.slice(0, 160));

  // 2) 刀具名从库里选：要带上库编号与价格/寿命快照
  before = writeCalls.length;
  const libraryName = run('(TDB.filter(function(row){return (row.grp||"hp")===G.prj;})[0]||TDB[0]||{}).tp||""');
  await run(`atT(0,1,${JSON.stringify(libraryName)})`);
  await new Promise(resolve => setTimeout(resolve, 400));
  calls = writeCalls.slice(before);
  const libraryPatch = calls.filter(call => call.startsWith('PATCH')).pop() || '';
  if (!libraryPatch) {
    console.log('     调试：libraryName=' + JSON.stringify(libraryName)
      + ' | PR.length=' + run('PR.length')
      + ' | current.process_table=' + run('(MachiningDFMHost.current()||{}).process_table')
      + ' | status=' + run("document.getElementById('serverSaveStatus').textContent"));
  }
  check('选库刀具 → PATCH 行', libraryPatch.includes('/tools/t-0-1'), libraryPatch);
  check('带库编号快照 tool_id', libraryPatch.includes('"tool_id"'), libraryPatch.slice(0, 200));
  check('带价格/寿命快照', libraryPatch.includes('"tool_price"') && libraryPatch.includes('"tool_life"'), libraryPatch.slice(0, 200));

  // 3) 工艺设置页的工序名/台数/设备价 → 行级保存
  before = writeCalls.length;
  await run("ProcessPage.setProcessField(0,'nm','机加工序-OP10 改名')");
  await new Promise(resolve => setTimeout(resolve, 300));
  calls = writeCalls.slice(before);
  check('工序名 → PATCH 工序行', calls.some(call => call.includes('/processes/p-0 ') && call.includes('改名')), calls.join(' | '));

  // 4) 非加工时间：一次提交六个计数
  before = writeCalls.length;
  await run("updNC(0,'cc',9)");
  await new Promise(resolve => setTimeout(resolve, 300));
  calls = writeCalls.slice(before);
  const ncPatch = calls.filter(call => call.includes('/processes/p-0')).pop() || '';
  check('非加工时间 → PATCH nc 六键', ncPatch.includes('"cc":9') && ncPatch.includes('"it"'), ncPatch.slice(0, 200));

  // 5) 新增/删除刀具行与工序
  before = writeCalls.length;
  await run('addTool(0)');
  await new Promise(resolve => setTimeout(resolve, 300));
  calls = writeCalls.slice(before);
  check('新增刀具行 → POST', calls.some(call => call.startsWith('POST') && call.includes('/processes/p-0/tools')), calls.join(' | '));
  before = writeCalls.length;
  await run('delTool(0,0)');
  await new Promise(resolve => setTimeout(resolve, 300));
  calls = writeCalls.slice(before);
  check('删除刀具行 → DELETE（逻辑删除）', calls.some(call => call.startsWith('DELETE') && call.includes('/tools/t-0-0')), calls.join(' | '));
  before = writeCalls.length;
  await run('addProc()');
  await new Promise(resolve => setTimeout(resolve, 300));
  calls = writeCalls.slice(before);
  check('新增工序 → POST', calls.some(call => call.startsWith('POST') && /\/processes[?\s]/.test(call)), calls.join(' | '));
  before = writeCalls.length;
  await run('delProc(0)');
  await new Promise(resolve => setTimeout(resolve, 300));
  calls = writeCalls.slice(before);
  check('删除工序 → DELETE（进回收站）', calls.some(call => call.startsWith('DELETE') && /\/processes\/p-/.test(call)), calls.join(' | '));

  // 6) 换设备：走**专门的**工序设备接口（下标映射经过上面的增删之后仍然指向正确的行）
  before = writeCalls.length;
  const firstProcessName = run('PR[0].nm');
  await run("setProcMachine(0, (MDB[0]||{}).id||'')");
  await new Promise(resolve => setTimeout(resolve, 300));
  calls = writeCalls.slice(before);
  const machinePatch = calls.filter(call => /\/machine\b/.test(call)).pop() || '';
  check('换设备 → PUT /processes/{id}/machine（不再 PATCH mid）',
    machinePatch.startsWith('PUT') && machinePatch.includes('"machine_id"'), machinePatch.slice(0, 160));
  const listingAfter = await processListing(run('MachiningDFMHost.current().id'));
  check('换设备改的是页面上这道工序（按下标对齐最新行）',
    listingAfter.processes[0] && listingAfter.processes[0].mid === run('(MDB[0]||{}).id'),
    JSON.stringify({ 页面第一道: firstProcessName, 表里第一行: listingAfter.processes[0] && listingAfter.processes[0].nm }));

  // 7) 保存后版本号与画面都跟着服务端走
  const version = run('MachiningDFMHost.current().revision');
  check('行级保存后版本号递增', Number(version) > 1, 'v' + version);
  const html = String(run("document.getElementById('mainPanels').innerHTML"));
  check('行级保存后界面重绘', html.length > 500, html.length + ' 字符');

  // 8) 行级保存之后不该再冒出"整份保存"（指纹对齐；否则一次编辑会存两遍、还可能盖回去）
  before = writeCalls.length;
  await run("sN(0,0,'ln',123)");
  await new Promise(resolve => setTimeout(resolve, 1800));
  calls = writeCalls.slice(before);
  const strayPut = calls.filter(call => call.startsWith('PUT'));
  check('行级保存后没有多余的整份保存', strayPut.length === 0, strayPut.join(' | '));
} catch (error) {
  problems.push('工序行级保存检查抛异常：' + error.message + '\n' + (error.stack || ''));
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 问题清单落表（2a）：开关关着时行为一字不变 ===');
try {
  check('IssuePage 已加载', run('typeof IssuePage') === 'object', run('typeof IssuePage'));
  check('线上（未迁移）问题清单开关是关的', run('IssuePage.enabled()') === false, String(run('IssuePage.enabled()')));
  const before = writeCalls.length;
  const issueCount = run('IS.length');
  if (issueCount > 0) {
    await run("iSet(0,'ds','开关关着时的描述')");
    await new Promise(resolve => setTimeout(resolve, 200));
    check('开关关着：问题描述只动内存', run("IS[0].ds") === '开关关着时的描述', String(run('IS[0].ds')));
    check('开关关着：没有行级写请求', writeCalls.length === before, writeCalls.slice(before).join(' | '));
  } else {
    console.log('  （这个项目没有问题清单行，跳过内存态检查）');
  }
  // 工序那一栏：开关关着仍然是可以直接输入名字的文本框
  const html = run('bIssues()');
  check('开关关着：工序一栏仍是文本输入', String(html).includes('placeholder="工序"'), String(html).slice(0, 120));
} catch (error) {
  problems.push('问题清单开关关闭态检查抛异常：' + error.message);
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 问题清单落表（2a）：开关打开后 → 行级保存 ===');
try {
  run("__enableIssueTable();MachiningDFMHost.current().issue_table=true;render();");
  await new Promise(resolve => setTimeout(resolve, 300));
  check('IssuePage.enabled() 跟随服务端开关', run('IssuePage.enabled()') === true, String(run('IssuePage.enabled()')));
  const listing = await issueListing(run('MachiningDFMHost.current().id'));
  const need = Math.max(1, listing.issues.length);
  while ((await issueListing(run('MachiningDFMHost.current().id'))).issues.length < need) break;
  check('问题清单表里有行可测', listing.issues.length > 0, String(listing.issues.length));
  if (listing.issues.length > 0) {
    // 1) 文本字段 → PATCH 到这一行（按行 id）
    let before = writeCalls.length;
    await run("iSet(0,'ds','行级保存的问题描述')");
    await new Promise(resolve => setTimeout(resolve, 400));
    let calls = writeCalls.slice(before);
    const patch = calls.filter(call => call.startsWith('PATCH')).pop() || '';
    check('问题描述 → PATCH 到行 id', patch.includes('/issues/i-0 '), patch);
    check('载荷是单字段（行级保存）', patch.includes('"ds":"行级保存的问题描述"'), patch.slice(0, 160));

    // 2) 工序下拉：选的是工序行 → 写外键 process_id（不是名字）
    //    注意：前面的用例删过一道工序，所以这里按**当前列表的第 0 道**来核对，不写死 p-0
    before = writeCalls.length;
    await run("IssuePage.setProcess(0,0)");
    await new Promise(resolve => setTimeout(resolve, 400));
    calls = writeCalls.slice(before);
    const fkPatch = calls.filter(call => call.includes('/issues/i-0')).pop() || '';
    const firstProcessId = (await issueListing(run('MachiningDFMHost.current().id'))).processes[0].id;
    check('选工序 → 写外键 process_id', fkPatch.includes('"process_id":"' + firstProcessId + '"'), fkPatch.slice(0, 160) + ' 期望 ' + firstProcessId);
    check('工序一栏已是下拉框', String(run('bIssues()')).includes('IssuePage.setProcess(0,this.value)'), String(run('bIssues()')).slice(0, 200));

    // 3) 状态
    before = writeCalls.length;
    await run("iSet(0,'st','已完成')");
    await new Promise(resolve => setTimeout(resolve, 300));
    calls = writeCalls.slice(before);
    check('状态 → PATCH 单字段', calls.some(call => call.includes('/issues/i-0') && call.includes('"st":"已完成"')), calls.join(' | '));

    // 4) 图片：粘贴走附件接口，删除走 DELETE
    before = writeCalls.length;
    await run("IssuePage.setPhoto(0,'bI','data:image/png;base64,iVBORw0KGgo=')");
    await new Promise(resolve => setTimeout(resolve, 400));
    calls = writeCalls.slice(before);
    check('优化前图片 → PUT 附件接口', calls.some(call => call.startsWith('PUT') && call.includes('/issues/i-0/photo/before')), calls.join(' | '));
    before = writeCalls.length;
    await run("IssuePage.setPhoto(0,'bI',null)");
    await new Promise(resolve => setTimeout(resolve, 300));
    calls = writeCalls.slice(before);
    check('删除优化前图片 → DELETE 附件接口', calls.some(call => call.startsWith('DELETE') && call.includes('/issues/i-0/photo/before')), calls.join(' | '));
  }

  // 5) 新增 / 删除 / 恢复：与旧 addIssue/delIssue 同名入口，走服务端
  let before = writeCalls.length;
  await run('addIssue()');
  await new Promise(resolve => setTimeout(resolve, 400));
  let calls = writeCalls.slice(before);
  check('新增问题 → POST /issues', calls.some(call => call.startsWith('POST') && call.includes('/issues ')), calls.join(' | '));

  const afterAdd = await issueListing(run('MachiningDFMHost.current().id'));
  before = writeCalls.length;
  await run('delIssue(' + (afterAdd.issues.length - 1) + ')');
  await new Promise(resolve => setTimeout(resolve, 400));
  calls = writeCalls.slice(before);
  check('删除问题 → DELETE（逻辑删除）', calls.some(call => call.startsWith('DELETE') && call.includes('/issues/')), calls.join(' | '));

  const bin = await run('IssuePage.recycleBin()');
  check('回收站能读到刚删的问题', Array.isArray(bin) && bin.length > 0, JSON.stringify(bin && bin.length));

  // 6) 行级保存之后不该再冒出"整份保存"
  before = writeCalls.length;
  await run("iSet(0,'ds','再改一次')");
  await new Promise(resolve => setTimeout(resolve, 1800));
  calls = writeCalls.slice(before);
  const strayPutIssue = calls.filter(call => call.startsWith('PUT') && !call.includes('/photo/'));
  check('问题清单行级保存后没有多余的整份保存', strayPutIssue.length === 0, strayPutIssue.join(' | '));
} catch (error) {
  problems.push('问题清单行级保存检查抛异常：' + error.message + '\n' + (error.stack || ''));
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 选型报价落表（2b）：开关关着时行为一字不变 ===');
try {
  check('SelectionPage 已加载', run('typeof SelectionPage') === 'object', run('typeof SelectionPage'));
  check('线上（未迁移）选型开关是关的', run('SelectionPage.enabled()') === false, String(run('SelectionPage.enabled()')));
  const before = writeCalls.length;
  const fixClasses = run('fixClasses().length');
  if (fixClasses > 0) {
    await run("setFixSel(0,'1025减震模具中心|开关关着时的夹具')");
    await new Promise(resolve => setTimeout(resolve, 200));
    check('开关关着：夹具选型只动内存', run('G.fixQ[0]') === '1025减震模具中心|开关关着时的夹具', String(run('G.fixQ[0]')));
    check('开关关着：没有行级写请求', writeCalls.length === before, writeCalls.slice(before).join(' | '));
  }
  // 是否报价的勾选框：开关关着仍然是老的"改内存 + 整份保存"
  check('开关关着：勾选框仍是旧写法', run('fxQuoteCall(0)').includes('G.fixQC[0]=this.checked'),
    String(run('fxQuoteCall(0)')));
} catch (error) {
  problems.push('选型开关关闭态检查抛异常：' + error.message);
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 选型报价落表（2b）：开关打开后 → 按格子行级保存 ===');
try {
  run("__enableSelectionTable();MachiningDFMHost.current().selection_table=true;render();");
  await new Promise(resolve => setTimeout(resolve, 300));
  check('SelectionPage.enabled() 跟随服务端开关', run('SelectionPage.enabled()') === true, String(run('SelectionPage.enabled()')));
  const listing = await selectionListing(run('MachiningDFMHost.current().id'));
  const fixtureListing = await selectionKindListing(run('MachiningDFMHost.current().id'), 'fixture');
  const gaugeListing = await selectionKindListing(run('MachiningDFMHost.current().id'), 'gauge');
  check('夹具/检具各有各的清单接口（4 + 5 格）',
    fixtureListing.slots.length === 4 && gaugeListing.slots.length === 5,
    fixtureListing.slots.length + '+' + gaugeListing.slots.length);
  check('清单里带表名，说明它落在哪张表',
    fixtureListing.table === 'project_fixtures' && gaugeListing.table === 'project_gauges',
    fixtureListing.table + '/' + gaugeListing.table);
  // 一个类别一格：夹具 4 + 检具 5 = 9 行。**没选型的格子也要有行**，否则"是否报价"的勾选会丢；
  // 这里不断言"空的正好几行"（前面几步自己也改过几格），只断言"空格子确实也有行、行都有 id"。
  const emptyRows = listing.rows.filter(row => !row.legacy_key);
  check('每个类别一格（4 + 5 = 9 行）', listing.rows.length === 9, listing.rows.length + ' 行');
  check('未选型的格子也有行、也有行 id（勾选不会丢）',
    emptyRows.length >= 5 && emptyRows.every(row => !!row.id),
    '空格子 ' + emptyRows.length + ' 个，全都有 id = ' + emptyRows.every(row => !!row.id));

  // 1) 夹具选型：按格子 PUT 到 /fixtures，不是按下标写整份
  let before = writeCalls.length;
  await run("setFixSel(0,'1025减震模具中心|两点式拉杆四轴机加夹具')");
  await new Promise(resolve => setTimeout(resolve, 400));
  let calls = writeCalls.slice(before);
  const fixPut = calls.filter(call => call.startsWith('PUT')).pop() || '';
  check('夹具选型 → PUT /fixtures/0', /\/projects\/[^/]+\/fixtures\/0\b/.test(fixPut), fixPut.slice(0, 160));
  check('选型提交的是旧格式字符串（服务端负责绑库）',
    fixPut.includes('"legacy_key":"1025减震模具中心|两点式拉杆四轴机加夹具"'), fixPut.slice(0, 200));
  const afterFix = await selectionListing(run('MachiningDFMHost.current().id'));
  const fixedRow = afterFix.rows.filter(row => row.kind === 'fixture' && row.slot === 0)[0];
  check('格子落在"表"里（类别 + 格子）', !!fixedRow && fixedRow.legacy_key.indexOf('两点式') >= 0,
    JSON.stringify(fixedRow && { category: fixedRow.category, key: fixedRow.legacy_key }));
  check('读模型 G.fixQ 跟着表变', run('G.fixQ[0]') === '1025减震模具中心|两点式拉杆四轴机加夹具', String(run('G.fixQ[0]')));

  // 2) 是否报价：只 PATCH 一个格子
  before = writeCalls.length;
  await run('SelectionPage.setQuoted(\'fixture\',1,false)');
  await new Promise(resolve => setTimeout(resolve, 400));
  calls = writeCalls.slice(before);
  const quotePatch = calls.filter(call => call.startsWith('PATCH')).pop() || '';
  check('是否报价 → PATCH 同一格', /\/projects\/[^/]+\/fixtures\/1\b/.test(quotePatch) && quotePatch.includes('"quoted":0'),
    quotePatch.slice(0, 160));
  check('读模型 G.fixQC 跟着表变', run('G.fixQC[1]') === 0, String(run('G.fixQC[1]')));
  check('勾选框 onchange 已接管', run('fxQuoteCall(1)').includes('SelectionPage.setQuoted'),
    String(run('fxQuoteCall(1)')));

  // 3) 检具选型（另一套类别）
  before = writeCalls.length;
  await run("setInspSel(2,'成品总成检具|控制器壳体总成检具|9081000615-01')");
  await new Promise(resolve => setTimeout(resolve, 400));
  calls = writeCalls.slice(before);
  const inspPut = calls.filter(call => call.startsWith('PUT')).pop() || '';
  check('检具选型 → PUT /gauges/2', /\/projects\/[^/]+\/gauges\/2\b/.test(inspPut), inspPut.slice(0, 160));
  const afterInsp = await selectionListing(run('MachiningDFMHost.current().id'));
  const inspRow = afterInsp.rows.filter(row => row.kind === 'gauge' && row.slot === 2)[0];
  check('检具格子落在"表"里', !!inspRow && inspRow.legacy_key.indexOf('9081000615-01') >= 0,
    JSON.stringify(inspRow && { category: inspRow.category, key: inspRow.legacy_key }));

  // 4) 清空：DELETE 这一格，行留着（勾选状态不丢）
  before = writeCalls.length;
  await run("setFixSel(0,'')");
  await new Promise(resolve => setTimeout(resolve, 400));
  calls = writeCalls.slice(before);
  const clearCall = calls.filter(call => call.startsWith('DELETE')).pop() || '';
  check('清空选型 → DELETE 这一格', /\/projects\/[^/]+\/fixtures\/0\b/.test(clearCall), clearCall.slice(0, 160));
  const afterClear = await selectionListing(run('MachiningDFMHost.current().id'));
  check('清空后行还在（只是不再绑库）',
    afterClear.rows.length === 9
    && afterClear.rows.filter(row => row.kind === 'fixture' && row.slot === 0)[0].legacy_key === '',
    String(afterClear.rows.length));

  // 5) 格子越界（字典刚改过）：不猜、不写、只刷新
  //    状态栏的文字会被页面自己的自动保存计时器覆盖，所以这里直接盯住 host.status 的调用
  run("window.__selNotices=[];(function(){var h=MachiningDFMHost,orig=h.status;"
    + "h.status=function(t,e){window.__selNotices.push(String(t));return orig.apply(h,arguments);};})();");
  before = writeCalls.length;
  await run("SelectionPage.setSelection('fixture',9,'1025减震模具中心|不该写进去')");
  await new Promise(resolve => setTimeout(resolve, 200));
  check('格子不在就不写请求', writeCalls.length === before, writeCalls.slice(before).join(' | '));
  const selNotices = run('JSON.stringify(window.__selNotices||[])');
  check('格子不在时给出提示', String(selNotices).includes('这一格已经不在了'), String(selNotices));

  // 6) 行级保存之后不该再冒出"整份保存"
  before = writeCalls.length;
  await run("setInspSel(3,'成品电子检具|再选一次')");
  await new Promise(resolve => setTimeout(resolve, 1800));
  calls = writeCalls.slice(before);
  const strayPutSelection = calls.filter(call => call.startsWith('PUT')
    && !/\/(fixtures|gauges)\/\d+(\s|$)/.test(call));
  check('选型行级保存后没有多余的整份保存', strayPutSelection.length === 0, strayPutSelection.join(' | '));

  // 7) 画面：报价表仍然由 legacy_app.js 出（本模块只写不画），并已挂到"夹具选型/检具选型"两个页签
  run('curTab=2;render();');
  await new Promise(resolve => setTimeout(resolve, 300));
  const quoteHtml = String(run('fixQuoteTable()'));
  check('夹具报价表仍由旧页面渲染', quoteHtml.includes('模具中心') && quoteHtml.includes('夹具选型'),
    quoteHtml.length + ' 字符');
  const fixturePage = String(run('bFixtureSelect()'));
  const gaugePage = String(run('bGaugeSelect()'));
  check('「夹具选型」页签里有夹具报价表与合计', fixturePage.includes('夹具选型') && fixturePage.includes('fixCostLine'),
    fixturePage.length + ' 字符');
  check('「检具选型」页签里有检具报价表 + 毛坯/成品检具类型 + 合计',
    gaugePage.includes('检具类别') && gaugePage.includes('毛坯检具类型')
    && gaugePage.includes('成品检具类型') && gaugePage.includes('inspCostLine'),
    gaugePage.length + ' 字符');
  check('「工艺设置」里不再重复放选型表（各归各页）',
    !String(run('bSettings()')).includes('夹具报价选型')
    && !String(run('bSettings()')).includes('检具报价选型'),
    String(run('bSettings()')).length + ' 字符');
} catch (error) {
  problems.push('选型报价行级保存检查抛异常：' + error.message + '\n' + (error.stack || ''));
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 版本履历落表（3a）：开关关闭态仍是旧路径 ===');
try {
  // 线上这个项目的 vh 是空的：先在"服务端记录"里造两行，页面 adopt 之后 VH 才有得改
  run("MachiningDFMHost.current().history_table=false;"
    + "MachiningDFMHost.adopt(__seedHistory(MachiningDFMHost.current().id),'seed');"
    + "MachiningDFMHost.current().history_table=false;render();");
  await new Promise(resolve => setTimeout(resolve, 250));
  check('HistoryPage 已加载', run('typeof HistoryPage') === 'object', run('typeof HistoryPage'));
  check('开关关着：HistoryPage.enabled() 为 false', run('HistoryPage.enabled()') === false,
    String(run('HistoryPage.enabled()')));
  check('页面内存里有 2 行履历（用来验旧路径）', run('VH.length') === 2, String(run('VH.length')));
  let before = writeCalls.length;
  await run("hpSet(0,'ver',{value:'V9.9-旧路径'})");
  await new Promise(resolve => setTimeout(resolve, 200));
  check('开关关着：改版本号只动内存', String(run('VH[0].ver')) === 'V9.9-旧路径', String(run('VH[0].ver')));
  check('开关关着：没有行级写请求', writeCalls.length === before, writeCalls.slice(before).join(' | '));
  await run("addVH()");
  await new Promise(resolve => setTimeout(resolve, 200));
  check('开关关着：新增仍是 VH.push', writeCalls.length === before, writeCalls.slice(before).join(' | '));
  check('开关关着：新增的一行排在最后（旧行为）', run('VH.length') === 3, String(run('VH.length')));
  // 旧路径本来就会安排一次"整份保存"：等它自己跑完，别干扰后面的检查
  await new Promise(resolve => setTimeout(resolve, 1800));
} catch (error) {
  problems.push('版本履历开关关闭态检查抛异常：' + error.message);
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 版本履历落表（3a）：开关打开后 → 按行行级保存 ===');
try {
  // 重造两行并打开开关（服务端记录与页面内存一起换）
  run("__enableHistoryTable();"
    + "MachiningDFMHost.adopt(__seedHistory(MachiningDFMHost.current().id),'seed');render();");
  await new Promise(resolve => setTimeout(resolve, 300));
  check('HistoryPage.enabled() 跟随服务端开关', run('HistoryPage.enabled()') === true,
    String(run('HistoryPage.enabled()')));
  check('开关打开后页面内存还是那 2 行', run('VH.length') === 2, String(run('VH.length')));
  const projectId = run('MachiningDFMHost.current().id');
  const listing = await historyListing(projectId);
  check('履历清单把旧 vh 原样搬成行', listing.count === 2 && listing.history[0].id === projectId + '-h0',
    JSON.stringify(listing.history.map(row => row.ver)));
  check('履历行的 id 与页面下标对齐', listing.history.map(row => row.id).join(',')
    === projectId + '-h0,' + projectId + '-h1', listing.history.map(row => row.id).join(','));

  // 1) 改一个格子：先 GET 清单换 id，再 PATCH 这一行
  let before = writeCalls.length;
  await run("hpSet(1,'ds',{value:'改结构（第二版）'})");
  await new Promise(resolve => setTimeout(resolve, 400));
  let calls = writeCalls.slice(before);
  const patch = calls.filter(call => call.startsWith('PATCH')).pop() || '';
  check('改一格 → PATCH /history/<行 id>', patch.includes('/history/' + projectId + '-h1'), patch);
  check('载荷是单字段（行级保存）', patch.includes('"ds":"改结构（第二版）"'), patch.slice(0, 200));
  check('读模型 vh 跟着表变', String(run('VH[1].ds')) === '改结构（第二版）', String(run('VH[1].ds')));

  // 2) 四个格子都试一遍（页面上的 date/文本框都走 hpSet）
  const fields = ['dt', 'ver', 'by'];
  for (const key of fields) {
    before = writeCalls.length;
    await run(`hpSet(0,'${key}',{value:'新${key}'})`);
    await new Promise(resolve => setTimeout(resolve, 350));
    calls = writeCalls.slice(before);
    const one = calls.filter(call => call.startsWith('PATCH')).pop() || '';
    check(`改 ${key} → PATCH 同一行`, one.includes('/history/' + projectId + '-h0')
      && one.includes(`"${key}":"新${key}"`), one.slice(0, 160));
  }

  // 3) 新增一行：POST（页面 addVH 收在 helper 里）
  before = writeCalls.length;
  await run('addVH()');
  await new Promise(resolve => setTimeout(resolve, 400));
  calls = writeCalls.slice(before);
  const post = calls.filter(call => call.startsWith('POST')).pop() || '';
  check('新增履历 → POST /history', post.includes('/history'), post.slice(0, 160));
  check('新增的日期默认今天（与旧 addVH 一致）', post.includes('"dt":"' + new Date().toISOString().slice(0, 10) + '"'),
    post.slice(0, 200));
  const afterAdd = await historyListing(projectId);
  check('表里多了一行', afterAdd.count === 3, String(afterAdd.count));

  // 4) 删除一行：DELETE（逻辑删除，进回收站）
  before = writeCalls.length;
  await run('window.confirm=function(){return true;};delVH(2)');
  await new Promise(resolve => setTimeout(resolve, 400));
  calls = writeCalls.slice(before);
  const removed = calls.filter(call => call.startsWith('DELETE')).pop() || '';
  check('删除履历 → DELETE 这一行（逻辑删除）',
    removed.includes('/history/' + projectId + '-h2') && removed.includes('reason='), removed.slice(0, 200));
  check('删除后读模型里没了这一行', run('VH.length') === 2, String(run('VH.length')));

  // 5) 行下标越界（列表刚被别处改过）：不猜、不写、只刷新
  run("window.__hisNotices=[];(function(){var h=MachiningDFMHost,orig=h.status;"
    + "h.status=function(t,e){window.__hisNotices.push(String(t));return orig.apply(h,arguments);};})();");
  before = writeCalls.length;
  await run("HistoryPage.setField(9,'ds','不该写进去')");
  await new Promise(resolve => setTimeout(resolve, 200));
  check('下标越界就不写请求', writeCalls.length === before, writeCalls.slice(before).join(' | '));
  const notices = run('JSON.stringify(window.__hisNotices||[])');
  check('越界时给出提示', String(notices).includes('这一行已经不在了'), String(notices));

  // 6) 行级保存之后不该再冒出"整份保存"
  before = writeCalls.length;
  await run("hpSet(0,'ds',{value:'再来一次'})");
  await new Promise(resolve => setTimeout(resolve, 1800));
  calls = writeCalls.slice(before);
  const strayPut = calls.filter(call => call.startsWith('PUT') && !call.includes('/history'));
  check('履历行级保存后没有多余的整份保存', strayPut.length === 0, strayPut.join(' | '));

  // 7) 画面：版本履历卡片仍然由 legacy_app.js 出（本模块只写不画）
  run('curTab=7;render();');
  await new Promise(resolve => setTimeout(resolve, 300));
  const versionHtml = String(run('bVersion()'));
  check('版本履历卡片仍由旧页面渲染',
    versionHtml.includes('版本变更履历') && versionHtml.includes("hpSet(0,'dt',this)"),
    versionHtml.length + ' 字符');
  check('版本履历表里用的是行级写入点（不再是 VH[i].x=this.value）',
    versionHtml.includes("hpSet(0,'dt',this)") && !versionHtml.includes('.dt=this.value'), '');
} catch (error) {
  problems.push('版本履历行级保存检查抛异常：' + error.message + '\n' + (error.stack || ''));
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 变更流水（3b）：服务端记录，页面只读不写 ===');
// 阶段 3b 的流水不是"页面上某个按钮触发的"，而是**服务端每个行级写入点的副产物**：
// 页面上改了哪一行，服务端就在同一次事务里记一条。所以这里要证明的恰恰是"页面什么都没干"：
// 上面已经跑过工序/刀具行/问题清单/选型报价/版本履历的一堆行级写入，一个 /changes 请求都不该有。
// （流水的界面留到阶段 4 回收站一起做，现在只有服务端记录 + 只读接口。）
try {
  const changeCalls = requestLog.filter(call => call.includes('/changes'));
  check('页面没有任何 /changes 请求（流水不由页面写，也不由页面读）',
    changeCalls.length === 0, changeCalls.join(' | '));
  check('上面那一堆行级写入确实发生过（否则这条检查是空的）',
    writeCalls.length > 5, String(writeCalls.length));

  const flag = run('typeof MachiningDFMHost.current().changes_table');
  check('记录里带着 changes_table 标志（页面能判断服务端有没有开这一批）',
    flag === 'boolean', String(flag) + '：' + String(run('MachiningDFMHost.current().changes_table')));
  // 标志必须跟着服务端的能力级别走（线上开关关着时 false；迁移打开之后是 true）。
  // 注意别写成"线上开关一定是关的"——那样这条检查会在迁移当天变红，而它想验的是"两边一致"。
  const version = run('MachiningDFMHost.current().business_version');
  check('changes_table 标志与服务端能力级别一致',
    run('MachiningDFMHost.current().changes_table') === (typeof version === 'number' && version >= 5),
    `business_version=${version}｜changes_table=${run('MachiningDFMHost.current().changes_table')}`);
  check('记录里没有渲染用的流水数组（界面还没做，不多塞数据）',
    run('typeof MachiningDFMHost.current().changes') === 'undefined',
    String(run('typeof MachiningDFMHost.current().changes')));

  // 静态兜底：页面的每个 JS 里都不该出现 /changes（连拼 URL 都不许）
  const pageFiles = ['legacy_app.js', 'host.js', 'process_page.js', 'issue_page.js',
    'selection_page.js', 'history_page.js', 'project_info.js'];
  const offenders = pageFiles.filter(name =>
    readFileSync(join(STATIC, name), 'utf8').includes('/changes'));
  check('页面 JS 里连 /changes 这个字符串都没有（前端零写入点）',
    offenders.length === 0, offenders.join(' | '));
} catch (error) {
  problems.push('变更流水检查抛异常：' + error.message + '\n' + (error.stack || ''));
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 交互：动作后界面是否真的重绘 ===');
// 回归点：模块自己的 render() 只返回字符串，动作里必须调 repaint() 才会换画面，
// 否则"新增/删除/换图"点了没反应（旧页面的 addF/delF 是直接调整页 render()）。
async function actionRepaints(label, expression, expectText) {
  const before = run("document.getElementById('mainPanels').innerHTML.length");
  try {
    await run(expression);
  } catch (error) {
    problems.push(`${label} 抛异常：${error.message}`);
    console.log(`  ✗ ${label} 抛异常:`, error.message);
    return;
  }
  await new Promise(resolve => setTimeout(resolve, 500));
  const after = run("document.getElementById('mainPanels').innerHTML");
  const changed = String(after).length !== before;
  const hasText = expectText ? String(after).includes(expectText) : true;
  check(`${label} 重绘界面`, changed && hasText, changed ? '' : '面板 HTML 未变化（DOM 未重绘）');
}

run('curTab=9;render();');
await new Promise(resolve => setTimeout(resolve, 300));
const firstFixtureId = run("FixturesPage.rows().length?FixturesPage.rows()[0].id:''");
await actionRepaints('夹具库·字段保存', `FixturesPage.saveField(${JSON.stringify(firstFixtureId)},'price','12345')`, '已保存');
await actionRepaints('夹具库·新增一行', "FixturesPage.add('1025减震模具中心')", '已新增');
await actionRepaints('夹具库·新增类别', "FixturesPage.addGroup()", '已新增');
await actionRepaints('夹具库·删除一行', `FixturesPage.remove(${JSON.stringify(firstFixtureId)})`, '已删除');
await run('curTab=7;render();');
await new Promise(resolve => setTimeout(resolve, 200));
await actionRepaints('设备库·新增一行', 'MachinesPage.add()', '已新增');
await run('curTab=8;render();');
await new Promise(resolve => setTimeout(resolve, 200));
await actionRepaints('刀具库·新增一行', 'ToolsPage.add()', '已新增');

console.log('\n=== 结构：项目 → 工序（行内选设备）→ 夹具选型 / 检具选型 ===');
try {
  // 1) 页签就这么几个，且**不再随工序数量变**：先记下工序数，加一道工序后页签尾巴必须一样
  const tabsBefore = String(run("document.getElementById('tabBar').innerHTML")).match(/class="tab/g);
  const tabCountBefore = (tabsBefore || []).length;
  const tabLabels = String(run("document.getElementById('tabBar').innerHTML"));
  for (const label of ['项目信息', '工序', '夹具选型', '检具选型', '问题清单', '版本履历', '工艺设置']) {
    check(`页签里有「${label}」`, tabLabels.includes(label), label);
  }
  check('工序不再是"每道工序一个页签"',
    (tabLabels.match(/>工序<br>/g) || []).length === 1 && !tabLabels.includes('-OP'),
    String((tabLabels.match(/>[^<]*OP\d+[^<]*</g) || []).join(',')).slice(0, 120));

  // 2) 工序总表：一行一道工序，行内就是设备下拉框
  run('curTab=1;procView=-1;render();');
  await new Promise(resolve => setTimeout(resolve, 300));
  const tableHtml = String(run("document.getElementById('mainPanels').innerHTML"));
  check('工序总表渲染', tableHtml.includes('工序 / Processes'), tableHtml.length + ' 字符');
  check('总表行数与工序数一致',
    (tableHtml.match(/setProcMachine\(\d+,/g) || []).length === run('PR.length'),
    String((tableHtml.match(/setProcMachine\(\d+,/g) || []).length) + ' / ' + String(run('PR.length')));
  check('总表能点进单道工序的刀具明细', tableHtml.includes('openProc(0)'), tableHtml.length + ' 字符');
  const junk = ['undefined', 'NaN', '[object Object]'].filter(token => tableHtml.includes(token));
  check('总表无 undefined/NaN 泄漏', junk.length === 0, junk.join(', '));

  // 3) 行内选设备 → PUT /processes/{id}/machine（不是再退回"整份保存"）
  const machineRows = await machineList();
  if (!machineRows.length) {
    console.log('  ！ 线上设备库是空的，跳过"选设备"检查');
  } else {
    const target = machineRows[machineRows.length - 1];
    let before = writeCalls.length;
    await run(`setProcMachine(0,${JSON.stringify(String(target.id))})`);
    await new Promise(resolve => setTimeout(resolve, 500));
    const calls = writeCalls.slice(before);
    const put = calls.filter(call => call.startsWith('PUT')).pop() || '';
    check('选设备 → PUT /processes/{id}/machine',
      /\/processes\/[^/]+\/machine\b/.test(put) && put.includes('"machine_id"'), put.slice(0, 160));
    const stray = calls.filter(call => call.startsWith('PUT') && !/\/machine\b/.test(call));
    check('选设备不顺手做整份保存', stray.length === 0, stray.join(' | '));
    check('读模型里的 mid 跟着变', String(run('PR[0].mid')) === String(target.id), String(run('PR[0].mid')));

    // 4) 清空设备 → DELETE 同一个接口，读模型退回兜底机型
    before = writeCalls.length;
    await run('setProcMachine(0,"")');
    await new Promise(resolve => setTimeout(resolve, 500));
    const clearCalls = writeCalls.slice(before);
    const del = clearCalls.filter(call => call.startsWith('DELETE')).pop() || '';
    check('清空设备 → DELETE /processes/{id}/machine', /\/machine\b/.test(del), del.slice(0, 160));
  }

  // 5) 单道工序详情有"返回总表"，且工序总表仍然在（不是又变回页签）
  run('openProc(0);');
  await new Promise(resolve => setTimeout(resolve, 300));
  const detailHtml = String(run("document.getElementById('mainPanels').innerHTML"));
  check('工序详情页有「返回工序总表」', detailHtml.includes('返回工序总表'), detailHtml.slice(0, 60));
  check('工序详情仍然只占"工序"这一个页签', run('curTab') === 1, String(run('curTab')));
  run('closeProc();');
  await new Promise(resolve => setTimeout(resolve, 200));
  check('返回后回到总表', String(run("document.getElementById('mainPanels').innerHTML")).includes('工序 / Processes'));

  // 6) 现在多加一道工序：页签数量不该变（这就是这次重构要修的事）
  await run('ProcessPage.addProcess()');
  await new Promise(resolve => setTimeout(resolve, 600));
  const tabCountAfter = (String(run("document.getElementById('tabBar').innerHTML")).match(/class="tab/g) || []).length;
  check('添加工序后页签数量不变', tabCountAfter === tabCountBefore,
    tabCountBefore + ' → ' + tabCountAfter);
} catch (error) {
  problems.push('工序/设备结构检查抛异常：' + error.message + '\n' + (error.stack || ''));
  console.log('  ✗ 抛异常:', error.message);
}

console.log('\n=== 选型页：夹具/检具数据能否被选型表读到 ===');
try {
  // 工序只有一张总表：页签 1 渲染的就是它
  const processHtml = String(run("(function(){curTab=1;procView=-1;render();return document.getElementById('mainPanels').innerHTML;})()"));
  check('工序总表（页签 1）渲染', processHtml.length > 500, processHtml.length + ' 字符');
  run('curTab=2;render();');
  await new Promise(resolve => setTimeout(resolve, 300));
  // legacy render() 末尾会对每个类别调 fixFilter(k)/iqFilter(k)，把库里的数据灌进选型下拉
  const fixOptions = run("document.getElementById('fqSel0').innerHTML");
  check('夹具选型下拉有选项', String(fixOptions).includes('未选型') && String(fixOptions).includes('¥'), String(fixOptions).slice(0, 90));
  const fixQuote = run('fixQuoteTable()');
  check('夹具报价选型表', String(fixQuote).includes('模具中心') && String(fixQuote).includes('夹具选型'), String(fixQuote).length + ' 字符');
  const inspQuote = run('inspQuoteTable()');
  check('检具选型表', String(inspQuote).includes('检具类别') || String(inspQuote).includes('类别'), String(inspQuote).length + ' 字符');
  console.log('     选型下拉首段:', String(fixOptions).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120));
} catch (error) {
  problems.push('选型页检查抛异常：' + error.message);
  console.log('  ✗ 选型页检查抛异常:', error.message);
}

console.log('\n=== 交互：夹具页逐字段保存（写请求被拦下记录）===');
try {
  const before = writeCalls.length;
  await run('(async()=>{await FixturesPage.saveField(FixturesPage.rows()[0].id,"price","12345");})()');
  await new Promise(resolve => setTimeout(resolve, 300));
  check('saveField 发出 PATCH', writeCalls.length > before, writeCalls.slice(before).join(' | '));
  const notice = run('document.getElementById("fixturesStatus").textContent');
  console.log('     状态栏:', notice);
} catch (error) {
  problems.push('saveField 抛异常：' + error.message);
  console.log('  ✗ saveField 抛异常:', error.message);
}

console.log('\n写请求（已拦下，未落库）:', writeCalls.length);
for (const call of writeCalls.slice(0, 12)) console.log('  ', call);
if (messages.length) {
  console.log('\n控制台输出:');
  for (const message of messages.slice(0, 15)) console.log('  ', message.slice(0, 200));
}

console.log('\n' + (problems.length ? '发现问题:\n - ' + problems.join('\n - ') : '全部检查通过 ✓'));
process.exitCode = problems.length ? 1 : 0;
