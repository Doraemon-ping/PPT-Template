# 当前开发上下文（唯一有效入口）

最后更新：2026-09-10  
项目：HPDC DFM 自动生成 / 多表单 PPT 模板工作台  
工作目录：`C:\Users\26257\Desktop\工作计划\6-DFM自动生成`

> 后续 Agent 先读本文，再看 `docs/CHANGELOG.md` 的增量记录。本文只描述当前有效架构和边界；按日期命名的旧交接文档均为历史参考，不应覆盖本文结论。

## 1. 当前产品定位

项目已经从单一 DFM 页面升级为“多表单应用 + 数据桥接 + PPT 模板工作台”：

1. 用户导入或选择 HTML 表单。
2. 系统识别结构化字段，复杂 DFM/报价表单可在隔离 iframe 中原样运行。
3. 用户在表单应用内维护数据项目、版本和草稿。
4. 用户导入任意 PPTX，按当前 PPT 页的对象选择目标。
5. 用户把 PPT 目标对象绑定到当前表单字段，保存为可复用方案。
6. 方案按数据生成 PPTX；模板未绑定内容和原始样式尽量保持不变。

当前仍是单机/单实例服务，不是多用户 SaaS：没有登录、权限、云端对象存储和审计隔离。

## 2. 运行方式

源码开发：

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

入口：

- `/forms`：表单中心。
- `/template-editor`：PPT 模板工作台。
- `/`：旧版 DFM 表单与兼容入口。

正式 Windows 绿色版：运行 `release\DFM报告生成器_win64\HPDC_DFM_Generator.exe`。应分发完整 `release\DFM报告生成器_win64` 目录或同名 ZIP，不能直接分发 `packaging\build_dist`，后者是 PyInstaller 中间产物，不含完整模板和运行数据。

## 3. 当前架构

### 后端

- `app/main.py`：FastAPI 应用、路由、作用域和服务端实时预览缓存。
- `app/calc.py`：原 HTML 工具的工艺计算后端化。
- `app/form_platform.py`：应用、项目、版本、归档、草稿和 SQLite 持久化。
- `app/native_forms.py`：复杂 HTML 表单运行态、字段目录和数据桥接。
- `app/report/ppt/template_registry.py`：内置/上传模板注册与路径解析。
- `app/report/ppt/template_engine.py`：Deck 编排、占位符、显式对象绑定、重复页和条件页。
- `app/report/ppt/openxml/`：OOXML 定点修改，处理文本、图片、表格、公式、跨模板拼页和依赖关系。
- `app/report/ppt/scheme_service.py`：保存、载入、版本化和复用绑定方案。
- `app/report/ppt/slide_preview.py`：原页/实时数据 PNG 预览。

### 前端

- `static/form_center.html/js/css`：多表单中心。
- `static/template_editor.html`：PPT 页面选择、目标对象选择、字段绑定、公式、方案保存和预览。
- `static/editor_ux.js`：对象导航、草稿、方案复用、分页配置等模型逻辑。
- `static/native_bridge.js`：原样 HTML iframe 与服务端数据桥接。

### 数据目录

- `data/form_platform/`：应用和项目数据库。
- `data/templates/`：用户上传模板及注册信息。
- `data/schemes/`：绑定方案和版本。
- `data/template_previews/`：原页预览缓存。
- 冻结版写入 EXE 同级 `data/`；源码版写入项目 `data/`。

## 4. 已实现能力

- HTML 字段识别、中文字段目录和复杂 DFM/报价 HTML 原样运行。
- 表单应用隔离、命名项目、历史版本、恢复、归档、JSON 导出和服务端草稿。
- 任意 PPTX 导入、页/形状/表格/图片/占位符扫描。
- 显式“PPT 目标对象 → 当前表单源字段”绑定，不依赖固定 `f.custName` 等旧字段别名。
- 文本整段替换、局部文本替换、图片绑定、单元格图片、整表绑定、重复页、条件页、跨模板拼页。
- 中文公式编辑器、公式图片、对象搜索、键盘选择、绑定草稿和已保存方案单页复用。
- 原样表单允许部分绑定后直接生成；未绑定 PPT 目标在 `missing=keep` 时保留模板原内容，响应头返回未绑定数量。
- 方案保存默认服务端持久化，不再只依赖浏览器 `localStorage`。

## 5. 预览现状与关键边界

### 当前实现

`slide_preview.py` 使用隐藏 PowerPoint COM 常驻 worker，并在 worker 失效时重建、重试，再降级到一次性 PowerShell 导出。前端先显示原模板底图，服务端有 24 条/90 秒实时预览缓存。

### 已验证

- 本机源码服务可生成 PNG。
- 本机完整绿色版 EXE 可启动，原页预览接口返回 `HTTP 200` / `image/png`。
- 最新发布 ZIP 已从头解压并启动验证。

### 不可忽略的环境要求

原页和实时数据 PNG 仍依赖运行服务的 Windows 机器安装桌面版 Microsoft PowerPoint。PyInstaller、`python-pptx` 和 Open XML 引擎不能替代 PowerPoint 的视觉渲染能力。

PPTX 生成本身不依赖 Office。目标机没有 PowerPoint 时，生成下载可以工作，但原样预览会失败。诊断命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\_internal\tools\check_preview_environment.ps1 -Root .\_internal
```

Aspose.Slides、LibreOffice Headless、ONLYOFFICE 尚未接入；如果产品必须在无 Office 主机上预览，应单独实现渲染后端抽象，优先评估 Aspose.Slides 的商业授权和真实模板还原度，不能直接宣称与 PowerPoint 完全一致。

## 6. API 主干

- `POST /api/form-apps/...`：表单应用与项目管理。
- `GET/POST /api/templates*`：模板注册、上传和删除。
- `POST /api/template/scan`：占位符和绑定目标扫描。
- `POST /api/template/inspect`：对象几何和表格结构扫描。
- `GET /api/templates/{id}/slides/{n}/preview.png`：原模板页 PNG。
- `POST /api/template/live-preview`：当前绑定和数据的临时 PNG。
- `POST /api/template/generate`：Deck 模板生成。
- `GET/POST/DELETE /api/schemes*`：方案保存、版本、删除和按方案生成。
- `POST /api/template/formula-preview`：公式预览。
- `/api/ppt`：旧版 47 页生产链路，保持兼容，不作为新模板引擎的实现依据。

## 7. 验证基线

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
node --test tests/editor_models.test.cjs tests/native_bridge.test.cjs
```

当前基线：Python 224 项通过，Node 12 项通过；PowerShell 构建脚本语法通过；完整发布 ZIP 解压后的 EXE 原页预览通过。

## 8. 当前未完成事项

1. 无 Office 主机的独立渲染后端。
2. 多用户登录、权限、配额、审计和云端存储。
3. 正式 84 页复杂 A12 模板的全量对象绑定验收。
4. 预览渲染队列、并发限制和跨进程缓存。
5. 更完整的字体、OLE、SmartArt、图表和特殊动画兼容性验证。

## 9. 后续开发规则

- 新功能或修复必须同步更新 `docs/CHANGELOG.md`，并更新本文涉及的章节。
- 不要把固定 DFM 字段名重新注入通用模板绑定；来源必须来自导入表单字段目录。
- 不要使用 `python-pptx` 整包重存正式复杂模板；正式生成继续使用 OOXML 定点编辑。
- 不要把 `packaging/build_dist` 当交付物。
- 任何视觉一致性结论都必须用真实 PPTX、实际渲染器和目标运行环境验证。

## 10. 历史文档处理

以下文档保留为专项审计记录，但不再作为当前开发入口：

- `HANDOFF_NEXT_AGENT_2026-09-02.md`
- `PPT_TEMPLATE_GENERATOR_HANDOFF.md`
- `PPT_TEMPLATE_ENGINE_COMPLETION.md`
- `EDITOR_UX_2026-09-03.md`
- `TABLE_PAGINATION_2026-09-03.md`
- `CELL_IMAGE_BINDING_2026-09-03.md`

它们包含阶段性测试数字、旧设计讨论和已被当前架构替代的建议；需要追溯历史时再查阅，不应据此改变当前实现。
