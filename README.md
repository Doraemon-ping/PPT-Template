# 机加 DFM 表单服务（machining）

本分支是三服务拆分的**机加表单服务**独立版本：只包含机加 DFM 表单所需的代码，
可单独部署运行，不依赖压铸表单服务与 PPT 工作台服务。

- 入口：`app/services/machining.py`（FastAPI 应用对象 `app`）
- 默认地址：`http://127.0.0.1:8002`
- 数据目录：`data/machining_dfm/`
  - `machining_dfm.sqlite3`：项目、历史版本、设备(`machines`)/刀具(`tools`)/夹具(`fixtures`)/检具(`gauges`)库与类别字典、附件元数据(`assets`)、后台配置
  - `assets/`：设备图片与资料**原始文件**（数据库里只存元数据与 URL）
  - `backups/`：结构升级前的自动备份（如 `pre-typed-machines.sqlite3`）
- 种子数据：`app/resources/machining_dfm_seed/`（拆分后的目录：`project/machines/tools/fixtures/gauges/categories.json` + `assets/machines/*.jpg`），首次运行自动建库；`app/resources/machining_dfm_seed.json` 只作为拆分工具的输入源保留

## 运行

```powershell
python -m pip install -r requirements.txt

python run_service.py                     # 默认 127.0.0.1:8002
python run_service.py --host 0.0.0.0      # 局域网可访问
python run_service.py --port 8012 --reload

# 或者直接用 uvicorn
.venv\Scripts\python.exe -m uvicorn app.services.machining:app --host 0.0.0.0 --port 8002
```

浏览器打开 <http://127.0.0.1:8002/machining-dfm> 使用机加 DFM 表单。

## 主要接口

| 路径 | 说明 |
| --- | --- |
| `GET /` | 跳转到 `/machining-dfm` |
| `GET /machining-dfm` | 机加 DFM 单页应用（静态资源在 `static/machining_dfm/`） |
| `GET /health` | 健康检查，返回 `{"service": "machining", "contract_version": "1.0"}` |
| `/api/machining-dfm/*` | 表单数据接口：bootstrap、项目增删改查、历史版本、后台配置、设备/刀具/夹具/检具库、登录与改密 |
| `/api/machining-dfm/machines` | **设备库（按行读写）**：`GET` 列表+字段表、`POST` 新增、`PATCH/DELETE /{id}`、`POST /reorder`、`PUT /{id}/default` |
| `/api/machining-dfm/trash` | **回收站（阶段 4）**：`GET` 全局（已删项目 + 8 张基础库/字典表的已删行）、`GET /projects/{pid}/trash` 本项目业务行、`POST /trash/{table}/{id}/restore` 恢复（表名白名单，**仅管理员**）；每条带 `deleted_at`/`deleted_by`/`deleted_reason`/被几个项目引用。**没有彻底删除、没有保留期**（口径 2）。项目「删除」= `DELETE /projects/{pid}`（管理员 + 写流水），「恢复」= `POST /projects/{pid}/restore`；老的 `POST /projects/{pid}/archive` 仍保留 |
| `/api/machining-dfm/machines/{id}/photo`·`/doc` | 设备图片/资料上传（`PUT` 原始字节，`Content-Type` 决定类型）与删除（`DELETE`） |
| `/api/machining-dfm/tools` | **刀具库（按行读写）**：`GET` 列表+字段表+自动列、`POST` 新增、`PATCH/DELETE /{id}`、`POST /reorder` |
| `/api/machining-dfm/tools/{id}/photo` | 刀具图片上传（`PUT` 原始字节）与删除（`DELETE`） |
| `/api/machining-dfm/tool-dictionaries` | 刀具**库分类 / 类型**两张字典表 + 各自被引用的次数（`GET`） |
| `/api/machining-dfm/tool-groups`·`/tool-categories` | 字典维护：`POST` 新增、`PATCH /{code}` 改名、`DELETE /{code}`（被引用或内置项返回 409） |
| `/api/machining-dfm/fixtures` | **夹具库（按行读写）**：`GET` 列表+字段表、`POST` 新增、`PATCH/DELETE /{id}`、`POST /reorder` |
| `/api/machining-dfm/gauges` | **检具库（按行读写）**：同上（价格单位万元·未税） |
| `/api/machining-dfm/fixtures/fields`·`/gauges/fields` | 两个库的字段登记表（表头、单位、类别下拉与 `references`） |
| `/api/machining-dfm/fixtures/{id}/photo`·`/gauges/{id}/photo` | 夹具/检具图片上传（`PUT` 原始字节）与删除（`DELETE`） |
| `/api/machining-dfm/fixture-centers`·`/gauge-categories` | 模具中心/检具类别字典：`GET` 名单+引用计数、`POST` 新增、`PATCH /{名}` 只改 `sort_order`（改名 422）、`DELETE /{名}?cascade=1`（内置项 409，有数据需 `cascade`） |
| `/api/machining-dfm/library-dictionaries` | 两个字典的名单与引用计数一次取全（`GET`） |
| `/api/machining-dfm/assets/{asset_id}` | 附件下载（内容寻址 ETag，`?download=1` 带文件名） |
| `GET /api/machining-dfm/projects/{pid}/export.zip` | **导出文件包（阶段 5 · §7.0）**：**只读**、按需生成、不落库、不写 `data/`。zip 内容 = `project.json`（与 `GET /projects/{pid}` 同一份形状的读模型，附件字段换成包内相对路径 `assets/<id>.<ext>`，另加顶层 `_export` 说明块）+ 本项目**真引用到**的附件原图 + `README.txt`（UTF-8）。响应 `application/zip` + `Content-Disposition: attachment; filename="DFM_<项目名>.zip"`（中文项目名走 RFC 5987 的 `filename*`）。项目不存在 → 404（中文 detail）；项目已删除也能出包（与读同一口径）；一个附件都取不到时照样出包 |
| `GET /api/integration/services` | 跨服务链接（表单中心 / 机加表单） |
| `GET /api/integration/workbench-link` | 生成 PPT 工作台跳转地址（默认 `http://127.0.0.1:8003`） |
| `/api/ppt-provider/v1/*` | 数据源契约：`sources`、`projects`、`snapshot`、`normalize`（供 PPT 工作台拉取项目快照） |
| `GET /api/logs/tail` | 服务端日志尾部（由 `app/services/observability.py` 提供） |

环境变量：

- `MACHINING_PUBLIC_URL`：对外公布的本服务地址（快照回链、跨服务导航用）
- `PPT_WORKBENCH_URL`：PPT 工作台地址，默认 `http://127.0.0.1:8003`
- `PPT_PROVIDER_TOKEN`：设置后 `/api/ppt-provider/v1/*` 需要 `Authorization: Bearer <token>`
- `DFM_APP_ROOT`：数据根目录（默认项目根，打包后为 exe 同级目录）

## 目录结构

```
app/
  settings.py               路径配置（BASE_DIR / APP_ROOT / DATA_DIR / STATIC_DIR）
  machining_dfm.py          机加表单存储与路由（SQLite，含鉴权与后台配置）
  machining_library.py      通用类型化基础库引擎（字段登记表 / 行级 CRUD / 附件 / 旧数据接入）
  machining_machines.py     设备库：字段登记表 + machines 表读写、迁移、兜底机型
  machining_tools.py        刀具库：字段登记表 + 两张字典表（库分类/类型）+ tools 表读写、迁移
  machining_fixtures.py     夹具库：字段登记表 + 模具中心字典 + fixtures 表读写、迁移
  machining_gauges.py       检具库：字段登记表 + 检具类别字典 + gauges 表读写、迁移
  machining_assets.py       附件库：assets 表 + 磁盘文件（内容寻址、去重、ETag）
  machining_process.py      工序与工序刀具行：project_processes / project_process_tools（含行级读写引擎）
  machining_issue.py        问题清单：project_issues（工序外键 + 两张图片走附件库）
  machining_selection.py    选型：project_fixtures（夹具选型）/ project_gauges（检具选型）两张项目级表
                            （各指自己的库行与类别字典 + 快照；老多态表 project_selections 只当搬迁来源）
  machining_history.py      版本履历：project_versions（保存版本 kind='save' + 页面履历 kind='history'）
  machining_changes.py      变更流水：project_changes（谁在什么时候把哪一行改成了什么，只增不改）
  machining_seed.py         种子数据读取（拆分目录或旧的单文件）
  machining_projection.py   机加数据 → 报告运行时投影（工序时间、节拍、月产能）
  native_forms.py           原样 HTML 表单解析/规范化（保存与快照共用）
  html_literals.py          HTML 内字段声明提取
  integration_contract.py   数据源契约模型（Snapshot / ReportContext）
  resources/machining_dfm_seed/  拆分后的种子数据（设备/刀具/夹具/检具 + 设备图片）
  services/
    machining.py            本服务入口
    provider_api.py         数据源导出 API + 跨服务链接（本分支只含机加部分）
    observability.py        日志与 /api/logs/* 接口
static/machining_dfm/       机加表单前端（index.html + host.js + machines.js + tools.js + library_pages.js + fixtures.js + gauges.js + project_info.js + process_page.js + issue_page.js + selection_page.js + history_page.js + legacy_app.js + PptxGenJS）
                             （变更流水 3b 没有前端模块：流水由服务端在每个行级写入点记录，页面只读不写）
docs/MACHINING_LIBRARY_REFACTOR.md  基础库拆分重构说明（表结构、接口、迁移、前端约定）
docs/MACHINING_BUSINESS_REFACTOR.md 业务数据重构方案（项目隔离 / 版本管理 / 逻辑删除；第一阶段"项目信息"已落地，见第 10 节）
docs/MACHINING_BUSINESS_REFACTOR_PHASE1B.md 1b 阶段设计：工序 + 工序刀具行 落表（表结构/引用改造/迁移口径/验收，待拍板）
docs/MACHINING_BUSINESS_REFACTOR_PHASE2.md  2a + 2b 阶段设计与落地：问题清单（project_issues）、选型报价（project_selections）落表（表结构/外键对账/迁移/接口/前端/验收）
docs/MACHINING_BUSINESS_REFACTOR_PHASE3_DESIGN.md 阶段 3 设计：版本履历（project_versions）+ 变更流水（project_changes）表结构与口径（3a/3b 均已落地）
docs/MACHINING_BUSINESS_REFACTOR_PHASE3.md  3a 阶段实施：版本履历落表（表结构/读模型/接口/前端接管/迁移/验收）
docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md 3b 阶段实施：变更流水落表（记录口径/标签/只读接口/迁移与探针/验收 + 第 14 节清旧副本）
docs/MACHINING_BUSINESS_REFACTOR_PHASE4_DESIGN.md 阶段 4 设计**与实施记录**：逻辑删除 + 回收站 + 变更流水界面（第 5 节 = 后端与前端的落地记录与两遍验收；基础库/字典也进回收站；查看两个角色、恢复只给管理员）
docs/MACHINING_BUSINESS_REFACTOR_PHASE5.md 阶段 5 验收记录：附件归项目（旧 `cI/bI/aI` 已是真外键）+ 导出改造（导出 JSON / 导出文件包 `.zip`，便携单文件 HTML 已退休；库里 0 行 base64）
docs/MACHINING_DB_STRUCTURE.md          清完旧副本之后的库结构清单（19 张表 / 40 个外键列 / 还剩多少 JSON / 怎么复查）
tests/test_machining_dfm.py 机加服务测试
run_service.py              单服务启动脚本
```

## 测试

```powershell
.venv\Scripts\python.exe -m pytest tests -q          # 全部 203 项
.venv\Scripts\python.exe -m pytest tests -q -k machine
.venv\Scripts\python.exe -m pytest tests -q -k tool
.venv\Scripts\python.exe -m pytest tests -q -k fixture
.venv\Scripts\python.exe -m pytest tests -q -k dictionary
.venv\Scripts\python.exe -m pytest tests -q -k project_settings   # 项目信息：行级保存/校验/图片/迁移
.venv\Scripts\python.exe -m pytest tests -q -k selection          # 选型报价落表（2b）：外键/快照/格子/迁移
.venv\Scripts\python.exe -m pytest tests -q -k history            # 版本履历落表（3a）：保存版本/履历行/CHECK/迁移
.venv\Scripts\python.exe -m pytest tests -q -k changes            # 变更流水落表（3b）：外键/CHECK/每个写入点都记/不追溯
.venv\Scripts\python.exe -m pytest tests -q -k export             # 导出文件包（阶段 5 · §7.0）：包结构/字节一致/只读/404
node tools\check_tools_page.mjs                      # 刀具页无头自检（表头/自动列/筛选/保存）
node tools\check_fixture_gauge_page.mjs              # 夹具/检具页无头自检（分组卡片/逐字段保存/类别增删/委托）
node tools\check_export_assets.mjs                 # 阶段 5：附件引用/取图/导出才内联/库里无 base64 + 导出改造（101 条，只读）
node tools\check_trash_page.mjs                     # 阶段 4：回收站面板 + 变更流水时间线（98 条，接口自 stub）
node tools\smoke_machining_page.mjs                  # 整页真跑一遍：加载顺序/各页签渲染/动作后是否重绘（写请求拦下不落库）
node tools\compare_library_pages.mjs                 # 与改造前页面结构对照（表头/卡片/按钮有没有悄悄丢）
.venv\Scripts\python.exe tools\verify_library_migration.py   # 用真实数据副本试跑四个库的迁移（不动线上库）
.venv\Scripts\python.exe tools\live_fixture_gauge_e2e.py     # 对着运行中的服务做夹具/检具全链路自检（跑完还原数据）
.venv\Scripts\python.exe tools\verify_project_settings_migration.py   # 项目信息迁移干跑（可 --from 指向迁移前的备份目录）
.venv\Scripts\python.exe tools\restore_project_settings.py           # 项目信息与迁移归档逐键核对（默认干跑，--apply 才写回）
.venv\Scripts\python.exe tools\live_project_info_e2e.py              # 项目信息线上全链路自检（跑完数据还原原状）
.venv\Scripts\python.exe tools\live_report_snapshot_check.py         # 报表/PPT 数据源快照核对（字段绑定/图片内联/表格绑定）
.venv\Scripts\python.exe tools\capture_process_cost_baseline.py      # 冻结/比对工序成本基线（1b 改造"数字逐位不变"的判据，--check 只比对）
.venv\Scripts\python.exe tools\show_business_shape.py                # 只读：线上 pr[]/tl[]/is[] 的真实字段形状
.venv\Scripts\python.exe tools\analyze_tool_name_matching.py         # 只读：刀具行按名字匹配库会踩到几行（重名/找不到）
.venv\Scripts\python.exe tools\check_process_mapping_roundtrip.py    # 只读：1b 表结构对真实数据做往返映射，验证不漏键、派生值可重算
.venv\Scripts\python.exe tools\rehearse_project_processes.py         # 用生产模块在副本上演练：工序落表后读模型逐字节不变（线上不动）
.venv\Scripts\python.exe tools\migrate_selection_split.py             # 选型拆表迁移（默认干跑：副本上逐字节比对；--apply 先整库备份；--status 只读）
.venv\Scripts\python.exe tools\catchup_project_tables.py              # 口径 7 补迁：把"表空、JSON 满"的项目（另存为出来的副本）搬进各域的表（默认干跑；--apply 先整库备份；--status 只读）
.venv\Scripts\python.exe tools\check_business_gate.py                # 开关自检：关着时"不该多出业务表"，开着时"该有的表都在 + 外键干净"
.venv\Scripts\python.exe tools\check_process_wiring.py               # 核对前端每个写入点都"走行级保存 + 留着旧路径"（3b 起还核对"流水只由服务端记录"）
.venv\Scripts\python.exe tools\migrate_project_changes.py             # 3b 变更流水迁移（默认干跑：建表 + 写键 + 功能探针）
.venv\Scripts\python.exe tools\clean_legacy_project_data.py           # 清旧副本（默认干跑；--apply 先备份再删旧副本表 + 清 state_json + VACUUM）
.venv\Scripts\python.exe tools\slim_version_snapshots.py              # 把历史快照里的内联图片抽成附件引用（默认干跑；--apply 先备份）
.venv\Scripts\python.exe tools\migrate_library_trash.py                # 阶段 4：给 8 张基础库/字典表补逻辑删除三列（默认干跑；--apply 先备份，线上只做只读验证）
.venv\Scripts\python.exe tools\audit_foreign_keys.py [--with-process] # 外键总清单（含 SET NULL 口径与故意软引用）
.venv\Scripts\python.exe tools\check_served_page.py          # 线上页面脚本/样式版本号与静态资源 200 核对
.venv\Scripts\python.exe tools\check_host_css.py             # 样式齐不齐（host.js 的 class 有没有样式、样式表有没有 404）
```

> 样式表：`host.css`（顶部项目条、后台配置弹窗、库计数）之前在分支拆分时被删掉，
> `index.html` 却一直挂着 `<link>`，浏览器拿到 404，页面顶部与弹窗等于没样式；
> 现已按拆分前的版本恢复。前端资源版本号统一为 `?v=project-v1`
> （阶段 2a 是 `process-v1`，阶段 4 是 `trash-v1`；2026-09-18 结构再调整后升到 `project-v1`
> ——页签结构与工序/选型页面改动较大，升版本号保证浏览器一定拉到新脚本）。

> 导出（阶段 5 · §7.0，`node tools\check_export_assets.mjs` 盯着）：**便携单文件 HTML 已退休**
> ——`buildPortableHTML()` / `writeDataFile()` / `dlPortable()` / `exportHTML()` 与 `DATA_MARKER` 全部删除，
> `host.js` 里 `window.exportHTML = window.exportData` 那行临时接线也删了。页面上只剩两条能兑现的导出，
> 「项目信息」与「数据保存与导出 / Save & Export」**两张卡片上都有**：
> **导出 JSON（单文件·图内联）**（`exportData()`，离线有图、便于再导入）与
> **导出文件包(.zip)**（`exportPackage()` → 服务端 `GET /projects/{pid}/export.zip`，只发一个 GET、
> 零写请求、取服务端当前已保存版本）。服务端保存仍在：顶部「立即保存」+ 自动保存
> （`window.saveAll`）；「另存为新项目」（`window.saveAs`）由 `host.js` 原样保留，但卡片换按钮后
> **界面上暂时没有入口**（要用得在顶部工具条补一个按钮，或在控制台调 `saveAs()`）。
> 该自检里"包内结构"那组需要**服务已跑新代码**：老进程会返回 FastAPI 默认 404 Not Found，
> 此时脚本会明着打印"跳过并说明原因"（重启后同一组自动生效），其余断言（含只读、零写请求）照常跑。

> 前端约定：各基础库模块的 `render()` **只生成 HTML**，动作（增删/换图/改字段/加删类别）
> 之后必须调自己的 `repaint()`，由它去调 `legacy_app.js` 的整页 `window.render()`；
> 漏掉这一步数据存进去了但屏幕不变，看起来就是"点了没反应"。改了前端记得同步
> 把 `index.html`（以及 `tools/integrate_machining_dfm.py` 的模板）里的 `?v=` 往上加一版
> ——**所有资源用同一个版本号**（阶段 2a 是 `process-v1`，阶段 4 是 `trash-v1`，
> 2026-09-18 结构再调整后是 `project-v1`），`tools/check_host_css.py` 会核对。

> 项目信息（`project_info.js`）另加一条约定：**逐字段保存一律用 `PATCH /projects/{id}/settings`**。
> `PUT` 是"整份覆盖"语义——没提交的字段会回默认值、没提到的图片会被清空；
> 保存成功后用 `MachiningDFMHost.adopt(record)` 让服务端记录接管内存与指纹，
> 否则下一次整份保存会拿旧内存把新值覆盖回去。

## 业务数据落表（1b 工序 / 工序刀具行：代码已就位，开关默认关）

> **开关状态（2026-09-18）**：线上**已经打开，级别 5**（工序 / 问题清单 / 选型报价 / 版本履历 / 变更流水
> 全部落表）。下面讲的"没打开时走 `state_json`"仍然成立——那既是回滚路径，也是别的环境
> （如没迁过的测试库）的行为。迁移记录见「工序落表（1b）迁移」一节。

`app/machining_process.py` 把工序与工序刀具行做成项目级多行表（`project_processes` /
`project_process_tools`）：行级保存、逻辑删除 + 回收站、价格快照、派生值读时算。

### 页面结构：项目 → 工序（行内选设备）→ 夹具/检具选型

**2026-09-18 再调整**：页面上原先是"每道工序一个页签"（`工序-OP10`、`工序-OP20`…），
跟"项目信息/选型/问题"平级，项目与工序的层级感被抹平；选型又跟基础库夹在一起。
现在按"创建项目 → 填项目信息 → 选设备、选检具、选夹具"的逻辑重排（对照原工艺维护的做法，
工艺维护是服务于项目的）：

```
0 项目信息  1 工序  2 夹具选型  3 检具选型  4 问题清单  5 版本履历
6 工艺设置  7 设备库  8 刀具库  9 夹具库  10 检具库        ← 后五个是"后台维护"
```

* **工序收成一页总表**：每行一道工序，行里直接选设备（`setProcMachine` → `PUT …/processes/{id}/machine`）、
  看台数/刀具数/节拍/月产能，点行进入该工序的**刀具明细**（`openProc(pi)` / `closeProc()`，
  详情仍在这一个页签里，有「← 返回工序总表」）。**添加工序不再新增页签**
  （`tools/smoke_machining_page.mjs` 专门断言"页签数不变"）。
* **设备跟工序走**：`project_processes.machine_id` 是唯一权威；
  `PUT …/processes/{id}/machine` 空值即清空（回退兜底机型），设备库里有价则同步 `eqP`。
  换设备**不再整份保存**（旧做法是 `PUT /projects/{id}` 把整份 state 发回去）。
* **夹具/检具选型各一页**（项目级一份，与原工艺维护口径一致），对应两张项目级表
  `project_fixtures` / `project_gauges`，见下一节。
* **基础库与工艺设置退到后台**：它们跟"这个项目的工序/选型"不是一条主线，只是维护数据。

`app/machining_process.py` 把工序与工序刀具行做成项目级多行表（`project_processes` /
`project_process_tools`）：行级保存、逻辑删除 + 回收站、价格快照、派生值读时算。

- **显式开关**：只有 `app_settings.project_business_version >= 1`（迁移工具写）或环境变量
  `MACHINING_PROJECT_BUSINESS=1` 时才建表并用表数据；没打开时读模型照旧走 `projects.state_json`，
  **线上行为一模一样**。所以代码可以先上线、迁移单独执行；
- **数字序列化必须跟 JS 一致**：读模型里所有数字都过 `js_number()`（`50.0` → `50`，`6.5` 保持），
  `bg` 给回布尔。前端 `calcT()` 算出并落库的 `_ct` 是 JS 的 `32`，服务端若写 `32.0`，
  虽然数值相同，但"迁移前后逐字节一致"、成本基线指纹、历史快照 diff 都会出现假差异；
- **派生字段不落库**（口径 5）：`_ct/_vc/_vf/_fz` 每次读时按同一公式算；
- **`nc` 不无中生有**：旧数据没有 `nc` 的工序，读模型也不补这个键；
- 验收判据：`tools/capture_process_cost_baseline.py --check`（成本数字）+ 
  `tools/rehearse_project_processes.py`（在副本上把真项目落表，`pr[]` 必须逐字节相同）。

工序接口（写接口都递增项目版本 + 留版本快照，并返回整个项目记录给前端 `adopt`）：

```
GET    /api/machining-dfm/projects/{pid}/processes                        # 列表（含刀具行/设备/回收站/字段表）
POST   /api/machining-dfm/projects/{pid}/processes                        # 新增工序
PATCH  /api/machining-dfm/projects/{pid}/processes/{id}                   # 行级保存（名称/台数/节拍等）
PUT|DELETE /api/machining-dfm/projects/{pid}/processes/{id}/machine        # 换设备 / 清空设备（空值=回退兜底机型）
DELETE /api/machining-dfm/projects/{pid}/processes/{id}                   # 逻辑删除（刀具行一并进回收站）
POST   /api/machining-dfm/projects/{pid}/processes/{id}/restore           # 回收站恢复
POST   /api/machining-dfm/projects/{pid}/processes/reorder                # {ids:[…]}
PUT|DELETE /api/machining-dfm/projects/{pid}/processes/{id}/photo         # 夹具示意图（旧 cI）
POST   /api/machining-dfm/projects/{pid}/processes/{id}/tools             # 新增刀具行
POST   /api/machining-dfm/projects/{pid}/processes/{id}/tools/reorder     # 刀具行排序
PATCH  /api/machining-dfm/projects/{pid}/tools/{id}                       # 刀具行级保存（含快照价）
DELETE /api/machining-dfm/projects/{pid}/tools/{id}                       # 逻辑删除
POST   /api/machining-dfm/projects/{pid}/tools/{id}/restore               # 回收站恢复
PUT|DELETE /api/machining-dfm/projects/{pid}/tools/{id}/photo             # 刀具图（旧 fi）
```

> 开关关着时这些接口返回 **409**（不是 500）；行不属于该项目返回 404；
> 附件库种类多了 `process_photo`（工序夹具示意图与刀具图共用）。

前端（`static/machining_dfm/process_page.js`）：页面结构与 DOM **不变**，只把写入点接过来——
工序表/粘贴图片/选设备/从刀具库选刀/派生列全照旧，改的是"写到哪里去"。三条约定：

- **行 id 不缓存**：每次写前先 `GET /processes` 拿最新行列表再按下标取行 id，
  长度对不上就提示刷新，不按下标硬写；
- **选刀时才写价格/寿命快照**，库里没价就按 0 并在状态栏说明（口径 4）；
- **保存后 `adopt(record)`**：指纹对齐后旧的整体保存不会再发，一次编辑不会存两遍。

新增检查（建议和单测一起跑）：

```
.venv\Scripts\python.exe tools\check_process_wiring.py    # 工序写入点清单：每个点都要走行级保存且旧路径仍在（会抓"漏网"的直接赋值）
node tools/smoke_machining_page.mjs                        # 冒烟：开关关着行为不变 + 开关打开后 8 组行级动作逐条断言
```

## 问题清单落表（2a：`project_issues`，代码已就位，开关默认关）

`app/machining_issue.py` 把问题清单做成项目级多行表，与 1b 同一套口径
（行级读写、逻辑删除 + 回收站、图片走附件库、每次写留版本快照）。**外键全部是真的**：

| 列 | 指向 | 说明 |
| --- | --- | --- |
| `project_id` | `projects(id)` | 必填 |
| `process_id` | `project_processes(id)` | **可空**：项目级问题不挂具体工序 |
| `before_photo_id` / `after_photo_id` | `assets(id)` | 优化前 / 优化后图片（旧 `bI`/`aI`） |

顺带修掉旧结构的真缺陷：旧 `is[].pr` 存的是**工序名字**，工序一改名这条问题就"指向不存在"。
现在 `pr` 由外键**现算当前工序名**，工序改名自动跟随、工序进回收站则回退到
`process_name_snapshot`（迁移/新建时记下的名字）。`state_json.is` 仍旧是只读影子副本。

**能力级别是递增的**：`app_settings.project_business_version` ≥1 开工序表、≥2 再加问题清单
（环境变量 `MACHINING_PROJECT_BUSINESS` 给整数即可，给 `true` 当 1）。所以 2a 一定晚于 1b。

```
GET    /api/machining-dfm/projects/{pid}/issues                          # 列表（含工序下拉数据/回收站/字段表）
POST   /api/machining-dfm/projects/{pid}/issues                          # 新增（process_id 可空）
PATCH  /api/machining-dfm/projects/{pid}/issues/{id}                     # 行级保存（换工序只提交 process_id）
DELETE /api/machining-dfm/projects/{pid}/issues/{id}                     # 逻辑删除（可在回收站恢复）
POST   /api/machining-dfm/projects/{pid}/issues/{id}/restore             # 回收站恢复
POST   /api/machining-dfm/projects/{pid}/issues/reorder                  # {ids:[…]}
PUT|DELETE /api/machining-dfm/projects/{pid}/issues/{id}/photo/{slot}    # slot = before / after
```

- 外键指向的行不存在 / 已被逻辑删除 → **422** 并说明是哪个外键（不是 500）；
- 绕开接口直接写库也会被 SQLite 拦住（`PRAGMA foreign_keys=ON`，有测试守着）；
- 前端 `static/machining_dfm/issue_page.js` 接管问题清单的 10 个写入点，
  工序那一栏在落表后变成**下拉选工序行**（写 `process_id`），开关关着时仍是原来的文本框。

**外键总清单**：`tools/audit_foreign_keys.py [--with-process]` 打印所有表的外键，
并说明哪些是"真外键、但按口径用 `ON DELETE SET NULL`"的列；"故意保持软引用"那一栏现在**是空的**——项目业务数据里有关联的列**全部**是真外键（`PRAGMA foreign_key_check` 干净）：

| 列 | 指向 | 删库行时 | 怎么保住项目里的数据 |
| --- | --- | --- | --- |
| `project_processes.machine_id` | `machines.id` | `SET NULL` | `machine_snapshot` 存型号/价格；读模型的 `mid` 按快照回退 |
| `project_process_tools.tool_id` | `tools.id` | `SET NULL` | `tool_price`/`tool_life` 快照 |
| `project_process_tools.handle_id` | `tools.id` | `SET NULL` | `hld_price` 快照 |
| `project_process_tools.accessory_id` | `tools.id` | `SET NULL` | `acc_price` 快照 |
| `project_fixtures.fixture_id` | `fixtures.id` | `SET NULL` | `price_snapshot`/`days_snapshot` 快照 |
| `project_fixtures.fixture_center` | `fixture_centers.name` | `SET NULL` | 字典用名字做主键；字典删掉这一格就不再出报价表，行留着当历史 |
| `project_gauges.gauge_id` | `gauges.id` | `SET NULL` | 同上（检具库） |
| `project_gauges.gauge_category` | `gauge_categories.name` | `SET NULL` | 同上（检具类别字典） |
| `project_versions.project_id` | `projects.id` | NO ACTION | 版本履历必挂在项目上（3a：本表没有别的引用列） |
| `project_changes.project_id` | `projects.id` | NO ACTION | 变更流水必挂在项目上（3b） |
| `project_changes.version_id` | `project_versions.id` | `SET NULL` | 这一条流水属于哪一次保存（就是那一版的快照） |
| `project_changes.process_row_id` | `project_processes.id` | `SET NULL` | 被改的工序行 |
| `project_changes.tool_row_id` | `project_process_tools.id` | `SET NULL` | 被改的工序刀具行 |
| `project_changes.issue_row_id` | `project_issues.id` | `SET NULL` | 被改的问题清单行 |
| `project_changes.fixture_row_id` | `project_fixtures.id` | `SET NULL` | 被改的夹具格子 |
| `project_changes.gauge_row_id` | `project_gauges.id` | `SET NULL` | 被改的检具格子 |
| `project_changes.selection_row_id` | —（老库上是 `project_selections.id`） | — | **历史遗留列**：拆表后新库不建那张老表，所以这一列只是可空列、不建外键（否则整张流水表插不进去）；老库上的外键留着不碍事 |
| `project_changes.history_row_id` | `project_versions.id` | `SET NULL` | 被改的版本履历行（与 `version_id` 指同一张表，语义不同） |

（这几列同时是"页面字段"：`mid`/`hld_id`/`acc_id` 是它们的键名，接口两边都认——
`mid` 与 `machine_id` 写哪个都行，库里存的是列。`project_processes.process_id`、
`project_issues.process_id`、`project_fixtures.project_id`、`project_gauges.project_id`、`project_versions.project_id`
这些是纯外键列（页面上没有对应的输入框），读模型里给 `None`，不硬套空串。）

共享库重建时的注意点：基础库迁移用"改名 → 建同名新表 → 搬数据 → 删旧表"，
`ALTER TABLE … RENAME` 默认会**改写子表里指向它的外键**，所以改名那一步包在
`_rename_compat()`（`PRAGMA legacy_alter_table=ON`）里，改名只改名。

## 选型落表（2b：夹具 `project_fixtures` / 检具 `project_gauges`，线上级别 5 已打开）

> **2026-09-18 结构再调整**：选型本来是**一张多态表** `project_selections`（用 `kind` 区分夹具格/检具格），
> 现在拆成**两张项目级表**：`project_fixtures`（夹具选型）与 `project_gauges`（检具选型）。
> 原因与迁移见 `docs/MACHINING_REFACTOR_ACCEPTANCE.md` 第六节；老表只当搬迁来源保留。

> **口径 7（新建项目也要落表）**：`POST /projects`（页面上是「新建」与「另存为新项目」）> 带过来的整份读模型**直接拆进各域的表**（`create(..., import_tables=True)` / `store.import_state()`），
> 拆完 `projects.state_json` 是 `{}`。改之前这条路只写 JSON、业务表一行不建 ——
> 于是副本项目永远"JSON 满、表空"：读模型看着有工序，`GET /projects/{id}/processes` 却是 0 行，
> 页面上那些行**没有行 id**，行级保存无从下手。
> 逐域幂等（表里有行就跳过那一域），某一域拆不动就**整域回退**到 JSON（先把这一域这次建的行删掉），
> 绝不出现"一半在表、一半在 JSON"。已经存在的这种项目用 `tools/catchup_project_tables.py` 补迁。

`app/machining_selection.py` 把"夹具报价选型 / 检具报价选型"那两张表落库。
口径与 1b/2a 一致（行级读写、逻辑删除 + 回收站、每次写留版本快照、派生字段不落库）。
**一行 = 一个格子**：`(类别, 该类别在字典里的下标)`；一个类别一格，**未选型的格子也有行**
（因为"是否报价"的勾选就存在这一行上，线上现在夹具 4 + 检具 5 = 9 格全都有值）。

外键同样是**真的**（用户要求"有关联的数据结构全部使用外键约束"），**每张表只指向自己那一类**：

| 表 | 列 | 指向 | ON DELETE | 说明 |
| --- | --- | --- | --- | --- |
| 两张 | `project_id` | `projects(id)` | NO ACTION | 必填 |
| `project_fixtures` | `fixture_center` | `fixture_centers(name)` | SET NULL | 夹具格子的类别（字典用名字做主键） |
| `project_fixtures` | `fixture_id` | `fixtures(id)` | SET NULL | 选中的夹具行 |
| `project_gauges` | `gauge_category` | `gauge_categories(name)` | SET NULL | 检具格子的类别 |
| `project_gauges` | `gauge_id` | `gauges(id)` | SET NULL | 选中的检具行 |

两张表**都没有 `kind` 列**：这一行是什么由表本身决定（拆表前靠一个字符串列区分、还要用 CHECK 挡着
"一行只挂一边"）。`quoted INTEGER CHECK (quoted IN (0,1))` 存旧的 `fixQC`/`inspQ`。
外键列都有索引；`fixtures_legacy_v1`/`gauges_legacy_v1` 那套库重建也不会把行卡住——
库行删掉时外键置空，价格/周期仍按 `price_snapshot`/`days_snapshot` 快照算（口径 4）。

顺带修掉旧结构的真缺陷：旧 `fixQ[]`/`insp[]` 存的是拼出来的字符串，**夹具库里改名之后
这一格就指向了不存在的夹具**。现在页面上选的是库里的那一行（外键），
读模型按当前库值现算字符串，改名自动跟随；`legacy_key` 列留着旧字符串，
保证迁移前后逐字节一致，也让"库里没有那条"的老值原样还回去。

**能力级别是递增的**：`project_business_version` ≥1 工序、≥2 问题清单、≥3 再加选型（拆表不新开级别）。

```
GET    /api/machining-dfm/projects/{pid}/fixtures/{slot}      # 夹具：这一格的清单（类别/下标/四个数组/行）
PUT    /api/machining-dfm/projects/{pid}/fixtures/{slot}      # 选一格 {legacy_key}（空串=清空）
PATCH  /api/machining-dfm/projects/{pid}/fixtures/{slot}      # 只改"是否报价" {quoted}
DELETE /api/machining-dfm/projects/{pid}/fixtures/{slot}      # 清空这一格（行保留、只解绑）
# gauges 同形：GET|PUT|PATCH|DELETE /projects/{pid}/gauges/{slot}
GET    /api/machining-dfm/projects/{pid}/selections           # 兼容入口：两类一起读（老前端/导出用）
```

- `slot` = 该类别在字典里的下标（页面上的格子号）；
- 选错类别（这条夹具不属于这一格的中心）→ **422**；库里同名多条 → **422**（不猜，提示直接选具体行）；
  下标越界 / 开关没开 → **404 / 409**；
- 前端 `static/machining_dfm/selection_page.js` 接管 4 个写入点
  （两个选型下拉 + 两个"是否报价"勾选框，夹具走 `/fixtures`、检具走 `/gauges`），
  开关关着时一律走原来的"改内存 + 整份保存"；
- **懒迁移**：某个项目的两张表都还空、而老数据还在时，第一次写任何一格会先静音地把老数据
  整份搬进来（否则"点第一格只建那一行"，别的格子会看着空）；
- 搬迁工具：`tools/migrate_selection_split.py`（`--status` / 干跑逐字节比对 / `--apply` 先备份）。

## 图片与历史版本：库里只存引用（口径：快照永久保留，回滚图也得在）

* **整份保存里的内联图先落成附件再做快照**：`MachiningDFMStore._materialise_inline_images()`
  在 `create()` / `update()` 落库前，把整份 state 里任何 `data:image/…;base64,…` 换成附件地址
  （按所在键决定附件分类）。否则页面上传的那张图会被写进**永久保留**的版本快照里。
* **快照引用着的附件不许回收**：`app/machining_library.py::asset_in_snapshots()` ——
  "换图"时判定图片还有没有人用，除了扫指向 `assets(id)` 的外键列，还要看
  `project_versions.state_json` 里有没有这个附件 URL。快照永久保留（口径 1）→ 旧图也永久保留。
  （老代码没这一步：线上的第 17/18/22/26/30/34/38/40 版因此成了死链，字节不可恢复；
  `tools/check_export_assets.mjs` 把这 7 个按已知清单单列，清单外的新死链一律失败。）
* 巡检工具：`tools/slim_version_snapshots.py`（**按值认**内联图，不按写死的键名清单；
  `--status` / 干跑 / `--apply` 先备份 + sha256 逐张核对）。

## 版本履历落表（3a：`project_versions`，代码已就位，开关默认关）

`app/machining_history.py` 把**两套互不相干**的"版本"合并进一张表，用 `kind` 分开：

| kind | 是什么 | 旧形态 | 谁在写 |
| --- | --- | --- | --- |
| `save` | 一次保存一份全量快照（`revision` = 当时的项目版本号） | 旧 `revisions` 表（已随旧副本清掉） | 每一次保存（含每个行级写入点） |
| `history` | 页面上「版本变更履历」的一行（`revision` 固定 0 = 哨兵） | `projects.state_json.vh[]`（`{dt,ver,ds,by}`） | 四个手填格子 + `addVH()` + `delVH()` + 客户版本切换的 `verRec()` |

口径与 1b/2a/2b 一致：行级读写、逻辑删除 + 回收站、每次写都递增项目版本并留版本快照、
派生字段不落库。关联列同样是**真外键**：

| 列 | 指向 | ON DELETE | 说明 |
| --- | --- | --- | --- |
| `project_id` | `projects(id)` | NO ACTION | 本表唯一的关联列（`ver/dt/ds/by` 是用户填的文本，不是引用） |

四条 `CHECK` 把两种行的语义钉死：`kind` 只能是 `save`/`history`；`save` 必须 `revision > 0`
且快照非空（**不许凭空造一个空版本**）；`history` 必须 `revision = 0` 且不带快照。

读模型 `vh[]` **逐字节不变**（含键序）：

- `compose_history()` 只输出旧四键，逻辑删除的行不进读模型；
- **表的权威信号是"有没有履历行"**，不是"表里有没有行"——开关一打开应用每次保存都会写 `save` 行，
  "有行"根本不代表履历已经迁过。没有履历行 → 回退 `state_json.vh`（与 `pr`/`is` 同一套规则）；
- `?revision=N` 的历史版本**只用那一版快照里的 `vh`**，不会被现在这张表覆盖（`historical=True`）；
- **兜底**：表里还没履历行时 `GET /history` 返回一份只读"影子清单"（`materialized: false`，
  id = `<项目 id>-h<下标>`），页面第一次改/删/加时服务端拿 `state_json.vh` **就地补建成真行**
  （id 与影子清单一致）——页面永远不用等迁移。

保存版本只写这一张表。**开关 < 4** 时（旧路径仍是权威、迁移工具还没跑）才额外写一份旧
`revisions` 影子副本，让"删掉版本键"就能回滚：

```
db.execute("INSERT INTO revisions(...) VALUES(?,?,?,?,?)", (..., payload, stamp))  # 仅开关 < 4
if self.history_enabled:
    insert_save_row(db, project_id, revision, name, payload, stamp)   # 同一串 payload
```

**开关 ≥ 4 之后 `revisions` 不建也不写**（口径 6：哪一级落表了，那一级的影子副本停写），
`projects.state_json` 里的 `pr`/`is`/`vh` 也在表能还原出那一份时被清掉——
同一份数据在库里只存一处。代价是**回滚从"删一个版本键"变成"从备份恢复"**，
所以每次迁移/清理都先整库备份（见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md` 第 14 节）。

```
GET    /api/machining-dfm/projects/{pid}/history                     # 履历清单（recycle=true 给回收站）
POST   /api/machining-dfm/projects/{pid}/history                     # 新增一行（缺的键补空串）
PATCH  /api/machining-dfm/projects/{pid}/history/{id}                # 只改提交上来的格子
DELETE /api/machining-dfm/projects/{pid}/history/{id}?by=&reason=    # 逻辑删除（进回收站，可恢复）
POST   /api/machining-dfm/projects/{pid}/history/{id}/restore        # 从回收站恢复
POST   /api/machining-dfm/projects/{pid}/history/reorder             # 重排（{"ids": [...]}）
```

- `PATCH` 只认 `dt/ver/ds/by`，其它键进 `extra_json` 兜底列（**不丢数据**）；
  未落表时也认"只给下标"（`{"index": 2, ...}`），按当前清单换算成 id，越界 → **409**（不猜）；
- 已删除的行再改 → **410**；跨项目的行 → **404**；开关没开 → **409**；
- 前端 `static/machining_dfm/history_page.js` 接管 7 个写入点
  （四个格子 + 新增 + 删除 + 客户版本切换自动追加），开关关着时一律走原来的"改内存 + 整份保存"；
- `reorder` 只动 `kind='history'` 的行，保存版本的 `sort_order`（存的是版本号）一根都不动。

**能力级别是递增的**：`project_business_version` ≥1 工序、≥2 问题清单、≥3 选型报价、**≥4 版本履历**。

## 变更流水落表（3b：`project_changes`，代码已就位，开关默认关）

`app/machining_changes.py` 把"**谁、什么时候、把哪一行、从什么改成什么**"记成一行流水。
流水**不是页面上某个按钮触发的**，而是**行级写入的副产物**：页面上改了哪一行，服务端就在
**同一个事务**里记一条（和这一版的快照一起提交）——所以这一阶段前端**一个写入点都没加**，
反而"前端零写入点"变成了验收项（界面留到阶段 4 与回收站一起做）。

| 列 | 指向 | ON DELETE | 说明 |
| --- | --- | --- | --- |
| `project_id` | `projects(id)` | NO ACTION | 必填 |
| `version_id` | `project_versions(id)` | SET NULL | 这一条流水属于"这一次保存"的那一版 |
| `process_row_id` | `project_processes(id)` | SET NULL | 被改的那一行（按实体六选一） |
| `tool_row_id` | `project_process_tools(id)` | SET NULL | 同上 |
| `issue_row_id` | `project_issues(id)` | SET NULL | 同上 |
| `fixture_row_id` | `project_fixtures(id)` | SET NULL | 被改的夹具格子（选型拆表后：夹具走这一列） |
| `gauge_row_id` | `project_gauges(id)` | SET NULL | 被改的检具格子（同一实体名 `selection`，靠 `extra_json.kind` 决定挂哪一列） |
| `selection_row_id` | —（老库上指向已废弃的 `project_selections(id)`） | — | **历史遗留列**：新库不建那张老表，所以这列可空、不建外键；老库上的外键留着不碍事 |
| `history_row_id` | `project_versions(id)` | SET NULL | 被改的版本履历行（与 `version_id` 同表、语义不同） |

- `entity` 七种：`project` 项目 / `settings` 项目信息 / `process` 工序 / `tool` 工序刀具行 /
  `issue` 问题清单 / `selection` 选型报价 / `history` 版本履历；`action` 七种：`create`/`update`/
  `delete`/`restore`/`reorder`/`photo`/`save`（整份保存）；
- `CHECK` 保证**最多挂一个行外键、而且必须与 `entity` 对应**（`project`/`settings` 一列都不挂）。
  写成"最多一个 + 必须对应"而不是"恰好一个"，是因为这五列都是 `ON DELETE SET NULL`：
  目标行被物理删掉时列会被置空，那种状态必须仍然是合法行（`label` 里仍写着改的是谁）；
- `label` 是给人看的一句话（"工序 OP10 精铣：设备台数 1→3；设备 Alpha A1→（空）"），
  结构化明细（`[{key,label,before,after}]`）存在 `extra_json.fields` 里，界面要用不用再解析这句话；
- **记什么**：每个行级写入点（含级联删除/恢复逐行记、换图、排序、选型格子、履历、项目信息、整份保存）；
  **不记**：什么都没改的保存（"失焦即保存"会发很多次）、被拒的写入（422/409/410/404，事务里没有草稿）、
  系统自己补建老履历（`_quiet_changes()` 静音）、以及**开关打开之前发生过的改动**（不追溯，回填等于编造历史）；
- **只读接口**（没有写接口，流水是追加型日志）：

```
GET /api/machining-dfm/projects/{pid}/changes?limit=200&entity=&action=&recycle=false
```

- 没打开开关时接口给 **409** 并告诉你跑哪个工具；读模型里 `changes_table=false`。
  详细口径见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md`（含与设计文档的 3 处差异说明）。

**能力级别是递增的**：`project_business_version` ≥1 工序、≥2 问题清单、≥3 选型报价、≥4 版本履历、**≥5 变更流水**。

## 工序落表（1b）迁移

工序数据默认仍存在 `projects.state_json.pr` 里；要切到独立表
（`project_processes` / `project_process_tools`），用迁移工具切——**默认干跑，只有 `--apply` 才动线上库**：

```powershell
.venv\Scripts\python.exe tools\migrate_project_processes.py --status   # 只读：现在迁到哪一步
.venv\Scripts\python.exe tools\migrate_project_processes.py            # 干跑（整库复制到临时目录，跑完删掉）
.venv\Scripts\python.exe tools\migrate_project_processes.py --apply    # 真迁移：先备份、再归档、再拆表、最后写开关
.venv\Scripts\python.exe tools\live_process_e2e.py                     # 迁完对着运行中的服务验"表↔读模型"

# 阶段 3a（版本履历）是单独一份工具：前置 = 1b/2a/2b 已迁完（版本键 ≥ 3）
.venv\Scripts\python.exe tools\migrate_project_versions.py --status    # 只读：版本键/表/行数
.venv\Scripts\python.exe tools\migrate_project_versions.py             # 干跑（前置没迁会先在副本上补跑，覆盖 0 → 4）
.venv\Scripts\python.exe tools\migrate_project_versions.py --apply     # 真迁移（先整库备份，最后写版本键 = 4）

# 阶段 3b（变更流水）也是单独一份工具：前置 = 3a 已迁完（版本键 ≥ 4）
.venv\Scripts\python.exe tools\migrate_project_changes.py --status     # 只读：版本键/表/流水行数/实体分布
.venv\Scripts\python.exe tools\migrate_project_changes.py              # 干跑（副本上建表 + 写键 + 真写几笔验证流水）
.venv\Scripts\python.exe tools\migrate_project_changes.py --apply      # 真迁移（先整库备份；只建表 + 写版本键 = 5）
```

> 3b **不搬旧数据**：流水从打开开关那一刻开始记（不无中生有）。所以 `--apply` 在线上只做两件事
> ——建表、写 `project_business_version = 5`；那几笔"真写进去看流水对不对"的探针**只在干跑副本上跑**。
> 回滚同样只是把版本键改回 4。

**线上已经迁完了（2026-09-18，级别 0 → 5）**：三份工具按顺序 `--apply`，每份先整库备份，
库从 20 张表变成 27 张。迁移前后用 HTTP 各抓一次读模型：`G`/`pr`/`is`/`vh` 四段**逐字节相同**
（含键序），`tools/capture_process_cost_baseline.py --check`（报价数字）与
`tools/live_report_snapshot_check.py`（报表契约）都是绿的，页面冒烟在开关打开的状态下也全绿。
变更流水是 **0 行**——第一条流水来自开关打开之后的第一次真实改动。
逐项证据与三个"迁移当天才发现"的工具问题见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md` 第 13 节。

**旧副本也清掉了（同一天，口径 6）**：迁移之后每种数据都有两份（表 + 回滚副本），
所以加了"哪一级落表了，那一级的影子副本就停写"这条规则，
并用 `tools/clean_legacy_project_data.py --apply` 把旧副本表（`revisions`、五张 `*_legacy_v1`、
设备库旧壳 `equipment`）+ `projects.state_json` 里的 `pr`/`is`/`vh` 一次清干净：
**27 → 19 张表、8.05 MB → 1.43 MB**，读模型逐字节不变，之后再保存 8 次副本也没长回来。
历史快照里那 16 份内联的同一张产品图，用 `tools/slim_version_snapshots.py --apply`
抽成了附件引用（947 KB → 0，图片 sha256 逐一核对相同）。**回滚路径从此是从备份恢复**
（`backups/pre-clean-legacy-<时间戳>.sqlite3`、`pre-slim-snapshots-<时间戳>.sqlite3`）。
详见同一份文档第 14 / 14.1 节。

⚠ **清完之后别再把 `project_business_version` 往下调**：级别 < 4 的读路径只认
`projects.state_json`，而它已经是 `{}`，页面会变空（数据在表里，只是这一档不读）。
`tools/check_business_gate.py` 会把这种情况报成不一致并提示"调回级别或从备份恢复"。
清完之后的库结构（19 张表 / 40 个外键列 / 还剩多少 JSON / 怎么复查）见 `docs/MACHINING_DB_STRUCTURE.md`。

- 备份落在 `data/machining_dfm/backups/pre-project-business-<时间戳>.sqlite3`
  （3a 是 `pre-project-versions-<时间戳>.sqlite3`，3b 是 `pre-project-changes-<时间戳>.sqlite3`，
  清旧副本是 `pre-clean-legacy-<时间戳>.sqlite3`）；
- 迁移前的 `state_json` 归档进 `processes_legacy_v1`；
- 开关是 `app_settings.project_business_version`（**最后一步**才写）：3 = 1b 工序 + 2a 问题清单 +
  2b 选型报价一次做完；4 = 再加 3a 版本履历（`migrate_project_versions.py` 单独写）；
  5 = 再加 3b 变更流水（`migrate_project_changes.py` 单独写）；
  `router_for` 每个请求都新造 store，构造时现读这个键 → **不用重启服务，下一个请求就切到表**；
- **回滚只需删掉/调小这个键**：`state_json.pr`/`state_json.is`/`state_json.vh` 与
  `project_settings.extra_json` 里那四个选型数组迁移时原样不动，
  3a 迁移时把每次保存同时写进 `revisions`（影子副本），所以调回 3 读模型能立刻回到旧路径；
**开关 ≥ 4 之后这条影子路已经停写、旧副本也清掉了**（口径 6，见第 14 节），
现在回滚靠备份；
  只是工序/问题清单/选型/版本履历接口会重新返回 409；3b 调回 4 只是不再记流水（表留着不碍事）；
- 开关关着时工序接口返回 409、`get(pid)["process_table"]` 为 `false`，前端自动退回旧路径——
  所以**代码可以先上线、数据晚点再迁**；
- 迁移的验证项里选型四个数组也是逐字节核对的：`√ 选型四个数组与迁移前一致（105 字节，含键序）`、
  `√ 只凭选型表就能完整还原选型与报价勾选`、`√ （副本上）把 extra_json 里的四个旧数组清掉后读模型依旧`；
  3a 的验证项见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3.md` 第 7 节（保存版本列表一致、
  每份快照与旧 `revisions` 逐字节相同（3a 迁移当天）、`vh[]` 逐字节相同、外键体检干净）；
  3b 的验证项见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md` 第 9 节（七个真外键、读模型逐字节相同、
  流水 0 → 0 不追溯、功能探针 18 笔写入逐条核对、被拒写入不留痕）；
  清旧副本的验证项见同一份文档第 14 节（读模型逐字节不变、业务表行数不变、接口 200、
  `foreign_key_check`/`integrity_check` 干净、再保存一次副本也不长回来）。

## 基础库拆分（设备库、刀具库、夹具库、检具库已落地）

四个库都不再整库存成一个 JSON 字段，也不再整表覆盖保存；
它们共用 `app/machining_library.py` 的引擎（字段登记表 → 建表 SQL / 校验 / 两套视图 / 附件 / 迁移）：

- **表结构**：`machines` 一行一台设备，字段按页面列一一对应（`brand/model/xyz/pos_acc/rep_acc/
  rapid/tool_change/spindle_rpm/atc/price/remark`），登记表在 `app/machining_machines.py::MACHINE_FIELDS`；
  `tools` 一行一件刀具（`tool_group/name/category/diameter/length/spindle_rpm/feed_rate/life_minutes/price`），
  登记表在 `app/machining_tools.py::TOOL_FIELDS`；页面自动列 `fz`/`vc` 只描述不入库；
  `fixtures` 一行一套夹具（`center/name/price/process_days/remark`，登记表 `app/machining_fixtures.py`）、
  `gauges` 一行一套检具（`category/name/drawing/product_size/inspection_size/price/design_days/process_days`，
  登记表 `app/machining_gauges.py`），键名仍是页面与成本表惯用的短键
  （`center/mc/rmk`、`type/drw/prdSize/inspSize/price/dc/mc`）；
- **字典表**：刀具的库分类与类型是两张独立表 `tool_groups` / `tool_categories`，
  `tools` 用文本码外键引用（`tool_group → tool_groups.code`、`category → tool_categories.code`），
  改名只动 `label`；夹具的模具中心（`fixture_centers`）与检具的检具类别（`gauge_categories`）
  也是独立字典表，外键直接用**中文名**（项目里 `G.fixQ`/`G.insp` 就是按名字拼的选择键，
  因此类别不可改名、只能新增/删除）；`.choices` 由字典表实时提供；
- **附件**：图片与资料存磁盘 `data/machining_dfm/assets/<kind>/<sha 前两位>/<sha><ext>`，
  数据库 `assets` 表只存 `kind/mime/name/size/sha256/path`，按 `(kind,sha256,name)` 去重
  （类别：`machine_photo/machine_doc/tool_photo/fixture_photo/gauge_photo`）；
- **项目数据**：项目快照里只存工序 → 设备 id（`pr[].mid`），旧的下标 `mi` 在读写两端自动双向兼容；
  刀具/夹具/检具按名称被成本表引用，不存下标，排序/删除不会错位；
  PPT 快照会把图片内联成 data URL，模板中的 `mdb_*_img_*` 图片槽位保持不变；
- **迁移**：旧库首次启动自动把 `equipment.payload_json`、`tools/fixtures/gauges.payload_json`
  （含 base64 图片）搬进类型化表与磁盘，原表留档为 `*_legacy_v1`；
  刀具库随后再走一步"分类拆表"迁移（重建 `tools` 以加上两条字典外键，旧分类码归一化、
  未知码补录进类型表），夹具/检具库走"建字典表 + 转列"迁移；备份到
  `backups/pre-typed-machines.sqlite3`、`pre-typed-tools.sqlite3`、`pre-tool-dictionaries.sqlite3`、
  `pre-typed-fixtures.sqlite3`、`pre-typed-gauges.sqlite3`，重复启动幂等；
- **兼容层**：`PUT /libraries` 只保留给缓存了旧 JS 的页面，语义固定为**只增改不删**
  （旧语义"提交里没有就删"实测一次就删掉了 177 条夹具 + 437 条检具，
  删除现在只走行级 `DELETE /{库}/{id}`）；误删可用 `tools/restore_fixture_gauge.py`
  按 `*_legacy_v1` 归档重放迁移恢复。

详见 `docs/MACHINING_LIBRARY_REFACTOR.md`。

## 与其它服务的关系

- 机加表单**不导入**压铸表单或 PPT 工作台的代码；跨服务只通过 HTTP：
  - 表单页「进入 PPT 工作台」→ `/api/integration/workbench-link` 返回工作台地址；
  - PPT 工作台通过 `/api/ppt-provider/v1/sources/machining-dfm/projects/{id}/snapshot` 拉取项目快照与字段目录。
- 三服务架构与契约说明见 `docs/SERVICE_ARCHITECTURE.md`；同系列分支：
  `hpdc`（压铸表单服务，8001）、`workbench`（通用 PPT 工作台，8003）、`New`（三服务合集 + 统一网关）。
