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
const SRC = path.join(ROOT, "HPDC_DFM_Generator_A13.html");
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
      } else if (field.type === "issueList") {
        tables[field.k] = { module: mod.name, group: group.name, label: "开口问题清单", columns: {
          no: "序号", desc: "问题描述", prop: "修改方案 / 建议", fb: "客户回复", st: "状态",
          before: "优化前图片", after: "优化后图片"
        }};
      } else if (field.k && !["machine", "vision", "videos"].includes(field.type)) {
        const pathKey = `f.${field.k}`;
        fields.push({ path: pathKey, module: mod.name, group: group.name, label });
      }
    });
  });
});

// A13 rich-state projections exposed by app.a13.project_state / a13_platform.js.
[
  ["quoteCustomer","客户名称"],["quoteMoldName","模具名称"],["quotePartNo","报价零件号"],
  ["quoteDate","报价日期"],["quoteAlloy","铝合金材料"],["quoteBlankWeight","毛坯重量"],
  ["quoteFinishedWeight","成品重量"],["quoteMoldType","模具类型"],["quoteMoldMaterial","模具材料"],
  ["quoteMachineTonnage","报价机型吨位"],["quoteStructureCondition","结构条件"],["quoteMoldQuantity","模具数量"],
  ["quoteHasSlider","有无滑块"],["quoteItemCount","报价项数"],["quoteNetTotal","未税合计"],
  ["quoteTax","税额"],["quoteGrossTotal","含税合计"],["visionDefectCount","缺陷标注数"],
  ["visionReviewedCount","已复核标注数"]
].forEach(([key,label])=>fields.push({path:`f.${key}`,module:key.startsWith("vision")?"模流分析（10 项）":"模具报价",group:key.startsWith("vision")?"缺陷标注汇总":"报价汇总",label}));

tables.quoteSheet={module:"模具报价",group:"报价单",label:"报价明细",columns:{key:"项目标识",cat:"类别",desc:"项目描述",unit:"单价",qty:"数量",total:"合计"}};
tables.machineLibrary={module:"产品信息",group:"压铸机选型评估",label:"项目设备库",columns:{brand:"品牌",model:"型号",ton:"吨位",lock:"锁模力",open:"开模行程",moldMin:"最小容模量",moldMax:"最大容模量",tie:"哥林柱间距",tieDia:"哥林柱直径",injForce:"压射力",injStroke:"压射行程",punch:"冲头直径",v0:"空压射速度",ejForce:"顶出力",ejStroke:"顶出行程",plate:"模板尺寸"}};
tables.visionDefects={module:"模流分析（10 项）",group:"缺陷标注汇总",label:"缺陷标注与复核",columns:{module:"模流项",image:"云图序号",type:"缺陷类型",severity:"严重度",advice:"处理建议",source:"来源",verdict:"复核结论",confidence:"置信度",x:"X",y:"Y",w:"宽",h:"高"}};

// Fixed, discoverable image paths for the first ten issue cards. Repeated issue
// pages can still bind relative paths (before.0 / after.0) from the table row.
for(let n=0;n<10;n++){
  images[`issueBefore${n+1}`]={module:"问题清单",group:"优化前后对比",label:`问题 ${n+1} 优化前`,path:`t.issues[${n}].before[0]`};
  images[`issueAfter${n+1}`]={module:"问题清单",group:"优化前后对比",label:`问题 ${n+1} 优化后`,path:`t.issues[${n}].after[0]`};
}

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
