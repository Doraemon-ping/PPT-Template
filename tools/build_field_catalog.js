// -*- mode: javascript; -*-
/* Build static/dfm_catalog.js — 字段中文目录（模块.分组.标签），
 * 数据源：static/index.html 中 MODULES Schema（其字段自带中文标签），
 * 仅供可视化绑定页展示翻译，不改任何数据/接口。
 * 运行：node tools/build_field_catalog.js
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const SRC = path.join(ROOT, "static", "index.html");
const OUT = path.join(ROOT, "static", "dfm_catalog.js");

const html = fs.readFileSync(SRC, "utf8");
const start = html.indexOf("var MODULES = [");
const markerIdx = html.indexOf("状态与渲染引擎", start);
const blockStart = html.lastIndexOf("/* ===", markerIdx);
if (start < 0 || markerIdx < 0 || blockStart < start) throw new Error("schema region not found in index.html");
const end = blockStart;
let region = html.slice(start, end);
// flowGroups 内用到 ASTM_LEVELS（定义在区域外），补桩
if (!region.includes("var ASTM_LEVELS")) {
  region = 'var ASTM_LEVELS=["ASTM E505 Level 1","ASTM E505 Level 8"];\n' + region;
}
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(region, sandbox);
const MODULES = sandbox.MODULES;
if (!Array.isArray(MODULES)) throw new Error("MODULES not evaluated");

const RESULT_LABELS = {
  rForce: "胀型力 / 锁模力校核",
  rTieBar: "哥林柱受力分布与平衡度",
  rHold: "包紧力计算",
  rEject: "顶杆顶出力与选型",
  rSqueeze: "挤压销计算",
  rSlider: "滑块油缸缸径计算",
  rVacuum: "抽真空计算",
  rCool: "冷却水量与冷却时间校核",
  rInject: "压射系统参数",
  rPQ2: "PQ² 工艺窗口",
  rMachine: "当前机型参数",
  rMachList: "机型对照表",
  rGateSpeed: "壁厚-内浇口速度对照表",
};

// 常见同义词/别名：用于把没有 schema 标签的少数自动字段映射为中文
const EXTRA = {
  "f.partNo": "零件号",
};

const fields = [];   // {path, module, group, label}
const tables = {};   // {tKey: {module, group, label, columns:{key:label}}}
const images = {};   // {k: {module, group, label}}

MODULES.forEach((mod) => {
  (mod.groups || []).forEach((group) => {
    (group.fields || []).forEach((field) => {
      const label = String(field.t || field.k || "");
      const meta = { module: mod.name, group: group.name, label };
      if (field.type === "table") {
        const cols = {};
        (field.cols || []).forEach((c) => { cols[c.k] = c.t || c.k; });
        tables[field.k] = { module: mod.name, group: group.name, label, columns: cols };
      } else if (field.type === "images") {
        images[field.k] = { module: mod.name, group: group.name, label, path: `i.${field.k}[0]` };
      } else if (field.k && field.type !== "machine") {
        const pathKey = `f.${field.k}`;
        fields.push({ path: pathKey, module: mod.name, group: group.name, label });
      }
    });
  });
});

// 补充后端派生/机器字段（Schema 里已覆盖大部分；这里兜底中文名）
const DERIVED_LABELS = {
  wPour: "每次浇注重量（自动）",
  cwM: "每次浇注金属量（自动）",
  aTotal2: "总投影面积（含滑块，自动）",
  pMax2: "最大铸造比压",
};

const catalog = { fields, tables, images, derived: DERIVED_LABELS, results: RESULT_LABELS };
const payload = `// 自动生成：node tools/build_field_catalog.js（勿手改）
window.DFM_CATALOG = ${JSON.stringify(catalog, null, 1)};
`;
fs.writeFileSync(OUT, payload, "utf8");
console.log(`written ${OUT}  fields=${fields.length} tables=${Object.keys(tables).length} images=${Object.keys(images).length}`);
