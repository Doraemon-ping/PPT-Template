# 机加 DFM 重构验收报告（分支 `machining`）

> **⚠ 本文是当时那次验收的历史记录**，其中 `app/machining_dfm.py` / `app/machining_*.py`
> 的路径与行号是**当时**的写法。2026-09 分层重构后的代码骨架见 `docs/MACHINING_CODE_LAYOUT.md`
> （含"旧路径 → 新路径对照表"）。本文的结论与口径仍然有效，只有路径需要换算。

- 验收分支：`machining`，HEAD `48dd22f`（"拆分机加 DFM 表单服务为独立分支（machining）"，2026-09-17）
- 验收对象：工作区当前未提交的重构成果（`git status` 共 125 项变更，含 `app/machining_*.py` 拆分、19 张表建表与迁移工具、行级 API、前端页面拆分）
- 验收问题（用户口径）：**① 数据表是不是最小单元结构？② API 是否可用或多余？**
- 线上数据：`data/machining_dfm/machining_dfm.sqlite3`，实测 1,626,112 字节、19 张表。**本次验收全程未写线上库**（所有探针跑在 `_audit/probe*/data/machining_dfm/` 副本上，且每次前后比对 sha256 一致）。
- 结论一句话：**数据表结构"基本达标但有一个结构性漏洞"**（表本身是最小单元，但"每份数据只存一份"没闭环：新建/另存为仍落在 `projects.state_json` 里，且两种形态会互相遮蔽）；**API"可用且无崩溃路由"，但有 1 个真实 500、1 个超大返回体、32/127 条前端不可达（其中 12 条确认冗余 + 2 条家族冗余 + 6 条待确认）**。

---

## 一、验收方法与证据基线

| 手段 | 覆盖 | 结果 |
| --- | --- | --- |
| 路由全量枚举 | 127 条（GET 44 / POST 30 / PUT 16 / DELETE 23 / PATCH 14） | 无重复 path+method |
| 无 token 全路由扫（`_audit/probe_all.py`） | 127 条 | 39×200、44×401、19×410（探针自己提前归档造成）、13×422、8×404、**0×5xx、0 异常** |
| 写路径冒烟（`_audit/probe_writes.py`） | 83 步真写（建项目/工序/刀具行/问题/选型/图片/导出/回收站/改密） | **76 通过**，7 非 2xx（其中 1 个真实 500，5 个是探针参数错，1 个是归档后 410 属设计） |
| 分支自带测试（`pytest tests`） | 203 项 | **203 passed**（修完 5 项缺陷后为 **208 passed**；1 warning：starlette 弃用 httpx） |
| 修复复验（`_audit/verify_fixes.py`，跑在副本库上） | 5 组 | **全部通过**，线上库 sha256 前后一致 |
| 前端可达性（`_audit/usage_match.py` + `_audit/classify.py`） | 127 条路由 × 全仓引用 | 前端可达 95 / 不可达 32 |
| 库结构巡检（`_audit/db_struct_audit.py` 等） | 19 表 / 40 外键 | `PRAGMA foreign_key_check` 空、`integrity_check` ok、字典→库外键 0 孤儿 |
| 迁移对账（`_audit/reconcile_backups.py`） | 17 个备份库 vs 线上 | 未发现搬家丢数据（`vh` 履历本来就是 0 条，不是迁移丢的） |

---

## 二、问题①：数据表是不是最小单元结构？

### 2.1 达标的部分（真实结论，不是客套）

1. **实体拆表、一值一列、关联用真外键**：19 张表 = 项目业务 8 张（`projects`/`project_settings`/`project_processes`/`project_process_tools`/`project_issues`/`project_selections`/`project_versions`/`project_changes`）+ 基础库 8 张（`machines`/`tools`/`fixtures`/`gauges` + `tool_groups`/`tool_categories`/`fixture_centers`/`gauge_categories`）+ 系统 3 张（`app_settings`/`auth_settings`/`assets`）。共 **40 条外键**，全部指向主表或字典表。（**第二轮拆表后**：21 张表 / 48 条外键，`project_selections` 换成 `project_fixtures` + `project_gauges`，见第六节。）
2. **附件抽表彻底**：`assets` 内容寻址（唯一键 `kind+sha256+name`，实测 17 行 / 250,497 字节），所有图片列都是 `assets(id)` 外键；全库**没有一处 base64 内联**（`project_settings.extra_json` 里也没有）。
3. **字典表是真的字典表**：`tools.category`→`tool_categories`、`fixtures.center`→`fixture_centers`、`gauges.category`→`gauge_categories` 取值全部可解析（0 孤儿），删除字典行有 `RESTRICT` 保护。
4. **没有"大宽表塞一切"**：项目信息 1:1 进 `project_settings`（30 列），工序 1:N 进 `project_processes`（2 行），工序用刀 1:N 进 `project_process_tools`（25 行），问题 1:N 进 `project_issues`，选型一格一行进 `project_selections`（9 行：fixture 4 + gauge 5；**第二轮拆成** `project_fixtures` 8 行 + `project_gauges` 10 行）。**这是本次重构最实的成果**：改造前这些都在 `projects.state_json` 的 `pr`/`is`/`vh` 数组里。

### 2.2 不达标 1（严重）：双存储形态并存，"每份数据只有一份"没闭环

**现象**：同一套系统同时跑两种形态 —— 表形态 与 `projects.state_json` 老整份 JSON 形态；读模型按"**表里有行才认表**"回退。

- 线上实测（`_audit/final_numbers.txt`）：

  | 项目 | revision | `state_json` | 工序表 | 刀具行表 | 问题表 | 判定 |
  | --- | --- | --- | --- | --- | --- | --- |
  | `b1f78663…`（主项目） | 90 | **2 字节**（`{}`） | 2 | 25 | 2 | 表形态 |
  | `04ea8ca4…`（_副本） | 3 | **5,711 字节**（`pr`:2、`is`:2） | 0 | 0 | 0 | JSON 形态 |

- 代码路径：`app/machining_dfm.py`
  - `_stored_arrays()` (2142) / `_array_in_table()` (2164) 决定"这份数组要不要再写进 JSON"；
  - `create()` (2182) 建/另存为项目时**只写项目行 + settings + 版本 + 变更流水，不插 `project_processes`/`project_process_tools`/`project_issues` 任何一行**；
  - `update()` (2213) 同样走 `_stored_arrays`。
  - ⇒ **默认路径（新建、另存为副本）产出的项目天然落在老 JSON 形态**。
- **实测后果（可复现，属数据可见性事故）**：在 JSON 形态项目上，`GET /projects/{id}` 报 `state.pr=2`，而 `GET /projects/{id}/processes` 返回 **0 行**；此后只要做**一次**行级写（`POST /projects/{id}/processes`），读模型就整体切到表形态，`state.pr` 掉到 **1** —— 两条旧工序（连同其刀具行）从读模型里消失。原因是新旧两份数据本来就不同步，切换瞬间老的那份被屏蔽。
- 迁移工具齐备但**只能手工跑**、且不在启动/保存路径上自动触发：`tools/migrate_project_processes.py`、`migrate_project_versions.py`、`migrate_project_changes.py`、`migrate_library_trash.py`。
- 另一个副作用：**空库不可用**。能力开关默认关闭，新库（或没跑迁移工具的库）调行级 API 直接 409 `"工序落表尚未启用（请先运行迁移工具打开开关）"`。

**判定：不达标。** "最小单元结构"的核心口径是"同一份数据只有一个权威副本"。现在的实现是"两套结构 + 一个运行时裁决规则"，结构上仍保留 `projects.state_json` 这条第二写路径，属于**未完成的重构**，而不是可接受的设计选择。

> **整改实测（2026-09-18 补）**：按下面的方案 1 动手改过一版（`create()`/`update()` 落表 + 首写前自动迁移 + `_stored_arrays` 收口），**42 项既有测试当场失败**（203 → 163 通过）。失败原因不是实现有 bug，而是**这些测试固化的就是"双形态"这份旧契约**：它们用种子项目构造"JSON 里有 pr、表里 0 行"的现场，再做写操作断言"表里仍然 0 行/读模型回退 JSON"；一旦新建即落表，这些现场根本构造不出来。
> 结论：**P0-2 不是补丁级改动，而是契约变更**，必须连同测试口径一起改（涉及 `test_machining_process.py`、`test_machining_issue.py`、`test_machining_selection.py`、`test_machining_history.py`、`test_machining_changes.py`、`test_machining_dfm.py` 六个文件）。所以这一条已**回退**，代码树保持 205 项测试全绿，等口径拍板后再一次性提交。

**建议（三选一，按推荐度）**
1. **推荐**：`POST /projects` 与 `另存为` 改为在建项目时就走行级表（把 `state.pr/is/vh` 一次性拆分落表，复用 `app/machining_process.apply_split`），随后删除 `_stored_arrays` 的 JSON 兜底；对已有 JSON 形态项目在**打开时自动迁移**（一次性、幂等）。
2. 折中：保留 JSON 形态兼容，但**禁止同一项目两种形态并存**——建项目时强制落表，读模型去掉"表里没行就回退 JSON"的模糊裁决，改为按 `project_schema_version` 显式定型。
3. 补丁级（不解决结构问题，只止血）：在行级写之前自动跑一次该项目的迁移，并在 UI 提示"检测到旧格式，已自动转换"；同时把 `state.pr` 与表行数不一致的情况在 `GET /projects/{id}` 里显式暴露，不再静默遮蔽。

### 2.3 不达标 2：JSON 列残余过多，占库体积 38%

实测（`_audit/final_numbers.txt`）：

| 表 | 列 | 行数 | 总字节 | 说明 |
| --- | --- | --- | --- | --- |
| `project_versions` | `state_json` | 93 | **615,606** | 每次保存一份全量读模型快照，占全库 JSON 的 98.6%、占整库 38% |
| `projects` | `state_json` | 2 | 5,713 | 双形态的另一半（见 2.2） |
| `project_settings` | `extra_json` | 2 | 1,090 | 里面塞了 `insp/fixQ/fixQC/inspQ/lang` 与**嵌套快照 `_vSnap`**（快照里再套快照） |
| `project_changes` | `extra_json` | 28 | 1,505 | 只有 `name`/`revision` 两个键；文档宣称的"结构化 diff"名不副实 |
| `project_processes` | `count_json` | 2 | 90 | 固定 6 键（cc/co/mc_/sc/ac/it），实际是 6 个计数，可平铺成列 |
| `project_processes` | `machine_snapshot` | 2 | 270 | 同上，单对象 JSON |
| `project_versions`/`project_issues` | `extra_json` | 93/2 | 186/4 | **93 行全是 `{}`、2 行全是 `{}` —— 死列** |

**判定：部分不达标。** `project_versions.state_json`（版本快照）保留 JSON 是合理的（快照本来就该是不可变整体）；但 `count_json`、`machine_snapshot`、两个恒为 `{}` 的 `extra_json`、以及 `_vSnap` 嵌套快照，都不符合"最小单元"。

### 2.4 不达标 3：快照列"结构先行、数据全空"，口径 4 在线不可验证

| 表 | 列 | 有值/总行 |
| --- | --- | --- |
| `project_process_tools` | `tool_price_snapshot` / `tool_life_snapshot` / `tool_handle_price_snapshot` / `tool_accessory_price_snapshot` | **0/25**（全空） |
| `project_selections` | `name_snapshot` / `drawing_snapshot` / `price_snapshot` / `days_snapshot` / `design_days_snapshot` | **0/9**（全空） |
| `tools` | `price` / `life_minutes` / `length` | **0/761**（全空） |
| `machines` | `price` / `doc_id` / `doc_name` | **0/27**（全空） |
| `fixtures` | `process_days` / `remark` / `photo_id` | **0/177**（全空） |
| `gauges` | `design_days` / `process_days` / `photo_id` | **0/437**（全空） |

已用 `_audit/seed_vs_db.py` 对种子 JSON 逐字段核对：**是种子数据本身没有这些字段**（而 fixtures/gauges 的种子**有**价格字段），不是迁移丢的。⇒ 快照列（口径 4："源库删掉后项目按快照价算"）在线上**永远取不到值**，这一口径实际未被验证过。

### 2.5 空转列 / 死列清单（建议清理或补用途）

- `project_versions.kind='history'` 路径 **0 行**（93 行全是 `kind='save'`）：`GET/POST/PATCH/DELETE + restore` 整套"版本履历"5+3 条 API 和 `vh` 数组、`extra_json` 列在线上从未被使用。
- 13 张业务表都带 `deleted_at/deleted_by/deleted_reason`（含 `deleted_at` 索引），线上**逻辑删除行数 0/全部**：回收站功能是新增能力，尚无使用记录（结构先行，可接受，但应知悉）。
- `assets.name` 全部为空串（`name_column` 机制空转）。

### 2.6 结构与数据不一致：`machines` 表有两条完全相同的索引 —— ✅ 已修

```
CREATE INDEX idx_machining_dfm_machines_sort  ON machines(sort_order, id)
CREATE INDEX idx_machining_dfm_machines_order ON machines(sort_order, id)   ← 完全重复
```

同表还有 `brand_model`、`trash` 索引，功能正常；重复索引纯属冗余，删除其一即可。

**实际修法（已落地）**：查清了根因——`_sort` 是**老命名**，现行代码统一叫 `_order`（`app/machining_library.py` 的 `index_ddl()`），只有 `machines` 表留着老名字的残留（其余 8 张库表的索引名都是 `_order`）。所以在 `create_indexes()` 里开库时顺手 `DROP INDEX IF EXISTS idx_machining_dfm_<表>_sort`，老库下次打开自动清理。回归测试：`tests/test_machining_dfm.py::test_stale_sort_index_is_cleaned_on_open`。

### 2.7 概念耦合（"最小单元"口径上可商榷，建议记入待办）

1. **`project_versions` 一表两义**：`kind='save'` 是"全量读模型快照"（93 行、615 KB），`kind='history'` 是"4 键履历（dt/ver/ds/by）"（0 行）。两种实体的列集与用途完全不同，靠 `CHECK` 约束硬塞一表。建议拆 `project_version_snapshots` + `project_version_history`。
2. **`project_selections` 多态一表**：`kind='fixture'`(4 行) 与 `kind='gauge'`(5 行) 列集不相交（`fixture_id`/`fixture_center` vs `gauge_id`/`gauge_category`），靠 `kind` + CHECK 保证。当前有约束兜住，**可接受**，但若继续加"选型类型"应拆分。
   → **第二轮已按这条建议拆掉**：`project_fixtures` + `project_gauges` 两张表，`kind` 列随之消失（见第六节）。
3. **基础库 `bootstrap` 反向依赖项目 JSON**：`app/machining_dfm.py` 里读默认库时会去取"最新项目的 `state_json`"（`_latest_project` 相关逻辑），属于跨上下文耦合；`GET /bootstrap` 一次回 260 KB（含全量库），建议改为按需分片。

### 2.8 逐表判定汇总

| 表 | 行数 | 判定 | 说明 |
| --- | --- | --- | --- |
| `projects` | 2 | ⚠️ 保留 | 主键/状态列干净；`state_json` 是双形态残留，必须处理 |
| `project_settings` | 2 | ✅ | 1:1 宽表合理；但 4 个图片槽位同 kind，是 500 缺陷现场（见 3.2） |
| `project_processes` | 2 | ⚠️ 保留 | 行级正确；`count_json`/`machine_snapshot` 两个 JSON 列建议平铺 |
| `project_process_tools` | 25 | ✅ | 行级正确；3 个 `tool_id` 靠库表 `scope` 区分，需文档说明 |
| `project_issues` | 2 | ✅ | 行级正确；`extra_json` 恒 `{}` 属死列 |
| `project_selections` | 9 | ⚠️ 保留（**第二轮已拆表**，见第六节） | 当时判"一格一行正确；多态一表，约束已兜住"——实际用起来仍然是"一张表装两种东西"，第二轮拆成 `project_fixtures` / `project_gauges` |
| `project_versions` | 93 | ❌ | 一表两义 + 615 KB JSON 快照；`kind='history'` 死路径 |
| `project_changes` | 28 | ✅ | 流水表，`extra_json` 内容偏薄 |
| `assets` | 17 | ✅ | 内容寻址 + 外键全库引用，设计最好的一张表 |
| `machines` | 27 | ⚠️ 保留 | 重复索引；`price`/`doc_id`/`doc_name` 全空 |
| `tools` | 761 | ✅ | 761 行字典正常；`price`/`life_minutes`/`length` 全空 |
| `fixtures` | 177 | ✅ | 正常；`process_days`/`remark`/`photo_id` 全空 |
| `gauges` | 437 | ✅ | 正常；`design_days`/`process_days`/`photo_id` 全空；`name` 有 2 行含换行（脏数据） |
| 4 张字典表 | 4/49/4/5 | ✅ | 真字典表，无孤儿引用 |
| `app_settings`/`auth_settings` | 13/2 | ✅ | 能力开关与账号，合理 |

---

## 三、问题②：API 是否可用或多余？

### 3.1 可用性：可用（无崩溃路由）

- 127 条路由全扫：**0 个 5xx、0 个未捕获异常**。
- 83 步写路径冒烟 76 通过，覆盖：建项目、改项目信息（客户/零件/机台数 3/夹具价 1200.0）、改进度（feed_rate=800.0）、4 个图片槽位上传/清空、工序 CRUD、刀具行 CRUD、问题 CRUD、选型、历史、导出 `export.zip`（25 个条目：`project.json` + `assets/*.jpg`）、配置读写往返、库整体替换往返（machines 28 / tools 762）、改密+登录+回滚、归档/恢复/删除、回收站查看与恢复。
- 203 项自带测试全通过。
- 附带说明：`pytest` 在受限沙箱下会因临时目录权限（WinError 5）报 200 个 fixture 错误，属环境限制、非产品缺陷；放行后 203 passed。

### 3.2 缺陷清单（按严重度）

#### 🔴 P1 缺陷 1：`DELETE /projects/{pid}/photos/{slot}` 抛 500（外键约束失败）—— ✅ 已修

- **复现**（`_audit/probe_trigger.py` A 场景，稳定复现）：
  1. 新建项目；2. 同一张 PNG 传到 `product`；3. 同一张 PNG 传到 `product2`（两次上传共用同一个 `assets` 行 `05d15df7…`）；4. `DELETE /projects/{pid}/photos/product2` → **500** `{"detail":"服务器内部错误：FOREIGN KEY constraint failed","request_id":"902c47312095"}`。
- **根因**：`project_settings` 一行有 **4 个**附件列（`product/product2/blank_insp/final_insp`，其中 product 与 product2 同属 `kind='project_photo'`）。清某槽位时 `_release_asset` 判定"这张图还有没有人用"，而跳过逻辑的粒度是**整行**：
  - `app/machining_project.py:384-388` `_asset_in_use(..., skip_key=self.key_column, skip_value=skip)`
  - `app/machining_library.py:141-143` `if skip_key and table == skip_table and skip_value is not None: sql += " AND project_id<>?"` ← **整行被排除**
  - ⇒ 同一行里**兄弟槽位**的引用被当成"不存在"，于是 `app/machining_assets.py:269` 执行 `DELETE FROM assets WHERE id=?`，但另一列外键还指着它 → `sqlite3.IntegrityError: FOREIGN KEY constraint failed` → 500。
- **影响面已确认**：只有 `ProjectSettings` 传了 `skip=`（`app/machining_project.py:363` 与 `:401` 两处），其他表（`machines` photo/doc、`project_issues` before/after）**不传 skip，因此同样场景返回 200**（`_audit/probe_bugclass.py` 已对照验证）。即这是**项目图片槽位独有**的缺陷，两条入口都中招：单槽位 `PUT/DELETE /photos/{slot}` 与整份保存 `save()`。
- **触发条件（精确）**：同一张图被**同一项目的两个图片槽位**共用，且**没有别的行**也引用它。若别的项目也用了这张图，判定为"还在用"→ 不删 → 不报错（所以偶发、难查）。
- **建议修法**：把跳过的粒度从"整行"改成"整列"——`asset_used_elsewhere` 增加 `skip_column` 参数，在 `skip_table` 上生成 `(其他列 = ? OR ...) AND 被改列不算`；或更简单：删除前先 `UPDATE` 该列为 NULL（已经先改了），随后对该行**只排除被改列**其余列照常参与判定。顺带补一条测试：同项目两槽位同图 → 清除其一必须 200 且 `assets` 行保留。
- **实际修法（已落地）**：`asset_used_elsewhere(...)` 新增 `skip_column` 参数（`app/machining_library.py:110`），逐列拼条件：被改的那一行**只有被改的那一列**不算，同一行其它附件列照常参与"还有没有人用"的判定；两个调用点（`app/machining_project.py` 的 `save()` 与 `_assign_attachment()`）都传上 `skip_column`。
  踩过一个 SQL 三值逻辑的坑：先写成 `WHERE (列1=? OR ...) AND NOT (被改列=? AND 主键=?)`，被清空后该列是 `NULL`，`NOT(NULL)` 仍是 `NULL`，整行会被滤掉、等于没修，所以改成"逐列拼 OR"。
  回归测试：`tests/test_machining_dfm.py::test_two_photo_slots_sharing_one_image_do_not_break_clearing`（HTTP 路径）与 `::test_whole_state_save_sharing_one_image_between_slots`（整份保存路径）。

#### 🟠 P2 缺陷 2：行级写返回整份读模型（约 259 KB/次）

- 实测：`POST /projects/{pid}/processes` → **258,797 字节**；`PATCH /projects/{pid}/processes/{id}`（只改一个格子 `mc:3`）→ **258,797 字节**；`POST .../tools` → 258,974 字节；`GET /projects/{id}` → 258,962 字节；`GET /bootstrap` → 260,030 字节。
- 问题：任何一次格子编辑都要在网络上搬 259 KB（含全量基础库 761 刀具 / 177 夹具 / 437 检具），前端还得整页重渲染。建议行级写只回被改实体 + 新 `revision`，或支持 `?fields=`/`Prefer: return=minimal`。
- 附带契约问题：`POST /projects/{pid}/issues` 等**创建接口返回整份项目**而不是新建的那条记录（探针脚本因此误取 `id` 拿到项目 id，报 404 "问题清单记录不属于该项目"），调用方拿不到新行 id。

#### 🟠 P2 缺陷 3：`POST /projects/{id}/archive` 既废弃又无鉴权 —— ✅ 已修（鉴权）

- 前端自己写着"已废弃"：`static/machining_dfm/host.js:48` —— `// 老路径 POST /projects/{id}/archive 仍在，只是页面不再用它。`
- 实测无 token 直接 `200`（`_audit/sweep_results.json`），而同组的 `DELETE /projects/{id}`、`POST /projects/{id}/restore` 均返回 401 `{"detail":"请先登录后台"}`。⇒ **一个无需登录就能归档项目的后门**（归档后项目在读模型里不可用、`GET /projects/{id}` 变 410）。
- 建议：删除该路由，或至少补上与其他写路由一致的 admin token 依赖。
- **实际修法（已落地）**：保留路由（前端已不用，但 `tools/check_trash_page.mjs` 还在调），**补上与其他写路由一致的 admin 鉴权**（`app/machining_dfm.py` 的 `archive_project`）；返回体形状不动，避免连带破坏老调用方。测试里补了"无 token → 401"的断言。是否最终删除，仍建议随"清理 12 条冗余路由"一起决定。

#### 🟡 P3 缺陷 4：`/api/logs/tail`、`/api/logs/download` 无鉴权 —— ✅ 已修

- `app/services/observability.py:36-43` 两个路由没有 token 依赖；无 token 实测 `200`，`download` 直接下载**全量服务器日志**（含所有项目名、id、请求路径）。若服务会暴露到非本机，建议加管理员鉴权或仅本机绑定。
- **实际修法（已落地）**：`install(app, name, guard=None)` 新增可选 `guard` 回调（`app/services/observability.py`），机加服务传入"管理员才放行"的校验（`app/services/machining.py` 的 `_guard_logs`，复用后台配置那套密码）。不传 `guard` 的服务行为不变（其他分支/服务不受影响）。实测无 token → 401、带 admin token → 200。

#### 🟡 P3 缺陷 5：422 文案误导 —— ✅ 已修

- 实测 `PATCH /projects/{pid}/issues/{id}` 传 `{"st":"已关闭"}` → 422 `"状态只能是：进行中（进行中）、已完成（已完成）"` —— 枚举值与显示名相同，提示等于没说。
- **实际修法（已落地）**：显示名与取值相同时不再套括号（`app/machining_library.py` 的 `_text()`），现在报 `"状态只能是：进行中、已完成"`。
- 根因的另一半（**同一字段两套键名**）仍未动：PATCH 里短键 `st` 与表列名 `status` 同时被接受（`{"status":…}` 有效、`{"st":…}` 也有效），`mc`/`dc`/`rmk` 对应 `process_days`/`design_days`/`remark` 同理。统一键名会影响前端与老调用方，建议单独立项。

### 3.3 多余 / 不可达 API 清单（前端不可达 32/127）

判定标准：静态前端（`static/machining_dfm/*.js`，含 `cfg.endpoint`/`cfg.dictionary`/`ROW_SEGMENTS`/slot 变量等动态拼路径，已人工复核）+ 工具脚本 + 测试 + 文档 全仓引用。

**A. 确认冗余，建议删除（12 条）**

| 路由 | 依据 |
| --- | --- |
| `POST /projects/{id}/archive` | `host.js:48` 自述"页面不再用它"；且无鉴权（见 P2-3） |
| `GET /project-settings/fields` | 前端**从列表响应里拿** `fields`（`project_info.js` 甚至自己硬编码了一份 FIELDS） |
| `GET /tools/fields` | `tools.js:78-80` 用的是 `GET /tools` 响应里的 `fields`；`tools.js:5` 的注释"来自 GET /tools/fields"**已过期**，只有测试还在打这条路由 |
| `GET /machines/fields` | `machines.js:46` 从列表响应取 `fields` |
| `GET /fixtures/fields` | `library_pages.js:78` 从列表响应取 `fields`（仅 `tools/live_fixture_gauge_e2e.py` 在引用） |
| `GET /gauges/fields` | 同上 |
| `POST /fixtures/reorder` | 前端夹具页无重排 UI（只有 `machines.js:214` 与 `tools.js:301` 用了 reorder），无任何调用方 |
| `POST /gauges/reorder` | 同上，仅测试引用 |
| `POST /projects/{pid}/processes/reorder` | 无调用方（仅 `app/machining_dfm.py:2836` 定义） |
| `POST /projects/{pid}/issues/reorder` | 同上（`app/machining_dfm.py:2733`） |
| `POST /projects/{pid}/history/reorder` | 同上（`app/machining_dfm.py:2799`） |
| `POST /projects/{pid}/processes/{proc}/tools/reorder` | 仅测试引用 |

**B. 家族冗余，建议合并（2 条）**

| 路由 | 依据 |
| --- | --- |
| `GET /tool-dictionaries` | 前端从 `GET /tools` 响应的 `fields.choices` 取组/类字典（`tools.js:63-75`），无调用方 |
| `GET /library-dictionaries` | 前端从 `GET /config`/各库列表取，无调用方 |

**B2. 建议先确认再删（6 条，目前仅测试引用）**

`POST/PATCH/DELETE /tool-groups/{code}` 与 `POST/PATCH/DELETE /tool-categories/{code}`：前端没有"刀具字典"编辑页（夹具/检具字典走 `library_pages.js` + `cfg.dictionary`，已达前端），这 6 条只有测试在打。若近期不打算做刀具字典页，应一并删除或明确标注为管理端专用。

**C. 保留（合理的外部件/运维面，不计冗余）**

`GET /health`、`GET /`、`GET /docs`、`/redoc`、`/openapi.json`、`GET /api/logs/*`（运维，但需补鉴权）、`GET/POST /api/ppt-provider/v1/*` 4 条（PPT 工作台的跨服务契约，另有 `GET /api/integration/workbench-link` 前端实际在用 `host.js:46`）。

**D. 前端可达但机制重复（建议收敛，非缺陷）**

回收站有**三套**恢复入口：`/trash/{table}/{id}/restore`、`/projects/{pid}/trash` 内的行恢复、以及各实体自己的 `/restore`；项目删除走 `DELETE /projects/{id}?reason=`，归档走 `/archive`。语义重叠、鉴权不一致，建议合并为一套。

### 3.4 契约一致性问题（不影响可用性，影响可维护性）

1. 返回体不统一：`POST /projects` 返回**裸记录**，`POST /projects/{pid}/processes` 等返回 `{"project": {...}}`（整份读模型）。
2. 同一资源两套键名：`st`/`status`、`mc`/`process_days`、`dc`/`design_days`、`rmk`/`remark`（见 P3-5）。
3. 写路由鉴权不齐：`.archive` 无 token；`/api/logs/*` 无 token；其余写路由要 admin。

---

## 四、验收结论与整改优先级

**验收结论：有条件通过。** 重构主体（表拆分、外键、附件抽离、行级 API、203 项测试）质量达标，具备继续迭代的基础；但"最小单元结构"这条验收口径**未闭环**，且有 1 个稳定复现的 500。

| 优先级 | 事项 | 状态 / 建议动作 |
| --- | --- | --- |
| **P0** | 新建/另存为仍落 JSON 形态 + 双形态互相遮蔽（2.2） | ⏸ **待拍板**：已实测改动会破 42 项测试（属契约变更），代码已回退；定了口径就一次性改代码 + 改测试 |
| **P0** | `DELETE /photos/{slot}` 500（3.2-1） | ✅ **已修**：跳过粒度改"整列"，2 条回归测试（HTTP + 整份保存） |
| **P1** | 行级写回 259 KB 整份读模型（3.2-2） | 未动（改返回体要前端同步改，建议单独立项） |
| **P1** | `POST /projects/{id}/archive` 无鉴权且已废弃（3.2-3） | ✅ **已修（鉴权）**；是否删除随"冗余路由"一起决定 |
| **P2** | `/api/logs/*` 无鉴权（3.2-4） | ✅ **已修**：`install(..., guard=)` 可选鉴权，机加服务传 admin 校验 |
| **P2** | 前端不可达 32 条中的 A+B 组 14 条冗余路由、B2 组 6 条待确认（3.3） | 未动（删路由要同步改测试与 `tools/*.mjs`，建议按组一次性清理） |
| **P2** | 快照列与库价格字段全空（2.4） | 未动（要补种子数据，属产品/数据决定） |
| **P3** | JSON 残余列（2.3） | 未动（`count_json`/`machine_snapshot` 可平铺，属结构演进） |
| **P3** | 重复索引 `idx_..._machines_order`（2.6） | ✅ **已修**：开库时清掉老命名的 `..._sort` 残留，1 条回归测试 |
| **P3** | `project_versions` 一表两义、`kind='history'` 死路径（2.7） | 未动（要定"履历功能留不留"） |
| **P3** | 422 文案与键名统一（3.2-5/3.4） | ✅ **文案已修**；键名统一未动（见 3.2-5） |

---

## 五、整改记录（本次已落地的 5 项）

改动文件：`app/machining_library.py`、`app/machining_project.py`、`app/machining_dfm.py`、`app/services/observability.py`、`app/services/machining.py`、`tests/test_machining_dfm.py`。

| # | 问题 | 改法 | 验证 |
| --- | --- | --- | --- |
| 1 | 同项目两图片槽位共用一张图时 `DELETE /photos/{slot}` 500 | `asset_used_elsewhere` 增加 `skip_column`，逐列拼 OR 条件：只排除"被改的那一行的那一列" | `_audit/verify_fixes.py` 第 3 组（副本库上实测 200 且兄弟槽位仍在、`assets` 不误删）；2 条新测试 |
| 2 | 旧归档入口 `POST /projects/{id}/archive` 无 token 可用 | 补 admin 鉴权（与 `DELETE /projects/{id}` 同口径），返回体形状不变 | 第 2 组：无 token → 401、带 admin → 200 且 `archived=true` |
| 3 | `/api/logs/tail`、`/api/logs/download` 裸奔 | `install()` 增加可选 `guard` 回调；机加服务传"管理员才放行" | 第 1 组：无 token → 401、带 admin token → 200 |
| 4 | `machines` 表两条一模一样的索引 | 开库时 `DROP INDEX IF EXISTS idx_machining_dfm_<表>_sort`（老命名残留） | 第 4 组：副本库开库后只剩 `_order`；1 条新测试 |
| 5 | 422 提示"进行中（进行中）" | 显示名与取值相同时不再套括号 | 第 5 组：报 `状态只能是：进行中、已完成`；1 条新测试 |

**测试基线**：改动前 203 passed → 改动后 **208 passed**（新增 5 条回归测试）。

**安全约束**：全部验证跑在线上库副本（`_audit/probe8`）上，`DFM_APP_ROOT` 指向副本；本次验收开始与结束时线上库 sha256 一致（`fd776895e5c11050…`，1,802,240 字节）。

---

## 六、结构再调整（第二轮：把工序/设备/选型重新围绕"项目"排）

**触发**：用户指出"各个工序和检具夹具选型应该围绕项目来，现在结构不清晰"，
要求按「创建项目 → 填项目信息 → 选设备、选检具、选夹具」的逻辑改，
并对照**原工艺维护**的逻辑（工艺维护是服务于项目的）。

### 6.1 改前的结构问题（用户说的"不清晰"具体是什么）

| # | 改前 | 为什么不清晰 |
| --- | --- | --- |
| 1 | 页面上**每道工序一个页签**（`工序-OP10`、`工序-OP20`…），几道工序就有几个页签 | 项目与工序的关系被抹平成"平级页签"，工序一多页签就糊成一片；没有"项目 → 工序"的层级感 |
| 2 | 选型（夹具/检具）挤在一张多态表 `project_selections` 里，夹具的列与检具的列各有一半永远为空 | 一张表装两种东西：外键、索引、CHECK 都只能按"最松"的那一边写；页面上两件事读同一张表 |
| 3 | "换设备"走整份 `PUT /projects/{id}`（把整份 state 发回去） | 改一道工序的设备要整份保存：既慢又容易覆盖别人的改动，也说不清"到底改了哪一行" |
| 4 | 基础库（设备/刀具/夹具/检具）与工艺设置跟业务页签平级、夹在中间 | 基础库是**维护**用的，不是每个项目每天要点的东西；跟"这个项目的工序/选型"混在一起，主线看不清 |

### 6.2 改后的结构（现在的逻辑）

```
项目（projects）
 ├─ 项目信息（project_settings）          客户/零件/工时口径/尺寸重量/4 张图
 ├─ 工序（project_processes）             ← 一页总表：每行一道工序，**行内直接选设备**
 │    └─ 工序刀具明细（project_process_tools）  点进单道工序看刀具（详情视图，仍在这一个页签里）
 ├─ 夹具选型（project_fixtures，项目级一份）    一行 = 一个模具中心下的一个格子
 ├─ 检具选型（project_gauges，项目级一份）      一行 = 一个检具类别下的一个格子
 ├─ 问题清单（project_issues）
 ├─ 版本履历（project_versions + project_changes）
 └─ 后台：工艺设置 · 设备库 · 刀具库 · 夹具库 · 检具库
```

页签顺序（`legacy_app.js` 里 `SI=4` 是基准，序号已固定）：

`0 项目信息` `1 工序` `2 夹具选型` `3 检具选型` `4 问题清单` `5 版本履历`
`6 工艺设置` `7 设备库` `8 刀具库` `9 夹具库` `10 检具库`

### 6.3 具体改了什么

**数据层（表 = 最小单元，对齐用户口径）**

* 新增两张**项目级**表，替掉多态表：
  * `project_fixtures`：`project_id` + `sort_order`（格子号）+ 快照（名称/价格/工期）+ `quoted` + `fixture_center → fixture_centers`、`fixture_id → fixtures`（都 SET NULL）；
  * `project_gauges`：同上，另有图号快照与设计周期，外键指 `gauge_categories` / `gauges`；
  * 两张表**都没有 `kind` 列**——"这一行是什么"由表本身决定，不再靠一个字符串列区分。
* `project_changes` 增加 `fixture_row_id` / `gauge_row_id` 两个真外键（老列 `selection_row_id` 留着但新库不建外键：
  它指的老表在新库里不存在，建了外键整张流水表都插不进去）；老库用 `ALTER TABLE ADD COLUMN` 就地补列，不重建表。
* `project_processes.machine_id` 成为**设备选择的唯一权威**（页面上"每道工序一台设备"），
  读模型的 `mid` 仍按快照回退——与口径 4（库行删掉不影响项目数字）一致。
* 老表 `project_selections` 只当**搬迁来源**保留，`_ProjectRows` 新增 `extra_columns` 钩子用于这类"只读老列"。

**接口层**

* `PUT /projects/{id}/processes/{proc_id}/machine`（空值 = 清空 → 回退兜底机型，库里有价则同步 `eqP`）与
  `DELETE …/machine`：换设备不再走整份保存。
* `GET|PUT|PATCH|DELETE /projects/{id}/fixtures/{slot}` 与 `…/gauges/{slot}`：两类选型各有自己的路径；
  老的 `GET /projects/{id}/selections` 保留为"两类一起读"的兼容入口。

**页面层**

* 「工序」收成**一页总表**：每行一道工序（名称、行内设备下拉、台数、刀具数、节拍、月产能、操作），
  点行进入该工序的刀具明细（`openProc(pi)`），详情页有「← 返回工序总表」；
  **添加工序不再新增页签**（冒烟里专门断言"添加工序后页签数不变"）。
* 「夹具选型」「检具选型」独立成两个页签，与项目级的两张表一一对应；
  原来塞在"工艺设置"里的选型块搬了出来，工艺设置只剩成本表/导出/公式。

### 6.4 数据搬迁与验证（跑在线上库的真实数据上）

* **搬迁工具**：新增 `tools/migrate_selection_split.py`（`--status` 只读 / 默认干跑 / `--apply` 真搬）。
  它先整库备份，再把老表每一行按 `kind` 搬进两张新表（**行 id 照搬**），最后逐项目比对**读模型逐字节一致**——
  不一致就报错停手（库已备份，可回退）。
* **搬迁结果（线上库，2026-09-18 22:59）**：
  * 主项目 `b1f78663…` 来源 = 老表 9 行（夹具 4 + 检具 5），行 id 全部对上；
  * 副本项目 `04ea8ca4…` 来源 = `extra_json` 里的四个数组（夹具 4 + 检具 5）——两条路都走到了；
  * 搬家前后读模型**逐字节一致**（页面四个数组一个字都没变）、`foreign_key_check` 干净、`integrity_check=ok`；
  * 备份：`data/machining_dfm/backups/pre-selection-split-20260918-225938.sqlite3`；
  * 老表 9 行**原样留着**（搬迁来源 + 天然备份），要清用 `tools/clean_legacy_project_data.py`。
* **懒迁移**：万一没跑迁移工具，用户第一次点任何一格选型时，服务端会先把老数据整份搬进两张新表
  （静音，不记流水），再存那一格——否则"点第一格只建那一行"，别的格子会看着空。
  这条路径有单独测试（`test_selection_writes_are_recorded` 断言首写是"改行"而非"建行"）。
* **回归**：`pytest tests` **220 passed**（原 208 → 第二轮结构再调整期间新增/改写选型结构、流水分列、
  懒迁移共 4 条；口径 7 落地又加 `tests/test_machining_project_tables.py` 8 条）；
  `tools/check_process_wiring.py`（前端接管完整）、`tools/check_business_gate.py`（能力级别与表对上）、
  `tools/audit_foreign_keys.py`（外键总账干净）、`tools/smoke_machining_page.mjs`（**全部检查通过**，
  含新页签结构、工序总表行内选设备、添加工序不增页签）、`tools/check_trash_page.mjs`（**全部检查通过**）。

### 6.5 顺带被这套结构暴露出来、这次一起加固的点

* `clear_slot` 增加"这一格本来就空就不写"的判断：否则懒迁移建好格子后，点一下清空会**白记一个版本**。
* 系统搬数据一律**静音**（`_quiet_changes`）：懒迁移不往流水里灌"新增夹具选型"这类无中生有的记录。
* `tools/audit_foreign_keys.py` 增加 `LEGACY_TABLES` / `LEGACY_FKS`：老库上还存在的老表与老外键
  只展示、不判错，新库则要求"清单里要求的外键都在"。

### 6.6 口径 7：新建项目（含「另存为新项目」）也必须落表

**问题（真实数据上验出来的）**：页面的「另存为新项目」走的是
`POST /projects {name, state}`（整份读模型一起发过来）。改之前这条路只把 state 写进
`projects.state_json`，业务表**一行都不建**：

* 线上副本项目 `04ea8ca4…`（rev=3）：`state_json` 5711 字节（2 道工序 + 2 条问题），
  而 `project_processes` = 0 / `project_tools` = 0 / `project_issues` = 0
  （只有懒迁移补出来的 4 夹具格 + 5 检具格）；
* 读模型看着有工序（表里没行就回退 JSON），但 `GET /projects/{id}/processes` **返回 0 行**
  → 页面上那些工序行**没有行 id** → 改名、选设备、配刀具这些行级保存全都做不了，
  只能整份保存；两份存储（JSON 与表）从此各走各的。

**改法**（`app/machining_dfm.py`）：

* 新增 `MachiningDFMStore.import_state(project_id, state)`：把整份读模型**逐域**拆进表 ——
  `apply_split`（工序 + 刀具）、`apply_issue_split`（问题清单，工序外键按工序名绑上）、
  `split_selections`（夹具/检具两张表）、`create_project_history`（版本履历行）；
  最后按"表里已经有行的那几域"重算 `state_json` —— 正常情况下就是 `{}`（**不留影子副本**）。
* `create(..., import_tables=True)`：`POST /projects` 路由传 `True`（产品路径），
  存储层默认 `False`（测试/迁移工具要用"只写 JSON"的老形状来验"从 JSON 拆进表"这段逻辑）。
  这样改的动静最小 —— 早先直接把 `create()` 改成"总是拆表"时打挂了 52 条测试，
  因为那些测试正是靠"表空、JSON 满"的老形状在验迁移逻辑。
* **逐域幂等**：某一域表里已经有行（含已逻辑删除）就跳过那一域，绝不"先清空再灌"（口径 2）。
* **逐域兜底**：某一域拆失败（外键指向的库行不存在等）就把**这一域这次刚建的行**删掉、
  让这一域干净地回到"只在 JSON 里"，并报 422 —— 不会出现"一半在表、一半在 JSON"。
* 机器/刀具的绑定**不依赖请求里带没带 `mdb`/`tdb`**：没有就取服务端自己的库表（`list_legacy()`），
  否则 `mid` 绑不上设备行、刀具的 `cat/hld/acc` 也会丢。
* 履历那一域先把 `vh` 从 JSON 里摘掉再逐行落表：读模型有一条"表里没有就从 `state_json.vh` 就地补建"
  的老逻辑，JSON 里还留着这一份的话，建一行会被补建逻辑看出"还缺"，于是**灌成两份**。

**补迁已有项目**：新增 `tools/catchup_project_tables.py`（`--status` / 默认干跑 / `--apply` 先整库备份），
判据就是"这一域表里没有行、而 JSON 里有数据"。核对口径比迁移工具松一格：
**原有字段一个都不能丢，只允许多出派生/默认值**
（`_ct/_vc/_vf/_fz` 读时算的、`cat/hld/acc/fi` 刀具库绑定结果、`cI/eqP/fixP` 工序空槽位）——
线上真实数据本来就带派生值（页面写出来的），所以选型拆表那次用的是"逐字节一致"；
而手写的裸数据走表会补一批默认值，逐字节并不成立，硬套只会得到假失败。

**线上补迁结果（2026-09-18 23:16）**：

* `04ea8ca4…` 拆了 processes、issues → `project_processes` 2 行、`project_issues` 2 行，
  `state_json` 变 `{}`；字段一个没丢；`foreign_key_check` 干净、`integrity_check=ok`；
* 备份：`data/machining_dfm/backups/pre-catchup-tables-20260918-231652.sqlite3`；
* 重启服务后核对：两个项目的 `GET /projects/{id}/processes` 都是 **2 行且每行都有行 id**
  → 「另存为」出来的项目现在可以行级编辑（改名/选设备/配刀具都走单行接口）。
* 新增 `tests/test_machining_project_tables.py`（8 条）：拆进表 + JSON 清空、行 id 与工序外键、
  派生/默认值只多这一批、逐域幂等、能力级别关掉的域留在 JSON、HTTP 创建后能行级改名。

**顺带修掉的一个巡检盲区**：`tools/slim_version_snapshots.py` 原来按写死的键名清单
（`pI/pI2/bI/fI/img/photo`）找内联图片，于是漏掉了老键名 `G.bInspImg` —— 它先报"内联图片：无"，
实际上第 91 版快照里还躺着 95.9 KB base64。现在改成**按值认**（顶层与 `G` 里任何 `data:image/` 开头的字符串），
抽取后 `--apply`：图片 sha256 与原内联字节逐一核对相同、108 份版本号与时间逐条不变、
`foreign_key_check` 干净，库 1.84 MB → 1.74 MB。

### 6.7 又两个被"加深检查"逼出来的真缺陷（都是数据层的，已修）

这一轮把 `tools/check_export_assets.mjs` 的附件断言写严之后，线上数据立刻顶出两件事：

**（1）历史快照里的图片会变成死链 —— 而且已经发生了**

* 判定"这张图还有没有人用"的 `asset_used_elsewhere()` 只扫**声明了 `assets(id)` 外键的列**；
  而版本快照（`project_versions.state_json`）里记的是附件 **URL**，不带外键 →
  用户换一张产品图，老版本里的那张就被回收掉，回滚过去是死链。
* 线上实测：第 17/18/22/26/30/34/38/40 版共 8 处快照指着 **7 个已经不存在**的附件；
  字节在当前库与三份整库备份里都找不到了（`_audit/probe_missing_assets.py` 逐一查过）→ **不可恢复**。
* 修法：新增 `app/machining_library.py::asset_in_snapshots()`，`asset_used_elsewhere()` 先问它 ——
  快照还引用着就当"有人用"、**绝不删**。代价是换图时旧图不回收（存储换"回滚图还在"，符合口径 1）。
  回归测试：`tests/test_machining_project_tables.py::test_replacing_a_photo_keeps_the_asset_a_snapshot_still_points_at`。
* 巡检工具同时写清楚：那 7 个按**已知清单**放行（`KNOWN_DEAD_ASSETS`，逐条注明第几版），
  清单外的任何新死链都会让检查失败 —— 不假装通过，也不让它继续涨。

**（2）整份保存会把 base64 写进永久快照**

* `create()` / `update()` 原来拿**请求里的原值**做版本快照：页面上传的那张产品图
  （60 KB `data:image/png;base64,…`）就被写进第 1 版快照。快照永久保留（口径 1）→
  "库里只存图片引用、不存 base64"当场破功。线上就有一个这样的项目
  （用户在页面上新建的项目「11」，第 1 版 `G.pI` = 60638 字符）。
* 修法：`MachiningDFMStore._materialise_inline_images()` —— 落库前先把整份 state 里
  任何 `data:image/…` 值落成附件、换成附件地址（按所在键决定附件分类：项目四图 / 工序示意图 /
  问题前后图 / 刀具图），**再做快照**。两条整份写入口（`create` 与 `update`）都走它。
  回归测试：`test_inline_image_in_the_submitted_state_never_reaches_the_database`、
  `test_whole_state_save_also_converts_inline_images`。
* 线上那个项目的第 1 版快照用 `tools/slim_version_snapshots.py --apply` 瘦掉了
  （图片 sha256 与原内联字节核对相同、版本清单逐条不变），现在全库 `data:image` 命中 **0 行**。

**这一轮的最终验证（全部现场跑过）**

| 项目 | 结果 |
| --- | --- |
| `pytest tests` | **223 passed** |
| `tools/check_process_wiring.py` | 前端接管完整（每个写入点走行级保存，流水只由服务端记） |
| `tools/check_business_gate.py` | 级别 5、该有的表都在、外键干净 |
| `tools/audit_foreign_keys.py` | 清单里要求的外键都在 ✓ |
| `tools/catchup_project_tables.py --status` | 3 个项目全部已落表（没有「表空、JSON 满」） |
| `tools/slim_version_snapshots.py --status` | 内联图片：无 |
| `tools/migrate_selection_split.py --status` | 选型已搬进两张新表 |
| `tools/smoke_machining_page.mjs` | 全部检查通过 ✓ |
| `tools/check_trash_page.mjs` | 全部检查通过 ✓ |
| `tools/check_export_assets.mjs` | 全部检查通过 ✓（内联图 0 行；已知历史死链 7 个单列） |
| 线上 HTTP 抽查 | 3 个项目的 `GET /projects/{id}/processes` 都有行 id、`projects.state_json` 全是 `{}` |


---

## 七、复现命令

```powershell
# 环境
$env:PYTHONIOENCODING='utf-8'

# 1) 路由清单 + 前端可达性 + 冗余判定
.venv\Scripts\python.exe _audit\list_routes.py          # -> _audit/routes.json
.venv\Scripts\python.exe _audit\usage_match.py          # -> _audit/usage.txt, usage_raw.json
.venv\Scripts\python.exe _audit\classify.py             # -> _audit/classify.txt, api_classification.json

# 2) 库结构与线上数据体检（只读）
.venv\Scripts\python.exe _audit\db_struct_audit.py
.venv\Scripts\python.exe _audit\db_column_audit.py
.venv\Scripts\python.exe _audit\seed_vs_db.py
.venv\Scripts\python.exe _audit\final_numbers.py        # -> _audit/final_numbers.txt
.venv\Scripts\python.exe _audit\reconcile_backups.py    # 备份库对账，查迁移丢数据

# 3) 全路由扫 + 写路径冒烟 + 缺陷复现（均跑在 data 副本上，不动线上库）
.venv\Scripts\python.exe _audit\probe_all.py            # -> _audit/probe_all.txt, sweep_results.json
.venv\Scripts\python.exe _audit\probe_writes.py         # -> _audit\probe_writes.txt, write_smoke.json
.venv\Scripts\python.exe _audit\probe_trigger.py        # 500 的精确触发矩阵（A 场景必现）
.venv\Scripts\python.exe _audit\probe_bugclass.py       # 对照：issues/machines 同场景不报错；行级写返回体大小

# 4) 自带测试
.venv\Scripts\python.exe -m pytest tests -q             # 220 passed（第二轮结构再调整 + 口径 7 之后）

# 5) 选型拆表（第二轮）：先看状态 → 干跑（副本上逐字节比对）→ 真搬（先整库备份）
.venv\Scripts\python.exe tools\migrate_selection_split.py --status
.venv\Scripts\python.exe tools\migrate_selection_split.py
.venv\Scripts\python.exe tools\migrate_selection_split.py --apply

# 6) 前端与接线自检（起服务后跑，服务在 127.0.0.1:8002）
.venv\Scripts\python.exe tools\check_process_wiring.py
node tools\smoke_machining_page.mjs                     # 页签结构 + 工序总表行内选设备
node tools\check_trash_page.mjs                         # 回收站 + 版本履历/变更流水
```

---

## 附录 A：本次验收产出的证据文件（均在 `_audit/`）

`routes.json`（127 条路由）、`usage.txt` + `usage_raw.json`（全仓引用矩阵）、`classify.txt` + `api_classification.json`（可达性最终判定）、`probe_all.txt` + `sweep_results.json`（全路由扫）、`probe_writes.txt` + `write_smoke.json`（写冒烟 83 步）、`probe_500.txt`（500 现场）、`probe_defects.txt`、`reconcile.txt`（备份对账）、`final_numbers.txt`（线上数字基线）、`fe_paths2.txt`（前端路径抽取）、`verify_fixes.py`（5 项修复的副本复验，改动后新增）。探针脚本同名 `.py` 可复跑（会自动建库副本，不触线上）。

## 附录 B：线上数据与运行态说明（重要）

1. **本次验收未修改线上数据**：所有探针把 `DFM_APP_ROOT` 指到 `_audit/probeN`，跑在副本上；每次探针前后比对线上库 sha256 一致。验收结束时线上库为 1,626,112 字节 / revision 90。
2. 验收期间线上服务**一直在跑**（`run_service.py`，PID 5164 / 6596，127.0.0.1:8002，20:50 启动）。`data/machining_dfm/logs/server.log` 显示验收窗口内有真实请求落库：`21:21:08 PUT /api/machining-dfm/projects/b1f78663…`（整份保存 → revision 89→90、`project_changes` +1、`project_versions` +1）、`21:21:33 GET …/export.zip`；另有 `20:57` 两次对 `04ea8ca4…`（副本）的整份保存。**这些写入不是本次验收探针造成的**（探针全部隔离在副本上，且 203 项测试使用 `tmp_path` 独立库）。如需纯净基线，请在停止服务后重新采集 `_audit/final_numbers.py`。
3. 线上库 `04ea8ca4…` 是"另存为副本"，它的形态（`state_json` 5,711 字节 + 业务表 0 行）本身就是 2.2 条缺陷的**现场证据**，不是人为构造。

---

## 附录 C：第二轮（结构再调整）对线上数据做过什么

第二轮**动过线上数据**，而且是刻意动的——拆表就是把老表的数据搬到新表里。全部动作与证据：

| 动作 | 工具 | 证据 |
| --- | --- | --- |
| 打开老库时补建两张新表、给流水表补两列 | 服务启动（`MachiningDFMStore` 建表 + `ensure_late_columns`） | 库从 19 张表 → 21 张；`project_changes` 出现 `fixture_row_id`/`gauge_row_id` |
| 复盘：先在**副本**上验证搬迁不改读模型 | `_audit/probe_selection_split.py` | 副本 `_audit/probe8~10`；每个探针前后线上库 sha256 一致 |
| 真正搬迁 9 行老选型数据（按 kind 分表） | `tools/migrate_selection_split.py --apply` | 备份 `pre-selection-split-20260918-225938.sqlite3`；读模型逐字节一致；`foreign_key_check` 干净 |
| 只读体检（能力级别 / 外键 / 表结构） | `tools/check_business_gate.py`、`tools/audit_foreign_keys.py`、`_audit/check_live_split.py`、`_audit/db_inventory.py` | 结果见 6.4 节 |

搬迁后线上库基线（2026-09-18 22:59）：**21 张表 / 1.83 MB / sha256 `fd555c9d4aa40fd4…`**，
`project_fixtures` 8 行、`project_gauges` 10 行、`project_selections` 9 行（原样留着）、
`project_versions` 108 行、`project_changes` 43 行、`foreign_key_check` 干净、`integrity_check=ok`。

第二轮期间服务一直在跑（`run_service.py`，127.0.0.1:8002）；页面自检（`smoke_machining_page.mjs`、
`check_trash_page.mjs`）发出的写请求**由脚本自己拦下**，不落库；期间 `revision` 的增长来自用户浏览器上的正常使用。
