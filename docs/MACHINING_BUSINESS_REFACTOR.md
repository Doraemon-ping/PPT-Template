# 机加 DFM 业务数据重构方案（项目隔离 · 版本管理 · 逻辑删除）

> 状态：**口径已确认，第一阶段（项目信息）已落地并上线**（2026-09-18）
> 上一轮：基础库（设备 / 刀具 / 夹具 / 检具 + 类别字典）已拆成独立表，行级 CRUD、附件走磁盘、迁移幂等。
> 本轮：把**项目业务数据**（工序 / 工序刀具行 / 问题清单 / 选型报价 / 项目参数）从"整份 `state_json`"里拆出来，
> 并加上**版本管理**与**逻辑删除**。
>
> 已确认口径（2026-09-18，用户拍板）：
> 1. **所有保存都留版本，且不设上限、不做节流**——原来"自动保存不留版本 + 30 分钟节流 + 上限 50 个"的建议作废；
> 2. **不允许永久删除**：不做 `?purge=1`，不做"保留期到期物理清理"；删除一律是逻辑删除，随时可恢复；
> 3. 字典/库**同名重建 = 复活原行**（并记一条审计）；
> 4. 源库被删后，项目里的选型报价**按选型当时的快照价**继续算，界面标注"来源已删除"；
> 5. 派生字段 `_ct/_vc/_vf/_fz` **不落库**（读时算）；
> 6. 要"谁改了什么"审计（`project_changes`，记录角色）；
> 7. `showFlow` 留在项目数据；`lang` 移出项目数据（写进 `app_settings` 当默认）；
> 8. 工序刀具行的 `tool_id` **可空**（允许库里没有的一次性刀具）；
> 9. 问题清单引用工序改 **`process_id` 外键**（改名不静默丢引用）。
>
> 顺手要修的三处"现状就会算错"：见**第 0.6 节**；第一阶段的落地证据见**第 10 节**。

---

## 0. 现状（实测，不是推断）

### 0.1 表与体量

| 表 | 行数 | 说明 |
|---|---|---|
| `projects` | 1 | `state_json` 65.6 KB（唯一项目：原文件集成 · 蓄电池支架） |
| `revisions` | 15 | **每次保存整份快照**，合计 1.0 MB |
| `machines` / `tools` / `fixtures` / `gauges` | 27 / 761 / 177 / 437 | 共享库（已拆分） |
| `tool_groups` / `tool_categories` / `fixture_centers` / `gauge_categories` | 4 / 49 / 4 / 5 | 类别字典 |
| `assets` | 16 | 只服务基础库图片 |
| `app_settings` | 11 | 迁移版本键 |

**没有任何表带 `deleted_at` / `archived` / `is_deleted` 字段**——除了 `projects.archived`（项目"删除"）。

### 0.2 项目数据的实际形状（`projects.state_json`）

```
G   dict  29 键   60.2 KB   ← 其中 G.pI 一张产品图 data URL 就占 59.2 KB
pr  list   2 项    6.5 KB   ← 工序，每项含 tl（刀具行）22 条 / 3 条
is  list   2 项    0.2 KB   ← 问题清单
vh  list   0 项    0.0 KB   ← 版本履历：人工维护（日期/版本/内容/变更人，可增可删），客户版本切换时自动补记
```

- 工序字段：`nm / mc / cI / nc / tl / fixP / eqP / mid`
- 刀具行字段：`id(=T01 行标签) / tp / ds / d / n / vf / ln / ps / cn / bg / td / fi / tt / sd / _ct / _vc / _vf / _fz / cat / hld / acc`
- 问题字段：`tp / pr / ds / fx / cr / st / bI / aI`
- `G` 的 29 个键：`cust part custVer dfmDate prj hpd sft dpm avl len wid hgt wgt showFlow lang
  fixQ fixQC insp inspQ bInspType bInspPrice bInspImg fInspType fInspPrice fInspImg msInspPrice pI pf _vSnap`

### 0.3 三条"必须一起改"的现状问题

1. **名称引用**（没有外键）：
   - 刀具行 `tl[].tp = "D50盘铣刀"` 按**名字**对应 `tools.name`（实测每个名字 1 条）；`tl[].id="T01"` 只是行标签，不是库外键。
   - 夹具选型 `G.fixQ[k] = "1025减震模具中心|两点式拉杆四轴机加夹具…"`、检具选型 `G.insp[k] = "类别|名称|图号"`（`fixByKey()` 靠 `split('|')` 解析）。
   - 问题清单 `is[].pr = "机加工序-OP10"` 按**工序名**引用。
2. **整份提交 + 整份快照**：前端每次自动保存 `PUT /projects/{id}` 提交整个 `state`；
   服务端每次保存插一条 `revisions` 全量快照（rev 已到 15）。行级改动也会生成一份 65 KB 的新版本。
3. **派生值混进存储**：刀具行的 `_ct/_vc/_vf/_fz` 是算出来的（`app/machining_projection.py:47-49` 在报表时重算），却和用户输入一起存进快照。
   前端 `_vSnap` 更是把 `G` 的每个键 `JSON.stringify` 后逐键比较来产出 `VH` 文案（`legacy_app.js:12-13`）。

### 0.4 不能碰坏的对外契约

- `store.compose(state)` 必须继续产出前端与报表要的读模型：`{mdb,tdb,fdb,idb,pr,is,vh,G}`（含 `G.icnX/G.fcnX`、`pr[].mi` 反推）。
- 报表链路：`store.get(project_id)` → `report_runtime(state)` → `normalize(..., include_legacy_aliases=False)` → `/api/ppt-provider/.../snapshot`。
- 项目接口：`GET/POST /projects`、`GET/PUT /projects/{id}`（带 `revision` 乐观锁 → 409）、`/projects/{id}/versions`、`/projects/{id}/archive`。
- 前端导出（JSON 备份 / PPT）走 `inlineSheetImages()` 把附件 URL 换回 data URL。

### 0.5 前端改造面（实测计数）

| 指标 | 数量 | 含义 |
|---|---|---|
| `save()` 调用点 | 15 | 每次都会 `PUT /projects/{id}` 整份 `state` |
| `sve()` 调用点 | 13 | 从 DOM 回填 `G`，典型写法 `onchange="sve();render()"` |
| `render()` 调用点 | 74 | 任一改动都整页重渲染 |
| 内联 `on*` 处理器 | 110 | 其中 **0** 处直接改数组/对象，全部走具名函数 → 改造面在函数级，不在几百处内联代码 |

页面（页签）与业务对应关系：

| 页签 | 渲染函数 | 业务数据 |
|---|---|---|
| 客户与零件 | `bSetup()` | `G.cust/part/len/wid/hgt/wgt…` |
| 工序 1..N | `bProcess(i)` | `PR[i]` + `PR[i].tl`（刀具行） |
| 流程图 | `bFlow()` | 由 `PR/tl` 派生 |
| 汇总 | `bSummary()` | 由 `PR/tl/G` 派生 |
| 问题清单 | `bIssues()` | `IS` |
| 版本变更履历 | `bVersion()` | `VH`（列：日期 / 版本 / 变更内容 / 变更人 / 操作，**目前可手改**） |
| 工艺设置 | `bSettings()` | `G`（产能、检具类型/价格/图片、项目类型） |
| 成本表 | `bCostTable()` | 由 `TDB/PR/G` 派生（`procToolCost/toolCost/refEqPrice/exportCost`） |
| 四个库 | `bMachDB/bToolDB/bFixDB/bInspDB` | 已拆分（上一轮） |

另外两处**容易被忽略的名称引用**：

- `G.bInspType` / `G.fInspType` 的下拉选项直接**从检具库里取**（`bSettings()`：`IDB[i].type==='毛坯检具'` 的名称 + 6 个固定项）
  → 检具库改名/删除会影响它，改造时要么建引用关系，要么明确保留字符串快照。
- `G.prj`（项目类型 hp/dp）同时当**刀具组代码**用（`atT()` 按 `TDB[j].grp===G.prj` 选刀），见 2.1。

### 0.6 现状会**算错**的三个业务缺陷（这次重构顺手修掉）

这三条不是"代码不好看"，是**现在就会出错**：

1. **刀具成本按名字匹配 → 刀库改个名字，项目成本表静默变 0**
   ```js
   function toolCost(t){for(var j=0;j<TDB.length;j++){if(TDB[j].tp===t.tp){var life=TDB[j].life||0,price=TDB[j].price||0;return life>0?price/life:0;}}return 0;}
   ```
   （`legacy_app.js`；`tl[].tp` 是名字，`tools` 表里对应列是 `name`）→ 匹配不到直接返回 0，不报错、不提示。
2. **没有报价快照 → 改库里的价格，历史项目报价跟着变**
   同上：`price/life` 每次都从库里现取。今天改一次刀具单价，所有历史项目的成本表数字一起变——要么不能改价，要么历史报价不可复现。
3. **夹具/检具选型按 "中心|名称" 字符串解析 → 库改名选型就失效**
   ```js
   function fixByKey(k){...var a=String(k).split('|');var nm=a.slice(1).join('|');for(...){if((FDB[i].center||'')===a[0]&&(FDB[i].name||'')===nm)return FDB[i];}return null;}
   ```
   改一次夹具名，项目里的选型悄悄变成空（报价少一项）；检具的 `G.bInspType` 选项也直接来自检具库。

**结论**：项目业务数据必须落成"**ID 外键 + 当时的名字/价格快照**"两套并存——外键保证改库名还能找到，
快照保证历史报价可复现，并提供"刷新为库中最新价"的显式操作（而不是每次打开自动跟随）。

---

## 1. 目标与非目标

**目标**

1. **每个项目单独存自己的数据**：业务数据落成带 `project_id` 的类型化表，字段可查、可索引、行级增删改；
   项目之间零串扰（包括附件、版本、回收站）。
2. **版本管理**：工作副本（实时）+ 不可变版本快照（手动提交/节流自动）+ 变更明细 + 对比 + 恢复 + 保留策略。
3. **逻辑删除**：业务行、基础库行、（项目本身）统一 `deleted_at` 语义，回收站可恢复，彻底删除单独授权。

**非目标（本轮不做）**

- 多人实时协同（仍按"工作副本 + 乐观锁"处理，不做 OT/CRDT）。
- 把计算引擎搬到服务端（节拍/报价仍由前端算，服务端只在报表时复算）。
- 基础库的**表结构**再动（只给它补 `deleted_at` 三列与回收站）。

---

## 2. 实体与表设计

统一约定：每张业务表都有 `id TEXT PK`（uuid hex）、`project_id TEXT NOT NULL`（`projects(id)`）、
`seq INTEGER`（排序）、`created/updated/updated_by`、以及逻辑删除三列
（`deleted_at TEXT NULL`、`deleted_by TEXT NULL`、`deleted_reason TEXT NULL`，NULL 表示有效）。

### 2.1 `project_settings`（1:1，替代 `G` 的业务键）

> 中文字段名沿用页面 `GLBL` 标签表（`legacy_app.js:11`），保证界面文案不用改。

| 列 | 来源键 | 页面标签 | 说明 |
|---|---|---|---|
| `project_id` | — | — | PK |
| `customer` / `part` / `customer_version` / `dfm_date` | `cust`/`part`/`custVer`/`dfmDate` | 客户 / 零件号 / 客户版本 / DFM完成时间 | 项目基本信息 |
| `project_type` | `prj` | 项目类型 | `hp` 高压 / `dp` 差压。**注意双重身份**：它同时是刀具组代码，`atT()` 选刀时用 `(TDB[j].grp||'hp')===G.prj` 过滤刀具（与 `tool_groups` 的 `hp/dp` 一致），所以不能当普通枚举丢掉 |
| `hours_per_day` / `shifts` / `days_per_month` / `availability` | `hpd`/`sft`/`dpm`/`avl` | 每月工作日 / 班次 / 每月天数 / 稼动率 | 产能参数（节拍与产能计算的输入） |
| `length` / `width` / `height` / `weight` | `len`/`wid`/`hgt`/`wgt` | 长度 / 宽度 / 高度 / 重量 | 零件尺寸 |
| `show_flow` | `showFlow` | 流程图显示 | 界面项，保留（同一项目分享时表现一致） |
| `blank_insp_type` / `blank_insp_price` / `blank_insp_photo_id` | `bInspType`/`bInspPrice`/`bInspImg` | 毛坯检具类型 / 价格 / 图片 | 毛坯检具 |
| `final_insp_type` / `final_insp_price` / `final_insp_photo_id` | `fInspType`/`fInspPrice`/`fInspImg` | 成品检具类型 / 价格 / 图片 | 成品检具 |
| `ms_insp_price` | `msInspPrice` | 测量支架价格 | 测量支架费用 |
| `product_photo_id` / `product_photo2_id` | `pI` / `pf` | 产品图片 / 产品图片2 | **图片转 assets**，不留 data URL（`pf` 目前界面没用，原样保留） |
| `extra_json` | 未知键 | — | 兜底：老页面带的、我们还没建模的键原样保留，不丢数据 |
| 语言偏好（`lang`） | `lang` | — | 见第 9 节问题 7：建议**移出项目数据**（存 localStorage / `app_settings`），否则"打开别人项目界面语言跟着变" |

> `_vSnap` **不迁移**（它只是前端的变更检测缓存，服务端用 `project_changes` 取代）。

### 2.2 `project_processes`（工序）

`id, project_id, seq, name(nm), machine_id(mid→machines.id), cycle(mc), photo_id(cI),
fixture_cost(fixP), equipment_cost(eqP), note,
nc_cc, nc_co, nc_mc, nc_sc, nc_ac, nc_it（原 nc 字典展开）, deleted_at/by/reason, created/updated/updated_by`

- `machine_id` 保持现在的 `mid` 语义（设备被删除 → 读模型按兜底机型解析，不静默换机）。
- `nc` 展开成列（6 个固定键），便于报表直接取。

### 2.3 `project_process_tools`（工序刀具行）

`id, project_id, process_id(→project_processes.id), seq, label(id 原值如 T01),
tool_id(→tools.id，由 tp 解析出的外键), tool_name(tp 快照),
purpose(ds), diameter(d), spindle_rpm(n), feed_rate(vf), length(ln), passes(ps), copies(cn),
spot_drill(bg), air_time(td), fixture_ref(fi), tool_time(tt), standby(sd),
category(cat), holder(hld), accessory(acc),
price_snapshot(选型时刀具单价), life_snapshot(选型时寿命),
deleted_at/by/reason, created/updated/updated_by`

- `_ct/_vc/_vf/_fz` **不落库**：读模型里现算（`report_runtime` 已经是这么干的）；前端也用同一公式渲染。
- `tool_id` 与 `tool_name` 并存：`tool_id` 用于"改刀库名字后仍能找到"，`tool_name` 是**当时的名字快照**（导出/旧页面继续按名字显示）。
- `price_snapshot/life_snapshot` 解决 0.6 的第 2 条：`toolCost()` 改为**优先用快照**，界面提供"按库中最新价刷新"按钮（显式操作，带变更记录）。

### 2.4 `project_issues`（问题清单）

`id, project_id, seq, type(tp), process_id(由 pr 名称改外键，可空=项目级),
description(ds), fix_plan(fx), customer_reply(cr), status(st),
process_name_snapshot(迁移/新建当时的工序名), before_photo_id(bI), after_photo_id(aI),
deleted_at/by/reason, created/updated`

> 两处与最初草案不同，按**页面上实际是什么**改正：
> * `cr` 在页面上是「客户回复 / Customer Reply」（草案写成 `creator`，是实现前核对时发现的笔误）；
> * 没有 `seq`/`updated_by` 两列：顺序用现成的 `sort_order`（1b 同一套排序/回收站口径），
>   `updated` 由服务端统一盖时间戳，审计信息在版本履历（阶段 3）里，不在这张表上重复存。
>
> 落地情况见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE2.md`（阶段 2a 已完成：`project_issues`
> 真外键指向 `projects` / `project_processes` / `assets`）。

### 2.5 `project_selections`（夹具 / 检具选型报价）

`id, project_id, seq, kind('fixture'|'gauge'), category(模具中心 / 检具类别),
library_id(fixtures.id / gauges.id), legacy_key(原 "中心|名称" 或 "类别|名称|图号"),
name_snapshot, drawing_snapshot, price_snapshot, unit_snapshot('元'|'万元'),
days_snapshot(制造/设计周期), quoted(fixQC / inspQ 的 0/1),
deleted_at/by/reason, created/updated/updated_by`

一次解决三件事：
- 名称引用 → **id 外键**（库改名不再"选型变空"）；
- 报价口径固定：**价格取选型当时的快照**（库改价不影响已出报价）；
- `fixQ/fixQC/insp/inspQ` 四个"按类别下标对齐的数组" → 变成行，顺序由 `seq` 决定，不再依赖下标。

### 2.6 `project_versions`（版本，统一"版本履历"与"数据快照"）

`id, project_id, revision(项目内递增), seq(展示顺序), label(版本号，如 V1.0), note(变更内容),
kind('manual'|'auto'|'restore'|'legacy'), author(变更人), event_date(日期，可手改),
has_snapshot(0/1), snapshot_json(**压缩**的业务快照，可空), size_bytes, checksum,
deleted_at/by/reason, created, updated, updated_by
UNIQUE(project_id, revision)`

**一个关键统一**：现在的"版本变更履历"(`VH`) 是**人工维护**的表格（日期 / 版本 / 变更内容 / 变更人 + 新增记录 + 删除，
见 `bVersion()`），而服务端另有一套"每次保存一条 `revisions` 快照"。两套互不相干。本次合并成一张表：

| 现在的行为 | 重构后 |
|---|---|
| "+ 新增版本记录"（只填日期/版本/变更内容/变更人） | 建一条 `kind='manual'`：默认**同时存快照**（可取消勾选），`label/note/author/event_date` 就是那四个输入框 |
| 行内改日期/版本/内容/变更人 | 改的是**元数据**（`event_date/label/note/author`），不动快照 |
| `delVH(i)`（按下标删） | 逻辑删除该版本记录（回收站可恢复） |
| 客户版本切换时 `verRec()` 自动写一条 | 服务端按真实行级差异写一条 `kind='auto'` + 变更明细（3.1） |
| 每次自动保存产生 `revisions` 快照（当前 15 条） | 迁移成 `kind='auto'`（`has_snapshot=1`）；此后自动保存只改工作副本 |

- 快照只含业务表（settings/processes/tools/issues/selections），**不含**共享库与附件二进制（附件按 id 引用，直到彻底删除）。
- `projects.revision` 保留为"工作副本版本号"，继续做乐观锁（保存时 409 提示重新载入）。

### 2.7 `project_changes`（变更明细，自动审计）

`id, project_id, at, actor, entity, entity_id, action('create'|'update'|'delete'|'restore'),
field, old_value, new_value, version_revision, note`

> **落地版（3b，见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md`）与上面这版的差异**：
> `actor`/`at`/`field`/`old_value`/`new_value` 这五列没有单独建列，而是合并成
> **`label`（一句人话：`工序 OP10 精铣：设备台数 1→3`）+ `extra_json`（结构化的
> `fields:[{key,label,before,after}]`、`by`、`reason`、`cascade`）**；
> `entity_id` 拆成 **5 个真外键列**（`process_row_id`/`tool_row_id`/`issue_row_id`/
> `selection_row_id`/`history_row_id`）+ **`version_id → project_versions(id)`**（本表 7 个外键），
> 因为一列多态没法建外键（用户口径：有关联的数据结构全部用真外键）；
> `entity` 是 `project|settings|process|tool|issue|selection|history`，
> `action` 多一个 `save`（整份保存）。理由与取舍逐条写在 PHASE3B 文档第 2 节。

- 由行级写操作自动写入，回答"这个版本比上个版本改了什么"（对比页与版本详情都用它）。
- 客户版本切换（`custVer` 变化）继续记一条业务事件：`note='客户版本切换 A → B'` + 当时的参数差异。
- 与 `VH` 的区别：`project_changes` **不可手改**，是审计流水；`project_versions` 是业务版本。

### 2.8 附件归属（`assets` 扩展）

- `assets` 增加 `project_id`（可空=共享库附件），`kind` 增加
  `project_photo` / `process_photo` / `issue_photo` / `inspection_photo`。
- 迁移时把 `state_json` 里的 data URL 抽出来落盘：`G.pI`（59 KB）、`cI`、`bI/aI`、`bInspImg/fInspImg`。
- 效果：项目 `state_json` 65.6 KB 里的 59.2 KB 图片移出数据库文本字段；导出仍由 `inlineSheetImages()` 内联。

---

## 3. 版本管理

**两层模型**

| 层 | 载体 | 何时产生 | 能否修改 |
|---|---|---|---|
| 工作副本 | `project_*` 表 | 每次行级编辑（自动保存） | 可改 |
| 版本 | `project_versions` | **每一次保存都产生一个版本**（自动保存、逐字段保存、传图都算） | 元数据可改，快照不可改 |

### 3.1 页面（"版本变更履历"页签的新形态）

保留现在的四列观感，但数据来自服务端：

```
日期(可改) | 版本(可改) | 变更内容(可改) | 变更人(可改) | 快照 | 操作(恢复/对比/删除)
```
- "快照"列显示是否有可恢复的数据快照（`has_snapshot`）+ 大小；
- "操作"：`恢复到此版本`、`与当前对比`、`与上一版本对比`、`删除`（逻辑删除，进回收站）；
- 自动版本（`kind='auto'`）带徽标，且**元数据不可改**（审计属性），只能恢复/删除；
- 版本详情展开时显示变更明细（`project_changes`：谁在什么时候把哪个工序/刀具行的哪个字段从 A 改成 B）。

### 3.2 每次保存都留版本（口径 1，已确认）

- **不留"自动/手动"的差别，也不节流、不设上限**：一次保存 = 一个版本 = 一份快照；`projects.revision` 每次都 +1。
- 快照只写变化的实体（3.0 的"两层模型"），不再像现在这样每次塞 65 KB 的整份 JSON；
  项目信息搬进表之后，单次快照已经实测降到 **5.6 KB**（第 10 节），工序/刀具行落表后还会继续降。
- 手动"新增版本记录"只是给某个版本补上 `label/note/author/event_date` 元数据，不再决定"要不要留快照"。

### 3.3 恢复

`POST /projects/{id}/versions/{revision}/restore`

1. 先给**当前**工作副本自动打一个 `kind='restore'` 的安全快照（可后悔）；
2. 按目标版本重建业务表：能对上的行保留 `id`（引用不断）；目标版本里没有的行做**逻辑删除**（不是物理删除）；
3. `projects.revision` 递增，写一条 `project_changes`（action=`restore`），并提示"已恢复到 V1.2，当前状态已自动存为 V1.3(恢复前)"。

### 3.4 对比

`GET /projects/{id}/versions/{a}/diff/{b}` → 结构化差异：
各实体数量增减（工序/刀具行/问题/选型）+ 字段级明细（最多前 N 条，其余给计数）。
界面上就是"V1.1 → V1.2 改了什么"，比现在 `_vSnap` 把每个键 `JSON.stringify` 后比字符串准确得多。

### 3.5 保留与清理

- **没有淘汰、没有清理**（口径 1+2）：`tools/prune_versions.py` 这类工具不做；
  逻辑删除的版本留在回收站里，随时可恢复，数据库与附件文件一律保留。
- 版本多到影响性能时的唯一减压手段是**只记变化的实体**（3.0），而不是删版本。

### 3.6 旧数据

- 15 条 `revisions` → `project_versions(kind='auto', label='历史版本 N', has_snapshot=1)`；
- `VH` 里的手填记录 → `project_versions(kind='legacy', has_snapshot=0)`（只作履历，不参与恢复）；
- `GET /projects/{id}/versions` 与 `GET /projects/{id}?revision=N` 保持兼容（读新表），旧前端/报表不受影响。

---

## 4. 逻辑删除

**统一语义**：`deleted_at IS NULL` = 有效；删除 = 填三列；所有列表接口默认只返回有效行。

- 作用范围：`project_processes` / `project_process_tools` / `project_issues` / `project_selections` /
  四张基础库表 / 四张类别字典表 / `projects`（把现有 `archived` 统一成 `deleted_at`，`archived` 逻辑保留兼容）。
- **回收站**：`GET /projects/{id}/trash`（业务行）与 `GET /trash`（基础库 + 项目），每条带
  `deleted_at / deleted_by / 剩余保留天数 / 引用它的项目数`。
- **恢复**：`POST /{实体}/{id}/restore`（把 `process_id` 指向已删除工序的刀具行一并恢复时给出提示）。
- **没有彻底删除**（口径 2）：不做 `?purge=1`，不做保留期到期清理；数据库里的行与附件文件都保留，回收站只是"标记 + 过滤"。
- **唯一性冲突**（必须定口径）：类别字典以中文名为主键，逻辑删除后同名再建会有歧义。
  口径：**同名新增 = 复活原行**（并写一条 `restore` 变更），而不是报错或建重名。
- **引用已删除的库行**：项目选型/刀具行保留 `*_snapshot` 值，界面标注"来源已删除"，
  报价按快照价继续计算（口径 4）。
- **删除 vs 归档**：项目"删除" = 逻辑删除（进"已删除项目"）；`archived` 与 `deleted_at` 统一成一套（`archived` 逻辑保留兼容）。

---

## 5. 接口设计（新增，全部在 `/api/machining-dfm` 下）

```
GET    /projects/{pid}/business                  # 聚合读：settings+processes+tools+issues+selections（一次取全）
GET    /projects/{pid}/settings                  # 项目参数（已落地）
PATCH  /projects/{pid}/settings                  # 行级保存（已落地）
PUT    /projects/{pid}/settings                  # 整份保存：没提交的字段回默认值（含"客户版本切换"事件）
POST   /projects/{pid}/processes                 # 新增工序
PATCH  /projects/{pid}/processes/{id}
POST   /projects/{pid}/processes/reorder         # {ids:[...]}
DELETE /projects/{pid}/processes/{id}            # 逻辑删除（没有 ?purge=1）
POST   /projects/{pid}/processes/{id}/tools      # 刀具行（同套 CRUD + reorder）
PATCH  /projects/{pid}/tools/{id}
DELETE /projects/{pid}/tools/{id}
POST   /projects/{pid}/issues , PATCH/DELETE .../issues/{id}
POST   /projects/{pid}/selections , PATCH/DELETE .../selections/{id}
PUT    /projects/{pid}/photos/{field}            # pI/pf/bInspImg/fInspImg 走 assets（已落地）
POST   /projects/{pid}/versions                  # 新增版本记录 {label, note, author, event_date}
GET    /projects/{pid}/versions                  # 列表（含 has_snapshot/变更条数）
PATCH  /projects/{pid}/versions/{revision}       # 改元数据（版本号/内容/变更人/日期）
DELETE /projects/{pid}/versions/{revision}       # 逻辑删除（进回收站，永不物理删除）
GET    /projects/{pid}/versions/{a}/diff/{b}
POST   /projects/{pid}/versions/{rev}/restore
GET    /projects/{pid}/changes?limit=100         # 变更明细（审计流水）
GET    /projects/{pid}/trash , GET /trash
POST   /{entity}/{id}/restore
```

- 写接口都要管理员或工艺设置令牌（沿用现有 `authorize`）。
- 旧接口全部保留：`GET/PUT /projects/{id}`（整份读写，内部转成行级 diff 后落库）、`/libraries`、`/bootstrap`。

---

## 6. 前端改造

- 新增 `static/machining_dfm/project_data.js`：项目业务数据的行级客户端（settings/processes/tools/issues/selections），
  复用上一轮的约定（**模块 `render()` 只生成 HTML，动作后 `repaint()`**）。
- `host.js`：`persist()` 从"整份 PUT state"改为"按脏行 PATCH"；`revision` 乐观锁保留（409 → 提示重新载入）。
- `compose()` 读模型不变：`PR/IS/VH/G/MDB…` 仍由服务端 compose 出来喂给现有计算与导出代码，
  `tl[].tp`、`G.fixQ` 这些**旧键继续输出**（值由新表渲染回去），保证报价/PPT/导出零改动。
- 计算引擎不动：`calC/calT/nct/cap` 等仍在页面里算，`_ct/_vc/_vf/_fz` 由读模型提供或前端现算。
- 版本页签：改成"版本列表（手动/自动徽标）+ 变更明细 + 对比 + 恢复"；回收站单独一个入口。

---

## 7. 数据迁移

1. `tools/verify_business_migration.py`：**先在有备份的副本上干跑**（沿用基础库那套：copy → migrate → 报 0 diff）。
2. 迁移内容：
   - `projects.state_json` → `project_settings` + `project_processes` + `project_process_tools` + `project_issues` + `project_selections`；
   - `tl[].tp` → 解析出 `tool_id`（名字匹配不到就留空 + 保留 `tool_name`，并在日志里列出未匹配项）；
   - `is[].pr` → 解析出 `process_id`（匹配不到留空）；
   - `fixQ/fixQC/insp/inspQ` → `project_selections` 行；
   - `revisions` → `project_versions`（kind='auto'，has_snapshot=1）；
   - `VH` → `project_versions`（kind='legacy'，has_snapshot=0，日期/版本/内容/变更人原样搬过来）；
   - data URL 图片 → `assets` + 磁盘，替换成 `*_photo_id`。
3. 归档与回滚：`projects_legacy_v1` / `revisions_legacy_v1` 保留原 JSON；
   另备 `tools/rollback_business_migration.py`（把新表导回 `state_json`，用于万一）。
4. 幂等：`app_settings.project_schema_version` / `business_data_migrated`；重复启动不重复导入。
5. 每一步都先 `_backup()`。

---

## 8. 分阶段交付与验收

| 阶段 | 内容 | 验收 | 状态 |
|---|---|---|---|
| 0 | 本方案确认 + 迁移干跑工具 | 副本迁移 0 差异；线上数据未动 | √ 完成 |
| 1 | **项目信息**（`project_settings` + 4 张项目图片 + 接口 + 前端页签 + 迁移） | pytest 全绿；`compose()` 输出与迁移前逐键一致；页面能逐字段维护项目信息 | √ 完成（见第 10 节） |
| 1b | `project_processes` + `project_process_tools`（工序与工序刀具行） | 页面工序页签与报价数字不变 | √ 完成（见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE1B.md`） |
| 2a | `project_issues`（问题清单，工序外键 + 两张图片） | 读模型 `is[]` 逐字节一致；行级增删改 | √ 完成（见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE2.md`） |
| 2b | `project_selections`（夹具/检具选型，库外键 + 快照价） | 选型/报价与迁移前一致；改名/改价不再影响已选项目 | √ 完成（同上） |
| 3a | 版本履历：`project_versions`（保存版本 `kind='save'` + 履历行 `kind='history'`） | 建版本→改数据→恢复；`?revision=N` 与 `vh[]` 逐字节不变 | √ 完成（见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3.md`） |
| 3b | 变更流水：`project_changes`（每个行级写入点自动记一条，7 个真外键） | 每个写入点都留流水、`version_id` 指得到那一次保存、老数据一行不补 | √ 完成（见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md`） |
| 4 | 逻辑删除（业务行 + 基础库 + 项目）+ 回收站 + 变更流水界面（**无彻底删除、无保留期**） | 删除→回收站可见→恢复原样；同名重建复活原行；引用提示正确 | **已完成**（后端 + 前端，见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE4_DESIGN.md` 第 5 节；真实 HTTP 闭环在副本上验过，线上库未动）。设计细节见 §5.6–5.8：项目删除按钮已切到 `DELETE /projects/{id}`（管理员 + 写流水，老 `/archive` 路由保留）；选型格子用「历史版本」恢复 |
| 5 | 附件归项目（`cI/bI/aI`）+ 导出/PPT 回归 | `state_json` 体积降到几 KB；PPT/JSON 导出图片正常 | **已完成**（见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE5.md`）：靶子在阶段 1b/2a 已顺带打中 —— `projects.state_json` 只剩 2 字符、18 个附件引用全是真外键且 0 悬空、全库 0 行 `data:image`；本轮固化常驻自检 `tools/check_export_assets.mjs`（87 条），并补上导出内联漏掉的 `TDB/IDB/G.pf/IS.bI/aI`。**遗留**：便携 HTML 单文件导出在拆页后失效 —— 用户已拍板改成「**导出 JSON + 导出文件包（zip）**」，见 PHASE5 §7.0（下一步实施） |

每阶段固定动作：`pytest tests -q`、迁移干跑、无头页面自检（`tools/*.mjs`）、整页 smoke、线上 e2e（跑完还原数据）、更新 `docs/` 与 `README.md`。

---

## 9. 需要你拍板的口径（**已拍板**）

> 用户答复（2026-09-18）：1 全部留版本；2 不允许永久删除；3 是；4 是；8 是。其余按下面建议执行。

1. **自动保存要不要留版本？** → **留**。每一次保存（含自动保存、逐字段保存、传图）都生成一个版本，永久保留，不节流、不设上限。
2. **逻辑删除保留期**？→ **没有保留期，也没有彻底删除**：删除只是打标记（`deleted_at/deleted_by/deleted_reason`），回收站里随时恢复；不做 `?purge=1`、不做到期物理清理。
3. **字典/库同名重建**？→ **同名 = 复活原行 + 记一条审计**（避免中文名主键冲突）。
4. **源库被删后，项目里的选型报价怎么算？** → **按选型当时的快照价**继续算，界面标注"来源已删除"。
5. **项目删除**是否连附件一起删？→ 不再涉及（没有彻底删除）。逻辑删除的项目，附件一并保留。
6. **要不要"谁改了什么"审计**？→ 要（`project_changes`，记录 admin/工艺设置两个角色）。
7. **`showFlow` 与 `lang` 的归属**：→ `showFlow` 留项目数据；`lang` **移出**项目数据（写进 `app_settings` 当默认）。
8. **派生字段 `_ct/_vc/_vf/_fz` 不落库**（读时算）→ 确认。
9. **工序刀具行的"刀具"是否必须绑库？** → `tool_id` 可空。
10. **问题清单的"工序"引用**：→ 改 `process_id` 外键。
11. **（2026-09-18 追加，口径 6）影子副本停写**：哪一级落表了，那一级的"影子副本"就停写 ——
    同一份数据不许在库里存两份。开关 < 4 时 `revisions` + `projects.state_json` 里的数组照旧维护
    （回滚靠它）；开关 ≥ 4 之后两者都不再写，`projects_legacy_v1` 也只在真有东西归档时才建。
    **代价：回滚从"删掉版本键"变成"从备份恢复"**。跟着落地的是
    `tools/clean_legacy_project_data.py`（清旧副本，默认干跑）与"`pr`/`is`/`vh` 永远是数组"的读模型加固；
    线上实测见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md` 第 14 节。

---

## 10. 第一阶段落地记录（项目信息，2026-09-18）

### 11.1 改了什么

| 层 | 文件 | 内容 |
|---|---|---|
| 数据 | `app/machining_project.py`（新增） | `project_settings` 表：一个项目一行，19 个业务字段一列一个；4 个图片槽（产品图片 / 产品图片2 / 毛坯检具图片 / 成品检具图片）走附件表；建模之外的键整份进 `extra_json` |
| 数据 | `app/machining_assets.py` | 新增附件类别 `project_photo`、`inspection_photo` |
| 数据 | `app/machining_dfm.py` | `_migrate_project_settings()`：迁移前归档到 `projects_legacy_v1` + 备份 `pre-project-settings.sqlite3`，把项目信息写进新表，`projects.state_json` 只留 `pr/is/vh`；`compose()` 用表里的值拼回原来的 `G`；新增 5 个接口 |
| 前端 | `static/machining_dfm/project_info.js`（新增） | 「项目信息」页签：改一个格 → PATCH 一个字段 → 服务端记录接管内存 → `repaint()`；图片上传/清除/查看 |
| 前端 | `static/machining_dfm/host.js` | `adopt()`（保存后用服务端记录刷新当前项目与指纹，防止旧内存把新值覆盖回去）、`current()`、`api` 支持 `json` 体；新建项目后直接跳到「项目信息」页 |
| 前端 | `static/machining_dfm/legacy_app.js` | `bSetup()` 委托 `ProjectInfoPage.render()`；「工艺设置」页里与项目信息重复的字段（项目类型 / 日可动时间 / 日班次 / 月可动日 / 可动率）移走 |
| 前端 | `static/machining_dfm/index.html` | 加载新模块，静态资源版本号 `library-v6` → `project-v1` |
| 工具 | `tools/verify_project_settings_migration.py` | 迁移干跑（可 `--from` 指向迁移前备份）；数值型差异容忍 `0` 与 `0.0`；线上已迁过时明确提示不再重复验 |
| 工具 | `tools/restore_project_settings.py` | 按迁移归档逐键核对 / 还原项目信息（默认干跑） |
| 工具 | `tools/live_project_info_e2e.py` | 线上全链路自检（迁移结果 / 字段表 / 单字段保存 / 整份保存 / 校验拒绝 / 图片上传清除 / 读模型与最新快照），跑完数据还原原状 |
| 测试 | `tests/test_machining_dfm.py` | 新增 8 个用例（行级保存、逐字段 PATCH 不动别的字段、校验 422、图片上传清除与附件回收、整份保存写表、接口往返、迁移幂等与归档、默认项目信息仍能渲染种子项目） |

### 11.2 线上实测证据

```
迁移前：projects.state_json 65.6 KB（G 29 键，其中 pI 是 59.2 KB 的 data URL）
迁移后：projects.state_json  5.6 KB（只剩 pr/is/vh），
        project_settings.extra_json 0.5 KB（insp/fixQ/fixQC/inspQ/lang/_vSnap，不含任何图片）
        G 逐键与归档一致（只多了 icnX/fcnX 这两个由字典派生的缓存键）＋ 产品图片字节一致（45460 B → 45460 B）
        历史版本 16 条快照原样保留，最新快照仍是完整读模型 {G,pr,is,vh}
```

验证命令与结果：

| 命令 | 结果 |
|---|---|
| `pytest tests -q` | 39 passed |
| `python tools/verify_project_settings_migration.py --from data/machining_dfm/backups/pre-project-settings-manual-*` | √ 干跑通过（逐键一致、历史版本可还原、项目信息已落表） |
| `python tools/restore_project_settings.py` | √ 与归档一致，无需还原 |
| `python tools/live_project_info_e2e.py` | 全部通过（34 项） |
| `node tools/smoke_machining_page.mjs` | 全部检查通过（含项目信息页渲染、单字段 PATCH、版本递增、按新版本重绘） |
| `python tools/check_served_page.py` | 11 个静态资源全部 200，版本号统一 `project-v1` |

### 11.3 接口（第一阶段新增）

```
GET   /api/machining-dfm/project-settings/fields          # 字段登记表（key/标签/单位/上限/选项）
GET   /api/machining-dfm/projects/{pid}/settings          # 读项目信息（旧键 + ?类型化键 + extra）
PATCH /api/machining-dfm/projects/{pid}/settings          # 行级保存：只提交改动的字段
PUT   /api/machining-dfm/projects/{pid}/settings          # 整份保存：没提交的字段回默认值、没提交的图片清空
PUT   /api/machining-dfm/projects/{pid}/photos/{slot}     # slot = product / product2 / blank_insp / final_insp
DELETE /api/machining-dfm/projects/{pid}/photos/{slot}
```

### 11.4 两个必须记住的坑（已写进实现注释）

1. **行级保存一律用 PATCH，别用 PUT**：PUT 是"整份覆盖"语义，只提交两个字段会把其余字段打回默认值、把没提到的图片清空（开发自检时踩过一次，用 `tools/restore_project_settings.py` 从迁移归档还原，已核对无残留差异）。前端每个字段的保存、传图都走 PATCH。
2. **每次保存都会 `revision +1` 并写入一条完整快照**（"全部留版本"口径），所以自检类脚本要如实报告自己产生的版本数，不要偷偷删版本——版本不允许删除。

### 11.5 下一步（第二阶段）

`project_processes`（工序）+ `project_process_tools`（工序刀具行）逐行落表：改 id 引用、价格快照、
派生字段读时算；`compose()` 继续输出旧键，保证报价/PPT/导出不变。

---

## 11. 风险与边界

- **读模型兼容**是最大风险：`compose()` 一旦少输出一个旧键，报价/PPT/导出就会静默算错。对策：迁移后做**逐键 diff 断言**（迁移前后 `compose()` 输出必须完全一致），并保留旧键输出通道。
- **名称引用改造**涉及前端 `fixByKey/fixFilter/setFixSel/setInspSel`、`TDB` 按名匹配、`is[].pr`：一次性全改还是双写过渡？建议**双写过渡**（新表为准，旧键由 compose 生成），一个阶段只切一处。
- **附件迁移**要验重（同一 data URL 多次出现 → 只存一份）+ 校验和。
- **并发**：行级写 + 乐观锁，仍可能出现"两人同时改同一行"→ 用 `updated` 时间戳做行级冲突提示（后写覆盖前写要留痕在 `project_changes`）。
- **性能**：项目业务行量级很小（2 工序 / 25 刀具行），无分页压力；761 条刀具库的读模型照旧一次 compose。
