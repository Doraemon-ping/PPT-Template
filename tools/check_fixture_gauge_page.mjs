/* 无头校验 library_pages.js + fixtures.js + gauges.js：
 * 用假 DOM/fetch 跑一遍渲染与交互，确认分组卡片、逐字段保存、类别增删与旧读模型同步都对。
 * 用法：node tools/check_fixture_gauge_page.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const read = name => readFileSync(join(here, '..', 'static', 'machining_dfm', name), 'utf8');
const shared = read('library_pages.js');
const fixturesSource = read('fixtures.js');
const gaugesSource = read('gauges.js');

const CENTERS = [
  { name: '1025减震模具中心', label: '1025减震模具中心', sort_order: 0, builtin: true },
  { name: '8107结构件模具中心', label: '8107结构件模具中心', sort_order: 1, builtin: true },
];
const CENTER_USAGE = { '1025减震模具中心': 2, '8107结构件模具中心': 0 };
const CATEGORIES = [
  { name: '毛坯检具', label: '毛坯检具', sort_order: 0, builtin: true },
  { name: '试验检具类别', label: '试验检具类别', sort_order: 5, builtin: false },
];
const CATEGORY_USAGE = { 毛坯检具: 1, 试验检具类别: 1 };

const FIXTURE_FIELDS = [
  { key: 'center', type: 'choice', label: '模具中心', unit: '', default: '', references: 'fixture_centers',
    choices: CENTERS.map(c => ({ value: c.name, label: c.name, builtin: c.builtin })) },
  { key: 'name', type: 'text', label: '名称', unit: '', default: '' },
  { key: 'price', type: 'real', label: '价格', unit: '¥', default: 0 },
  { key: 'mc', type: 'int', label: '制造周期', unit: '天', default: 0 },
  { key: 'rmk', type: 'text', label: '备注', unit: '', default: '' },
];
const GAUGE_FIELDS = [
  { key: 'type', type: 'choice', label: '检具类别', unit: '', default: '', references: 'gauge_categories',
    choices: CATEGORIES.map(c => ({ value: c.name, label: c.name, builtin: c.builtin })) },
  { key: 'name', type: 'text', label: '检具名称', unit: '', default: '' },
  { key: 'drw', type: 'text', label: '检具图号', unit: '', default: '' },
  { key: 'prdSize', type: 'text', label: '产品尺寸', unit: 'mm', default: '' },
  { key: 'inspSize', type: 'text', label: '检具尺寸', unit: 'mm', default: '' },
  { key: 'price', type: 'real', label: '价格', unit: '万¥', default: 0 },
  { key: 'dc', type: 'int', label: '设计周期', unit: '天', default: 0 },
  { key: 'mc', type: 'int', label: '制造周期', unit: '天', default: 0 },
];
const FIXTURES = [
  { id: 'f1', center: '1025减震模具中心', name: '四轴机加夹具', price: 12000, mc: 30, rmk: '', photo_url: null },
  { id: 'f2', center: '1025减震模具中心', name: '五轴机加夹具', price: 35000, mc: 45, rmk: '含外购件', photo_url: '/api/machining-dfm/assets/x1' },
];
const GAUGES = [
  { id: 'g1', type: '毛坯检具', name: '左后纵梁毛坯检具', drw: '9020045309-01', prdSize: '1138*700*461',
    inspSize: '1200*1000*1400', price: 12.5, dc: 15, mc: 40, photo_url: null },
  { id: 'g2', type: '试验检具类别', name: '试验检具', drw: 'T-001', prdSize: '10*20*30',
    inspSize: '40*50*60', price: 1, dc: 1, mc: 2, photo_url: null },
];

const calls = [];
globalThis.window = globalThis;
// 旧读模型与类别缓存必须存在，新模块才会就地同步
globalThis.FDB = [];
globalThis.IDB = [];
globalThis.G = { icnX: [], fcnX: [] };
globalThis.TR = value => value;
globalThis.f = (value, digits) => Number(value || 0).toFixed(digits);
globalThis.armPaste = callback => { globalThis.__pasteCb = callback; };
globalThis.confirm = () => true;
globalThis.prompt = () => '1999试验模具中心';
globalThis.document = {
  getElementById: () => null,
  createElement: () => ({ click() {}, set onchange(v) {}, files: null }),
  body: { appendChild() {} },
};

const json = body => ({ ok: true, status: 200, json: async () => body });
const coerce = (body, numeric) => {
  const out = { ...body };
  for (const key of Object.keys(out)) if (numeric.has(key)) out[key] = Number(out[key] || 0);
  return out;
};
globalThis.fetch = async (url, init = {}) => {
  const method = init.method || 'GET';
  const body = init.body && typeof init.body === 'string' && init.body.startsWith('{') ? JSON.parse(init.body) : null;
  calls.push({ url, method, body });
  if (url.endsWith('/fixtures') && method === 'GET') return json({ fixtures: FIXTURES, fields: { fields: FIXTURE_FIELDS }, count: FIXTURES.length });
  if (url.endsWith('/fixture-centers') && method === 'GET') return json({ rows: CENTERS, usage: CENTER_USAGE });
  if (url.endsWith('/gauges') && method === 'GET') return json({ gauges: GAUGES, fields: { fields: GAUGE_FIELDS }, count: GAUGES.length });
  if (url.endsWith('/gauge-categories') && method === 'GET') return json({ rows: CATEGORIES, usage: CATEGORY_USAGE });
  if (url.includes('/fixtures') && method === 'POST') {
    return json({ fixture: { id: 'fnew', photo_url: null, ...coerce(body, new Set(['price', 'mc'])) }, count: 3 });
  }
  if (url.includes('/gauges') && method === 'POST') {
    return json({ gauge: { id: 'gnew', photo_url: null, ...coerce(body, new Set(['price', 'dc', 'mc'])) }, count: 3 });
  }
  if (url.includes('/fixtures/') && method === 'PATCH') {
    return json({ fixture: { ...FIXTURES.find(r => r.id === 'f1'), ...coerce(body, new Set(['price', 'mc'])) } });
  }
  if (url.includes('/gauges/') && method === 'PATCH') {
    return json({ gauge: { ...GAUGES.find(r => r.id === 'g1'), ...coerce(body, new Set(['price', 'dc', 'mc'])) } });
  }
  if (url.includes('/fixtures/') && method === 'DELETE') return json({ removed: { remaining: 1 }, usage: [{ project: 'P1' }] });
  if (url.includes('/gauges/') && method === 'DELETE') return json({ removed: { remaining: 1 }, usage: [] });
  if (url.endsWith('/fixture-centers') && method === 'POST') return json({ row: { name: body.name, builtin: false } });
  if (url.includes('/fixture-centers/') && method === 'DELETE') return json({ removed: { removed_rows: 2 } });
  if (url.includes('/gauge-categories/') && method === 'DELETE') return json({ removed: { removed_rows: 1 } });
  if (url.includes('/photo') && method === 'DELETE') return json({ fixture: { id: 'f2', photo_url: null }, gauge: { id: 'g2', photo_url: null } });
  throw new Error('未预期的请求 ' + method + ' ' + url);
};

new Function('window', 'document', 'fetch', 'Headers', 'TR', 'f', shared)(
  globalThis, globalThis.document, globalThis.fetch, globalThis.Headers, globalThis.TR, globalThis.f,
);
for (const [name, source] of [['fixtures.js', fixturesSource], ['gauges.js', gaugesSource]]) {
  new Function('window', 'document', 'fetch', 'Headers', 'TR', 'f', 'createNamedLibraryPage', source)(
    globalThis, globalThis.document, globalThis.fetch, globalThis.Headers, globalThis.TR, globalThis.f,
    globalThis.createNamedLibraryPage,
  );
  if (name === 'fixtures.js' && !globalThis.FixturesPage) throw new Error('fixtures.js 未导出 FixturesPage');
  if (name === 'gauges.js' && !globalThis.GaugesPage) throw new Error('gauges.js 未导出 GaugesPage');
}
const fixtures = globalThis.FixturesPage;
const gauges = globalThis.GaugesPage;
const problems = [];
const check = (label, ok, extra = '') => { if (!ok) problems.push(label + (extra ? ' → ' + extra : '')); };

// ---------------- 夹具库 ----------------
await fixtures.load();
check('FDB 旧读模型同步', globalThis.FDB.length === 2, String(globalThis.FDB.length));
check('G.fcnX 同步为字典类别', globalThis.G.fcnX.join(',') === '1025减震模具中心,8107结构件模具中心', String(globalThis.G.fcnX));

let html = fixtures.render();
const cards = [...html.matchAll(/<h3>(.*?)<\/h3>/g)].map(m => m[1]);
check('每个模具中心一张卡片', cards.length === 2 && cards[0].includes('1025减震模具中心'), JSON.stringify(cards));
const headers = [...html.matchAll(/<th>(.*?)<\/th>/g)].map(m => m[1]).slice(0, 6);
check('夹具表头与页面一致',
  JSON.stringify(headers) === JSON.stringify(['图片', '名称', '价格(¥)', '制造周期(天)', '备注', '操作']),
  JSON.stringify(headers));
check('夹具值渲染', html.includes('value="四轴机加夹具"') && html.includes('value="12000"') && html.includes('value="30"'), '');
check('图片单元格：有图显示换图/删除，无图显示粘贴/上传',
  html.includes('换图') && html.includes('📁') && html.includes('/api/machining-dfm/assets/x1'), '');
check('空类别提示', html.includes('该类别下暂无记录') && html.includes('0 条'), '');
check('内置类别不显示删除入口', !html.includes("removeGroup('1025减震模具中心')"), '');

await fixtures.saveField('f1', 'price', '13500');
const patch = calls.filter(c => c.method === 'PATCH').pop();
check('夹具逐字段 PATCH', patch && patch.body.price === 13500 && Object.keys(patch.body).length === 1, JSON.stringify(patch && patch.body));
check('夹具已回填为数字', fixtures.rowById('f1').price === 13500, String(fixtures.rowById('f1').price));

await fixtures.add('8107结构件模具中心');
const addCall = calls.filter(c => c.method === 'POST' && c.url.endsWith('/fixtures')).pop();
check('夹具新增带上中心与默认值',
  addCall && addCall.body.center === '8107结构件模具中心' && addCall.body.price === 0 && addCall.body.mc === 0,
  JSON.stringify(addCall && addCall.body));

await fixtures.remove('f1');
html = fixtures.render();
check('夹具删除提示引用项目', html.includes('1 个项目引用过它'), '');

await fixtures.addGroup();
const groupCall = calls.filter(c => c.method === 'POST' && c.url.endsWith('/fixture-centers')).pop();
check('新增模具中心走字典接口', groupCall && groupCall.body.name === '1999试验模具中心', JSON.stringify(groupCall && groupCall.body));

await fixtures.removeGroup('试验检具类别');
check('空类别删除不带 cascade', calls.filter(c => c.method === 'DELETE')[0].url.indexOf('cascade') < 0, '');

// ---------------- 检具库 ----------------
await gauges.load();
check('IDB 旧读模型同步', globalThis.IDB.length === 2, String(globalThis.IDB.length));
check('G.icnX 同步为字典类别', globalThis.G.icnX.join(',') === '毛坯检具,试验检具类别', String(globalThis.G.icnX));

html = gauges.render();
const gaugeHeaders = [...html.matchAll(/<th>(.*?)<\/th>/g)].map(m => m[1]).slice(0, 9);
check('检具表头与页面一致', JSON.stringify(gaugeHeaders) === JSON.stringify([
  '图片', '检具名称', '检具图号', '产品尺寸(mm)', '检具尺寸(mm)', '价格(万¥)', '设计周期(天)', '制造周期(天)', '操作',
]), JSON.stringify(gaugeHeaders));
check('检具值渲染',
  html.includes('value="9020045309-01"') && html.includes('value="1138*700*461"') && html.includes('value="12.5"')
  && html.includes('value="15"') && html.includes('value="40"'), '');
check('自定义类别显示删除入口', html.includes("removeGroup('试验检具类别')"), '');

await gauges.saveField('g1', 'dc', '20');
const gaugePatch = calls.filter(c => c.method === 'PATCH' && c.url.includes('/gauges/')).pop();
check('检具逐字段 PATCH', gaugePatch && gaugePatch.body.dc === 20, JSON.stringify(gaugePatch && gaugePatch.body));

await gauges.removeGroup('试验检具类别');
const cascade = calls.filter(c => c.method === 'DELETE' && c.url.includes('/gauge-categories/')).pop();
check('有数据的类别删除带 cascade=1', cascade && cascade.url.includes('cascade=1'), cascade && cascade.url);

await gauges.add('毛坯检具');
const gaugeAdd = calls.filter(c => c.method === 'POST' && c.url.endsWith('/gauges')).pop();
check('检具新增带上类别', gaugeAdd && gaugeAdd.body.type === '毛坯检具', JSON.stringify(gaugeAdd && gaugeAdd.body));

// ---------------- legacy_app.js 的委托（静态检查，防止又被写回旧渲染逻辑）----------------
const legacy = read('legacy_app.js');
check('bFixDB 委托 FixturesPage.render', /function bFixDB\(\)\{[\s\S]{0,300}?FixturesPage\.render\(\)/.test(legacy), '');
check('bInspDB 委托 GaugesPage.render', /function bInspDB\(\)\{[\s\S]{0,300}?GaugesPage\.render\(\)/.test(legacy), '');
check('addFixClass 委托 FixturesPage.addGroup', /function addFixClass\(\)\{[\s\S]{0,160}?FixturesPage\.addGroup\(\)/.test(legacy), '');
check('delFixClass 委托 FixturesPage.removeGroup', /function delFixClass\(k\)\{[\s\S]{0,160}?FixturesPage\.removeGroup\(/.test(legacy), '');
check('addInspClass 委托 GaugesPage.addGroup', /function addInspClass\(\)\{[\s\S]{0,160}?GaugesPage\.addGroup\(\)/.test(legacy), '');
check('delInspClass 委托 GaugesPage.removeGroup', /function delInspClass\(k\)\{[\s\S]{0,160}?GaugesPage\.removeGroup\(/.test(legacy), '');
check('addF/addI 委托新模块', /function addF\([\s\S]{0,160}?FixturesPage\.add\(/.test(legacy)
  && /function addI\([\s\S]{0,160}?GaugesPage\.add\(/.test(legacy), '');
check('index.html 已加载新模块', (() => {
  const html = read('index.html');
  const versions = new Map([...html.matchAll(/machining_dfm\/([\w.]+\.js)\?v=([\w.-]+)/g)].map(m => [m[1], m[2]]));
  const wanted = ['host.js', 'library_pages.js', 'fixtures.js', 'gauges.js', 'legacy_app.js'];
  return wanted.every(name => versions.has(name)) && new Set([...versions.values()]).size === 1;
})(), '');
check('host.js 不再整库保存基础库', /function libraryState\(\)\{return \{\};\}/.test(read('host.js')), '');
// 动作（增删/换图/改字段/加删类别）之后必须 repaint()，否则数据存进去而屏幕不变
check('library_pages.js 动作后重绘', (read('library_pages.js').match(/repaint\(\)/g) || []).length >= 6, '');

console.log('请求次数:', calls.length);
for (const call of calls) console.log(' ', call.method, call.url, call.body ? JSON.stringify(call.body) : '');
console.log(problems.length ? '发现问题:\n - ' + problems.join('\n - ') : '全部检查通过 ✓');
process.exitCode = problems.length ? 1 : 0;
