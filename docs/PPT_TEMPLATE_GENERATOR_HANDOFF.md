# PPT 模板生成器开发交接文档

> 原始交接日期：2026-09-02；当前实现更新：2026-09-09。完整时间线见 [项目更新记录](CHANGELOG.md)。
> 目标读者：接手开发 PPT 模板编辑器/模板生成器的工程师或 Agent  
> 当前结论：FastAPI、DFM 计算、HTML 表单数据、原样 HTML 桥接和通用 PPT 模板工作台均可运行；
> 不应继续为 84 页正式模板手写页面坐标，应使用“导入 PPT → 选择模板目标 → 选择表单源字段 → 保存方案 → 生成”的链路。

## 当前已交付基线（2026-09-09）

- `/forms` 提供多表单应用、命名数据项目、版本历史和按应用隔离的模板/方案空间。
- 普通 HTML 支持字段识别和确认；指定 DFM/报价 HTML 支持“原样运行 HTML + 数据桥接”，字段目录保留源路径（如 `G.cust`）。
- `/template-editor` 支持导入任意 `.pptx`，按真实页面几何选择文本、图片、表格单元格和占位符目标；
  `/api/template/scan` 同时返回 `placeholder_paths` 与 `binding_targets`。
- 方案保存显式的 `PPT 目标 → 表单源` 关系。旧 DFM 路径仅在历史方案明确引用时迁移解析，新表单不会自动套用 `custName`、`partNo` 等别名。
- 原样 HTML 生成前执行最终 OOXML 未绑定占位符检查；图片缺失按保留原模板对象处理，必需文本和损坏图片仍报错。
- 实时预览使用隐藏 PowerPoint worker、450ms 输入防抖和短期 LRU 缓存；默认导出 1280×720，响应头 `X-DFM-Preview-Cache` 可观察命中状态。Worker 返回失效句柄时会销毁、重建并重试，之后才降级为一次性导出重试。
- 当前回归：Python 224 项、Node 12 项通过；本机服务为 `127.0.0.1:8000`。

## 1. 产品目标

项目需要把任意正式 PowerPoint 模板配置为可复用的报告生成器（DFM 只是内置应用之一）：

1. 用户打开或导入 PPT 模板。
2. 编辑器载入 Excel 或现有 FastAPI 提供的结构化数据字段。
3. 用户在 PowerPoint 中选择文本框、图片、表格、表格单元格或组合区域。
4. 用户把选中的 PPT 对象绑定到结构化字段。
5. 编辑器保存“原始 PPT + 数据 Schema + Binding Manifest”为版本化模板生成器包。
6. FastAPI 运行时只替换绑定对象的文字、图片或表格数据，不创建或重画模板样式。

目标链路：

```text
HTML / Excel / API 数据
        ↓
Form App Schema + Runtime Data
        ↓
Template Targets → Source Bindings
        ↓
Slide Planning / Repeat / Conditions
        ↓
Open XML 定点替换
        ↓
Validator
        ↓
保持原模板样式的 PPTX
```

## 2. 当前项目可以运行的能力

### 2.1 FastAPI 与前端

入口为 `app/main.py`，前端为 `static/index.html`。

当前接口：

| 方法 | 路径 | 当前行为 |
| --- | --- | --- |
| GET | `/` | 返回现有 HTML 表单 |
| POST | `/api/calc` | 接收 `{f, t, apply_machine}`，执行 DFM 工艺计算 |
| POST | `/api/ppt` | 使用 `app/ppt.py` 生成旧版 47 页 PPT |
| POST | `/api/ppt/preview-v2` | Feature Flag 控制的 6 页 Named-Shape 试点 |
| GET | `/api/demo` | 返回内置 `{f, t, i}` 示例数据 |
| GET | `/api/project/load` | 读取 `data/project.json` |
| POST | `/api/project/save` | 保存 `{f, t, i}` |

现有 HTML 数据已经结构化为：

```json
{
  "f": {"字段名": "字段值"},
  "t": {"表格名": [{"列名": "值"}]},
  "i": {"图片槽位": ["data:image/png;base64,..."]}
}
```

其中：

- `f`：项目、零件、工艺输入、计算输入和说明文字。
- `t`：履历、问题、材料、公差等数组数据。
- `i`：前端压缩后的 Base64 图片。
- `app/calc.py`：13 组 DFM 工艺计算和派生结论。
- `app/machines.py`：压铸机参数库和工艺参考数据。
- `app/demo.py`：可重复使用的开发样例。

重要：不要为了模板编辑器重新开发 DFM 计算，也不要让 PPT Renderer 再做工艺判断。

### 2.2 旧 PPT 生成器

`app/ppt.py` 是当前生产可用路径：

```text
POST /api/ppt
  → build_pptx(f, t, i)
  → python-pptx 从空 Presentation 绘制
  → 47 页 PPTX
```

它仍然是默认接口，不能删除。已记录的内置示例回归基线：

| 指标 | 基线 |
| --- | ---: |
| Slides | 47 |
| Shapes | 1189 |
| 文件大小 | 182840 bytes |
| 文本 SHA-256 | `6ea475a0cde76775cdcc3aeca2bc324de17e0a53b0c53f3e789984aaace99fc2` |

旧生成器的问题：

- 运行时代码硬编码大量坐标、字体、字号、颜色和表格宽度。
- 页面结构、业务字段、图片处理和渲染混在一个大函数中。
- 视觉样式并非直接来自 `1-基础数据` 中的正式 A12 模板。
- 模板变化需要修改 Python。
- 无法让业务用户自行绑定新模板。

### 2.3 已实现的统一数据与 PPT 基础模块

已经存在：

```text
app/dfm/
├── models/
│   ├── report.py          # DFMReport、Project、Summary、PartSpecifications
│   ├── issue.py           # DFMIssue、IssueSeverity
│   └── slide.py           # SlidePlan、SlideType
└── adapters/
    └── legacy.py          # {f,t,i} → DFMReport

app/report/ppt/
├── engine.py              # 6 页 Named-Shape 试点引擎
├── exact_engine.py        # 84 页 OOXML 定点替换实验
├── template_loader.py
├── slide_planner.py
├── slide_factory.py
├── shape_resolver.py
├── schema.py
├── schema_loader.py
├── binding_resolver.py
├── retirement.py
├── renderers/
│   ├── text_renderer.py
│   ├── image_renderer.py
│   └── complex_image_renderer.py
├── validators/
│   ├── template_validator.py
│   ├── slide_validator.py
│   └── report_validator.py
└── schemas/
```

已实现能力：

- Pydantic `DFMReport` 数据边界。
- 旧 `{f,t,i}` Adapter，不修改输入数据。
- SlidePlanner，可根据 Issue 图片选择标准页或对比页。
- 基于 Shape Name 的精确查找，缺失和重复 Shape 会报明确异常。
- YAML Slide Schema 和数据路径解析。
- TextRenderer：替换文本并保留模板样式。
- ImageRenderer：支持 `contain`、`cover`、`center_crop`、`preserve_aspect_ratio`。
- ComplexImageRenderer：接收已经合成标注的复杂 DFM 图片。
- 模板、单页和报告级 Validator。
- 模板版本和生成器版本元数据。
- 旧引擎退役门禁。

### 2.4 当前统一模型并不完整

`DFMReport` 目前只稳定覆盖：

- 项目信息。
- Issue 汇总。
- Issue 列表。
- 产品基础参数的一部分。
- 报告元数据。

内置示例仍有约 65 个非空 `f` 字段、`dfmHist` 表格以及顶层图片未进入统一模型。运行：

```powershell
python tools/audit_legacy_retirement.py
```

会得到 `ready: false`。这是预期状态，表示旧引擎不能删除。

模板编辑器不必等待所有字段先被手工加入 `DFMReport`。建议新增 Field Catalog，把当前 `{f,t,i}`、`compute_all()` 输出和 Pydantic JSON Schema 统一暴露给编辑器；随后再逐步完善 Canonical Report Model。

## 3. 正式模板与已有实验的真实状态

### 3.1 正式模板

正式源文件位于：

```text
1-基础数据/高压项目DFM交流模板A12版_中文_2025-09-30.pptx  -  已修复.pptx
```

已确认特征：

- 84 页。
- 16:9，尺寸为 `12192000 × 6858000 EMU`。
- 包含图片、组合对象、原生表格、公式和 Embedded OLE Object。
- 很多页面包含黄色“注：”编辑说明和示例内容。
- 当前对象名称主要是 PowerPoint 自动名称，尚不具备完整 Binding ID。

### 3.2 `DFM_Master_v1.pptx`：不要作为正式方向

`templates/DFM_Master_v1.pptx` 是早期 6 页试点：

- 从正式模板抽取少量页面后重新绘制 Shape。
- 用来验证 Planner、Schema、Renderer、Validator 是有效的。
- 它的样式不是正式 84 页模板的完全复刻。
- `/api/ppt/preview-v2` 当前仍指向它。

后续 Agent 不应继续把正式 84 页模板手工重画到该文件中。

### 3.3 `DFM_Master_exact_v1.pptx`：实验，不是最终编辑器

`templates/DFM_Master_exact_v1.pptx` 保留正式模板 84 页，并给少数原对象添加 Name。

`app/report/ppt/exact_engine.py` 当前只实验性绑定：

- 第 1 页封面标题和日期。
- 第 4 页产品信息表格单元格。
- 第 77 页第一个 Issue 的文字。
- 第 1 页输出时删除填写说明。

该实验验证了一个重要事实：正式模板必须采用 OOXML 定点编辑，不能用 `python-pptx` 整包重存。

原因：这份正式模板包含 OLE 等复杂关系。测试中，`python-pptx` 能重新读取其自己保存的文件，但 PowerPoint 曾拒绝打开该文件；采用 PowerPoint 自身命名模板，再定点修改 Slide XML 后，PowerPoint 可以正常打开 84 页输出。

因此：

- `python-pptx` 可继续用于小型测试模板和简单页面。
- 正式模板运行时不要调用 `Presentation.save()` 重存整包。
- 不要在 FastAPI Web 请求线程中启动 PowerPoint COM。
- 对正式模板优先使用 Open XML/ZIP Part 定点修改，完整保留未知 Part 和 Relationship。

## 4. 推荐的模板编辑器技术路线

### 4.1 推荐组合

```text
PowerPoint VSTO Add-in（C#/.NET）
  ├── 读取当前 Presentation/Slide/Selection
  ├── 给 Shape 写入稳定 Binding ID
  ├── WebView2 显示字段树和绑定属性
  └── 保存模板包

FastAPI（现有 Python 项目）
  ├── 提供字段目录和示例数据
  ├── Excel → Canonical JSON
  ├── 校验 Manifest
  ├── 生成任务 API
  └── 模板版本管理

Open XML Generation Worker
  ├── 根据 Manifest 修改文本节点
  ├── 替换图片 Part/Relationship
  ├── 复制 Repeat Slide
  └── 保留母版、主题、OLE 和未知对象
```

推荐 VSTO 而不是先做浏览器 PPT 编辑器，原因：

- 用户在真正的 PowerPoint 中选择对象，视觉结果没有浏览器渲染误差。
- 对现有复杂组合对象、表格和 OLE 的覆盖更完整。
- 不需要重新实现 PowerPoint Canvas。
- 当前使用环境为 Windows，正式模板也依赖桌面 PowerPoint 验证。

Office.js 可作为后续跨平台版本，但首版需要先验证客户 PowerPoint 的 API Set，以及图片、表格、Group、OLE 等对象覆盖。

### 4.2 为什么生成端不能依赖 PowerPoint COM

COM/VSTO 适合有用户登录的模板设计端，不适合 FastAPI 后台批量生成：

- Office 是交互式桌面应用。
- 可能弹出修复、字体、链接、权限或保存对话框。
- COM 为 STA，吞吐和并发能力差。
- 异常时容易残留 POWERPNT 进程或阻塞。

生产生成端应采用 Open XML 定点处理；PowerPoint 只作为设计和验收工具。

## 5. 模板编辑器的用户流程

建议 PowerPoint 右侧任务窗格提供以下流程：

1. 打开 PPT 模板。
2. 连接当前 FastAPI 项目或导入 Excel。
3. 展示 Field Catalog。
4. 用户在 PowerPoint 中选择一个对象。
5. 编辑器显示对象类型、Slide ID、Shape ID、Name、尺寸和当前绑定。
6. 用户选择字段并设置 Renderer。
7. 编辑器写入 `DFM_BIND_ID`，并更新 Manifest。
8. 使用 `/api/demo` 或上传 Excel 即时预览当前页。
9. 执行模板验证。
10. 保存为 `.dfmt` 模板生成器包。

第一版必须支持：

- Text Shape。
- Picture/图片占位区域。
- Table Cell。
- 整个 Table。
- Group 作为整体图片区域。
- `repeat_slide`，用于 `issues[]`。
- `visibility`，用于可选页和可选对象。
- 空值策略。
- 图片 `contain/cover`。
- 绑定、解除绑定、重新绑定。
- 搜索字段。
- 显示未绑定、缺失和重复绑定。
- 用示例数据预览。

## 6. Field Catalog 设计

不要让插件直接理解 `f/t/i` 的业务细节。FastAPI 应提供字段目录：

```http
GET /api/template-editor/field-catalog
```

建议响应：

```json
{
  "schema_version": "1",
  "roots": [
    {
      "path": "project.part_number",
      "label": "零件号",
      "type": "string",
      "sample": "TP-HPDC-2026-0087"
    },
    {
      "path": "issues[]",
      "label": "DFM问题",
      "type": "array",
      "children": [
        {"path": "issues[].description", "type": "string"},
        {"path": "issues[].images.before", "type": "image"}
      ]
    }
  ]
}
```

字段来源应包括：

1. `DFMReport` Pydantic JSON Schema。
2. 当前 HTML `f/t/i` 字段注册表。
3. `compute_all()` 派生结果。
4. Excel Import Schema。

长期应逐步把 2、3、4 收敛到表单应用 Schema + Runtime Data，而不是让 Manifest 永久绑定固定的
`f.xxx`。当前工作台已经按当前应用目录保存显式的“PPT 目标 → 表单源”关系；旧 DFM 路径只为
历史方案提供限定迁移。

## 7. Excel 导入约定

建议 Excel 先转换为 JSON，再进入模板编辑器。不要让 PPT 生成器在渲染过程中读取任意工作簿。

建议工作表：

```text
Project       # key/value 项目字段
Parameters    # key/value 工艺参数
Issues        # 一行一个 Issue
Images        # image_id、文件路径或资源 ID
History       # DFM 履历
Tables_*      # 其他业务数组
```

原始设计阶段建议的接口（当前尚未实现为独立 Excel API）：

```http
POST /api/template-editor/import-excel
POST /api/template-editor/validate-data
```

当前优先使用 `/forms` 导入 HTML 并生成应用字段目录；若后续增加 Excel 导入，推荐使用现有
Python 环境中的 `openpyxl`（需要加入依赖），输出统一 JSON 和导入警告：

```json
{
  "data": {},
  "warnings": [],
  "source": {
    "filename": "project.xlsx",
    "sha256": "..."
  }
}
```

必须限制文件大小、Sheet 数、行数、图片大小和公式处理；首版不要执行 VBA，也不要接受宏作为业务逻辑。

## 8. Binding Manifest 建议

不要只把字段路径写进 `shape.name`。名称可能被用户修改，也不适合存复杂配置。

推荐使用：

- `binding_id`：稳定 UUID。
- PowerPoint Shape Tag：`DFM_BIND_ID`。
- Shape Name：可读名称，方便人工定位。
- Manifest：完整绑定配置的唯一事实来源。
- PPT Custom XML Part：可选的嵌入副本，便于模板随文件移动。

示例：

```json
{
  "manifest_version": "1.0",
  "template_id": "dfm-a12",
  "template_version": "1.0.0",
  "source_sha256": "...",
  "bindings": [
    {
      "binding_id": "bnd-cover-part-number",
      "slide_id": 256,
      "shape_id": 3,
      "shape_name": "DFM_COVER_PART_NUMBER",
      "target": {"type": "text"},
      "source": "project.part_number",
      "renderer": "text",
      "required": true,
      "options": {
        "empty": "clear",
        "overflow": "warn"
      }
    },
    {
      "binding_id": "bnd-issue-before",
      "slide_key": "ISSUE_COMPARE",
      "shape_name": "ISSUE_IMAGE_BEFORE",
      "target": {"type": "image"},
      "source": "$item.images.before",
      "renderer": "image",
      "options": {"mode": "contain"}
    }
  ],
  "repeaters": [
    {
      "slide_key": "ISSUE_COMPARE",
      "source": "issues",
      "item_alias": "$item"
    }
  ]
}
```

表格单元格 Target：

```json
{
  "target": {
    "type": "table_cell",
    "row": 1,
    "column": 2
  }
}
```

首版禁止 Manifest 执行 Python、JavaScript 或任意表达式。格式化只允许白名单操作，例如 `date`、`number`、`join`、`default` 和单位后缀。

## 9. 模板生成器包格式

建议扩展名为 `.dfmt`，内容为 ZIP：

```text
DFM_A12_1.0.0.dfmt
├── master.pptx
├── manifest.json
├── data-schema.json
├── version.json
├── assets/
└── thumbnails/
```

`version.json` 至少记录：

```json
{
  "template_id": "dfm-a12",
  "template_version": "1.0.0",
  "manifest_version": "1.0",
  "created_at": "2026-09-02T12:00:00+08:00",
  "source_sha256": "...",
  "minimum_generator_version": "1.0.0"
}
```

保存时必须验证：

- Binding ID 唯一。
- 绑定对象仍存在。
- 字段路径存在且类型兼容。
- 图片只能绑定到图片目标。
- 表格坐标有效。
- Repeat Slide 不引用全局错误作用域。
- 必填字段有示例值。
- 模板文件可被 PowerPoint 打开。

## 10. 推荐新增目录

不要把编辑器代码塞进 `app/report/ppt/engine.py`。

建议：

```text
template-editor/
├── Dfm.TemplateEditor.sln
├── Dfm.TemplateEditor.AddIn/       # VSTO、Selection、Tags、保存
├── Dfm.TemplateEditor.Contracts/   # C# Manifest DTO
└── ui/                             # WebView2 React/Vue 任务窗格

app/template_editor/
├── api.py
├── field_catalog.py
├── excel_importer.py
├── manifest_models.py
├── manifest_validator.py
├── package_service.py
└── preview_service.py

app/report/ppt/openxml/
├── package_editor.py
├── text_binding.py
├── image_binding.py
├── table_binding.py
├── slide_repeater.py
└── relationship_manager.py
```

前后端应共享 `manifest.schema.json`，通过 JSON Schema 做兼容验证。

## 11. 首个开发里程碑

后续 Agent 应先做一个纵向闭环，不要立即处理 84 页：

### Milestone 1：选中对象并保存绑定

范围：

1. 创建 PowerPoint VSTO Task Pane。
2. 读取当前选中 Shape。
3. 从 FastAPI 获取 Field Catalog。
4. 把一个文本字段绑定到选中 Shape。
5. 给 Shape 写入 `DFM_BIND_ID` Tag。
6. 生成 `manifest.json`。
7. 关闭并重新打开 PPT 后仍能识别绑定。
8. FastAPI 使用该 Manifest 和 `/api/demo` 替换该 Shape 文本。
9. 输出文件可以在 PowerPoint 打开，且除文字内容外视觉对象不变。

验收测试：

- Shape 改名后仍能通过 Binding ID 恢复。
- Shape 删除后 Validator 明确报告缺失。
- 同一 Binding ID 重复时保存失败。
- 未绑定对象不发生任何 OOXML 变化。
- 模板中的 OLE、图片、母版和 Relationship 保持存在。

原始路线中的图片绑定、表格单元格/整表绑定、Repeat、条件页面、模板注册和方案版本管理已在
当前代码中交付。Excel 直接导入仍是后续增强项；现阶段可先通过表单中心的 HTML Schema 或
FastAPI 结构化数据进入工作台。

## 12. 原始建议 API 与当前替代接口

以下接口保留用于追溯最初设计，当前实现以 README 和[多表单应用平台交接](FORM_PLATFORM_2026-09-09.md)
列出的接口为准：

```text
GET  /api/template-editor/field-catalog
GET  /api/template-editor/sample-data
POST /api/template-editor/import-excel
POST /api/template-editor/manifest/validate
POST /api/template-editor/package
POST /api/template-editor/preview

POST /api/templates
GET  /api/templates
GET  /api/templates/{template_id}/versions
POST /api/templates/{template_id}/generate
```

当前对应关系为：`/api/template/scan`、`/api/template/inspect`、`/api/template/live-preview`、
`/api/template/generate`、`/api/templates/*` 和 `/api/schemes/*`；旧 `/api/ppt` 仍保留作为
DFM 生产链路，不与通用模板工作台互相覆盖。

## 13. 测试与质量门禁

当前测试入口：

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

本文原始设计阶段的最近一次结果为 79 项通过、4 项 HTTP 集成测试因 bundled runtime 缺少
FastAPI/httpx 而跳过；该数字仅作历史快照。当前基线为 Python 224 项、Node 12 项通过，
详见本文件顶部“当前已交付基线”和 [项目更新记录](CHANGELOG.md)。

模板编辑器新增测试至少包括：

- Manifest Model 和 JSON Schema。
- Field Catalog 路径和类型。
- Excel Importer。
- Shape Tag/Binding ID 持久化。
- 文本、图片、表格单元格 Binding。
- Repeat Slide。
- 未绑定 OOXML Part 字节保持测试。
- 模板缺失/重复对象错误。
- PowerPoint 本机打开冒烟测试。
- 生成前后 Slide 数、母版、OLE、媒体和 Relationship 数量对比。

建议把 PowerPoint 冒烟测试作为 Windows CI 或人工发布门禁，不要让普通单元测试依赖本机 Office。

## 14. 安全要求

- 默认拒绝 `.pptm`、`.xlsm`，除非进入隔离流程。
- 不执行 VBA、Excel 宏或 Manifest 中的任意脚本。
- 上传文件设置大小、页数、Shape 数、图片像素和解压后总体积限制。
- 防止 ZIP Slip 和压缩炸弹。
- 图片数据只允许受控 MIME 类型。
- 外部 URL 默认不下载，或使用域名白名单和超时。
- 模板包记录 SHA-256 和创建者。
- 每次生成使用临时副本，永不覆盖源模板。

## 15. 开发禁区

后续 Agent 不应：

- 继续手写 84 页坐标来模仿正式模板。
- 用 `python-pptx` 整包保存正式 A12 模板。
- 用 `slide.shapes[index]` 作为运行时绑定协议。
- 把字段路径只存进 Shape Name。
- 在 PPT Renderer 中重新计算 DFM 工艺结论。
- 在 FastAPI 请求线程中使用 PowerPoint COM。
- 在新路径稳定前删除 `app/ppt.py` 或改变 `/api/ppt` 默认行为。
- 把浏览器 PPT 画布作为首版范围。

## 16. 接手后的建议阅读顺序

1. 本文档。
2. `app/main.py`：当前 API 和 Feature Flag。
3. `app/demo.py`：完整示例 `{f,t,i}`。
4. `app/calc.py`：结构化计算输出。
5. `app/dfm/models/` 和 `app/dfm/adapters/legacy.py`。
6. `app/report/ppt/schema.py`、`binding_resolver.py`、`renderers/`。
7. `app/report/ppt/validators/`。
8. `app/report/ppt/exact_engine.py`：只用于理解 OOXML 定点替换实验。
9. `tests/`：已有行为和安全边界。

## 17. 最终架构决策摘要

- HTML/FastAPI 已经能够提供结构化数据，继续复用。
- Excel 是额外的数据导入通道，不是 PPT 渲染层的数据模型。
- PowerPoint 是视觉编辑器，不在浏览器重做 PowerPoint。
- VSTO 插件负责选择对象、绑定字段和保存模板生成器。
- Manifest 是绑定配置的事实来源，Shape Tag 保存稳定 Binding ID。
- FastAPI 负责字段目录、数据校验、模板管理和生成调度。
- Open XML Worker 负责生产环境的无 Office 定点生成。
- 未绑定的模板对象必须保持不变。
- 旧 `/api/ppt` 在新路径通过完整回归前继续保留。
