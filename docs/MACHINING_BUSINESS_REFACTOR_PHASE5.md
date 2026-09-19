# 阶段 5：附件归项目（`cI`/`bI`/`aI`）+ 导出/PPT 回归

> 口径来自 `docs/MACHINING_BUSINESS_REFACTOR.md` 第 8 节：
> "附件归项目（`cI/bI/aI`）+ 导出/PPT 回归"，验收 = **`state_json` 体积降到几 KB**、**PPT/JSON 导出图片正常**。

## 1. 结论先说

这一阶段的靶子在阶段 1b / 2a / 2b 里**已经顺带打中了**：图片早已是"一个附件行 + 一个真外键"，
数据库里**一行内联 base64 都没有**，`projects.state_json` 只剩 2 个字符。
阶段 5 因此**不搬家、不改结构**，做的是两件事：

1. **把验收钉住**：新增常驻无头自检 `tools/check_export_assets.mjs`（见第 4 节），
   把"读模型给引用、导出时才内联、库里不许有 base64"变成每次都能跑一遍的检查；
2. **把导出链路写清楚**（第 3 节），免得以后有人以为导出还需要库里有 base64。

## 2. 实测现状（2026-09-18，线上库）

| 项目 | 实测 |
| --- | --- |
| `projects.state_json` | **2 字符**（`{}`）—— 业务数据全部落表，影子副本已停写（口径 6） |
| 项目四张图 | `project_settings.product_photo_id` / `product2_photo_id` / `blank_insp_photo_id` / `final_insp_photo_id` → `assets.id` |
| 工序夹具示意图（旧 `cI`） | `project_processes.fixture_photo_id` → `assets.id` |
| 问题清单优化前/后（旧 `bI`/`aI`） | `project_issues.before_photo_id` / `after_photo_id` → `assets.id` |
| 库图片/资料 | `machines.photo_id`/`doc_id`、`tools.photo_id`、`fixtures.photo_id`、`gauges.photo_id` → `assets.id` |
| `assets` 表 | **17 行**（`machine_photo` 16 + `project_photo` 1）；列 `id/kind/mime/name/size/sha256/path/created` |
| 文件 | `data/machining_dfm/assets/<kind>/<sha 前 2 位>/<sha>.<ext>`，**17 个文件 / 244.6 KB** |
| 行 ↔ 文件 | **一一对上**：有行没文件 0，有文件没行 0 |
| 引用是否悬空 | 项目与库共 **18 个引用，悬空 0**（真外键兜住了） |
| 库里有没有内联图 | 19 张表所有文本列扫 `data:image` → **0 行** |
| 唯一的大文本 | `project_versions.state_json`：87 份、最长 6734 字符、合计约 549 KB（是**读模型快照**，不含 base64） |

**交叉验证（同一时刻两边数出来的）**：库里 18 个附件引用 = 读模型里 18 个
`/api/machining-dfm/assets/<id>` URL（项目产品图挂在 `G.pI`，16 张设备图挂在库行 `img`）。
附件接口 `GET /api/machining-dfm/assets/{id}` 正常返回图片；不存在的 id 返回
`404 {"detail":"附件不存在"}`。
（读模型整体约 320 KB —— 那是四个基础库全量内联的结果，跟"库里存不存 base64"是两件事。）

## 3. 导出链路（PPT / JSON 备份 / 便携 HTML）

1. **库里只有引用**：读模型（`GET /projects/{pid}`、`/bootstrap`）里这些字段给的是
   `/api/machining-dfm/assets/<id>` 这样的服务端 URL；
2. **导出前一次性内联**：`static/machining_dfm/legacy_app.js` 的 `inlineSheetImages()`
   （注释在文件第 42–43 行附近）把读模型里的图片 URL 统一换成 data URL，
   `exportHTML()` / `exportJSON()` / PPT 导出都先走它 —— 所以**导出的文件离线也能显示图片**，
   而库里始终不存 base64；
3. **服务端留了一个内联开关**：`libraries(inline_assets=True)` / `compose(..., inline_assets=True)` /
   `defaults(inline_assets=True)`，需要"一份自带图片的整包数据"时可用（老导出路径兼容用），
   日常读写走默认 `False`（给 URL）。

## 4. 验收动作

```powershell
node tools\check_export_assets.mjs        # 阶段 5 新增：引用/取图/导出内联/库里无 base64
node tools\smoke_machining_page.mjs       # 整页冒烟（导出按钮所在页面没退化）
node tools\check_trash_page.mjs           # 阶段 4 的两条界面自检
node tools\check_tools_page.mjs
node tools\check_fixture_gauge_page.mjs
.venv\Scripts\python.exe -m pytest tests -q
```

## 5. 导出链路实测抓到的缺口（已修）

**`inlineSheetImages()` 漏了四个来源**：它原来只内联 `MDB[].img`（设备库）、`FDB[].img`（夹具库）、
`PR[].cI`（工序夹具示意图）和 `G.pI / bInspImg / fInspImg` 三张项目图，**没有**：

| 漏掉的 | 现在的字段 |
| --- | --- |
| 刀具库图片 | `TDB[].img` |
| 检具库图片 | `IDB[].img` |
| 产品图 2 | `G.pf`（`project_settings.product2_photo_id`） |
| 问题清单优化前/后 | `IS[].bI` / `IS[].aI`（`project_issues.before/after_photo_id`） |

线上此刻只有设备图（`machines.photo_id` 17 个引用）与 1 张项目产品图，所以**没暴露**；
但只要有人上传刀具图、检具图、第二张产品图或问题清单图片，导出出去的 PPT / JSON 备份 / 便携 HTML
里那些图就会变成裂图（导出文件是离线打开的，加载不到 `/api/...` 的相对地址）。

已在 `static/machining_dfm/legacy_app.js` 的 `inlineSheetImages()` 里补齐为：
四个库（`MDB/TDB/FDB/IDB`）+ 项目四张图（`pI/pf/bInspImg/fInspImg`）+ 工序 `cI` + 问题 `bI/aI` 全覆盖。
改完 `smoke_machining_page.mjs`、`check_trash_page.mjs`、`check_tools_page.mjs`、
`check_fixture_gauge_page.mjs`、`check_host_css.py` 全绿。

> 教训：这类"导出才内联"的路径，字段一旦落表/改名就很容易漏；所以第 4 节的常驻自检里
> 专门有一条扫"读模型里所有 `/api/machining-dfm/assets/` 字段是否都能被内联覆盖"。

## 6. 验收结果（2026-09-18 实测）

`node tools\check_export_assets.mjs` → **87 条全绿**（exit 0），五组：
读模型两份（`bootstrap` 与 `/projects/{pid}`）扫 `data:image` / `;base64,` **各 0 处**、18 个附件引用形状都对；
**17 个引用逐个真 GET 全部 200 + `image/*` + 有字节**，未知 id → `404 附件不存在`；
vm 沙箱里真跑整页导出（`exportData()` / `writeDataFile()`）：入口自己打出 17 个全 GET 的 `/assets/`、
读模型**就地**变成 `data:`、产出的 JSON 备份 584751 字符**含内联图、不含 `/assets/`**、**全程零写请求**；
只读打开 SQLite（试写被库挡住，有证明）扫 19 张表 `data:image` **0 行**、
`assets` 17 行 244.6 KB 与磁盘 17 个文件**一一对上**、13 个 `assets(id)` 外键列 18 个引用**零悬空**；
以及一条**前向哨兵**：读模型里每一条 `/assets/` 字段路径都必须能被 `inlineSheetImages()` 覆盖 ——
将来谁加了新图片字段却忘了加进内联，这条立刻红（正是本轮 §5 那个缺口的成因）。

## 7. 已知残留

### 7.0 用户拍板（2026-09-18）：不做单文件 HTML，改成「导出 JSON + 导出文件包」

> 用户答复原文：**"导出json和文件包"**

也就是把 `saveAll/saveAs` 那条"便携单文件 HTML"的承诺**换成两条能兑现的导出**：

1. **导出 JSON**（现有 `exportData()` 已经能用：读模型带内联图，584751 字符实测通过，离线打开图片也在）；
2. **导出文件包**：一个归档包，里面放 `project.json`（读模型）+ 它真正用到的图片文件
   （`assets/<id>.<ext>`），适合存档、发给别人、以后再导入。

实施要点（下一步做）：
* **服务端出包**（推荐，别在前端手写 zip）：新增
  `GET /api/machining-dfm/projects/{pid}/export.zip`，用 Python `zipfile` 打包
  `project.json`（读模型，图片按包内相对路径引用）+ 该项目引用到的 `assets/*` 原始文件；
  只读、按需生成、不落库、不写 `data/`（附件本来就是项目附件，口径 5）。
* **前端**：`saveAll()`/`saveAs()`（`legacy_app.js:183-184`，按钮在 `:406` 与
  `:520` 的"数据保存与导出 / Save & Export"卡片里）改成调这两条；
  `buildPortableHTML()`/`dlPortable()`/`writeDataFile()`/`DATA_MARKER` 那一套**退休**
  （或保留函数但不再挂按钮），`host.js:85` 把 `window.exportHTML` 指到 `exportData` 的临时接线同时清理。
* **验收**：`tools/check_export_assets.mjs` 里"按当前实际行为写死"的两条（`host.js:85` 接线、
  `writeDataFile` 回调 `no`）要同步改；再补两条：导出包里 `project.json` + 图片齐全、包内路径能对上；
  全程只读、零写请求。
* PPT 导出（`exportDFM`）与 JSON 导出本轮已实测通过，**不受影响**。

#### 7.0.1 已实施（2026-09-18，本文档随本次改造更新）

**接口形状**（新增 1 条路由，`app/machining_dfm.py`，112 → 113 条）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/machining-dfm/projects/{project_id}/export.zip` | 导出文件包：**只读**、按需生成、不落库、不写 `data/`。响应 `application/zip` + `Content-Disposition: attachment; filename="DFM_<项目名>.zip"; filename*=UTF-8''…`（中文项目名走 RFC 5987 的 `filename*`，ASCII 兜底名里非法字符 `\/:*?"<>|` 与控制字符都换成 `_`）。项目不存在 → `404 机加 DFM 项目不存在`；项目已删除（`archived`）**照旧能出包**（与 `GET /projects/{pid}?allow_archived=true` 同一口径：数据还在就给）；一个附件都取不到时照样出包（不写空的 `assets/` 条目）。实现落在 `MachiningDFMStore.export_package()`（`(建议文件名, zip 字节)`） |

**包结构**（口径定死，不自创，共三类条目）：

* `project.json` —— 与 `GET /api/machining-dfm/projects/{pid}` **同一份形状**的读模型（顶层键一个不多一个不少），
  只是每个指向附件的字段值从 `/api/machining-dfm/assets/<id>` 换成包内相对路径 `assets/<id>.<ext>`
  （`ext` 先取 `assets.path` 的后缀、取不到再用 `mime` 推，最后兜底 `.bin`）；另加顶层说明块
  `_export` = `{"format":"machining-dfm-package","version":1,"project_id":…,"revision":…,"exported":…,"assets":<包内附件个数>}`。
  覆盖范围与"导出前内联"同一套字段（`mdb/tdb/fdb/idb` 行的 `img`/`doc`、`G.pI/pf/bInspImg/fInspImg`、
  `pr[].cI`、`is[].bI/aI`）—— 走的是**同一份读模型**递归替换，将来加字段不会漏。
* `assets/<id>.<ext>` —— 该项目读模型里**真正引用到**的附件原始文件，字节与磁盘一致；
  没被引用的、别的项目引用的、以及没人引用的孤儿附件都不打包。
* `README.txt` —— UTF-8，五行说明：怎么用、图片在 `assets/`、包格式与版本、
  **由哪个服务哪个版本导出**（机加 DFM 项目工作台 `app/services/machining.py`）、导出只读。

**前端两条入口**（`static/machining_dfm/legacy_app.js`，「项目信息」与「数据保存与导出 / Save & Export」
**两张卡片上都有**，文案写明区别）：

* 「导出 JSON（单文件·图内联）」→ `exportData()`：一个 `.json`，图片内联在里面，离线有图、便于再导入；
* 「导出文件包(.zip)」→ 新函数 `exportPackage()`：`fetch` 一个 GET 打服务端新接口，文件名取服务端
  `Content-Disposition`（`DFM_<项目名>.zip`），**不内联图片、不保存、不改任何数据**，取的是服务端当前已保存的版本。

**退休清单**（不留半死不活的接线）：`legacy_app.js` 里 `buildPortableHTML()` / `writeDataFile()` /
`dlPortable()` / `fhName()` / `exportHTML()` / `_fh` 与 `saveAll()`/`saveAs()` 的单文件实现全删；
`host.js` 里 `window.exportHTML = window.exportData` 那行临时接线删除（**不再导出 `exportHTML`**，
不留名不副实的别名）；两张卡片里的「保存/另存为」按钮**换成上面两条导出**。
`tools/process_wiring.py` 的 `HISTORY_EXEMPT` 里那条"导出便携 HTML"载荷豁免随之删掉（行已不存在）。

> **换按钮带出来的一个副作用（需要用户拍板）**：卡片上原来那两个按钮是"另存为新项目"在界面上
> **唯一**的入口，换成导出以后它就没有按钮了。服务端保存本身没丢 —— 顶部「立即保存」+ 自动保存
> （`window.saveAll`）照旧；但"另存为新项目"（`window.saveAs`，`host.js` 原样保留、可在控制台调）
> 目前**没有界面入口**。要恢复只需在顶部服务端工具条（`host.js` 的 `installBar()`）里加一个
> `<button id="serverSaveAs">另存为</button>` 并绑 `saveAs`（一行改动）；本轮按"两张卡片上放这两条导出"
> 的原话做，没有自创按钮。参考：`docs/MACHINING_BUSINESS_REFACTOR_PHASE5.md` 本节 + README 的导出说明。

**验收（本次实测）**：

> 除了下面这些命令，还拿**线上数据的副本**（`data/machining_dfm` 整目录复制到临时目录，线上一个字节没动）
> 用新代码干跑了一遍真接口：`HTTP 200 application/zip`、
> `Content-Disposition: attachment; filename="DFM_Battery_Bracket.zip"; filename*=UTF-8''DFM_%E5%8E%9F…`、
> 包内 19 条 = `project.json` + `README.txt` + 17 张原图（18 处引用去重成 17 个附件），
> `project.json` 里 **0 处**残留 `/api/machining-dfm/assets/`、**0 处**包内路径找不到，
> 每个附件字节与磁盘 `assets/` 逐字节一致，`_export = {format: machining-dfm-package, version: 1,
> project_id, revision: 88, exported, assets: 17}`。干跑脚本：`%TEMP%\dfm_export_rehearsal.py`（连同数据副本，
> 可随时删）。

| 命令 | 结果 |
| --- | --- |
| `.venv\Scripts\python.exe -m pytest tests -q` | **203 项全通过**（189 → 203：新增 `tests/test_machining_export_package.py` **14 项** —— 包内**正好**三类条目、附件字节与磁盘逐字节一致、`project.json` 附件字段是包内相对路径且逐个找得到、不打包别的项目/孤儿附件、未知项目 404（中文 detail）、已删项目照旧出包、无附件照旧出包、文件名非法字符与空名兜底、**读模型导出前后逐字节不变** + `assets` 表与 `data/` 目录文件哈希前后一致（只读证明）、两次导出除时间戳外完全一致） |
| `node tools\check_export_assets.mjs` | **101 条全绿**（exit 0）：其中"便携单文件那一套已退休"8 条、"两条导出入口都在两张卡片上 + 只 GET 不写"6 条、沙箱里 `exportPackage()` 只发 1 个 GET 到新接口且零写请求、"导出 JSON 仍走 `exportData()` 并产出内联图 json"2 条；`host.js:85` 接线与 `writeDataFile 回调 === 'no'` 两条**已按新行为改写**。包内结构那组（3c）在服务重启前会**明着跳过**并说明原因（运行中的老进程返回 FastAPI 默认 404 Not Found；重启后自动生效） |
| `node tools\smoke_machining_page.mjs` / `check_trash_page.mjs` / `check_tools_page.mjs` / `check_fixture_gauge_page.mjs` | 全绿 |
| `.venv\Scripts\python.exe tools\check_process_wiring.py` / `check_served_page.py` / `check_host_css.py` | 全绿（前端资源版本号仍是统一的 `?v=trash-v1`，没有新增/改名脚本文件，所以没动版本号） |

### 7.1 便携 HTML 单文件导出（**已由「文件包」取代 —— §7.0 已实施，函数与接线全部删除**）

历史记录（这个缺口长什么样）：`static/machining_dfm/index.html` 里**没有 `<!-- DATA_MARKER -->`**，
于是 `legacy_app.js` 的 `buildPortableHTML()` 直接返回 `null` → `writeDataFile()` 回调 `no` →
`exportHTML()`/`saveAs()` 弹 `Marker not found`；而页面上**真点得到**「保存/另存为」按钮
（`saveAll()` 走的就是 `writeDataFile`），点了会说"已保存"却什么都没产出。
`docs/MACHINING_LIBRARY_REFACTOR.md:360-364` 早已把它记为既有边界；JSON 备份（`exportData`）与
PPT（`exportDFM`）不受影响。

**结论（§7.0 已实施）**：这条不再修，直接退休 —— 单文件的函数、调用点、`DATA_MARKER` 与
`host.js` 的 `window.exportHTML` 别名全部删除，取而代之的是两条能兑现的导出
（**导出 JSON**：单文件、图内联、便于导入；**导出文件包(.zip)**：`project.json` + 原图 + `README.txt`，
便于存档转发）。唯一残余是 `legacy_app.js` 的 `embMerge()`：它是"从旧单文件 HTML 读内嵌数据"的
**导入**半边，函数体第一行就是 `var raw=null;if(!raw)return;` —— 早已是立刻返回的空壳、也无人调用；
本次没动它（不在 §7.0 的退休清单里），要清可以顺手删掉。


### 7.2 版本快照体积（要动就得动口径，用户此前明确暂缓）

* **版本快照体积**：`project_versions.state_json` 每份约 6.5 KB × 87 份 ≈ 549 KB。
  它是"那一次保存时的整份读模型"，**不含图片 base64**，所以不是阶段 5 的问题；
  要进一步瘦身只能改成"首版全量 + 后续只存差异"，那是**口径 1** 的改动，用户已明确暂缓。
* **`assets` 不做回收站**：附件是内容寻址文件，删除引用后文件保留（口径 2 没有彻底删除）；
  目前没有"无引用附件"的清理工具，文件量 244 KB 级别，暂时不需要。

* **版本快照体积**：`project_versions.state_json` 每份约 6.5 KB × 87 份 ≈ 549 KB。
  它是"那一次保存时的整份读模型"，**不含图片 base64**，所以不是阶段 5 的问题；
  要进一步瘦身只能改成"首版全量 + 后续只存差异"，那是**口径 1** 的改动，用户已明确暂缓。
* **`assets` 不做回收站**：附件是内容寻址文件，删除引用后文件保留（口径 2 没有彻底删除）；
  目前没有"无引用附件"的清理工具，文件量 244 KB 级别，暂时不需要。
