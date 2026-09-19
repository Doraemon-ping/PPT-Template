# 机加 DFM 库结构（2026-09-18 清掉旧副本与冗余 + 选型拆表之后）

> 这份是**清完之后**的结构现状：27 → **21 张表**（选型拆表后净增 2 张），8.05 MB → **1.83 MB**，
> 每种数据只有一份（旧副本已删、历史快照里的内联图片已抽成附件，见
> `docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md` 第 14 / 14.1 节；
> 选型从一张多态表拆成"夹具/检具"两张，见下面第 1 节与
> `docs/MACHINING_REFACTOR_ACCEPTANCE.md` 的"结构再调整"一节）。
> 行数是线上 2 个项目的实测值。外键只列真外键（`PRAGMA foreign_key_list` 读出来的）。

线上库：`data/machining_dfm/machining_dfm.sqlite3`｜能力级别 `project_business_version = 5`
（1 工序 / 2 问题清单 / 3 选型报价 / 4 版本履历 / 5 变更流水）。

## 1. 项目业务数据（9 张，全都挂在项目上；`assets` 是附件表，见第 3 节）

| 表 | 行 | 说明 | 关键外键 |
| --- | --- | --- | --- |
| `projects` | 2 | 项目行：`id/name/revision/state_json/archived` | — |
| `project_settings` | 2 | 项目信息（原来 `state_json.G`）：30 列，含客户/零件/工时口径/尺寸重量 + 4 张项目图片 | `project_id → projects`，4 个 `*_photo_id → assets` |
| `project_processes` | 2 | 工序：名称/**设备（`machine_id`）**/台数/夹具与设备费/节拍 `count_json`/设备快照 | `project_id → projects`，`machine_id → machines` SET NULL，`fixture_photo_id → assets` |
| `project_process_tools` | 25 | 工序刀具行：34 列，刀具参数 + **价格/寿命快照** + 快照绑定的库行 | `process_id → project_processes`，`tool_id`/`handle_id`/`accessory_id → tools` SET NULL，`tool_photo_id → assets` |
| `project_issues` | 2 | 问题清单：类型/描述/整改/客户回复/状态 + 两张图片 | `project_id → projects`，`process_id → project_processes`，`before/after_photo_id → assets` |
| `project_fixtures` | 8 | **夹具选型（项目级，一格一行）**：一行 = 一个模具中心下的一个格子，含名称/价格/工期快照与"是否报价"勾选 | `project_id → projects`，`fixture_center → fixture_centers`、`fixture_id → fixtures`（都 SET NULL） |
| `project_gauges` | 10 | **检具选型（项目级，一格一行）**：一行 = 一个检具类别下的一个格子，含名称/图号/尺寸快照/价格/设计周期/制造周期与勾选 | `project_id → projects`，`gauge_category → gauge_categories`、`gauge_id → gauges`（都 SET NULL） |
| `project_versions` | 108 | 保存版本（`kind='save'`）+ 页面版本履历（`kind='history'`）。保存版本带整份快照 `state_json`（图片走附件引用） | `project_id → projects` |
| `project_changes` | 43 | 变更流水：一行 = 一次改动里的一个实体，`label` 是人话、`extra_json` 带结构化 diff | `project_id → projects` + 8 个 SET NULL：`version_id`/`history_row_id → project_versions`、`process_row_id`/`tool_row_id`/`issue_row_id`、**`fixture_row_id → project_fixtures`、`gauge_row_id → project_gauges`**，另有老列 `selection_row_id`（可空、新库不建外键，见下） |
| `assets` | 17 | 附件库（图片/文档），按内容 sha 去重落盘 —— 历史快照里的图片也指向这里，不再内联 base64 | — |
| `project_selections` | 9 | **已废弃**的老多态表（选型拆表前，夹具/检具挤在一张表里用 `kind` 区分）。现在只当**搬迁来源**：老库打开时数据会按 kind 搬进上面两张表，行 id 照搬；新库不再创建这张表 | `project_id → projects` 等 5 个（老库上留着，不影响任何东西） |

> **为什么拆**：一张多态表里，夹具那几列和检具那几列各有一半永远为空（约束写不出来、
> 索引也只能建半张），页面上"夹具选型/检具选型"两件事却要读同一张表。
> 拆开之后每张表只装一种东西，外键、索引、CHECK 都能按各自的口径写死；
> 迁移与读模型逐字节比对见 `tools/migrate_selection_split.py`。

## 2. 基础库（8 张 = 4 张本体 + 4 张字典，表之间也是真外键）

| 表 | 行 | 说明 | 关键外键 |
| --- | --- | --- | --- |
| `machines` | 27 | 设备库：品牌/型号/行程/精度/快移/换刀/转速/价格 + 图片与资料 | `photo_id`/`doc_id → assets` |
| `tools` | 761 | 刀具库：类型 `tool_group` + 类别 `category` + 直径/转速/进给/寿命/价格 | `tool_group → tool_groups.code`，`category → tool_categories.code`，`photo_id → assets` |
| `tool_groups` | 4 | 刀具类型字典（外键目标） | — |
| `tool_categories` | 49 | 刀具类别字典（外键目标，`scope` 区分加工/刀柄/配件等） | — |
| `fixtures` | 177 | 夹具库：加工中心 + 名称 + 价格/工期 | `center → fixture_centers.name`，`photo_id → assets` |
| `fixture_centers` | 4 | 加工中心字典（外键目标） | — |
| `gauges` | 437 | 检具库：类别 + 名称 + 图号 + 尺寸 + 价格/工期 | `category → gauge_categories.name`，`photo_id → assets` |
| `gauge_categories` | 5 | 检具类别字典（外键目标） | — |

> `equipment`（设备库拆表**之前**的旧壳，288 KB、含内联图片）**已经清掉了**：
> 线上 `library_schema_version = 2`，`_migrate_machine_library()` 一进门就 return，
> 这份数据早就没人读；而且它和 `machines` 的 id 一个都对不上。
> `SCHEMA` 里也已不再创建它 —— 只保留一个能力：老库（还没到 2）里如果还有这张表，
> 迁移仍会拿它当搬迁来源（`_table_exists` 判断）。其余四张库旧壳
> （`tools/fixtures/gauges/equipment_legacy_v1`）随旧副本一起清掉了。

## 3. 系统表（3 张）

| 表 | 行 | 说明 |
| --- | --- | --- |
| `app_settings` | 13 | 站点设置 + 各阶段的能力级别键（`project_business_version` 等） |
| `auth_settings` | 2 | 两个角色的密码（salt + 迭代哈希） |
| `assets` | 17 | 见上（同时属于业务与库） |

## 3.1 逻辑删除三列（阶段 4 加的，8 张表各一份）

`machines` / `tools` / `fixtures` / `gauges` 与四张字典表（`tool_groups` / `tool_categories` / `fixture_centers` / `gauge_categories`）都加了 `deleted_at` / `deleted_by` / `deleted_reason`（可空）与 `(deleted_at, sort_order)` 索引。
这两套列**不动外键、不动既有行**：删除只是打标记，回收站里随时恢复；项目里的引用（`machine_id` / `tool_id` / `fixture_id` …）照旧指向那一行，读模型一个字节都不变（口径 2 没有彻底删除、没有保留期）。

## 4. 外键总账（21 张表共 48 个外键列）

* **挂在项目上**：`project_settings` / `project_processes` / `project_process_tools` / `project_issues` /
  `project_fixtures` / `project_gauges` / `project_versions` / `project_changes`
  各有一个 `project_id → projects.id`（NO ACTION）；
* **指向基础库**：`project_processes.machine_id → machines`、`project_process_tools.{tool,handle,accessory}_id → tools`、
  `project_fixtures.{fixture_center → fixture_centers, fixture_id → fixtures}`、
  `project_gauges.{gauge_category → gauge_categories, gauge_id → gauges}`，
  删库行一律 `SET NULL`（价格/寿命早有快照，项目数字不受影响）；
* **指向附件**：14 个 `*_photo_id`/`doc_id → assets.id`
  （项目信息 4 + 工序 1 + 刀具行 1 + 问题清单 2 + 设备 2 + 刀具 1 + 夹具 1 + 检具 1）；
* **流水指向被改的行**（3b）：`project_changes` 那 8 个 SET NULL 外键（工序/刀具行/问题/夹具格/检具格/两版/履历行），
  加上 `project_id` 一共 9 个。**老列 `selection_row_id` 例外**：它指向已废弃的 `project_selections`，
  新库不创建那张表，所以这一列在新库里只是普通可空列（老库上那个外键留着也不影响）。

`tools/audit_foreign_keys.py` 会核对"清单里要求的外键都在"，`PRAGMA foreign_key_check` 与
`integrity_check` 现在都是干净的。

## 5. 还剩多少 JSON（2026-09-18 实测）

| 位置 | 体积 | 是什么 |
| --- | --- | --- |
| `project_versions.state_json` | 699 KB（108 行，最大约 6.5 KB／平均 6.5 KB） | **每次保存的整份快照** —— 口径 1"每次保存都留版本且全部保留"，回滚与"看第 N 版"都靠它。含 `data:image` 的快照 = **0 份**（图片走附件引用；第 91 版那张老键名 `G.bInspImg` 也在 2026-09-18 抽成附件了） |
| `project_changes.extra_json` | 3.1 KB | 流水的结构化 diff（人话在 `label`） |
| `projects.state_json` | **全部是 `{}`**（2 个项目，0 字节业务数据） | 壳（业务数组都在表里；口径 7 之后，**新建/另存为的项目也当场落表**，这里不再堆影子副本；老项目用 `tools/catchup_project_tables.py` 补迁，补完也是 `{}`） |
| `project_settings.extra_json` | 1.1 KB | 建模之外的键（`lang` 等） |
| 各类 `*_snapshot` / `count_json` | 约 1 KB | 选刀/选设备/选型当时的价格与寿命快照（口径 4）、工序节拍 |
| **合计** | **约 825 KB**（库文件 1.83 MB） | 清之前是 1767 KB |

## 6. 怎么再看一遍

```powershell
.venv\Scripts\python.exe tools\audit_foreign_keys.py          # 外键总账 + PRAGMA foreign_key_check
.venv\Scripts\python.exe tools\check_business_gate.py         # 开关级别与表是否对得上
.venv\Scripts\python.exe tools\migrate_selection_split.py --status      # 选型拆表迁到哪一步了
.venv\Scripts\python.exe tools\catchup_project_tables.py --status       # 还有没有"表空、JSON 满"的项目（口径 7）
.venv\Scripts\python.exe tools\clean_legacy_project_data.py --status    # 还有没有旧副本（含 project_selections 这张老表）
.venv\Scripts\python.exe tools\slim_version_snapshots.py --status       # 还有没有快照带着内联图片
.venv\Scripts\python.exe tools\list_machining_routes.py       # 工序模块的路由清单
# 想用图形工具看结构：sqlitebrowser / DB Browser 打开 data/machining_dfm/machining_dfm.sqlite3
```

## 7. 与改造前的对照（为什么现在是这样）

* 改造前：业务数据全在 `projects.state_json` 一个大 JSON 里（工序/刀具行/问题清单/选型/履历 + 四个基础库 + 图片 data URL）；
* 现在：每个域一张表、字段类型化、关联列全是真外键、附件进 `assets`、每次保存留一版快照、每个行级改动留一条流水；
* 页面看到的 `state.pr`/`state.is`/`state.vh`/`state.G` 是**读模型现算出来的旧形状**（给老前端与 PPT 导出用），
  库里并不存在第二份；
* **结构再调整（选型拆表 + 设备跟工序走）**：一张多态表拆成 `project_fixtures` / `project_gauges`，
  每道工序的设备改成显式外键 `project_processes.machine_id`（页面上在"工序"总表行内直接选），
  页签顺序改为「项目信息 → 工序 → 夹具选型 → 检具选型 → 问题清单 → 版本履历 → 工艺设置 → 四个基础库」，
  基础库与工艺设置退到后台。详见 `docs/MACHINING_REFACTOR_ACCEPTANCE.md`。
