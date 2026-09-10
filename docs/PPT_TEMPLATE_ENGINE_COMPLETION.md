# PPT 模板编排与生成能力（pptx-template 路线）完成说明

> 原始状态日期：2026-09-02；当前增量：2026-09-09
> 参考实现：<https://github.com/m3dev/pptx-template>  
> 范围：补齐交接文档第 4/5/10/11/12 节中的“Open XML 定点生成 Worker + Deck 编排”纵向闭环，
> 不改变现有 `/api/ppt` 默认行为，不引入 PowerPoint COM，不重画模板样式。

> 2026-09-09 增量：引擎继续兼容模板内 `{path}` 占位符，同时由工作台提供显式的“PPT 模板目标 →
> 当前表单源字段”绑定。导入的 PPT 占位符现在是待选择的目标槽位，不再被当作跨表单通用字段；
> 原样 HTML 生成会在最终 OOXML 中检查未绑定目标。多表单隔离、源路径规则和旧方案迁移策略见
> [多表单应用平台交接](FORM_PLATFORM_2026-09-09.md)。

> 预览性能增量：`slide_preview.py` 通过 `tools/preview_worker.ps1` 复用隐藏 PowerPoint 进程，
> 进程内 LRU 缓存避免相同请求重复渲染；编辑台先显示原模板底图，默认 1280×720 导出。

## 1. 核心思路（与 pptx-template 一致）

pptx-template 的做法是：**模板文本里直接写 `{path.to.data}` 占位符，数据模型（JSON）驱动生成**——
占位符本身就是绑定，不需要额外的 Binding Manifest 编辑界面也能完成“模板 → 报告”的编排与生成。

本项目在 OOXML（zip）层面实现了同一约定，并扩展了交接文档要求的：

- **文本占位符填充**（跨 run 拆分、保留字体样式）；
- **图片部件替换**（只改目标媒体 part / 关系，其余部件字节不变）；
- **重复页（repeat slide）**（issue 列表 → N 页，克隆 slide part + 关系重映射）；
- **条件页（condition）**（可选页按数据真假跳过）；
- **两种输出模式**：`deck`（按 Deck 重建输出页列表）与 `in_place`（保留全部页、就地填充）。

## 2. 新增模块

```text
app/report/ppt/
├── openxml/                      # zip 级 OOXML 定点编辑（不重存整包）
│   ├── package_editor.py         #   OoxmlPackage：part 读取/写入/删除、Content-Type 注册
│   ├── placeholder_scanner.py    #   {path} 占位符清单扫描（slide/shape/出现次数）
│   ├── text_binding.py           #   占位符填充：run 拆分保留 rPr；keep/clear/error 策略
│   ├── image_binding.py          #   命名 Picture 形状的媒体部件替换（PNG 就地或新 part）
│   ├── shape_binding.py          #   shape_id/形状名绑定：文本、复合文本、表格
│   ├── visual_binding.py         #   AutoShape 图片区域、OLE 动态公式图
│   ├── shape_inventory.py        #   形状清单检查（名称/类型/文本/表格行列）
│   └── slide_repeater.py         #   slide part 克隆 + presentation.xml sldIdLst 重建
├── deck.py                       # DeckDefinition/DeckSlide/DeckPlanner（编排模型）
├── template_engine.py            # TemplateEngine：扫描→规划→填充→重建→验证
├── template_registry.py          # 模板注册表（内置 + 用户上传，持久化到 data/templates/）
└── decks/demo.yaml               # 示例编排定义
tools/
├── scan_template.py              # CLI：扫描任意 pptx 的占位符清单
├── build_demo_template.py        # 生成占位符演示模板（DFM_Template_Placeholder_Demo.pptx）
└── ...                           # 表格演示模板 DFM_Template_Table_Demo.pptx（table-demo）
static/template_editor.html       # 模板工作台：上传 → 检查形状 → 绑定 → 生成
```

数据路径解析（`PathResolver`）：支持 `{f.partNo}`、`{t.issues[0].desc}`、`{t.issues.0.desc}`、
`{derived.wPour}`、`{calc_results.rForce.verdict}`；重复页内先查 item 作用域（`{desc}`），
再查全局数据（`{f.partNo}`）。

数据上下文由 `build_data_context()` 自动合成：`{f, t, i}` + `compute_all()` 的派生值
（`derived`）+ 各结果结论文本（`calc_results.*.verdict`），渲染层不重复计算工艺结论。

## 3. 快速使用

### 3.1 扫描模板占位符

```powershell
python tools/scan_template.py templates/DFM_Template_Placeholder_Demo.pptx
python tools/scan_template.py "1-基础数据/高压项目DFM交流模板A12版_中文_2025-09-30.pptx  -  已修复.pptx" --json
```

`POST /api/template/scan`（body：`{"template": "demo"}`）返回同样的清单：
`{slide_count, placeholder_count, placeholder_paths, slides:[{slide_index, shape_name, path, occurrences}]}`。
官方 84 页模板当前无占位符 —— 需要先在 PowerPoint 中把目标文字改成 `{f.xxx}` 形式
（pptx-template 约定），保存后即可被扫描与填充。

### 3.2 Deck 编排生成

```json
POST /api/template/generate
{
  "template": "demo",
  "output_mode": "deck",
  "missing": "keep",
  "slides": [
    {"source": 1},
    {"source": 2, "images": {"PART_IMAGE": "i.logoImg[0]"}},
    {"source": 3, "repeat": "t.issues"}
  ],
  "data": {"f": {}, "t": {}, "i": {}}
}
```

- `slides[].source`：模板页序号（1 起）。
- `slides[].repeat`：数组路径；重复页内占位符先解析 item 作用域。
- `slides[].condition`：路径为空/假时整页跳过。
- `slides[].images`：形状名 → 图片数据路径（支持 base64 data URI / 文件路径）。
- `missing`：`keep`（保留原占位符）/ `clear`（清空）/ `error`（报错）。
- `output_mode`：`deck`（默认）或 `in_place`（in_place 不允许 repeat）。

响应为 `.pptx` 下载；响应头携带诊断：`X-DFM-Slide-Count`、`X-DFM-Text-Replaced`、
`X-DFM-Images-Bound`、`X-DFM-Missing-Placeholders`。

CLI 等价示例：

```powershell
python -m uvicorn app.main:app
# 或直接调用 Python API：
#   from app.report.ppt.deck import DeckDefinition, DeckSlide
#   from app.report.ppt.template_engine import TemplateEngine
```

## 4. 关键质量保证（与交接文档一致）

- **未绑定部件逐字节不变**：`TextBindingFiller` 对无占位符部件做字节级短路，不做任何 XML
  序列化；对官方 84 页模板 `in_place` 空填充的实测结果：**全部部件内容一致，零差异**。
- **不重存整包**：所有编辑基于 zip part 级读写；theme / master / OLE / 未知关系保持原样。
- **不依赖 PowerPoint COM**，可在 FastAPI 请求线程中直接运行。
- **渲染层不做工艺判断**：结论来自 `app.calc` 的输出（作为数据注入）。
- **旧 `/api/ppt` 未改动**：47 页旧引擎仍是默认生产路径。

## 4.1 模板导入与显式绑定（补）

- `POST /api/templates/upload`（multipart）导入任意 `.pptx`，校验后注册并持久化到
  `data/templates/<id>/master.pptx` + `registry.json`（sha256 / 版本 / 上传时间）；
  `DELETE /api/templates/{id}` 删除上传模板；内置模板只读。
- `POST /api/template/inspect` 返回每页形状清单（形状名/类型/文本/占位符/表格行列），
  对官方 84 页模板实测 0.2s 完成 781 个形状检查。
- `DeckSlide.bindings` 支持显式对象绑定：`text|text_template|table_cell|table_rows|image|image_region|formula`；
  `options.shape_id` 是页面内稳定选择器，可处理 PowerPoint 允许的重名对象。
  - `text`：替换整形状文本（保留首 run 的 rPr，清空其余），适合无占位符模板；
  - `table_cell`：`options: {row, column}`（0 起）写指定单元格；
  - `image`：复用图片部件替换；
  - 语义：source 路径缺失且 `required=true` → 报错；空值默认清空形状文本，
    `options.empty="keep"` 则保留模板文本；形状缺失且 `required=false` → 跳过计数。
- 两种绑定可混用：先按占位符约定填充，再应用显式绑定（显式绑定覆盖整形状文本）。

## 5. 测试

新增（本文 2026-09-02 引擎阶段共 129 项全绿；该数字为历史快照，当前全量回归为 Python 223 项、
Node 12 项）：

- `tests/test_placeholder_scanner.py` — 扫描清单与形状名、zip 往返内容一致
- `tests/test_text_binding.py` — 混合 run 拆分、保留 rPr、keep/clear/error 策略、字节短路
- `tests/test_image_binding.py` — 图片媒体部件就地替换、未绑定部件字节一致、非法图片报错
- `tests/test_slide_repeater.py` — slide 克隆、Content-Type 注册、presentation 重建与顺序
- `tests/test_template_engine.py` — deck/repeat/condition/in_place/missing/部件保持 E2E
- `tests/test_template_registry.py` — 上传/列表/持久化/删除、内置冲突与非法 id
- `tests/test_explicit_binding_engine.py` — 形状名文本/表格单元格/图片绑定、缺失与可选语义
- `tests/test_template_import_api.py` — 上传→扫描→检查→绑定生成→删除 全链路 API

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## 6. 与交接文档后续路线的衔接

- 本实现把第 10 节推荐的 `app/report/ppt/openxml/`（package_editor / text_binding /
  image_binding / slide_repeater）落地为可运行代码。
- 字段目录（Field Catalog）可以直接复用占位符扫描结果与 `build_data_context()`；
  `GET /api/template/scan` 是它的最小可用形态。
- 模板生成器包（`.dfmt`）与 VSTO 绑定编辑器仍按交接文档推进：本引擎可直接消费
  VSTO 写出的同一套 `{path}` 约定模板；`manifest.json` 方案可作为占位符的补充
  （绑定 ID / 渲染选项）在后续阶段加入，不需要推翻占位符机制。
