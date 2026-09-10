# 交接文档：模板绑定/生成引擎 现状与下一步（2026-09-02）

> 2026-09-09 最新架构：先读 [多表单平台交接](FORM_PLATFORM_2026-09-09.md)。已从单 DFM 扩展为 HTML Schema 驱动的独立应用/项目/模板空间，原 DFM 保留。本文以下内容为原模板引擎历史交接。

> 最新图片问题：见 [单元格图片绑定修复](CELL_IMAGE_BINDING_2026-09-03.md)。兼容旧方案 table_cell 误绑图片；跨模板依赖图不再按 XML 内容跨源去重。用户四页混合方案通过 PowerPoint 打开及逐页导出。

> 最新：见 [表格分页与兼容性修复](TABLE_PAGINATION_2026-09-03.md)。已定位并修复页面 tags 被共用、导入 master/layout ID 碰撞及已删除 notes 的悬空引用；上传模板 3 的续页和模板 2+3 混合分页已通过 PowerPoint 实测。下文旧兼容性结论属于历史记录，不代表这两个样本的最新结果；正式 84 页全量组合仍需单独验收。

> 2026-09-03 增量：先读 [方案复用与编辑交互](EDITOR_UX_2026-09-03.md)。用户明确要求复用的是**已保存方案中的一页（含绑定）**，不是只从原始 PPT 模板取页。

> 2026-09-09 增量：模板绑定已切换为“PPT 模板目标驱动”。`/api/template/scan` 返回
> `binding_targets`，工作台先选择当前页的文本框、图片、表格或占位符目标，再从当前表单应用的
> 字段目录选择来源；原样 HTML 只保留自己的稳定源路径（例如 `G.cust`），不会自动注入旧 DFM
> 字段别名。正式生成会扫描最终 OOXML，仍残留未绑定占位符时直接返回错误。详见
> [多表单应用平台交接](FORM_PLATFORM_2026-09-09.md)和[项目更新记录](CHANGELOG.md)。

> 2026-09-09 预览性能：编辑台在 PowerPoint 返回前保留原模板底图；请求 450ms 防抖，服务端使用
> 24 条/90 秒进程内 LRU 缓存，相同请求直接复用 PNG；预览导出默认 1280×720。响应头
> `X-DFM-Preview-Cache` 可区分 `hit`/`miss`。

> 写给接手开发的 Agent/工程师。接手前请先读：
> - `docs/PPT_TEMPLATE_GENERATOR_HANDOFF.md`（原始产品/架构交接，仍有效）
> - `docs/PPT_TEMPLATE_ENGINE_COMPLETION.md`（占位符/Deck 引擎完成说明）
> - 本文档 = 本轮（模板导入、可视化点选绑定、模板方案、多模板、整表填入、
>   PowerPoint 兼容性排障）之后的增量交接与**关键结论**。

## 1. 运行方式（已在本机验证）

```powershell
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000     # http://127.0.0.1:8000
node tools/build_field_catalog.js              # 字段中文目录（Schema 变更后重跑）
python -m unittest discover -s tests -p "test_*.py"   # 当前 224 项
node --test tests/editor_models.test.cjs tests/native_bridge.test.cjs  # 当前 12 项前端模型/桥接测试
```

页面：
- `/` 原 DFM 表单（可「📋 按方案生成」）
- `/template-editor` 可视化点选绑定工作台（上传模板→点对象→绑字段→存方案→生成）

## 2. 本轮新增能力（文件地图）

| 能力 | 位置 |
| --- | --- |
| 模板上传/注册（持久化 `data/templates/`） | `app/report/ppt/template_registry.py`；`POST /api/templates/upload` |
| 形状清单（几何+表格逐格） | `app/report/ppt/openxml/shape_inventory.py`；`POST /api/template/inspect` |
| 对象绑定（text/text_template/table_cell/table_rows/image/image_region/formula） | `shape_binding.py`、`image_binding.py`、`visual_binding.py`；用 `shape_id` 区分重名对象 |
| 整表填入（列映射 columns_map、删/补行、vMerge 拆开） | 同上 + `tests/test_explicit_binding_engine.py` |
| 模板方案（保存/载入/一键生成/二次编辑） | `app/report/ppt/scheme_service.py`；`/api/schemes*`；方案存 `data/schemes/*.json` |
| 跨模板拼页（导入依赖 part） | `app/report/ppt/openxml/slide_importer.py`（见 §4 限制） |
| 字段中文目录（模块.分组.标签） | `tools/build_field_catalog.js` → `static/dfm_catalog.js`（158 字段+9 表+24 图片+派生/结论） |
| 可视化绑定工作台 | `static/template_editor.html`（画布按真实几何可点选；点击即绑；列对应面板） |
| 示例数据补全默认表格 | `app/demo.py` `DEFAULT_TABLES`（dfmHist/fileStat/mech/matList/asm/seal/spr1Table/tol/issues） |
| `2.pptx` 产品分析页完整生成 | 通用对象绑定；参考脚本 `scripts/generate_product_analysis_page.py`；`tests/test_product_analysis_page.py` |
| 跨模板新增页 UI | `state.previewSource` 将模板预览与报告页分离；`state.baseTemplate` 保留生成基准模板，切换预览不改旧页 |
| 原页可视化选择 | `slide_preview.py` + `tools/export_slide_preview.ps1` 调 PowerPoint 导出缓存 PNG；画布透明选区；首次点对象自动入 deck |
| 当前页 + 数据实时预览 | `POST /api/template/live-preview`：临时 PPTX 原地填入绑定并渲染 PNG，不改源模板；前端防抖/取消/过期结果保护，数据或绑定变化自动刷新 |
| 局部文字替换 | `openxml/partial_text.py` + `text_replace` 绑定；`options.original_text/replacements[{start,end,text,source}]`，Unicode 码点位置，原文校验，跨 run 保留格式，支持单元格；清单新增未截断 `full_text` |

实时预览补充：重复页仅展示数组首条，忽略页面显示条件以便编辑；数据路径缺失时保留
对应原对象并通过 `X-DFM-Preview-Skipped` 返回数量。2026-09-03：正式生成的 `image` /
`image_region` 缺少数据或值为空时也保留原对象，统计 `images_missing` 并通过
`X-DFM-Images-Missing` 返回缺图数量（工作台生成和方案生成两个入口均支持）。
不更改绑定记录；必需文本缺失、已提供图片损坏等仍使用原有校验。
PowerPoint 渲染失败时前端回退原模板并显示错误。原页选区仍以模板几何为准，整表绑定
若增删行，生成后的新增行并非新的可绑定对象。当前环境通过项目 `.venv/Scripts/python.exe`
启动服务（依赖见 requirements-dev.txt），模板引擎启动所需的 `Optional` 导入已补齐。

用户当前真实使用：方案 `data/schemes/tp-dfm--v1-0.json`（官方模板+自传封面页，第 2 页「表格 3」整表填 dfmHist）。

## 3. 关键技术结论（新 Agent 务必先看，避免重复踩坑）

### 3.1 PowerPoint 兼容性（最重要）
用 **PowerPoint COM（本机 Office16 有）** 实测判定“能否被 PowerPoint 打开”，`python-pptx` 能打开 ≠ PowerPoint 能打开。

| 操作 | PowerPoint 结果 |
| --- | --- |
| in_place（保留全部页、原地改内容/表格） | ✅ 打开正常（84 页） |
| deck 模式克隆页/删页重建/跨模板导入（对官方 84 页模板） | ❌ 报“文件损坏/无法打开” |
| deck 模式（对 python-pptx 自建小模板，如 demo/table-demo） | ✅ 正常 |

- 原因**尚未彻底定位**（怀疑与官方模板含 notesSlides/OLE/复杂表格布局、或 rebuild 后残留关系有关，已做多组对照实验均未命中单点）。
- **结论：官方模板只走 `output_mode="in_place"`（整份 84 页，内容原地替换）**；需要“只留几页/跨模板拼/重复页”时，先解决幻灯片复制兼容性（见 §5）。
- 引擎已在 `template_engine.py` deck 分支加入“快速路径”：单一模板+无重复+每源页一次 → 仍走原 rebuild（对小模板 OK，官方模板请用 in_place）。

### 3.2 单元格写入被 PowerPoint 忽略（“第二行看不见”）根因
- 空行单元格段落常带 `<a:endParaRPr>`；把新 `<a:r>` **append 到它后面**违反 OOXML 顺序（endParaRPr 必须在所有 run 之后），PowerPoint 静默忽略该 run。
- 修复：`shape_binding.py` `_set_cell_text` 中，若段落已有 endParaRPr，把 run **insert 到它之前**。
- 已用 PowerPoint COM 读取 + 导出 PNG 像素检测（文字带数量）验证第二行真实渲染。

### 3.3 其它本轮修复（保留）
- 整表填入前去掉 `rowSpan/vMerge`（合并延续行文字不显示）；写值 run 强制深色 `srgbClr 262626`（模板白字/无样式导致不可见）；行数不足克隆补行、超出删行。
- `t.*` 表数据缺失时 `table_rows` 跳过而非报错（数据填好后自动生效）。
- 中文方案名进响应头要 ASCII 化（`quote`），否则 Starlette latin-1 编码报错。
- 官方模板源文件可能被 OneDrive/Office 同步替换 → `tests/test_exact_template_engine.py` 的快照比对已放宽为“顺序/类型/位置/文本”一致（不比较宽高）。

### 3.4 验证手段（本机可复现）
```powershell
# 1) PowerPoint 打开判定（COM 反射方式，避免 Interop 转换报错）
$type=[type]::GetTypeFromProgID('PowerPoint.Application'); $ppt=[Activator]::CreateInstance($type)
$pres=$ppt.GetType().InvokeMember('Presentations',[Reflection.BindingFlags]::GetProperty,$null,$ppt,$null).Open($p,...)
# 2) 导出 PNG 后用像素统计确认“文字带”数量（row 是否真的渲染）
python - <<py  # 用 PIL/numpy 统计 <100 灰度像素的连续行带
```

### 3.5 `2.pptx` 单页的关键结论

- 左侧产品信息是一个表格单元格里的十个段落，不能用十个独立形状绑定；用
  `text_template` + `{ppt.product_info}`，写入时按现有段落分配，才能保留项目符号和行距。
- 两个绿色图片槽是 AutoShape 且同名，不是 `p:pic`。`image_region` 会按原几何和 z-order
  把选中 AutoShape 换成图片；选择对象必须传 `options.shape_id`。
- 六个公式是 `Equation.3` OLE。不要修改 `.bin`；`formula` 在同一对象几何位置生成透明 PNG，
  并把该 OLE 替换为静态图片。生成文件已用 PowerPoint COM 打开并导出 PNG 验证。
- 公式/复合显示上下文新增 `ppt.product_info` 与 `ppt.force.*`；工艺拆分值仍来自
  `app.calc.calc_force`，其中新增产品/流道/渣包分项力和可选滑块角度折算。

## 4. 当前遗留/已知边界（接手后按序处理）

1. **官方模板的幻灯片复制不兼容 PowerPoint**（克隆/导入/删页重建）——这是最大技术债。
   建议方向：逐字节 diff PowerPoint 自修后的文件，或改用“整份复制不重映射 rId”（试过仍失败）、
   或换 python-pptx `add_slide`+整包另存（交接文档禁止用于正式模板），需先在 PowerPoint 验证再定。
2. **官方模板页面组合能力**：因 1 受限，目前官方模板只能整份 in_place；用户如要“只取某几页”，
   需等 1 解决或改用自建小模板做页级编排。
3. 用户方案 `tp-dfm--v1-0`：含一页从模板 `1`（其自传封面）导入 + 官方第 2 页（含一次重复的第 2 页，
   建议删除无绑定重复页）；涉及跨模板 → 目前需拆开用 in_place 分别生成，或等 1 解决后合并。
4. `shape_inventory` 对“横向合并 gridSpan/hMerge/复杂表格”仅记录不展开；绑定编辑器对合并列需人工按列选。
5. 网页表单（`static/index.html`）保存的“服务器项目”是数据源之一；工作台数据源有 demo/project/empty。

## 5. 推荐下一步（优先级排序）

1. **攻关“PowerPoint 兼容的幻灯片复制/删除/导入”**（§4.1）。验收标准：用官方模板克隆第 2 页生成的文件能被 PowerPoint COM 打开，且第 2 页表格（含合并）内容正常。成功后：
   - 放开 deck 子集/跨模板/重复页对官方模板的支持；
   - 让用户的 TP-DFM 方案能合成“封面(自传模板)+官方若干页”单文件。
2. 将 `.dfmt` 模板包（manifest+master+version，见原始交接 §9）落地，方案可导出/导入。
3. Excel 导入（原始交接 §7）：openpyxl → 统一 JSON。
4. 绑定编辑器体验：表格列“表头自动对应”的二次校验（未匹配列提示已做）、行起始可调已做；
   可加“绑定结果预检”与错误行定位。
5. UI：给 `/template-editor` 增加“生成用哪个模板/数据源”的一键流程与错误 toast 细化。

## 6. 关键 API 速查（新 Agent 常调）

```
POST /api/template/generate   {template, output_mode(deck|in_place), missing, slides:[{source,template?,repeat?,condition?,images?,bindings:{k:{type,source,shape,options}}}] , data:{f,t,i}}
POST /api/schemes             {name, template, slides[], description?}  保存方案
POST /api/schemes/{name}/generate  {data:{f,t,i}}
GET  /api/template/inspect    {template} → 形状/几何/表格 cells
GET  /api/template/scan       {template} → 占位符清单
GET/POST/DELETE /api/templates(/{id})  上传/列表/删除
```

引擎解析顺序：占位符 `{path}` 填充 → 文本/表格 bindings → 图片区域/公式 bindings。
数据上下文 = `{f,t,i}` + `derived` + `calc_results.*.verdict` + `ppt.*`（PPT 展示用组合字段）。

## 7. 测试
`tests/` 在本文最初交接时为 153 项；截至 2026-09-09 全量为 224 项（以本文 §1 命令为准）。与本轮强相关：
- `test_explicit_binding_engine.py`（table_rows/columns_map/vMerge/endParaRPr 顺序/缺失跳过）
- `test_template_engine.py`（deck/in_place/重复/多模板）
- `test_schemes.py`、`test_template_import_api.py`、`test_template_registry.py`
- `test_field_catalog.py`（中文目录与 Schema 覆盖一致性；改 Schema 后跑 `node tools/build_field_catalog.js`）
- `test_product_analysis_page.py`（重名 shape_id、OLE 识别、复合文本、六个公式图）
