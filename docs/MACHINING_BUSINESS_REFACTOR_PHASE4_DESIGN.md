# 阶段 4 设计：逻辑删除 + 回收站 + 变更流水界面

> 前置：阶段 1 / 1b / 2a / 2b / 3a / 3b 都已落地（业务数据全部落表、关联列全是真外键），
> 线上能力级别 `project_business_version = 5`。
> 本阶段按已拍板口径执行：**逻辑删除、没有保留期、没有彻底删除**（口径 2），
> **字典/库同名重建 = 复活原行**（口径 3），**源库删掉后按快照价算**（口径 4）。
> 落地顺序：**先库与接口（可验证）→ 再前端**；沿用每阶段的固定动作（pytest / 干跑 / 无头自检 / smoke / 线上 e2e 还原）。

## 1. 现状盘点（已经有的）

| 能力 | 现状 |
| --- | --- |
| 业务行三列 | `project_settings` / `project_processes` / `project_process_tools` / `project_issues` / `project_selections` / `project_versions` / `project_changes` **七张表都有** `deleted_at/deleted_by/deleted_reason`（线上当前已删行 = 0） |
| 业务行删除 | 工序、刀具行、问题行、履历行、选型格 都有 DELETE 接口（选型格是 `DELETE /selections/{kind}/{slot}`） |
| 业务行恢复 | 工序、刀具行、问题行、履历行 都有 `/restore`；**选型格没有** |
| 变更流水 | `GET /projects/{pid}/changes`（3b）+ 每个行级写入点自动记一条；**界面还没做** |
| 基础库 | `machines`/`tools`/`fixtures`/`gauges` 与 4 张字典（`tool_groups`/`tool_categories`/`fixture_centers`/`gauge_categories`）**都没有三列**；删除是物理删（`DELETE /tools/{id}` 等） |
| 项目删除 | 只有 `projects.archived`（"已删除项目"入口 + `?allow_archived`），没有 `deleted_at` 三列 |
| 回收站接口 | **一个都没有**（`GET /trash`、`GET /projects/{pid}/trash` 待建） |
| 附件 | `assets` + `prune_orphans()`；按口径 2，逻辑删除时附件一律保留 |

## 2. 要做的四件事

### 2.1 基础库与字典补"逻辑删除三列"（迁移）

* 8 张表各补 `deleted_at TEXT` / `deleted_by TEXT` / `deleted_reason TEXT`（可空，默认 NULL）；
* 索引：`(deleted_at, sort_order)`，回收站按删除时间倒序；
* 字典表（`tool_groups`/`tool_categories`/`fixture_centers`/`gauge_categories`）主键是中文名/code，
  **同名重建 = 复活原行**：`POST` 遇到已逻辑删除的同名行 → 把三列清空、写一条 `restore` 流水，
  而不是新建重复行；
* **基础库的引用列不动**：项目里指向已删库行的外键本来就是 `ON DELETE SET NULL`，
  逻辑删除不触发它（行还在），所以"来源已删除"要靠读模型判断 `deleted_at IS NOT NULL` 并标注，
  价格/工期照旧走 `*_snapshot`（口径 4）。

迁移工具：`tools/migrate_library_trash.py`（默认干跑：副本上加列 + 验证读模型逐字节不变；
`--apply` 先整库备份）。加列是 `ALTER TABLE ADD COLUMN`，不动任何既有数据，风险极低。

### 2.2 回收站接口（新增）

```
GET    /api/machining-dfm/trash                     # 全局：已删除项目 + 各基础库/字典（管理员）
GET    /api/machining-dfm/projects/{pid}/trash       # 本项目：业务行按实体分组
POST   /api/machining-dfm/projects/{pid}/selections/{kind}/{slot}/restore   # 补上唯一缺的一个恢复
POST   /api/machining-dfm/projects/{pid}/restore     # 恢复已删除项目（等价于 archived=0）
POST   /api/machining-dfm/trash/{table}/{id}/restore # 基础库/字典行恢复（表名白名单校验）
DELETE /api/machining-dfm/tools/{id} 等              # 由物理删 → 逻辑删（既有路由改语义）
```

每条回收站记录带四个信息（计划第 4 节要求）：
`deleted_at`、`deleted_by`、`deleted_reason`、**引用它的项目数**
（例：某设备被 2 个项目的工序引用 → 恢复前就看得见；引用数从 `project_processes.machine_id` 等外键现算）。

**没有 `?purge=1`、没有保留期、没有定时清理**：回收站只是"标记 + 过滤"，
库里行与附件文件一律保留（口径 2）。`assets.prune_orphans()` 只在附件确实没有任何引用时回收文件。

### 2.3 项目删除统一口径

* 保留 `projects.archived`（历史兼容 + 现有列表接口），**不**再补一套 `deleted_at`：
  一个项目只有"在/不在"两种状态，两套标记必然跑偏；
* 项目"删除"= `archived=1` + 记一条 `[project/delete]` 流水；"恢复"= `archived=0` + `[project/restore]` 流水；
* 项目列表默认过滤已删，`?archived=true` 看"已删除项目"（现有行为不变）。

### 2.4 前端

* **回收站**：主界面加一个入口（项目列表页 + 每个项目页签行），点开一个面板，
  按实体分组列出已删行、显示"谁删的/为什么/引用数"，每行一个「恢复」按钮；
  基础库/字典的回收站在对应库页面里各加一个「回收站」按钮（同一个面板组件）；
* **变更流水时间线**：版本履历页签下半部分按时间倒序列出 `GET /changes` 的条目
  （`label` 是人话，`extra_json` 折行显示 diff）；支持按实体过滤（工序/刀具/问题/选型/项目/履历）；
* 写操作照旧走 `withAdmin`（管理员）+ 服务端令牌（现有一套 `authorize`）。

## 3. 验收（每一条都要有命令/证据）

1. `pytest tests -q` 全绿，新增用例：删除 → 回收站可见（带删除人与原因）→ 恢复原样（读模型逐字节回到删除前）、
   同名重建复活原行、已删库行的项目引用提示"来源已删除"且价格走快照、回收站接口的权限与表名白名单；
2. 迁移干跑：加列前后**读模型逐字节相同**、`PRAGMA foreign_key_check`/`integrity_check` 干净；
3. 无头自检（`tools/check_trash_page.mjs`，写请求拦下不落库）+ 整页 smoke；
4. 线上 e2e（`tools/live_trash_e2e.py`）：真删一行 → 回收站里看到 → 恢复 → 数据回到原样 → 跑完清理干净；
5. 文档：`README.md`、本文件、`docs/MACHINING_DB_STRUCTURE.md` 同步。

## 4. 待拍板（3 件小事）

1. **谁能看/谁能恢复回收站**：只管理员，还是管理员 + 工艺设置都能看（恢复只给管理员）？
   建议：看给两个角色，恢复只给管理员。
2. **删基础库行时，被项目引用要不要"硬挡"**：现在外键是 SET NULL，删掉不挡；
   建议照旧不挡（价格有快照，删了不影响项目数字），但删除前在界面上提示"有 N 个项目在用"。
3. **变更流水时间线这次一起做，还是只做回收站**：建议一起做（数据早就在库里，界面是纯前端工作）。

---

## 5. 实施记录（2026-09-18：后端一半已落地）

用户拍板：**基础库/字典也进回收站**；**查看给两个角色（admin / process），恢复只给管理员**。

### 5.1 已落地

| 位置 | 做了什么 |
| --- | --- |
| `app/machining_library.py` | 引擎：`ddl()` 带三列 + `ensure_trash_columns()` 老库自愈（幂等、可空）；`rows()` 默认只出在用行、新增 `trash()`；`delete(id, by, reason)` 改**逻辑删除**（不再回收附件）；新增 `restore(id)`；`create()` 命中回收站里同一"自然键"的行 → **复活原行**（`_find_deleted_natural`/`_revive`，口径 3）；兜底行只在**在用**行里挑；`replace_legacy(prune=True)` 也改成逻辑删除 |
| 同文件 `NameDictionary` | 四张"中文名做主键"的字典表（模具中心/检具类别）同样补三列 + 过滤 + `trash()` + `restore()`；`create()` 同名 = 复活原行；`delete(cascade=True)` 连带把下面的数据行**逻辑删除**（附件保留）；引用计数只算在用行 |
| `app/machining_tools.py` | `tool_groups`/`tool_categories` 补三列（回收站索引**在补列之后**建 —— 老库先建索引会报 no such column）、`groups()/categories()/scope_of()` 过滤已删行、删除改逻辑删除、新增 `restore_group/restore_category/trash`、按 code 同名复活 |
| `app/machining_fixtures.py` / `machining_gauges.py` | `delete_by_center`/`delete_by_category` 改为逻辑删除（不再删附件），并把 `by`/`reason` 记到行上 |
| `app/machining_dfm.py` | store 新增 `project_trash()` / `library_trash()` / `restore_trash_row()` / `delete_project()` / `restore_project()`（+`_note_project_action`、`_referencing_projects`）；5 条路由（见 5.2）；库/字典的删除路由把**角色**传进 `by` |
| `tools/migrate_library_trash.py` | 新增：默认**干跑**（副本还原成"没有三列"的老库 → 补列 → 逐一验证），`--apply` 先整库备份再动线上，`--status` 只读 |
| `tests/test_machining_trash.py` | 新增 7 个用例：业务行删/恢复闭环、项目删除恢复（两头留流水）、库行回收站带"被 N 个项目引用"、表名白名单、字典同名复活、老库自愈、迁移工具干跑 |

### 5.2 接口（实际形状）

```
GET    /api/machining-dfm/projects/{pid}/trash    # 本项目业务行（按实体分组）
GET    /api/machining-dfm/trash                   # 全局：已删项目 + 8 张库/字典表的已删行
POST   /api/machining-dfm/trash/{table}/{id}/restore     # 恢复（仅管理员；表名白名单）
DELETE /api/machining-dfm/projects/{pid}          # 项目"删除" = archived=1 + 流水
POST   /api/machining-dfm/projects/{pid}/restore  # 项目恢复 = archived=0 + 流水
```

每条记录都带四样：`deleted_at` / `deleted_by` / `deleted_reason` / `references`（被几个项目引用）。

### 5.3 实施中定的三处口径（与 §2 的差异，以这里为准）

1. **选型格子不产生回收站条目**：`DELETE /selections/{kind}/{slot}` 是"清空这一格"（行保留、
   `*_snapshot` 与"是否报价"勾选都留着），本来就没有逻辑删除状态，所以**不补** `/restore`；
   要回到清空前的值走版本恢复（3a 的 `POST /versions/{rev}/restore`）。§2.2 里那条接口因此取消。
2. **项目级动作不递增项目版本**：删除/恢复只改 `archived` 并写一条 `[project/delete|restore]` 流水，
   不造版本快照（没有数据改动）。流水直接落在当前版本上（`_note_project_action`）。
3. **引用列不置空**：库行/字典行逻辑删除后，项目里的外键**保持指向**那一行（行还在），
   所以 `ON DELETE SET NULL` 不会触发；"来源已删除"由界面拿回收站列表标注，
   读模型（`state`）一个字节都不变 —— 恢复之后引用原样接回来。

### 5.4 线上执行与证据（2026-09-18 19:17）

* `--status`：8 张表都缺三列 → `--apply`（先备份 `backups/pre-library-trash`，1.49 MB）
  → 8 张表三列齐全、`integrity_check = ok`、`foreign_key_check` 干净、
  **每个项目的读模型逐字节不变**；库 1472 KB → **1524 KB**；
* 服务重启后：页面 200、项目记录完好（revision 86 / 级别 5 / 工序 2 行）；
  `GET /projects/{pid}/trash` 与 `GET /trash` 都 200（`enabled=true`，当前 0 条）；
  `POST /trash/projects/whatever/restore` → **422 白名单拒绝**；无令牌 → 401；
* `pytest tests -q` **189 passed**；整页 smoke「全部检查通过」；开关自检、外键总账（19 张表）、
  报价基线指纹 `b1b29eef9cf66e7a`、报表契约、前端接管自检全部照旧通过。

### 5.5 前端一半（同日落地）

| 位置 | 做了什么 |
| --- | --- |
| `static/machining_dfm/trash_page.js`（新） | 回收站入口 + 面板 + 恢复：按 `group` 分组，每行显示 `title` / 谁删的 / 为什么 / 人话时间 / 「被 N 个项目引用」；「恢复」按钮**只有管理员可见**，非管理员能看不能恢复；成功后刷新读模型并重绘、把那一行移出面板；失败把后端原因写在面板里 |
| `static/machining_dfm/changes_page.js`（新） | 版本履历页签下半部分的**变更流水时间线**（只读）：倒序、按 `entity` 过滤（8 个按钮，标签优先取后端 `entity_labels`/`action_labels`）、显示 `v<版本>`、`extra` 常见键给中文标签、超长截断、空清单给一句人话 |
| `legacy_app.js` / `machines.js` / `tools.js` / `library_pages.js` / `host.js` / `host.css` / `index.html` | 页签行与四个库页面各挂一个回收站入口；登录成功后探一次回收站（入口跟着登录状态出现/收回）；面板与时间线样式；**资源版本号 `?v=process-v1` → `?v=trash-v1`** |
| `tools/check_trash_page.mjs`（新） | 无头自检 **98 条**：管理员（入口自动出现、6 分组、四个字段、`POST /trash/{table}/{id}/restore` 带令牌、项目业务行走模块接口、成功后行消失、失败原因上屏、时间线倒序 + 过滤 + 空态 + 只读）、工艺设置（能看、**没有恢复按钮**、硬调也发不出请求）、以及 401 / 404 / `enabled=false` / 未登录四种降级（入口整块消失、控制台无 error、无写请求） |

**降级口径**：回收站接口 404 / 403 / `enabled=false` / 未登录 → 入口整块隐藏，页面照常渲染，不报错。
**懒加载**：时间线只在切到版本履历页签、换项目、点过滤时拉 `GET /changes`，纯重绘只吐缓存（这样 3b 那两条"页面不发 `/changes`"的 smoke 断言照旧成立）。

### 5.6 项目删除按钮（用户拍板：切到新接口）

页面顶部「删除项目」原本走的是老接口 `POST /projects/{id}/archive`（**无鉴权、不写流水**）。
用户拍板后已切到阶段 4 的新接口：

* 删除 → `DELETE /projects/{id}?reason=…`（**仅管理员**，服务端写一条 `project/delete` 流水，带删除原因）；
* 在「已删除项目」里按钮变成「恢复项目」→ `POST /projects/{id}/restore`（仅管理员，写 `project/restore` 流水）；
* 没登录 / 只有工艺设置令牌 → 页面直接挡下（一个写请求都不发），提示去「后台配置」用管理员密码登录。

**老路由 `POST /projects/{id}/archive` 保留不动**（老路径仍在：其它调用方不受影响），只是页面不再用它。
`tools/check_trash_page.mjs` 新增 **H / H3 两节共 14 条断言**盯这条路径：发的是 `DELETE` 而不是 `/archive`、
带原因、带管理员令牌、删除后重新探回收站、整段只有一个写请求、切到「已删除项目」后按钮文案变、恢复发
`POST /projects/{id}/restore`、恢复后文案变回、非管理员点删除零写请求且提示要管理员身份。

### 5.7 验收（同日，两遍：我自己一边、页面/HTTP 一边）

* `pytest tests -q` **189 passed**；`node tools/check_trash_page.mjs`、`smoke_machining_page.mjs`、
  `check_tools_page.mjs`、`check_fixture_gauge_page.mjs`、`check_host_css.py`、`check_served_page.py` 全
  「全部检查通过 ✓」（静态资源 17 个全 200，版本号统一）；
* **真实 HTTP 闭环（在副本库上跑，另一个端口）**：登录 → 回收站 0 条 → `DELETE /tools/{id}`
  （记下 `deleted_by=admin`）→ `GET /trash` 里那一行带 `group=基础库`/`entity_label=刀具库`/`references=1`
  → `DELETE /projects/{pid}/processes/{id}` 后项目回收站 **23 条**（工序 1 + 刀具行 22，工序上 `references=22`）
  → 恢复工序回 0 条 → `POST /trash/tools/{id}/restore` → 刀具库回到 761 行、那一行原样回来
  → 工艺设置读 200、恢复 **403**；
* 副本跑完后与线上逐表比对：**线上库一个字节没动**（mtime、刀具 761 行、版本 86、流水 21 全部照旧，
  `integrity_check=ok`、外键干净）；副本才是被写的那个（版本 88、流水 67）。

### 5.8 还剩的两处（都是设计选择，不是缺陷）

1. ~~页面顶部「删除项目」仍走老的 `POST /archive`~~ → **已按用户拍板切到新接口**，见 §5.6。
2. **选型报价的格子**没有独立恢复接口（清空格子不是逻辑删除），界面上不给恢复按钮、写明"请用「历史版本」恢复"。

### 5.9 教训（已修）

`migrate_library_trash.py --apply` 那时也跑了"删一行 → 恢复"的**写探针**：虽然当场恢复、备份对比只差那一行的
`updated` 时间戳（业务表一行未动），但线上不该出现任何写探针。
工具已改成 **`--apply` 只做只读验证**，写探针只在干跑副本上跑（`run()` 里 `report` 只传给干跑分支）。
后来那次"真实 HTTP 闭环"就是用**副本库 + 另一个端口的临时服务**做的，验完即关。
