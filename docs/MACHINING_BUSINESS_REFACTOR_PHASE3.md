# 机加 DFM 业务数据重构 · 阶段 3a：版本履历落表（`project_versions`）

> 状态：**代码已落地，线上开关默认关（`project_business_version` 还是 0）**。
> 阶段 3 的设计与拍板记录在 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3_DESIGN.md`；
> 本文记的是 3a 的实施细节、验证证据与验收判据。
> 3b（`project_changes` 变更流水）还没做。

## 1. 这一阶段解决什么

线上原来有**两套互不相干**的"版本"：

| | 旧形态 | 谁在写 | 页面在哪看 |
| --- | --- | --- | --- |
| **保存版本** | `revisions` 表：每次保存一行全量快照（线上 60 行，每份约 65–67 KB，合计约 3.9 MB） | 每一次保存（含每个行级写入点） | 「版本」弹窗：版本号 / 时间 / 「恢复此版本」 |
| **版本履历** | `projects.state_json.vh[]`：`{dt,ver,ds,by}` 四键一行 | 页面上手填四个格子、`addVH()`、`delVH()`、客户版本切换时的 `verRec()` 自动追加 | 「版本变更履历」卡片 + PPT 导出里的版本表 |

3a 把两者落进**同一张表** `project_versions`，用 `kind` 分开：

* `kind='save'` —— 一次保存一行，`revision` = 当时的项目版本号，`state_json` = 那份全量快照。
  对外提供 `GET /versions` 与 `?revision=N` 还原（字段与旧 `revisions` 完全一致）；
* `kind='history'` —— 页面「版本履历」里的一行，`revision` **固定 0**（哨兵：它不是保存版本），
  四个键 `ver/dt/ds/by` 就是旧四键。

这么做的直接好处：版本履历终于**可以按行改**（不再每次改一个格子就整份保存），
可以逻辑删除 + 回收站恢复，可以带 `extra_json` 兜底列，而且**有关联的列是真外键**。

## 2. 表结构

```sql
CREATE TABLE project_versions(
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),   -- 真外键
    sort_order INTEGER NOT NULL DEFAULT 0,
    "kind" TEXT NOT NULL DEFAULT 'history',
    "revision" INTEGER NOT NULL DEFAULT 0,
    "ver" TEXT NOT NULL DEFAULT '', "dt" TEXT NOT NULL DEFAULT '',
    "ds" TEXT NOT NULL DEFAULT '', "by" TEXT NOT NULL DEFAULT '',
    "name" TEXT NOT NULL DEFAULT '',
    "state_json" TEXT NOT NULL DEFAULT '{}',            -- 保存版本的全量快照
    "extra_json" TEXT NOT NULL DEFAULT '{}',            -- 履历行的兜底键
    deleted_at TEXT, deleted_by TEXT NOT NULL DEFAULT '', deleted_reason TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL, updated TEXT NOT NULL,
    CHECK (kind IN ('save','history')),
    CHECK (kind='history' OR revision > 0),             -- 保存版本必须有版本号
    CHECK (kind='save'    OR revision = 0),             -- 履历行不许带版本号
    CHECK (kind='history' OR state_json <> '{}'),       -- 保存版本必须有快照（不许造空版本）
    CHECK (kind='save'    OR state_json = '{}')         -- 履历行不许带快照
);
```

索引：`project_id` 外键列有索引；`(project_id, kind, revision)` 有索引（`?revision=N` 与列表都走它）。

**外键口径**（用户要求"有关联的数据结构全部使用外键约束"）：

| 列 | 指向 | ON DELETE | 说明 |
| --- | --- | --- | --- |
| `project_id` | `projects(id)` | NO ACTION | 本表唯一的关联列，真外键；`PRAGMA foreign_key_check` 为干净 |

本表**没有软引用列**：`ver/dt/ds/by` 是用户填的文本，不是"指向别的表里的行"。
`tools/audit_foreign_keys.py --with-process` 会核对这一条（清单里已登记 `project_versions`）。

## 3. 读模型：`vh[]` 逐字节不变

* `compose_history()` 只输出旧四键 `dt,ver,ds,by`（顺序 = 页面上 `addVH()` 的插入顺序），
  逻辑删除的行不进读模型；
* **表的权威信号是"有没有履历行"**（`kind='history'`），不是"表里有没有行"：
  开关一打开，应用每次保存都会写保存版本，所以"有行"根本不代表履历已经迁过。
  没有履历行时 `legacy_history()` 返回 `None` → 读模型回退 `projects.state_json.vh`，
  与 `pr`/`is`/选型四数组同一套"表里有数据才是权威"的规则；
* `?revision=N`（历史版本）**只用那一版快照里的 `vh`**，不会被"现在这张履历表"覆盖。
  3a 之前没有履历表，历史路径本来就是读快照的，这里把它原样保住
  （`_record(..., historical=True)`）；`pr/is` 维持 1b/2a 已上线的口径（表是权威），本阶段不改。

### 3.1 兜底：没赶上迁移的老项目

老项目的履历还在 `state_json.vh` 里，而页面只有行下标时怎么办？两段配合：

1. `GET /history` 发现表里**没有履历行** → 返回一份**只读的"影子清单"**（`materialized: false`），
   id 就是 `<项目 id>-h<下标>`，内容由 `state_json.vh` 现算。读模型这一刻仍在回退 `state_json.vh`，
   页面上看到的和改造前一模一样；
2. 页面第一次改/删/加（拿的就是影子清单里的那个 id）→ 服务端把这个项目的 `state_json.vh`
   **就地补建成真行**（id 与影子清单一致），再执行这次写入。

所以：**页面永远不用等迁移**，也不会出现"刚看到就说这一行不在了"。
迁移工具做的是同一件事，只是提前一次性做完。

## 4. 保存版本的写入：`revisions` 继续写，当影子副本

`_write_snapshot()`（以及 `create()` / `update()` 两处建项目与整份保存）在同一次事务里写两张表：

```python
db.execute("INSERT INTO revisions(...) VALUES(?,?,?,?,?)", (project_id, revision, name, payload, stamp))
if self.history_enabled:
    insert_save_row(db, project_id, revision, name, payload, stamp)   # 同一串 payload 字节
```

* 两份 `state_json` 是**同一串字节**（迁移工具逐版核对过：65/65 相同）；
* 代价是快照在库里存两遍（线上约 3.9 MB + 3.9 MB）——**换来的是回滚只是"删一个版本键"**：
  删掉 `app_settings.project_business_version` 后读模型立刻回到 `revisions`，一行都不会丢；
* 回滚点写在迁移工具的收尾提示里。

## 5. 接口

```
GET    /api/machining-dfm/projects/{pid}/history                     # 履历清单（recycle=true 给回收站）
POST   /api/machining-dfm/projects/{pid}/history                     # 新增一行（缺的键补空串）
PATCH  /api/machining-dfm/projects/{pid}/history/{id}                # 只改提交上来的格子
DELETE /api/machining-dfm/projects/{pid}/history/{id}?by=&reason=    # 逻辑删除（进回收站，可恢复）
POST   /api/machining-dfm/projects/{pid}/history/{id}/restore        # 从回收站恢复
POST   /api/machining-dfm/projects/{pid}/history/reorder             # 重排（{"ids": [...]}）
GET    /api/machining-dfm/projects/{pid}/versions                    # 保存版本列表（3a 之后读新表）
GET    /api/machining-dfm/projects/{pid}?revision=N                  # 历史版本（vh 用那一版快照）
```

每个写接口都返回整个项目记录（前端 `MachiningDFMHost.adopt(record)` 接管内存），
并且**每次写都递增项目版本 + 留一个保存版本**（口径 1：每次保存都留版本、全部保留）。

行为细节：

* `PATCH` 的载荷只认 `dt/ver/ds/by`，其它键（除了服务端列）进 `extra_json` 兜底列，**不丢数据**；
* `PATCH` 未落表时兼容"只给下标"（`{"index": 2, ...}`）：服务端按**当前清单**换算成行 id，
  越界 → **409**（提示"第 N 行已经不在了，请刷新"），绝不猜；
* 已删除的行再改 → **410**；不属于这个项目的行 → **404**；开关没开 → **409**；
* 删除是**逻辑删除**（口径 2：永不物理删除），行还在表里、回收站能恢复；
* `reorder` 只重排 `kind='history'` 的行，保存版本的 `sort_order`（存的是版本号）一根都不动。

## 6. 前端接管

新增 `static/machining_dfm/history_page.js`，接管页面上 7 个写入点（`legacy_app.js`）：

| # | 写入点 | 新写法 | 旧路径（开关关着） |
| --- | --- | --- | --- |
| 1-4 | 履历卡的日期/版本号/变更内容/变更人四个格子 | `hpSet(i,'dt'/'ver'/'ds'/'by',this)` → `HistoryPage.setField` | `VH[i][k]=v;render()` |
| 5 | 「+ 新增版本记录」 | `addVH()` → `HistoryPage.add(rec)` | `VH.push(rec);render()` |
| 6 | 行尾「X」删除 | `delVH(i)` → `HistoryPage.remove(i)` | `VH.splice(i,1);render()` |
| 7 | 客户版本切换自动追加（`verRec`） | `HistoryPage.add(_rec)` | `VH.push(_rec)` |

* 页面只给**下标**，所以每次写入都先 `GET /history` 拿最新清单、用下标换行 id；
  下标越界就只刷新不瞎写（与 `process_page.js`/`issue_page.js`/`selection_page.js` 同一套路）；
* 本模块**只写不画**，画面仍由 `legacy_app.js` 的 `bVersion()` 与 PPT 导出出；
* `tools/check_process_wiring.py` 会把"行级保存 + 旧路径"逐条核对，并扫一遍
  `legacy_app.js` 找**没被接管**的 `VH[]` 写入点（漏一个就是"界面上改了、表里没变"）：
  现在是 `√ 前端接管完整：工序、问题清单、选型报价与版本履历的每个写入点都走行级保存，且旧路径仍在`。

## 7. 迁移

```powershell
.venv\Scripts\python.exe tools\migrate_project_versions.py --status   # 只读：版本键/表/行数
.venv\Scripts\python.exe tools\migrate_project_versions.py            # 干跑（副本，跑完删掉）
.venv\Scripts\python.exe tools\migrate_project_versions.py --keep      # 干跑并保留副本目录
.venv\Scripts\python.exe tools\migrate_project_versions.py --apply     # 真迁移（先整库备份）
```

顺序（每一步都可重复执行）：

1. **前置检查**：`project_business_version >= 3`（1b/2a/2b 已迁）。干跑遇到前置没迁的副本，
   会先在**副本上**把 1b/2a/2b 跑一遍再跑 3a —— 所以今天就能在真实数据上端到端演练 0 → 4；
   `--apply` **不会**替你补前面的阶段，会直接告诉你先跑 `migrate_project_processes.py --apply`；
2. **体检（写任何数据之前）**：`state_json` 是不是合法 JSON、`vh` 是不是数组、
   每条履历是不是对象、每个旧快照是不是合法 JSON —— 有一样不对就**拒绝迁移**，
   绝不替人猜、更不静默丢；
3. **整库备份** → `data/machining_dfm/backups/pre-project-versions-<时间戳>.sqlite3`；
4. **逐项目搬**：`revisions` 行原样搬进 `kind='save'`（`state_json` 一个字节都不重排）；
   `state_json.vh[]` 按下标进 `kind='history'`（id = `<项目 id>-h<下标>`，所以重复跑得到同一行）；
5. **写开关**：`app_settings.project_business_version = 4`（最后一步；`router_for` 每个请求新建 store，
   下一个请求就切到表，**不用重启服务**）；
6. **逐字节验证**（重新打开 store，纯靠版本键）：
   * 保存版本列表与迁移前 `revisions` 完全一致（版本号/名字/时间）；
   * 每一份保存版本的 `state_json` 与 `revisions` 里那一行**逐字节相同**（影子副本对得上 → 回滚无损）；
   * 抽首/中/末三版 `?revision=N`：能打开，`vh[]` 与"开关关着时"的读模型一致；
   * `vh[]` 与迁移前逐字节相同（含键序）；只凭 `project_versions` 也能还原出同样的 `vh`；
   * 干跑副本上还会把 `state_json.vh` 清掉，证明读模型不掉任何东西；
   * `PRAGMA foreign_key_check` 干净、没有悬空的 `project_id`。

**回滚**：把 `app_settings.project_business_version` 改回 `3`。（`revisions` 表是影子副本，一行没少；
`state_json.vh` 迁移时也不动。）

### 7.1 干跑证据（线上真实数据副本，60 行保存版本）

```
=== 体检（写数据之前）===
  项目 1 个｜revisions 共 65 行
  state_json.vh 共 0 条
  √ 体检通过：旧数据形态都能原样搬进表

=== 搬版本数据 ===
  项目「原文件集成 · 蓄电池支架 Battery Bracket」：已搬｜旧 revisions 65 行 / 旧 vh 0 条
      → 表里 65 个保存版本 + 0 行履历

=== 开关 ===
  已写 project_business_version = 4（保存版本 + 版本履历从此都走 project_versions）

=== 验证（重新打开 store，只靠版本键启用）===
  √ 保存版本列表与迁移前的 revisions 完全一致（65 个版本）
  √ 65 份保存版本快照与 revisions 逐字节相同（回滚无损）
  √ 第 1 版 ?revision= 的 vh[] 与迁移前一致
  √ 第 33 版 ?revision= 的 vh[] 与迁移前一致
  √ 第 65 版 ?revision= 的 vh[] 与迁移前一致
  √ vh[] 与迁移前逐字节相同（2 字节，含键序）
  √ 老 vh 本来是空的：表里 0 行履历，读模型按设计回退 state_json.vh

=== 外键体检 ===
  project_versions = 保存版本 65 行 + 履历 0 行
  PRAGMA foreign_key_check = 干净
  悬空的 project_id = 0

√ 干跑通过：可以放心执行 --apply
```

> 两点说明：
> 1. 副本上 `revisions` 是 65 行而不是设计文档里记的 60 行：干跑先在副本上跑了 1b/2a/2b，
>    那几步自己也会留版本快照（正常现象，线上 `--apply` 时前置早已迁完，不会多出来）；
> 2. 这个项目的 `vh` 本来就是空的，所以迁完是 **0 行履历**，`legacy_history()` 返回 `None`、
>    读模型按设计回退 `state_json.vh` —— 校验项特意区分了"老数据本来没有" 与 "有却读不到"，
>    后者才会判失败。

## 8. 测试与自检

```powershell
.venv\Scripts\python.exe -m pytest tests -q                     # 150 项（3a 新增 31 项）
.venv\Scripts\python.exe -m pytest tests -q -k history           # 只跑 3a
.venv\Scripts\python.exe tools\check_process_wiring.py           # 前端每个写入点：行级保存 + 旧路径
.venv\Scripts\python.exe tools\migrate_project_versions.py        # 干跑（默认，不动线上）
.venv\Scripts\python.exe tools\audit_foreign_keys.py --with-process   # 外键总清单（含本表）
node tools\smoke_machining_page.mjs                              # 整页真跑（含 3a 的两个新段落）
```

`tests/test_machining_history.py` 覆盖：

1. 能力级别 ≥4 才启用（3 时接口 409、表都没建）；
2. `project_id` 是真外键（凭空 pid 插不进去）；
3. 四条 CHECK 把语义钉死（kind 只能是 save/history；save 必须 `revision>0` 且快照非空；
   history 必须 `revision=0` 且不带快照）；
4. 每次保存都写 save 行、与 `revisions` 逐字节相同、`/versions` 列表一致、`?revision=N` 能打开；
5. `vh[]` 往返逐字节相同（含键序）、有履历行时表是权威、没有履历行时回退 `state_json.vh`、
   兜底键不丢；
6. 行级写入：一格一存、缺键补空串、下标换 id、越界 409；
7. 删除 = 逻辑删除 + 回收站 + 恢复后读模型回到原样；已删除的行不能再改（410）；跨项目行 404；
8. 迁移助手幂等（重复跑不插第二遍）、体检拦住非对象/非数组的旧数据、不静默丢；
9. 兜底路径：影子清单 id 与"就地补建"的 id 一致，第一次写就把老履历补成真行。

## 9. 本阶段改动的文件

| 文件 | 改动 |
| --- | --- |
| `app/machining_history.py` | **新增**：表定义 / 字段 / CHECK / 轻量读 / 读模型 / 清单 / 行载荷 / 迁移助手 |
| `app/machining_dfm.py` | 接线：能力级别 4、`history_enabled`、建表、`_history_arrays`、读模型 `vh`、保存时写 save 行、`/versions` 与 `?revision=N` 改读新表、7 个路由 |
| `app/machining_process.py` | 引擎：`create()` 支持 `record_id`/`created`（迁移要幂等与保留历史时间戳） |
| `static/machining_dfm/history_page.js` | **新增**：行级写入模块（只写不画） |
| `static/machining_dfm/legacy_app.js` | 7 个 `VH[]` 写入点改走 `hpSet`/`addVH`/`delVH`/`verRec` 里的 `HistoryPage`，旧路径保留 |
| `static/machining_dfm/index.html` | 加载 `history_page.js` |
| `tools/migrate_project_versions.py` | **新增**：默认干跑 + 体检 + 备份 + 搬数据 + 逐字节验证 + 回滚说明 |
| `tools/process_wiring.py` / `tools/check_process_wiring.py` | 3a 的写入点清单、豁免清单与自检项 |
| `tools/audit_foreign_keys.py` | 能力级别开到 4（把本表也建出来一起审） |
| `tools/smoke_machining_page.mjs` | 假服务端加 `/history`，新增两段自检（开关关着/打开后） |
| `tests/test_machining_history.py` | **新增** 31 项 |
| `README.md` / 本文 | 文档 |

## 10. 已知边界（本阶段刻意没做的事）

1. **整份保存 / "恢复此版本" 不会把老数据反拆回表**：`PUT /projects/{id}` 与「恢复此版本」
   走的是整份覆盖，只写 `G`（项目信息）与一份新的保存快照；`pr`/`is`/`vh` 在表里有数据时
   仍然是表说了算，所以"恢复到某一版"**不会**把那一版的工序/问题清单/履历回灌进表。
   这是 1b/2a 上线时就存在的行为，3a 只是让它对履历也成立（`?revision=N` 只读、只展示，
   不写表）。要真正做"恢复此版本"就得给每张表都写一套回灌逻辑，那是单独一件事，本阶段没动；
2. **保存快照存两遍**（`revisions` + `project_versions.kind='save'`，线上约 3.9 MB × 2）——
   换回滚零风险，见第 4 节；
3. **任意键序不可复现**：履历行的四个键之外如果有别的键，会进 `extra_json` 兜底列，
   但它们在 `state_json.vh` 里的**原始插入顺序**没法复原（读模型按 `dt,ver,ds,by` 在前、
   其余随便的固定顺序输出）。线上 `vh` 是空的，所以现在没有实际影响；
   迁移的"逐字节相同"校验会兜住这件事（真出现差异会直接报错，不静默通过）；
4. **刀具库 761 行价格/寿命为 0**（跑 `tools/analyze_tool_name_matching.py` 可见）：
   工序刀具行落表后价格/寿命是从库里快照下来的，库里没填就快照成 0。
   要不要在页面上提示"库价未填"是产品决定，本阶段没做；
5. **阶段 4/5 未做**：回收站界面（逻辑删除的行现在只能靠接口 `?recycle=true` 看）、
   附件归项目（`assets` 现在还挂在库行上）。

## 11. 下一步（3b / 后续阶段）

* **3b `project_changes`**：四列真外键（`project_id` / `process_id` / `tool_row_id` / `issue_id`，
  加"恰好挂一个"的 CHECK）记录每一次行级写入的改动流水；
* 线上迁移还没执行（`--apply` 需要单独确认）；迁移工具干跑已通过；
* 待办（本阶段没做，已记录）：刀具库有 761 行价格/寿命为 0，页面上要不要提示"库价未填"；
  阶段 4 回收站界面；阶段 5 附件归项目。
