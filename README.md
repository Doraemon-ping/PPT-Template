# HPDC DFM 报告自动生成工具（FastAPI 版）

> 完整更新记录见 [项目更新记录](docs/CHANGELOG.md)；本文保留快速开始、API 和当前工作台用法。

> 维护约定：后续每次功能或修复都要同步追加 [项目更新记录](docs/CHANGELOG.md)，并更新受影响的接口/交接文档。

> 2026-09-09：新增 [表单中心](http://127.0.0.1:8000/forms)，支持 HTML 字段识别与确认、复杂 DFM/报价 HTML 的原样运行+数据桥接、独立表单应用、命名数据项目/历史恢复、按应用隔离的 PPT 工作台和服务端草稿。实现、部署边界与接手说明见 [多表单平台交接](docs/FORM_PLATFORM_2026-09-09.md)。当前为本机服务端存储，尚未加入多用户登录权限或云端部署。

> 图片绑定修复（2026-09-03）：支持向单元格区域填图片，兼容旧方案误存的文本类型；修复跨模板相同 XML 不同依赖误复用。详见 [单元格图片绑定修复](docs/CELL_IMAGE_BINDING_2026-09-03.md)。

> 表格分页修复（2026-09-03）：整表绑定默认按原表格区域自动续页，数据行采用统一参考样式；实时预览可切换续页。详见 [表格分页与兼容性修复](docs/TABLE_PAGINATION_2026-09-03.md)。

> 更新（2026-09-03）：编辑台新增**已保存方案的单页复用**、中文公式编辑器、对象搜索与绑定草稿。操作与开发说明见 [方案复用与编辑交互](docs/EDITOR_UX_2026-09-03.md)。

> 当前开发上下文唯一入口：[当前开发上下文](docs/DEVELOPMENT_CONTEXT_CURRENT.md)。按日期命名的交接文档仅用于历史追溯。

由原单文件 HTML 工具（`HPDC_DFM_Generator_A12.html`）改造为 **Python FastAPI 项目**：

- 前端界面与原工具完全一致（表单、图片上传、导航、结果展示）
- 全部工艺计算移至 **Python 后端**（`app/calc.py`，13 组计算：胀型力/锁模力、哥林柱平衡、包紧力、顶杆、挤压销、滑块缸径、抽真空、冷却水、压射参数、PQ² 等）
- 现有生产 PPT 由后端 `python-pptx` 生成 47 页；该旧版输出可用，但视觉样式并非直接复用基础数据中的 84 页正式 A12 模板
- 新增 **模板编排与生成能力**（参考 [m3dev/pptx-template](https://github.com/m3dev/pptx-template)）：
  模板内 `{path}` 占位符 + Deck 编排（重复页 / 条件页 / 图片绑定），OOXML zip 级定点填充，
  未绑定部件逐字节不变（详见 [docs/PPT_TEMPLATE_ENGINE_COMPLETION.md](docs/PPT_TEMPLATE_ENGINE_COMPLETION.md)）
- 新增服务器端项目保存 / 载入接口

## 目录结构

```
6-DFM自动生成/
├── app/
│   ├── main.py        # FastAPI 应用与路由
│   ├── calc.py        # 工艺计算引擎（原 JS 全部 calc_*/r_* 函数）
│   ├── machines.py    # 压铸机参数库 / 顶杆规格 / 浇口速度对照表
│   ├── ppt.py         # 当前生产路径：python-pptx 生成 47 页 PPT
│   ├── dfm/           # 统一 DFMReport、Issue、SlidePlan 与旧数据 Adapter
│   ├── report/ppt/    # Planner、Schema、Renderer、Validator、OpenXML 模板引擎
│   │   ├── openxml/   #   占位符扫描/文本填充/图片替换/slide 克隆（zip 级）
│   │   ├── deck.py    #   Deck 编排模型与规划器
│   │   ├── template_engine.py  # 模板编排生成引擎
│   │   ├── schemas/   #   试点 Slide Schema（YAML）
│   │   └── decks/     #   示例 Deck 编排
│   ├── demo.py        # 示例数据 + 默认 LOGO
│   ├── utils.py       # 通用工具（num / fmt / esc 等）
│   └── assets/logo.png
├── static/
│   └── index.html     # 前端界面（渲染引擎 + API 调用）
├── data/              # 服务器保存的项目（project.json）
├── docs/              # 架构、交接与完成说明文档
├── templates/         # 试点/实验模板、样张与占位符演示模板
├── tools/             # 模板构建、占位符扫描 CLI、退役审计
├── tests/             # 单元与集成测试
├── requirements.txt
└── README.md
```

## 快速开始

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

浏览器打开 <http://127.0.0.1:8000> 即可使用。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/` | 前端界面 |
| GET | `/forms` | 多表单应用中心：导入 HTML、管理数据项目并进入对应 PPT 工作台 |
| GET/POST | `/api/form-apps` | 表单应用列表、普通 HTML 字段发现与原样 HTML 导入 |
| GET/POST/PUT | `/api/form-apps/{app_id}/projects*` | 按应用隔离的数据项目、服务端草稿、版本历史、归档和 JSON 导出 |
| POST | `/api/calc` | 工艺计算。请求 `{f, t, apply_machine}`，返回 `{derived, machine_fill, results}`（结果含界面 HTML 与 PPT 结论文本） |
| POST | `/api/ppt` | 生成 PPT（旧版 47 页）。请求 `{f, t, i}`（i 为 base64 图片），返回 `.pptx` 文件 |
| POST | `/api/ppt/preview-v2` | Named-Shape 新引擎预览；默认关闭，请求结构与旧 PPT 接口一致 |
| GET | `/template-editor` | 模板工作台页面：上传模板 → 扫描/检查形状 → 绑定字段 → 生成下载 |
| GET | `/api/templates` | 已注册模板清单（内置 official/exact/pilot/demo/table-demo + 用户上传） |
| POST | `/api/templates/upload` | 导入 .pptx 模板文件（multipart `file`），持久化并注册 |
| DELETE | `/api/templates/{id}` | 删除用户上传的模板 |
| POST | `/api/template/scan` | OOXML 占位符与模板目标扫描：`{template}` → `{slide_count, placeholder_paths, binding_targets, slides[]}` |
| POST | `/api/template/inspect` | 形状清单检查：每页形状名/类型/文本/表格行列（绑定选择用） |
| POST | `/api/template/formula-preview` | 中文公式编辑器预览：`{expression, data}` → PNG；缺字段数量见 `X-DFM-Formula-Missing`；仅编排现有数据，不执行用户代码 |
| POST | `/api/template/generate` | Deck 编排生成：`{template, output_mode, missing, slides[], data}` → `.pptx` |
| GET | `/api/schemes` | 已保存的模板方案列表（名称/模板/绑定数） |
| POST | `/api/schemes` | 保存/更新模板方案（`{name, template, slides[], description?}`） |
| GET | `/api/schemes/{name}` | 载入方案完整内容（供二次编辑） |
| DELETE | `/api/schemes/{name}` | 删除方案 |
| POST | `/api/schemes/{name}/generate` | 一键生成：方案（模板+绑定）+ `{data:{f,t,i}}` → `.pptx` |
| GET | `/api/demo` | 示例项目数据 |
| GET | `/api/project/load` | 载入服务器保存的项目（`data/project.json`） |
| POST | `/api/project/save` | 保存项目到服务器 |

表单应用的模板、方案和草稿均按 `app_id` 隔离。普通 HTML 进入统一字段表单；受支持的复杂
DFM/报价 HTML 进入“原样运行 HTML + 数据桥接”，PPT 工作台不会把旧 DFM 字段名自动当作新表单字段。
完整接口、数据模型、部署边界和迁移说明见 [多表单应用平台交接](docs/FORM_PLATFORM_2026-09-09.md)。

前端行为说明：

- 💾 **保存项目** → 保存到服务器 `data/project.json`；📂 **载入项目** → 从服务器载入
- ⬇/⬆ **导出/导入 JSON** → 本地文件（浏览器端完成）
- 🧪 **载入示例** → 请求 `/api/demo`
- ⚡ **生成 PPT** → 请求 `/api/ppt`，浏览器自动下载
- 表单输入后自动防抖调用 `/api/calc` 刷新派生值与计算结果；机型切换时自动带出设备参数（`apply_machine`）

## 模板编排与生成（pptx-template 路线）

在模板文本中写入 `{path}` 占位符（例如 `{f.partNo}`、`{t.issues[].desc}`、`{derived.wPour}`、
`{calc_results.rForce.verdict}`），即可用 Deck 编排把模板页组装成报告：按顺序取页、按数组重复
（issue 列表 → N 页）、按条件跳过可选页、按形状名绑定图片。生成在 OOXML zip 层完成，
未绑定部件逐字节不变（对官方 84 页模板 `in_place` 空填充实测零差异）。

示例 Deck（`app/report/ppt/decks/demo.yaml`）与演示模板 `templates/DFM_Template_Placeholder_Demo.pptx`：

```powershell
# 扫描占位符
python tools/scan_template.py templates/DFM_Template_Placeholder_Demo.pptx
# 生成（curl）
curl -X POST http://127.0.0.1:8000/api/template/generate -H "Content-Type: application/json" -d "{\"template\":\"demo\",\"slides\":[{\"source\":1},{\"source\":2,\"images\":{\"PART_IMAGE\":\"i.logoImg[0]\"}},{\"source\":3,\"repeat\":\"t.issues\"}]}" -o report.pptx
```

详细用法见 [docs/PPT_TEMPLATE_ENGINE_COMPLETION.md](docs/PPT_TEMPLATE_ENGINE_COMPLETION.md)。

## 模板导入、绑定与替换（可视化点选绑定）

打开 **<http://127.0.0.1:8000/template-editor>**：导入一页或几页 PPT，PowerPoint 会把原始
页面渲染为真实预览底图，透明对象选区按模板原始坐标覆盖其上。用户可以像在 PPT 软件中一样
直接**点击页面上的标题/文本框/表格单元格/图片**，把它关联到
网页表单里用户填写的字段（项目信息 `f.*`、问题表格 `t.issues`、图片 `i.*`、自动派生
`derived.*`、计算结论 `calc_results.*`），生成替换内容后的 PPT：

> 原页 PNG 和实时数据 PNG 预览需要运行服务的 Windows 机器安装桌面版 Microsoft PowerPoint。
> 模板生成下载本身不依赖 Office。发布目标机时请分发 `release/DFM报告生成器_win64` 或其 ZIP，
> 不要直接分发 `packaging/build_dist` 中间目录。

1. **导入模板**：内置模板或上传任意 `.pptx`（服务器持久化到 `data/templates/`）。
2. **原页点选**：`GET /api/templates/{id}/slides/{n}/preview.png` 调用桌面 PowerPoint 导出并缓存
   原页 PNG；`/api/template/inspect` 返回 EMU 坐标和表格逐格坐标，前端仅叠加透明选择层。
   切换模板或页码只改变预览，不覆盖已加入报告的页面；首次点击对象时当前页自动加入报告，
   无需先操作“新增一页”。
3. **关联字段（中文层级名）**：字段目录按「模块.分组.标签」翻译显示，例如
   `f.partNo → 项目信息.封面信息.零件号`、问题表列 `desc → 问题描述`；
   文本→文本替换、图片→图片替换、表格单元格→按 行/列 绑定；还支持复合文本模板、
   把任意 AutoShape 当作图片区域，以及把旧版 Equation/MathType OLE 转为动态公式图；每页可设
   「重复数组」（如 `t.issues`，每条问题生成一页）与「显示条件」；多页组成报告。
   - **局部文字替换（默认文字模式）**：点选文本框或单元格 → 在完整原文中框选要替换的数值/词语 →
     搜索中文字段名 →「将选中文字关联到此字段」→「保存绑定并预览」。同一对象可选择多处，
     相同文字按位置区分；未选中的标签、单位、段落和文字格式保持不变，不需要手写字段路径。
     当前缺失或空值保留原片段；选区不能跨行或相互重叠。替换值继承选区起点格式；
     如果要覆盖全部内容，显式选择「替换整个文本框/单元格」。旧复合文本绑定仍可用。
   - 图片对象点选后，弹层优先给出「当前数据已有图片」（示例数据下即公司 LOGO），
     单击即绑定；下方完整目录里「图片（上传到表单）」始终列出 LOGO 等 24 个图片槽位。
   - **跨模板拼页**：可先取模板 A 的几页，再切换到模板 B 取几页——切换/加载模板不会清空
     已有页面与绑定；每页记录所属模板，生成时把不同模板的页面（含版式/母版依赖）合成
     一份 PPTX（同一报告可混 A、B 模板页面）。
4. **实时数据预览**：默认开启，画布先显示原模板底图，再调用
   `POST /api/template/live-preview`。后端在临时副本中按当前绑定填入数据，由 PowerPoint
   渲染当前页 PNG，原模板和已保存方案不变。重复页展示数组首条数据；编辑预览不应用显示条件。
   输入变化采用 450ms 防抖；相同模板/页/绑定/数据会命中服务端短期缓存。预览默认以 1280×720
   导出，保持 16:9 选区精度并减少等待。
   缺失数据的绑定保留原对象并显示数量提示；渲染失败会明确提示并回退原模板。
   取消「实时数据预览」可查看未填入数据的原模板。首次启动 PowerPoint 可能需要数秒，
   服务端会复用隐藏渲染进程，后续页面更新通常更快；预览并非逐帧刷新；
   快速切换使用防抖、取消请求及序号校验，防止旧结果覆盖新选择。
5. **生成**：与占位符路线共用 `/api/template/generate`（Deck 中每页携带 `bindings` 与可选 `template`）。导入的 PPT 占位符是目标槽位，工作台保存的显式 `PPT 目标 → 表单源` 关系优先；原样 HTML 应用不会自动套用固定的客户/零件字段别名。
   图片绑定（`image` / `image_region`）缺少数据或值为空时，正式生成也保留模板原对象，
   不因缺图中断；编辑台和表单页显示缺图数量。补充图片后再次生成即可替换。
   已提供但损坏的图片、缺失的必需文本字段仍报错；不会删除已有绑定。

无占位符的模板（含官方 84 页模板的自动命名对象）同样适用。含 `{f.xxx}` 占位符的模板
会在当前页的「模板目标」面板中逐个列出，选择来源字段后才会写入方案；绑定记录保存在浏览器
localStorage 和服务端草稿，可随时续编。对原样 HTML 应用，未绑定的模板目标不再阻止生成；
默认 `missing=keep` 时保留 PPT 模板中的原内容（包括原占位符）。

### 产品分析/压铸设备选择单页（`2.pptx`）

工作台的通用绑定能力已能处理该页，不重画表格或版式。导入
`1-基础数据/新建文件夹/2.pptx` 后，可在画布逐项配置：

- 产品信息单元格：`text_template` 复合十个结构化字段，逐段落保留原项目符号、字号和间距；
- 正面/反面 AutoShape：`image_region`，分别读取专用字段
  `i.productRunnerFrontImg[0]`、`i.productRunnerBackImg[0]`；
- 六个 Equation.3 OLE：`formula`，按投影面积、压力、滑块角度和安全系数生成透明公式图；
- 页面内两个同名 `PA_形状 26`：使用稳定的 `shape_id` 分别绑定，不再发生重名冲突。

新增表单字段：`f.moldStructure`、`f.sliderForceAngle`、`f.lockSafetyFactor`。公式支持
`[[分子|分母]]` 语法。也可用参考脚本直接生成并传入真实正反面图：

```powershell
python scripts/generate_product_analysis_page.py `
  --template "1-基础数据/新建文件夹/2.pptx" `
  --data data/project.json --front front.png --back back.png `
  --output output/product-analysis.pptx
```

**字段中文目录**：`static/dfm_catalog.js` 由首页表单 Schema（`static/index.html` 的
MODULES，字段自带中文标签）自动生成（158 个表单字段 + 9 张表格列 + 24 个图片槽位，
另有自动派生值与计算结论的中文名）。若修改了 Schema，执行：

```powershell
node tools/build_field_catalog.js   # 重新生成 static/dfm_catalog.js
```

```bash
# 上传模板
curl -F "file=@模板.pptx" "http://127.0.0.1:8000/api/templates/upload?template_id=my-template"
# 检查第 1 页对象（含几何位置与表格单元格）
curl -X POST http://127.0.0.1:8000/api/template/inspect -H "Content-Type: application/json" -d '{"template":"my-template"}'
# 按对象绑定生成
curl -X POST http://127.0.0.1:8000/api/template/generate -H "Content-Type: application/json" -d '{"template":"my-template","slides":[{"source":1,"bindings":{"b1":{"shape":"COVER_TITLE","type":"text","source":"f.partNo"}}}]}' -o out.pptx
```

详细用法见 [docs/PPT_TEMPLATE_ENGINE_COMPLETION.md](docs/PPT_TEMPLATE_ENGINE_COMPLETION.md)。

## 模板绑定方案：绑定一次，反复生成

可视化工作台里完成绑定后可**保存为“模板方案”**（服务器持久化在 `data/schemes/`），
方案 = 模板 pptx + 绑定关系（页面顺序/重复/条件/字段绑定）：

1. **工作台（/template-editor）**：绑定完成后填方案名 → 「💾 保存方案」。
2. **填表生成（首页 /）**：在网页表单填完数据 → 顶栏「📋 按方案生成」→ 选方案 → 一键生成
   （方案 + 当前表单数据，无需再进工作台）。
3. **二次编辑**：工作台「② 模板方案」下拉选择已存方案 → 「载入编辑」→ 画布与绑定全部还原，
   改完再次「保存方案」即覆盖更新。
4. 方案可列出/删除；同名保存即更新。

```bash
# API：保存方案 / 列表 / 载入 / 删除 / 一键生成
curl -X POST http://127.0.0.1:8000/api/schemes -H "Content-Type: application/json" \
  -d '{"name":"我的方案","template":"demo","slides":[{"source":1,"bindings":{"b1":{"type":"text","source":"f.partNo","shape":"COVER_PART_NUMBER"}}}]}'
curl http://127.0.0.1:8000/api/schemes
curl http://127.0.0.1:8000/api/schemes/我的方案
curl -X POST http://127.0.0.1:8000/api/schemes/我的方案/generate -H "Content-Type: application/json" -d '{"data":{"f":{},"t":{},"i":{}}}' -o out.pptx
curl -X DELETE http://127.0.0.1:8000/api/schemes/我的方案
```

## PPT V2 试运行

新模板引擎不会替换现有 `/api/ppt`。需要试运行时，在启动服务前设置：

注意：当前 V2 是用于验证 Planner、Schema、Renderer 和 Validator 的 6 页试点，
不是正式 84 页模板编辑器的最终实现。

```powershell
$env:DFM_PPT_V2_ENABLED = "true"
uvicorn app.main:app --reload
```

然后调用 `POST /api/ppt/preview-v2`。可选环境变量：

- `DFM_PPT_V2_TEMPLATE`：覆盖版本化 PPTX 模板路径
- `DFM_PPT_V2_SCHEMA_DIR`：覆盖 Slide Schema 目录

响应头会返回 Engine、模板版本、Generator 版本、页面数和 validation warning 数量。

复杂 CAD 截图（含红框、箭头、标注和前后对比）在 V2 Schema 中使用
`complex_image` 渲染器。当前实现原样放置上游已经合成的位图，继续支持路径、
bytes、Data URI 和旧图片列表，不在 PPT 层重画标注。代码同时提供
`SnapshotBackend` 协议，供后续接入 HTML/CSS → Playwright → PNG；当前版本不引入
Playwright 运行时依赖。

## 旧 PPT 引擎退役门禁

旧 `app/ppt.py` 只有在数据覆盖、页面数量、输出等价、API 切换和回滚验证全部通过后
才允许删除。可运行以下审计；退出码 `0` 表示允许退役，`1` 表示仍有阻断项：

```powershell
python tools/audit_legacy_retirement.py
```

当前正式示例仍由旧引擎生成 47 页完整工艺报告，而 V2 只规划基础页和 Issue 页，
因此门禁预期为阻断状态，`/api/ppt` 继续使用旧引擎。

已完成的等价迁移页：

- `1.4 产品基本参数`：统一映射重量、壁厚、外形尺寸、腔数、铸造压力、材料、
  年产量、项目类型、表面和气密要求；对应模板键为 `PART_SPECIFICATIONS`。

正式 A12 模板的“完全一致”路径使用 `DFM_Master_exact_v1.pptx` 和
`ExactTemplateEngine`。版本化模板保留原始 84 页，只通过 PowerPoint 给现有对象命名；
生成时直接修改目标 OOXML 文字节点，不重建或重存母版、OLE、图片、表格和装饰对象。

## 与原 HTML 工具的差异（有意为之）

1. **计算全部在服务端**：前端不再包含任何计算逻辑，结果统一由 `/api/calc` 返回，保证界面与 PPT 结论完全一致。
2. **PPT 服务端生成**：不再依赖 PptxGenJS CDN，离线可用。
3. **修复壁厚-浇口速度推荐缺陷**：原 JS 用 `parseFloat('≤1.5') / parseFloat('> 8.0')` 解析区间下界，均得到 NaN→0，导致按壁厚选择推荐区间时恒选最后一行（"> 8.0 → 20~28 m/s"）。Python 版使用显式阈值表 `GATE_SPEED_THRESHOLDS`，按预期逻辑选择（如 3.0 mm → 35~45 m/s）。
4. **图片存储**：仍以前端压缩后的 base64 存入状态，随 PPT / 保存请求提交后端；未上传图片时 PPT 中渲染占位框。

## 已知说明

- PPT 使用“微软雅黑”字体；若目标机器未安装该字体，PowerPoint 会自动替换。
- 项目保存在 `data/project.json`（单项目覆盖式保存）；如需多项目，可自行扩展 `/api/project/save` 增加项目名参数。
