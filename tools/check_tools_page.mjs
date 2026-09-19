/* 无头校验 tools.js：用假 DOM/fetch 跑一遍渲染与交互，确认与旧页面行为一致。
 * 用法：node tools/check_tools_page.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'static', 'machining_dfm', 'tools.js'), 'utf8');

const CATS = [
  ['f', '面铣刀', 'cut'], ['hm', '合金铣刀', 'cut'], ['hd', '合金钻头', 'cut'], ['other', '其他', 'cut'],
  ['cn', '国内', 'nc'], ['im', '进口', 'nc'],
];
const FIELDS = {
  fields: [
    { key: 'grp', type: 'choice', label: '库分类', unit: '', default: 'hp', choices: [
      { value: 'hp', label: '高压项目刀具' }, { value: 'dp', label: '差压项目刀具' },
      { value: 'hld', label: '刀柄' }, { value: 'acc', label: '配件' }] },
    { key: 'tp', type: 'text', label: '型号', unit: '', default: '' },
    { key: 'cat', type: 'choice', label: '类型', unit: '', default: 'other',
      references: 'tool_categories',
      choices: CATS.map(([value, label, scope]) => ({ value, label, scope })) },
    { key: 'd', type: 'real', label: 'D', unit: 'mm', default: 0 },
    { key: 'ln', type: 'real', label: '长度L', unit: 'mm', default: 0 },
    { key: 'n', type: 'real', label: '转速n', unit: 'rpm', default: 0 },
    { key: 'vf', type: 'real', label: '进给vf', unit: 'mm/min', default: 0 },
    { key: 'life', type: 'real', label: '寿命', unit: 'min', default: 0 },
    { key: 'price', type: 'real', label: '价格', unit: '¥', default: 0 },
  ],
  derived: [
    { key: 'fz', label: '每齿进给', unit: 'mm', formula: 'vf/n' },
    { key: 'vc', label: '线速度', unit: 'm/min', formula: 'π·d·n/1000' },
  ],
};
const TOOLS = [
  { id: 't1', grp: 'hp', tp: 'D50面铣刀', cat: 'f', d: 50, ln: 0, n: 3000, vf: 3000, life: 0, price: 0, photo_id: null, photo_url: null },
  { id: 't2', grp: 'hp', tp: 'D10合金铣刀', cat: 'hm', d: 10, ln: 75, n: 3000, vf: 800, life: 120, price: 260, photo_id: 'a1', photo_url: '/api/machining-dfm/assets/a1' },
  { id: 't3', grp: 'hld', tp: 'BT30刀柄', cat: 'cn', d: 0, ln: 0, n: 0, vf: 0, life: 0, price: 800, photo_id: null, photo_url: null },
];

const calls = [];
globalThis.window = globalThis;
// legacy_app.js 里的旧读模型与筛选全局必须存在，tools.js 才会就地同步
globalThis.TDB = [];
globalThis.toolGrp = 'all';
globalThis.toolCat = '';
const NUMERIC = new Set(['d', 'ln', 'n', 'vf', 'life', 'price']);
const coerce = body => {
  const out = { ...body };
  for (const key of Object.keys(out)) if (NUMERIC.has(key)) out[key] = Number(out[key] || 0);
  return out;
};
globalThis.TR = value => value;
globalThis.f = (value, digits) => Number(value || 0).toFixed(digits);
globalThis.fi = value => String(value);
globalThis.armPaste = cb => { globalThis.__pasteCb = cb; };
globalThis.confirm = () => true;
globalThis.document = {
  getElementById: () => null,
  createElement: () => ({ click() {}, set onchange(v) {}, files: null }),
  body: { appendChild() {} },
};
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null });
  const json = body => ({ ok: true, status: 200, json: async () => body });
  if (url.endsWith('/tools') && (!init.method || init.method === 'GET')) {
    return json({ tools: TOOLS, fields: FIELDS, count: TOOLS.length });
  }
  if (url.includes('/tools/reorder')) return json({ tools: TOOLS });
  if (url.includes('/tools') && init.method === 'POST') {
    return json({ tool: { ...TOOLS[0], id: 'new', ...coerce(JSON.parse(init.body)) }, count: TOOLS.length + 1 });
  }
  if (url.includes('/tools/') && init.method === 'PATCH') {
    const id = url.split('/tools/')[1];
    return json({ tool: { ...TOOLS.find(t => t.id === id), ...coerce(JSON.parse(init.body)) } });
  }
  if (url.includes('/tools/') && init.method === 'DELETE') {
    return json({ removed: { id: 't1', tp: 'D50面铣刀', remaining: 2 }, usage: [{ project: 'P1' }, { project: 'P2' }] });
  }
  throw new Error('未预期的请求 ' + url + ' ' + (init.method || 'GET'));
};

// 以 window 身份执行 tools.js（IIFE 会把 ToolsPage 挂到 window 上）
new Function('window', 'document', 'fetch', 'Headers', 'TR', 'f', 'fi', source)(
  globalThis, globalThis.document, globalThis.fetch, globalThis.Headers, globalThis.TR, globalThis.f, globalThis.fi,
);
const page = globalThis.ToolsPage;
const problems = [];
const check = (label, ok, extra = '') => { if (!ok) problems.push(label + (extra ? ' → ' + extra : '')); };

await page.load();
check('TDB 旧读模型同步', Array.isArray(globalThis.TDB) && globalThis.TDB.length === 3, String(globalThis.TDB && globalThis.TDB.length));

let html = page.render();
const headers = [...html.matchAll(/<th>(.*?)<\/th>/g)].map(m => m[1]);
const expected = ['库分类', '型号', '图片', '类型', 'D(mm)', '长度L(mm)', '转速n(rpm)', '进给vf(mm/min)',
  '每齿进给fz<br>(自动)', '线速度Vc<br>(自动)', '寿命(min)', '价格(¥)', '操作'];
check('表头与旧页面一致', JSON.stringify(headers) === JSON.stringify(expected), JSON.stringify(headers));
check('自动列 fz = vf/n', html.includes('<td class="ro2">0.267</td>'), '');
check('自动列 Vc = π·d·n/1000', html.includes('<td class="ro2">94</td>'), '');
check('图片单元格', html.includes('/api/machining-dfm/assets/a1') && html.includes('粘贴'), '');
check('共 N 项', html.includes('共 3 项'), '');

// 库分类筛选到刀柄：切削四列整列消失，且不出现刀柄行的切削输入
page.setFilter('hld', '');
html = page.render();
check('刀柄页隐藏切削列', !html.includes('转速n(rpm)') && !html.includes('线速度Vc'), '');
check('刀柄过滤只剩 1 行', html.includes('共 1 项'), '');
check('刀柄类型下拉为国内/进口', html.includes('>国内<') && html.includes('>进口<') && !html.includes('>面铣刀<'), '');
check('库分类已同步旧全局', globalThis.toolGrp === 'hld', String(globalThis.toolGrp));

// 全部：刀柄行显示 —，切削行显示输入
page.setFilter('all', '');
html = page.render();
check('全部视图含 — 占位', html.includes('<td class="ro2">—</td>'), '');

// 单字段保存：切到刀柄要把类型改成国内
await page.saveField('t1', 'grp', 'hld');
const patch = calls.filter(c => c.method === 'PATCH').pop();
check('切库分类同时改类型', patch && patch.body.grp === 'hld' && patch.body.cat === 'cn', JSON.stringify(patch && patch.body));
check('切库分类已落库回填', page.toolById('t1').grp === 'hld' && page.toolById('t1').cat === 'cn', '');

await page.saveField('t2', 'price', '310');
const priceCall = calls.filter(c => c.method === 'PATCH').pop();
check('数值字段按原值提交', priceCall && priceCall.body.price === '310', JSON.stringify(priceCall && priceCall.body));
check('数值已回填为数字', page.toolById('t2').price === 310, String(page.toolById('t2').price));

// 新增：跟随当前筛选分类
page.setFilter('hld', '');
await page.add();
const addCall = calls.filter(c => c.method === 'POST').pop();
check('刀柄新增默认值', addCall && addCall.body.grp === 'hld' && addCall.body.cat === 'cn' && addCall.body.n === 0, JSON.stringify(addCall && addCall.body));

// 删除：提示按名称引用它的项目数
const removed = await page.remove('t1');
const delHtml = page.render();
check('删除提示引用项目', delHtml.includes('2 个项目的成本表按名称引用过它'), '');

// 排序提交全部 id
await page.move('t3', -1);
const reorder = calls.filter(c => c.url.includes('/reorder')).pop();
check('排序提交 id 列表', reorder && Array.isArray(reorder.body.ids) && reorder.body.ids.length === 3, JSON.stringify(reorder && reorder.body));

// 动作（增删/换图/改字段）之后必须 repaint()，否则数据存进去而屏幕不变
check('tools.js 动作后重绘', (source.match(/repaint\(\)/g) || []).length >= 5, '');

console.log('请求次数:', calls.length);
for (const call of calls) console.log(' ', call.method, call.url, call.body ? JSON.stringify(call.body) : '');
console.log(problems.length ? '发现问题:\n - ' + problems.join('\n - ') : '全部检查通过 ✓');
process.exitCode = problems.length ? 1 : 0;
