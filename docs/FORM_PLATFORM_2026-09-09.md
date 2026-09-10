# 多表单应用平台：实现与交接（2026-09-09）

> 完整时间线见 [项目更新记录](CHANGELOG.md)。本文聚焦多表单应用、原样 HTML 桥接和按应用隔离的 PPT 工作台。

## 使用入口

打开 `/forms`（原 DFM 页顶部也有「表单中心」）。

1. 导入 HTML，选择运行方式。普通页面可查看识别警告、确认/修改中文名称、类型、稳定标识、选择项和明细列；复杂 DFM/报价页面选择「原样运行 HTML + 数据桥接」。
2. 创建表单应用。在该应用中新建命名数据项目；普通模式填写生成的表单，原样模式直接使用原 HTML 页面，上传图片、增减明细行和计算均由原页面处理。
3. 保存项目或另存新项目；更新保留历史版本，支持历史恢复、归档/取消归档、JSON 导入导出。
4. 从项目进入 PPT 工作台，导入自己的 PPT，点选对象绑定此表单字段，保存方案；回到项目选择方案生成报告。

新应用默认没有 DFM 模板。不同应用的项目、模板、方案与工作台草稿独立。原 DFM 保留原计算表单与模板，新增命名项目保存、历史恢复以及带项目上下文的工作台链接。原样应用的字段目录在首个项目保存后由完整数据快照动态生成。

## 代码导航

| 模块 | 职责 |
| --- | --- |
| `app/form_platform.py` | HTML 控件发现、Schema 校验、动态字段目录、SQLite 项目及版本、应用路由 |
| `app/html_literals.py` | 安全解析脚本中的静态字段配置对象，不执行 JavaScript |
| `app/native_forms.py` | 原样应用适配器：识别受支持的原 HTML、归一化完整快照并生成 PPT 参数目录 |
| `static/native_host.js` / `static/native_bridge.js` | 沙箱 iframe 宿主与原页面数据桥；隔离 localStorage、监听变更、保存/恢复完整快照 |
| `static/form_center.html/css/js` | 表单中心、字段确认、自动表单、数据项目、历史恢复、报告入口 |
| `static/named_projects.js` | 旧 DFM 页面接入命名项目、历史版本及工作台项目链接 |
| `app/main.py` | `app_id` 请求作用域、隔离模板注册表/方案目录、旧数据迁移入口 |
| `static/template_editor.html` | 按应用加载目录与项目，草稿服务端同步，所有模板请求携带作用域 |
| `app/report/ppt/template_engine.py` | 泛型应用只使用结构化数据；仅 `dfm` 执行 DFM 计算 |
| `app/report/ppt/template_registry.py` | 非 DFM 不包含内置模板；重名上传分配新 ID，不覆盖原模板 |
| `app/report/ppt/scheme_service.py` | 保存方案时保留历史快照，当前文件原子替换 |

## 数据及接口

- `data/form_platform/platform.sqlite3`：表单 Schema、命名项目、项目历史版本、工作台草稿。
- `data/form_platform/applications/{app_id}/`：该应用独立的模板注册表、PPT 文件和方案；内部目录结构沿用原注册表/方案服务。
- DFM 原 `data/schemes/`、模板与 `data/project.json` 保留。旧数据可在 DFM 应用列表点击导入，复制为新项目。
- 浏览器 localStorage 仍作为编辑草稿缓存，不再是项目唯一保存来源。
- 项目创建总是新 UUID，同名不会覆盖；更新需要当前 revision，过期请求返回 409。恢复旧项目内容通过正常更新创建新版本。
- 工作台草稿以应用 + 项目（或 templates）为键，600 ms 防抖保存；冲突停止自动同步并保留本地缓存、提示刷新或另存方案。

主要接口：

```text
GET/POST /api/form-apps
POST /api/form-apps/discover                  multipart HTML
POST /api/form-apps/import-native             multipart HTML，受支持复杂页面原样导入
GET /api/form-apps/{app_id}/catalog
GET /api/form-apps/{app_id}/defaults
GET /api/form-apps/{app_id}/runtime-source    原样应用的完整 HTML（JSON 字段）
GET/POST /api/form-apps/{app_id}/projects
GET/PUT /api/form-apps/{app_id}/projects/{id}
GET /api/form-apps/{app_id}/projects/{id}?revision=N
GET /api/form-apps/{app_id}/projects/{id}/versions
POST /api/form-apps/{app_id}/projects/{id}/archive?archived=true
GET /api/form-apps/{app_id}/projects/{id}/export
GET/PUT /api/form-apps/{app_id}/drafts/{key}
```

模板扫描接口 `/api/template/scan` 另外返回 `binding_targets`，每条记录包含
`slide_index / shape_name / path / target_id`。这些是 PPT 的目标槽位，不是当前 HTML
表单的字段路径；方案中的 `bindings` 才保存用户选择的来源字段。

原模板/方案接口通过 `?app_id=...` 隔离；缺省值为 `dfm`，非法应用不能回退到 DFM。`GET /api/schemes/{name}/versions` 返回方案历史完整记录；目前方案历史仅提供 API，尚无可视化历史恢复入口。同名保存前前端确认，并保留快照；更换名称即另存。

## HTML 识别边界与安全

支持 input/select/textarea、关联 label、默认值、必填、fieldset、图片输入、具有表头和输入控件的明细表。还支持脚本内可静态解析的 `k/key + type` 字段配置及静态 cols/rows。

普通模式不执行上传 HTML 的业务脚本，只提取控件并按统一组件呈现，因此不保证原 HTML 外观或计算联动一致。对已识别的 DFM/报价页面，原样模式会保存完整 HTML，并在沙箱 iframe 内运行其内联脚本；外部脚本、网络请求、表单提交、iframe/object/embed 被禁用。宿主通过 `postMessage` 接收适配器快照，不把原页面脚本混入平台主页面。用户只应导入信任的 HTML。

标准 HTML 输入按字段标识提取；特殊布局表可能误判为明细，需在确认页调整。原样模式目前提供 `dfm_quote_v1` 适配器，针对 `DFM及报价模版20260827.html` 的 `G / PR / MDB / TDB / IS / FDB / IDB / VH` 数据模型，并把原页面计算的工序节拍/产能汇总加入 PPT 参数目录。其他 React/Vue 或自定义数据模型会安全拒绝原样导入，需新增适配器；不能把任意 HTML 推断为已完整桥接。

## 验证结果

- Python `python -m unittest discover -s tests`：224 项通过（含实时预览缓存与失效 PowerPoint worker 恢复回归）。
- Node `node --test tests/editor_models.test.cjs tests/native_bridge.test.cjs`：12 项通过；新增前端脚本语法检查通过。
- 本机实时预览 smoke：后台 PowerPoint 渲染器首次请求约 2.6 秒，不同数据的下一次请求约 0.1 秒，相同请求缓存命中约 0.005 秒。
- 新增 `tests/test_form_platform.py`：同名不覆盖、版本冲突/恢复、项目/模板/方案/草稿隔离、重复上传保留、泛型生成不调用 DFM、目录图片路径、非法 Schema。
- 浏览器：导入巡检 HTML，确认 7 字段、1 张明细；新建项目并保存两个版本，恢复历史后为版本 3；进入对应 PPT 工作台、上传 PPT、绑定说明字段、保存方案成功。
- 浏览器：导入真实 `DFM及报价模版20260827.html`，选择原样模式；项目页面保留客户、工序、流程图、报价计算等原布局，修改客户名称后保存为版本 2，重新打开恢复；进入项目上下文 PPT 工作台可读取该项目快照。
- 原样桥接 PPT 生成验证：参数目录得到 40 个源字段、11 张明细表、21 个图片槽位；在导入模板中将 `COVER_CUSTOMER` 显式绑定到原 HTML 的 `G.cust` 源路径，并用真实 `PART_IMAGE` 图片对象生成 PPT 成功，校验 OOXML 文本与图片关系。输出 `data/native-form-bridge-verified.pptx`。
- 模板驱动绑定：原样快照只保留 `G / PR / MDB / …` 的稳定源路径；导入 PPT 后扫描出每页的占位符目标，用户在对象面板中选择当前表单字段建立显式 `PPT 目标 → 表单源` 关系。不会把 `custName/partNo` 等 DFM 名称当作所有表单的通用字段。
- 旧方案兼容：历史方案若明确引用旧 DFM 名称，生成时只对这些明确引用做迁移解析；新方案目录和默认上下文不展示、不自动注入这些别名。原样正式生成允许保留未绑定模板目标，并通过 `X-DFM-Unbound-Targets` 响应头返回数量。
- 实时预览优化：编辑台先显示原模板底图；输入 450ms 防抖；服务端对相同请求使用 24 条/90 秒的进程内缓存；PowerPoint 预览默认 1280×720。常驻 PowerPoint worker 出现 `WinError 6` 等失效句柄时会自动重建一次，再降级为一次性导出并重试；部署更新后必须重启服务进程。
- 远端排障：发布目录提供 `tools/check_preview_environment.ps1`。若服务器未安装桌面版 PowerPoint，PPTX 仍可由 Open XML 引擎生成，但原页 PNG 和实时数据预览无法渲染；若 PowerPoint 可用但返回 `WinError 6`，优先检查服务账户桌面会话、残留 `POWERPNT.EXE` 和完整 onedir 发布目录。
- 实际 HTTP 生成 PPT 成功，并核验 OOXML 文本包含 `EQ-009` 与 `例行巡检`。输出 `data/form-platform-smoke-output.pptx`。本轮未单独完成该生成文件的 PowerPoint 视觉验收。
- 保留「设备巡检 · 示例应用」及「巡检示例 · 一号设备」供试用；其 PPT 方案是复用现有占位符演示 PPT 的测试方案，不是完整巡检报告设计。

## 部署与后续优先事项

这是服务端持久化的单实例版本，不是已经上线的云端 SaaS。当前服务仍在本机 127.0.0.1:8000，数据库也在本机服务目录。无登录/用户级权限，应用隔离不是身份授权；不能直接暴露公网。多人部署先补认证、所有权/授权校验、上传与图片配额、备份和审计。

备份应包含 SQLite、整个应用目录、DFM 方案与模板文件；停服务后整体复制，或使用 SQLite backup API 配合文件一致性备份。勿仅复制浏览器缓存。

后续：已创建表单的 Schema 版本/迁移管理、原 HTML 归档、方案历史恢复 UI 与并发控制、上传注册表并发写入保护、复杂 HTML 适配插件、按用户权限隔离。当前 Schema 创建后不支持编辑；变更可导入为新应用，但跨 Schema 数据与绑定映射迁移尚未实现。

原样 PPT 预览仍依赖既有 Windows/PowerPoint 渲染通道；不能以泛型表单功能已完成推断 Linux 原样预览已支持。
