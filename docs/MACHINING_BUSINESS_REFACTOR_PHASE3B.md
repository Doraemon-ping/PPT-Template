# 阶段 3b 实施：变更流水落表（`project_changes`）

> 前置设计见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3_DESIGN.md` 第 4 节（表结构已按本文件第 2 节的
> 差异做了修订）。3a（版本履历 `project_versions`）见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3.md`。
> 本阶段只做**服务端记录 + 只读接口**，界面留到阶段 4 与回收站一起做。

## 1. 一句话

**每次行级改动都留一条"谁、什么时候、把哪一行、从什么改成什么"**，落在 `project_changes` 一张表里；
每条流水都指向"这一次保存"的那一版快照（`version_id`），以及被改的那一行（五个行外键之一）。

流水**不是**页面上某个按钮触发的，而是**行级写入的副产物**：页面上改了哪一行，服务端就在
**同一个事务**里记一条。所以这一阶段前端**一个写入点都没加**（反而是"前端零写入点"变成了验收项）。

## 2. 与设计文档的差异（拍板内容之外的增补，逐条说明）

设计文档里定的核心口径一条没改：**四个"被改的行"外键 + `version_id → project_versions(id)`、
`ON DELETE SET NULL`、写入时"恰好挂一个"、回填留空**。实现时按真实写入点补了三处：

| 项 | 设计文档 | 实现 | 为什么 |
| --- | --- | --- | --- |
| `entity` 取值 | `project`、`settings`、`process`、`tool`、`issue`、`selection` | 再加 **`history`** | 版本履历（3a）本身就是页面上可增删改的一行，改它必须留痕；不加这一类，"谁删了那条履历"就查不到 |
| `action` 取值 | `create`、`update`、`delete`、`restore`、`reorder`、`photo` | 再加 **`save`** | "整份保存"（旧 `PUT /projects/{id}`）不是上面任何一种：它一次写的是整个项目文档。硬套 `update` 会让"改了哪一行"看起来像改了一行 |
| 行外键列 | `process_row_id`、`tool_row_id`、`issue_row_id`、`selection_row_id` | 再加 **`history_row_id → project_versions(id)`** | 与 `version_id` 指同一张表，但语义完全不同：一个是"被改的那条履历行"，一个是"这一次保存的版本"。共用一个列会把两个意思搅在一起 |

另外两处**约束写法**上的修订（都是实现时被真实场景逼出来的，不是口味问题）：

- 设计文档写"CHECK 保证**恰好**挂一个"。实现改成 **"最多挂一个 + 挂上的那一列必须与 `entity` 对应
  （`settings`/`project` 一列都不挂）"**。原因：五个行外键都是 `ON DELETE SET NULL`，目标行被物理
  删掉时列会被置空——"恰好一个"会把 `SET NULL` 这步顶掉，SQLite 直接报
  `IntegrityError: CHECK constraint failed`，连"删掉一行"都做不成（写这版时真踩到了，
  `tests/test_machining_changes.py::test_check_allows_row_to_become_null` 就是那条回归点）。
  **"写入时必须挂上"由写入方保证**，单测逐条断言了每种实体的流水都挂着对应的行。
- `reorder`（排序调整）是**整表操作**，不针对某一行：它记的流水五列全空（`extra_json` 里带行数）。

`entity`/`action` 的全量字典（也是接口返回值里的字典）：

| `entity` | 中文 | 挂哪一列 |
| --- | --- | --- |
| `project` | 项目 | 无（整项目） |
| `settings` | 项目信息 | 无（整项目） |
| `process` | 工序 | `process_row_id` |
| `tool` | 工序刀具行 | `tool_row_id` |
| `issue` | 问题清单 | `issue_row_id` |
| `selection` | 选型报价 | `selection_row_id` |
| `history` | 版本履历 | `history_row_id` |

`action`：`create` 新增 / `update` 修改 / `delete` 删除 / `restore` 恢复 / `reorder` 排序 /
`photo` 换图 / `save` 整份保存。

## 3. 表结构

`app/machining_changes.py`：`CHANGES_TABLE = "project_changes"`、`CHANGES_VERSION = 5`。

```sql
CREATE TABLE project_changes(
    id TEXT PRIMARY KEY,                       -- <项目 id>-c<本版序号>-<本版内第几条>
    project_id TEXT NOT NULL REFERENCES projects(id),
    sort_order INTEGER NOT NULL DEFAULT 0,     -- 与 project_versions.revision 同源，用来排序/分组
    "entity" TEXT NOT NULL DEFAULT 'process',
    "action" TEXT NOT NULL DEFAULT 'update',
    "label" TEXT NOT NULL DEFAULT '',          -- 给人看的一句话（"工序 OP10 精铣：设备台数 1→3"）
    "extra_json" TEXT NOT NULL DEFAULT '{}',   -- 兜底：by/reason/cascade/字段明细/has_asset…
    "version_id" TEXT REFERENCES project_versions(id) ON DELETE SET NULL,   -- 这一次保存的那一版
    "process_row_id"   TEXT REFERENCES project_processes(id)     ON DELETE SET NULL,
    "tool_row_id"      TEXT REFERENCES project_process_tools(id) ON DELETE SET NULL,
    "issue_row_id"     TEXT REFERENCES project_issues(id)        ON DELETE SET NULL,
    "selection_row_id" TEXT REFERENCES project_selections(id)    ON DELETE SET NULL,
    "history_row_id"   TEXT REFERENCES project_versions(id)      ON DELETE SET NULL,
    deleted_at TEXT, deleted_by TEXT NOT NULL DEFAULT '', deleted_reason TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL, updated TEXT NOT NULL,
    CHECK (entity IN (…七种…)),
    CHECK (action IN (…七种…)),
    CHECK ((process_row_id IS NULL) + (tool_row_id IS NULL) + (issue_row_id IS NULL)
           + (selection_row_id IS NULL) + (history_row_id IS NULL) >= 4),        -- 最多挂一个
    CHECK (process_row_id IS NULL OR entity='process'),   -- …五列各一条：挂上的必须与实体对应
    CHECK (entity NOT IN ('project','settings') OR 五列全空)
)
```

- **七个关联列全是真外键**（用户要求"有关联的数据结构全部使用外键约束"）：项目、保存版本、
  五个"被改的行"。建索引的是 `project_id`、`sort_order`、`version_id` 与五个行外键；
- 五个行外键 + `version_id` 一律 `ON DELETE SET NULL`：目标行被物理删掉时**流水行留着**
  （`label` 里写着当时改的是谁）——历史不因为删行而消失；
- `id` 形如 `b1f7866…-c12-1`：`-c<本版序号>` 与那一版的 `revision` 对得上，肉眼就能看出"这批改动属于第几版"；
- `_ProjectRows` 基类本来就有 `deleted_at/by/reason`，所以"隐藏某条流水"将来（阶段 4）不用改表。

## 4. 记录口径

| # | 情形 | 记不记 | 说明 |
| --- | --- | --- | --- |
| 1 | 行级写入：新增/修改/删除/恢复/排序/换图 | 每次一条 | 包括工序、工序刀具行、问题清单、选型格子、版本履历五张表 |
| 2 | 级联：删工序时它的刀具行一起进回收站 | **逐行各一条** | 写"随工序删除"，恢复时同样写"随工序恢复" |
| 3 | 项目信息（`PATCH /settings`） | 一条 `settings/update` | 标签里逐个字段写"旧值→新值" |
| 4 | 整份保存（`PUT /projects/{id}`） | 一条 `project/save` | 标签写"整份保存：<项目名>（第 N 版）" |
| 5 | 新建项目 | 一条 `project/create` | |
| 6 | 系统自己搬数据（老 `state_json.vh` 就地补建成履历行） | **不记** | `_quiet_changes()` 静音：这是系统补建，不是用户改动（"不无中生有"） |
| 7 | 被拒的写入（422/409/410/404） | **不记** | 草稿只在事务里落库；事务回滚就连草稿一起没 |
| 8 | 迁移工具搬旧数据 | **不记** | 迁移直接调引擎方法，那时开关还没开到 5；而且 3b 本来就不回填流水 |
| 9 | 开关打开**之前**发生过的改动 | **不追溯** | 流水表迁移后是 0 行：要查历史改动的样子看那一版的完整快照。回填等于编造历史 |
| 10 | 读（列表/详情/报表/导出） | 不记 | 只读不写库 |
| 11 | 提交上来的字段**一个都没变**（页面上"失焦即保存"会发很多次这种请求） | **不记** | 流水是一句人话，不是访问日志；`update()` 里"真变了才记" |

**写在同一个事务里**：`_bump_project()` 里先写快照（`revisions` + `project_versions` 的 save 行），
拿到这一版的 `revision`，再 `_flush_changes(db, pid, revision)` 落流水 —— 与快照同一个事务提交。
这样只有两种结局：**要么"改动 + 这一版快照 + 这一批流水"都在，要么都不在**，
不会出现"流水说改了、快照里没有"这种对不上的中间态。

## 5. 标签怎么生成（`label`）

流水行的可读性全在这句话上，规则写在 `_ProjectRows` 里（五张表共用）：

- **行标题** `row_title()`：按每张表声明的 `title_keys` 取字段拼起来（工序 `nm`、刀具行 `code tp`、
  问题 `tp ds`、选型 `row_title()` 重写成"夹具第 N 格（名称）"、履历 `ver dt`），超 60 字截断加 `…`；
- **改了什么** `_diff_fields()` + `_diff_label()`：先算出**提交上来的字段里真正变了的**那些
  （`[{key,label,before,after}]`，整份存进 `extra_json.fields`，信息不丢），再把前 6 项写成一句话
  （更多就写"等 N 项"）；字段名用登记表的 `label`；纯符号字段（`n`/`vf`/`D`/`L`…）补中文名
  →"转速 n 3000→3500"；
- 值的展示过 `display_value()`：布尔给"是/否"、空串给"（空）"、数字过 `js_number()`（与页面一致）；
- 图片槽用中文名：`change_slot_labels`（照片/布局图/修改前/修改后/资料；刀具行是"刀具图"）
  →"工序刀具行 T01 D50盘铣刀：换图（刀具图）"；
- 一条 `label` 上限 400 字（`LABEL_LIMIT`），`extra_json` 里另存结构化明细（`fields`、`by`、`reason`、`cascade`）。

## 6. 服务端接线（`app/machining_dfm.py`）

- **门禁**：`self.changes_enabled = self.business_version >= 5`；建表、表对象、`changes_table` 标志都在这一档；
- **表对象**：`self.change_table = ProjectChanges(...)`（**不能**叫 `self.changes` —— 会盖掉 `changes()` 方法，
  项目里已经因为这个踩过两次，所以统一叫 `*_table`）；
- **记录入口**：`self._note_change(action, *, row=None, label="", record_id=None, extra=None)`
  → 只往 `self._pending_changes` 里放**草稿**（不写库）；
- **落库**：`_flush_changes(db, pid, revision, created=…)` 在 `_bump_project()` 的同一个连接里
  `insert_drafts()`（原生 INSERT，`version_id` = `save_row_id(pid, revision)`）；
- **写入点**：五张表的引擎把 `change_sink` 指向 `_note_change`（`_ProjectRows` 的 create/update/
  soft_delete/restore/reorder/set_attachment_value 各记一条，级联删除/恢复由
  `ProjectProcessTools.soft_delete_by_process/restore_by_process` 逐行记）；
  `ProjectProcesses.set_machine`、`ProjectSelections`（格子写入）、`ProjectVersions.reorder_history`
  各自补记；项目信息与整份保存由 store 层记；
- **静音**：`@contextmanager _quiet_changes()` —— `_ensure_history_rows()`（老履历就地补建）在里面跑；
- **只读接口**：`GET /api/machining-dfm/projects/{project_id}/changes`（`limit`/`entity`/`action`/`recycle`）；
- 没开关时：接口 **409** 并给出要跑哪个工具（不 500、也不偷偷建表）；读模型里 `changes_table=false`。

## 7. 接口

```
GET /api/machining-dfm/projects/{pid}/changes?limit=200&entity=&action=&recycle=false
```

返回：`{enabled, table, count, limit, entities, entity_labels, actions, action_labels, changes:[…]}`
（新的在前）。每条：`id, sort_order, entity, action, label, extra, version_id, version_revision,
version_name, 五个 *_row_id, deleted_at/by/reason, created, updated`（不含 `project_id`，调用方已经知道）。

- `entity`/`action` 传空串 = 不筛；`recycle=true` 给"被隐藏的流水"（阶段 4 用）；
- **没有写接口**：流水是追加型日志，`store` 上连 `create_project_change` 这类方法都没有（单测断言）。

## 8. 前端：零写入点（这一阶段的验收项之一）

页面**不写也不读** `/changes`：流水是服务端副产物，界面（时间线视图）留到阶段 4 与回收站一起做。
这一条是可查的，不是口头约定：

- `tools/check_process_wiring.py` 第 5 节：扫描每个页面 JS/HTML，**出现写 `/changes` 的请求即失败**；
  同时核对引擎里六种动作都记流水、五张表都声明了 `change_entity`、服务端三处接线都在；
- `tools/smoke_machining_page.mjs` 的"变更流水（3b）"一节：跑完上面几十个行级写入之后，
  **请求日志里一条 `/changes` 都没有**，而且页面 JS 文件里连 `/changes` 这个字符串都不出现；
- 记录里带 `changes_table` 标志（页面能判断服务端开没开这一批），但不塞任何"待渲染的流水数组"。

## 9. 迁移（`tools/migrate_project_changes.py`）

**这一阶段不搬旧数据**：流水从打开开关那一刻开始记（口径 5）。所以"迁移"只有三件事：
建表、写版本键 = 5、逐字节验证"打开开关没有改变任何既有读模型"。

```powershell
.venv\Scripts\python.exe tools\migrate_project_changes.py --status   # 只读：版本键/表/流水行数/实体分布
.venv\Scripts\python.exe tools\migrate_project_changes.py            # 干跑（副本；前置没迁会先在副本上补跑 1b→3a）
.venv\Scripts\python.exe tools\migrate_project_changes.py --apply    # 真迁移：先整库备份，再建表 + 写版本键 = 5
.venv\Scripts\python.exe tools\migrate_project_changes.py --keep     # 干跑后保留副本目录
```

前置：版本键 ≥ 4（3a 已迁）。`--apply` 只允许对线上目录使用，且**不会**在线上跑"写入探针"
（那才是真无中生有）；探针只在干跑副本上跑。

干跑逐项验证（`--apply` 跑前 5 条）：

1. 表在，且**七个真外键**都在（`PRAGMA foreign_key_list` 逐个核对，不是看建表 SQL 字符串）；
2. **开关打开后每个项目的读模型与打开前逐字节相同**（只多一个 `changes_table` 标志）；
3. 老数据的流水行数 **0 → 0**（不无中生有；重复跑第二遍还是 0，幂等）；
4. `GET /changes` 清单结构可用（`enabled=true`、实体 7 种、动作 7 种）；不存在的项目给明确 404；
5. `PRAGMA foreign_key_check` 干净、没有悬空的 `project_id` / `version_id`；
6. **功能探针（只在副本上）**：真写 18 笔（建项目 → 工序增改删恢复 → 刀具行增改换图 →
   问题增改 → 选型格子 → 履历增改 → 项目信息 → 整份保存 → 排序），逐条核对：
   七种实体、六种动作都记上了；每条流水都挂着被改的那一行、`version_id` 指得到那一次保存
   （`kind='save'` 且属于本项目）；被拒的写入（非法状态 422）一条都没留；
   记流水**不影响**保存版本（`project_versions` 的 save 行与 `revisions` 依旧逐字节相同）；
   写完之后 `foreign_key_check` 依旧干净。

回滚：把 `app_settings.project_business_version` 改回 4 —— 表留着不碍事，写入点只是不再记流水。

## 10. 测试与验收

```powershell
.venv\Scripts\python.exe -m pytest tests -q                # 全部 179 项（3b 新增 29 项）
.venv\Scripts\python.exe -m pytest tests -q -k changes     # 只跑这一阶段：tests/test_machining_changes.py
.venv\Scripts\python.exe tools\migrate_project_changes.py            # 干跑：见上面 6 条验证
.venv\Scripts\python.exe tools\audit_foreign_keys.py --with-process  # 26 张表，清单里要求的外键都在 ✓
.venv\Scripts\python.exe tools\check_process_wiring.py               # 前端写入点 + 流水"只由服务端记录"
node tools\smoke_machining_page.mjs                                  # 整页真跑（130 项通过，含 3b 一节）
.venv\Scripts\python.exe tools\check_served_page.py                  # 线上资源版本号与 200
```

`tests/test_machining_changes.py` 覆盖：门禁（4 不开 / 5 才开 / 不开也照样写行）、七个真外键
（凭空 id 插不进去、目标行物理删掉时 `SET NULL` 且不挡删除）、CHECK（实体与列不匹配拒绝、
`settings` 不许挂行、一次挂两列拒绝、未知实体/动作拒绝、目标行没了必须仍然合法）、
每个写入点都留一条（含级联删除/恢复、换图、排序、选型格子、履历、项目信息、整份保存）、
`version_id` 指得到"这一次保存"、标签可读性与截断、被拒写入不留痕、系统搬数据不记流水、
只读清单（按项目隔离/筛选/回收站列表/软删列）、没有写接口、以及"记流水不影响保存版本
（save 行与 `revisions` 逐字节相同）"。

## 11. 已知边界与后续

- **界面没做**：流水的展示（时间线/按版本分组）留到阶段 4，与回收站、版本对比一起做；
- **不追溯**：开关打开之前的改动没有流水（设计口径）；要"看到"历史改动只能看那一版的快照差异；
- **物理删行之后**：流水行的行外键会 `SET NULL`（`label` 里仍写着改的是谁）。真实口径下业务行只逻辑删除，
  所以正常路径不会出现；
- **`extra_json` 里有机器人可解析的结构化 diff**（`fields: [{key,label,before,after}]`），
  所以"字段级对比界面"（阶段 4）不用改表；
- **顺手修掉的两个真缺陷**（都是"打开开关才会走到"的路，所以线上一直没暴露）：
  1. `set_issue_photo()` 以前调的是 `self.assets.store(...)` —— 附件库根本没有这个方法，
     所以"问题清单上传图片"一调就是 500（3b 的流水要记这个问题图片，于是暴露出来）。
     现在与工序/刀具行图片（`_set_row_photo`）同一套写法，空内容 422，并补了单测；
  2. `ProjectProcesses.set_machine()` 直接 `machine.get(key)`，而 `Machines.find()` 返回的是
     `sqlite3.Row`（没有 `.get()`）—— 真服务上"换设备"一调就是 500。现在先统一成 dict，
     并且流水里写"型号"而不是 uuid；单测
     `test_machine_change_is_recorded_by_model_name` 就是这两个点的回归；
- 未迁移时 `GET /changes` 给 409（与其他 3a/2b 接口一致），前端不需要为它写降级分支（页面本来就不读）。

## 12. 改动文件

| 文件 | 改动 |
| --- | --- |
| `app/machining_changes.py` | **新增**：表结构/口径/标签/清单（`ProjectChanges`） |
| `app/machining_process.py` | 引擎加变更钩子（`change_entity/title_keys/change_sink/_note_change/row_title/display_value/_diff_label/change_label/change_slot_label`），工序/刀具行六种写入点 + 级联逐行记录，`set_machine` 记录 |
| `app/machining_issue.py` | `change_entity="issue"` + 标题字段 |
| `app/machining_selection.py` | `change_entity="selection"` + `row_title`（"夹具第 N 格（名称）"） |
| `app/machining_history.py` | `change_entity="history"`、`save_row_id()`、`reorder_history` 记录 |
| `app/machining_dfm.py` | 门禁 5、表对象、草稿落库（与保存版本同事务）、静音、只读接口、`changes_table` 标志；顺手修 `set_issue_photo` 500 |
| `tests/test_machining_changes.py` | **新增**：28 项单测 |
| `tools/migrate_project_changes.py` | **新增**：干跑/迁移/探针/验证 |
| `tools/audit_foreign_keys.py` | 登记 7 个新外键 + 6 条 `SET NULL` 说明；`--with-process` 档位到 5 |
| `tools/check_process_wiring.py` | 新增第 5 节：流水只由服务端记录（前端零写入点 + 服务端接线齐全） |
| `tools/smoke_machining_page.mjs` | 新增请求日志与"变更流水（3b）"一节 |
| `README.md`、`docs/MACHINING_BUSINESS_REFACTOR_PHASE3_DESIGN.md` | 文档同步 |
| `docs/MACHINING_BUSINESS_REFACTOR.md` | 阶段表更新（1b/2a/2b/3a/3b 已完成）+ `project_changes` 设计差异说明 |
| `tools/capture_process_cost_baseline.py` | 指纹不再包含 `revision`（见第 13 节第 3 条） |
| `tools/check_business_gate.py` | 状态感知：开关关着时核对"没有多出表"，开着时核对"该有的表都在 + 外键干净" |

## 13. 线上迁移记录（2026-09-18）

按顺序跑了三份 `--apply`（每份都先整库备份），线上库 20 张表 → **27 张**，
版本键 `project_business_version` 缺省 → **5**：

```powershell
python tools\migrate_project_processes.py --apply   # 15:43:25  备份 pre-project-business-20260918-154325.sqlite3
python tools\migrate_project_versions.py  --apply   # 15:43:30  备份 pre-project-versions-20260918-154330.sqlite3
python tools\migrate_project_changes.py   --apply   # 15:43:34  备份 pre-project-changes-20260918-154334.sqlite3
```

迁移结果与验证证据：

| 项 | 结果 |
| --- | --- |
| 拆表 | 工序 2 行、工序刀具行 25 行、问题清单 2 行、选型格子 9 行（每个类别一格，含未选型的格） |
| 保存版本 | `revisions` 65 行 → `project_versions` 65 个 `kind='save'` 行（快照与 `revisions` 逐字节相同） |
| 履历 | 老 `vh` 本来是空的 → 0 行（读模型按设计回退 `state_json.vh`） |
| 变更流水 | **0 行**（不追溯；第一条流水来自打开开关之后的第一次真实改动） |
| 读模型逐字节 | 迁移前（HTTP、开关 0）→ 迁移后（HTTP、开关 5）：`G` 1205 字节/`6b9e597afea0`、`pr` 5869/`5abe68681324`、`is` 205/`c4258e6e059e`、`vh` 2/`97d170e1550e` —— 四个全同（含键序） |
| 接口 | 工序 2 / 问题清单 2 / 选型格子 9 / 保存版本 65 / 履历 0 / 变更流水 0，六个读接口全 200 |
| 库体检 | `integrity_check = ok`、`foreign_key_check` 干净、`revisions` 影子副本 65 行一行没少 |
| 报价数字 | `tools/capture_process_cost_baseline.py --check` → **与基线完全一致**（合计、每行成本、诊断全同） |
| 报表契约 | `tools/live_report_snapshot_check.py` → 全部通过（字段 49 / 表格 9 / 图片 21，901 KB） |
| 页面 | 整页冒烟 `node tools/smoke_machining_page.mjs` → 全部检查通过（开关已开的状态下） |

三件与迁移本身无关、但迁移当天必须处理的工具问题（都已修）：

1. **`capture_process_cost_baseline.py` 的指纹把 `revision` 算进去了** —— 基线冻在 v41、
   线上已经 v65，于是"业务数字一位没变"也报 `× 与基线不一致`。现在指纹排除 `revision`
   （它只表示"又保存过几次"），侧边也把 `revision` 单列出来说明；改完 `--check` 是绿的；
2. **`check_business_gate.py` 只会说"开关关着"** —— 迁移后它没话说了。改成状态感知：
   关着时核对"业务表一张都不该多出来"，开着时核对"该有的表都在 + `foreign_key_check` 干净 +
   逐表行数"，两种状态各跑一次都验过（拿迁移前的备份当"关着"的样本）；
3. **冒烟脚本里那条"线上开关一定是关的"** —— 迁移当天必然变红，而它想验的是"标志与服务端一致"。
   改成核对 `changes_table === (business_version >= 5)`，与开关状态无关，迁移前后都绿。

**没有**跑的检查：`tools/live_process_e2e.py` 这类"对着线上写一遍再还原"的 e2e ——
开关打开之后它们会真的留下改动、版本和流水（`revisions` 里那 5 行内容相同的 v61-65 就是这么来的），
与本阶段"不无中生有"的口径冲突。写入路径的证据由**干跑副本上的 18 笔功能探针**与本阶段
29 项单测提供。

回滚（任一步都可以单独回）：把 `app_settings.project_business_version` 改回 4 / 3 / 删掉，
表留着不碍事；三份迁移前的整库备份都在 `data/machining_dfm/backups/`。

## 14. 清掉旧副本（口径 6，2026-09-18 同一天）

迁移完之后库里每种数据都有**两份**：表里一份（权威）+ 旧副本一份（回滚用）。
副本长这样：`projects.state_json` 里的 `pr`/`is`/`vh`、`revisions`（每次保存的整份快照）、
`projects_legacy_v1`/`processes_legacy_v1`（拆表前的整份 JSON）、
四张 `*_legacy_v1`（基础库类型化之前的旧壳）。8 张表 + 一行 6 KB 的 JSON，看结构时全是干扰，
而且同一份数据两条路走迟早跑偏。

**先发现的问题**：直接 `DELETE`／`DROP` 没用 —— 写路径会把一部分副本**重新长回来**。
在副本上演练过一次：删掉 8 处之后只保存一次，`state_json` 又变回 6081 字节、
`revisions` 又多了 2 行、`projects_legacy_v1` 又建了个空壳
（`processes_legacy_v1` 与四张库旧壳没回来，它们确实没人再写了）。

**所以先改代码（口径 6：哪一级落表了，那一级的影子副本就停写）**：

| 改哪儿 | 改成什么 |
| --- | --- |
| `SCHEMA` / `LEGACY_REVISIONS_SCHEMA` | 旧 `revisions` 表只在**开关 < 4**（旧路径还是权威）时才建 |
| `create()` / `update()` | 开关 < 4：照旧写 `revisions`、`state_json` 存三份数组；开关 ≥ 4：都不写 |
| `_stored_arrays()`（新） | `state_json` 逐键判断：**表能还原出这一份**才丢，表里没有而非空的老数组照旧留着（防"开关被人手动调到 4、表却是空的"） |
| `_write_snapshot()` | 快照只写 `project_versions`（开关 ≥ 4）；`revisions` 只在影子模式下写 |
| `_migrate_project_settings()` | `projects_legacy_v1` **只在真有东西要归档时才建**（不然每次开库都建个空壳） |
| `_rewrite_process_machine_refs()` / `_migrate_project_snapshots()` | `revisions` 表不在就跳过（不再当成必然存在） |
| `compose()` | 三份业务数组**永远是数组**：表是权威时"表里 0 行"就是空 `[]`，不能整个键消失（`state_json` 清空后原来会变 `undefined`） |

**清理动作**：`tools/clean_legacy_project_data.py`（默认干跑，`--apply` 先整库备份）：

```
python tools\clean_legacy_project_data.py --status     # 只读：还剩哪些旧副本
python tools\clean_legacy_project_data.py              # 干跑：副本上真删真验（含"再保存一次看会不会长回来"）
python tools\clean_legacy_project_data.py --apply      # 真清理（备份 → DROP 7 张表 → 清 state_json → VACUUM）
```

线上实测（2026-09-18 16:32）：

| 项 | 结果 |
| --- | --- |
| 删掉 | `revisions` 74 行、`projects_legacy_v1` 1 行、`processes_legacy_v1` 1 行、`equipment/fixtures/gauges/tools_legacy_v1` 共 1402 行 |
| `state_json` | 6081 字节（`pr`/`is`/`vh`）→ **`{}`** |
| 读模型逐字节 | `G` 1205/`6b9e597afea0`、`pr` 5869/`5abe68681324`、`is` 205/`c4258e6e059e`、`vh` 2/`97d170e1550e` —— 清理前后**四个全同** |
| 业务数据 | 工序 2 / 刀具行 25 / 问题清单 2 / 选型 9 / 保存版本 74 / 流水 9，一行没少 |
| 库体检 | `foreign_key_check` 干净、`integrity_check = ok` |
| 表数 / 体积 | 27 → **20 张**；8.05 MB → **2.57 MB**（VACUUM 之后） |
| 真停写 | 清理后线上又保存了 7 次（revision 74 → 81）：`revisions`、`projects_legacy_v1` 都没回来，`state_json` 仍是 `{}`，流水照记（9 → 16 条） |

**回滚口径变了，必须记住**：以前"删掉版本键就回到旧路径"；现在旧副本没了，
回滚 = 把 `data/machining_dfm/backups/pre-clean-legacy-20260918-163240.sqlite3`
复制回 `data/machining_dfm/machining_dfm.sqlite3`。**业务数据本身仍然全部在表里**
（这就是"删的只是重复那一份"的意思）。

**顺着这条口径要当心的三件事**（清理后都验过）：

1. **不许把能力级别往下调**。旧副本清了之后，级别 < 4 的读路径只能读 `state_json`，
   而那里已经是 `{}` —— 页面会变空（数据在表里，只是这一档不读）。`tools/check_business_gate.py`
   现在会把这种情况直接报成不一致，并提示"把级别调回去或从备份恢复"；
   三个迁移工具也早已在"级别已经 ≥ 目标档"时直接退出，不会去重建旧副本。
2. **新建库不会再长出旧副本**。`revisions` 只在级别 < 4 时才建；`projects_legacy_v1`
   只在真有东西要归档时才建；四张库旧壳只在"类型化的表还是空的"时候当搬迁来源。
3. **迁移工具的干跑要拿"迁移前的库"跑**。拿清干净的库去掉级别去干跑，
   会看到 `pr[] 迁移前 2 字节 → 现在 6974 字节` 这种"假红"——
   那是旧副本本来就已经不在了，不是迁移出问题。要看历史形态，用 `backups/` 里迁移前的备份。

### 14.1 再清两处（同一天稍晚，用户看过库结构之后）

用户问"为什么项目表还有大量 json"。查下来 `projects` 表本身已经是 2 字节的 `{}`，
"大量 json" 是另外两处：

| 位置 | 体积 | 是什么 | 怎么办 |
| --- | --- | --- | --- |
| `equipment.payload_json` | 288 KB（27 行，最大一行 24.8 KB 且含内联图片） | **设备库类型化之前的旧壳**。`library_schema_version = 2` → `_migrate_machine_library()` 一进门就 return，这份数据**早就没人读了**；而且它和 `machines` 的 id 一个都对不上 | 删（已做）：`SCHEMA` 里不再建 `equipment`，`_migrate_machine_library()` 改成"有这张表才读"（老库仍能拿它当搬迁来源）；清理工具加进 `LEGACY_TABLES`，并带一条护栏——`machines` 是空的时候跳过不删（那说明还没迁完） |
| `project_versions.state_json` 里的内联图片 | 947.5 KB（16 份快照 × 59.2 KB） | 阶段 1 之前项目图片是 base64 内联在 `state_json` 里的，所以第 1~16 版各自快照了**同一张 45 KB 产品图**（sha256 `d75ec2a343e3`，`assets` 里已经有它） | 抽成附件引用（已做）：新工具 `tools/slim_version_snapshots.py`（默认干跑，`--apply` 先备份） |

`tools/slim_version_snapshots.py` 的验证项（干跑与 `--apply` 都跑）：

* 每份被改的快照，**改前内联字节的 sha256 == 改后附件文件的 sha256**（图片一个字节没变）；
* 除图片那几个键之外，快照**逐键逐字节相同**；版本数、版本号、时间、名字前后一致；
* `?revision=N` 打开历史版本：`G` 键数、`pr`/`is` 行数不变，图片字段变成
  `/api/machining-dfm/assets/f95d0a5f…`（HTTP 200、45460 字节、PNG 头正确、sha256 与原来相同）；
* `PRAGMA foreign_key_check` / `integrity_check` 干净；VACUUM 之后库体积变小。

线上实测（2026-09-18 17:0x，两次操作各一份备份）：库 **2.66 MB → 1.43 MB**（先删 `equipment` 到 2.36 MB，再瘦快照到 1.43 MB）；
表数 **20 → 19**；读模型 `G`/`pr`/`is`/`vh` 指纹**一个都没变**；85 份保存版本一份不少；
六个读接口 + `bootstrap`（259.8 KB）+ 报表快照（904.3 KB）全 200；
`projects.state_json = {}`、带内联图片的快照 **0 份**。
