# 阶段 3 设计：版本履历落表（`project_versions` + `project_changes`）

> **实施进度**：**3a（`project_versions`）与 3b（`project_changes`）都已按本文落地**，
> 实施细节、验证证据与验收判据见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3.md`（3a）与
> `docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md`（3b，含与本文表设计的 3 处差异说明与修订后的 DDL）。
> 本文继续作为设计记录。
>
> 这一版只有设计，没有任何代码改动（按你的要求：先给设计、确认后再动代码）。
> 口径沿用已定稿的六条：每次保存都留版本且全部保留 / 不允许永久删除（逻辑删除永久可恢复）/
> 字典与库同名重建=复活原行 / 源库删了就按快照价 / 派生字段不落库 / **有关联的数据结构全部用真外键**。

---

## 1. 实测现状（线上 1 个项目，v60）

| 事实 | 值 | 怎么测的 |
| --- | --- | --- |
| `revisions` 表 | 60 行（`revision` 1..60），每行一份**全量快照** 65741→67118 字节，共约 3.9 MB | `SELECT COUNT(*), length(state_json) FROM revisions` |
| `revisions` 结构 | `project_id, revision, name, state_json, created`，`PRIMARY KEY(project_id, revision)`，`FOREIGN KEY(project_id) REFERENCES projects(id)` | `SELECT sql FROM sqlite_master WHERE name='revisions'` |
| `projects.state_json` | 只剩三个键 `pr / is / vh` | `json.loads(state_json).keys()` |
| `vh[]`（页面"版本履历"表） | **0 行**（这个项目没填过） | 同上 |

> **补充（3a 落地时的复测）**：写这份设计时线上是 v60 / `revisions` 60 行；
> 3a 落地当天复测是 v65 / 65 行（多出来的 5 份**内容逐字节相同**，
> `project_settings.updated` 同步被刷过一次）——是一轮"写进去再还原"的线上自检留下的保存版本。
> 内容没有任何变化（口径 1：每次保存都留版本、全部保留），迁移干跑就是按 65 行跑的。

**`revisions` 现状就是"每次保存一行"**：`_write_snapshot()`（`app/machining_dfm.py:905`）在一份写事务里
落一个快照，调用方三处：

* `create()`（新项目，revision=1，`machining_dfm.py:1643`）；
* `update()`（整份保存，`machining_dfm.py:1673`）；
* `_bump_project()`（**行级保存的统一收尾**，`machining_dfm.py:940`）与
  `save_project_settings()`（`:964`）——1b/2a/2b 的行级写全都会走到这里。

**`vh[]` 的现状（页面上那张"版本履历"表）**

* 行形状固定 4 键，插入顺序就是显示顺序：`{dt, ver, ds, by}`
  （`dt` 日期字符串、`ver` 版本号如 `V1.0`、`ds` 变更内容、`by` 变更人）；
* **7 个写入点**（全在前端 `static/machining_dfm/legacy_app.js`）：

  | 写入点 | 位置 | 说明 |
  | --- | --- | --- |
  | `VH[i].dt` | `:161` | 日期格 |
  | `VH[i].ver` | `:162` | 版本号格 |
  | `VH[i].ds` | `:163` | 变更内容格 |
  | `VH[i].by` | `:164` | 变更人格 |
  | `addVH()` | `:169` | 新增一行 |
  | `delVH(i)` | `:170` | 删一行 |
  | `verRec(ov,nv)` | `:13` ← 由 `sve()` 在 `G.custVer` 变化时调用 `:297` | **自动追加**一行：`by='自动'`，`ds` 是"客户版本切换 + `G._vSnap` 与当前 `G` 的 diff 文本" |

* 渲染在页面版本履历卡片（`:160-165`）与 PPT 导出表格（`:605-606`，`vh` 为空时打印一行"初版"）；
* 读模型里的位置：`PROJECT_ARRAYS = ("pr","is","vh")`，`_snapshot_arrays()` 取 `state_json.vh` 进版本快照。

**版本接口现状**

* `GET /api/machining-dfm/projects/{id}/versions` → `{versions:[{revision,name,created}]}`（`machining_dfm.py:1688`）；
* `GET /api/machining-dfm/projects/{id}?revision=N` → 从 `revisions.state_json` 按 JSON 还原（`:1613`，历史不可变）；
* 前端 `host.js::showVersions()`：列出版本 → "恢复此版本" = 取旧版本 → `PUT` 保存成**新版本**（历史不删）。

**代码里已经给这一步留了位置**：`_migrate_project_settings()` 的 docstring（`machining_dfm.py:791-792`）
写着"历史版本（`revisions`）的快照保持原样……版本管理重构那一阶段再统一收进 `project_versions`"。

---

## 2. 目标

1. `vh[]`（手工/自动版本履历）与 `revisions`（保存版本）都落表 → `project_versions`；
2. 新的"这次保存改了什么" → `project_changes`（一行 = 一个被改的实体行）；
3. 两张表里**所有关联列都是真外键**（本设计里没有任何软引用）；
4. 读模型 `vh[]` 与 `/versions`、`?revision=N` **对外行为一个字不变**；
5. 幂等迁移（默认干跑）+ 单测 + 冒烟，线上数据要动之前单独等你点头。

---

## 3. 门禁（与 1b/2a/2b 同一套数字等级）

| 等级 | 含义 |
| --- | --- |
| ≥1 | 工序落表 |
| ≥2 | + 问题清单 |
| ≥3 | + 选型报价（现在线上是 0，等 1b/2a/2b 的 `--apply`） |
| **≥4（本次新增）** | **+ 版本履历落表** |

`app_settings.project_business_version = 4`（由本轮迁移工具 `--apply` 写入），
环境变量 `MACHINING_PROJECT_BUSINESS=4` 打开全部；store 属性新增 `history_enabled`。
每个请求都新造 store，所以迁移完**不用重启服务**，下一个请求就切过来。

---

## 4. 表设计（完整 DDL）

### 4.1 `project_versions` —— 一行 = 一个版本（保存版本 或 履历行）

```sql
CREATE TABLE IF NOT EXISTS project_versions(
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id),
    sort_order    INTEGER NOT NULL DEFAULT 0,
    kind          TEXT NOT NULL DEFAULT 'history',   -- 'save' | 'history'
    revision      INTEGER NOT NULL DEFAULT 0,        -- save 行 = 保存版本号；history 行 = 0
    ver           TEXT NOT NULL DEFAULT '',          -- vh[].ver
    dt            TEXT NOT NULL DEFAULT '',          -- vh[].dt
    ds            TEXT NOT NULL DEFAULT '',          -- vh[].ds
    by            TEXT NOT NULL DEFAULT '',          -- vh[].by
    name          TEXT NOT NULL DEFAULT '',          -- 保存时的项目名（原 revisions.name）
    state_json    TEXT NOT NULL DEFAULT '{}',        -- 保存快照（原 revisions.state_json）
    deleted_at    TEXT,
    deleted_by    TEXT NOT NULL DEFAULT '',
    deleted_reason TEXT NOT NULL DEFAULT '',
    created       TEXT NOT NULL,
    updated       TEXT NOT NULL,
    CHECK (kind IN ('save','history')),
    CHECK (kind='history' OR revision > 0),
    CHECK (kind='save' OR revision = 0),
    CHECK (kind='history' OR state_json <> '{}')      -- 保存版本必须有快照，不无中生有
);
```

两种行的分工（这是**口径级**决定，请你过目）：

| | `kind='save'` | `kind='history'` |
| --- | --- | --- |
| 谁产生 | 每次保存（行级/整份/新建），`revision` = 当时的项目版本号 | 页面上"版本履历"表里的行：手填的 + `verRec` 自动追加的 |
| 出现在哪 | `GET /versions`、`?revision=N` 还原 | **`vh[]` 读模型**（页面履历卡片、PPT 导出） |
| 有没有全量快照 | 有（`state_json`） | 没有（`'{}'`）——履历行只是一条记录 |
| `revision` | >0，唯一 | 0（哨兵值：它不是保存版本） |

> 为什么用 `revision=0` 而不是 `NULL`：本引擎的可空列只有外键列（DDL 里普通字段都是
> `NOT NULL DEFAULT …`），用 0 当哨兵 + `CHECK` 保证"history 行必须为 0、save 行必须 >0"，
> 语义不会串。对外接口里 history 行的 `revision` 显示成 `null`（不暴露哨兵）。
>
> 另一条路是拆成两张表（`project_versions` + `project_history`）。**不推荐**：
> 主计划里写的就是"`vh[]` + `revisions` 合并成 `project_versions`"，一张表用 `kind` 分开更贴合。

索引：

```sql
CREATE INDEX IF NOT EXISTS idx_project_versions_project   ON project_versions(project_id);
CREATE INDEX IF NOT EXISTS idx_project_versions_kind      ON project_versions(project_id, kind);
CREATE UNIQUE INDEX IF NOT EXISTS idx_project_versions_save
    ON project_versions(project_id, revision) WHERE kind='save';   -- 保存版本号不重复
```

（前两条与引擎现有的 `index_ddl()` 一致；第三条是**部分唯一索引**，需要在引擎里加一个小口子
`extra_indexes`——约 10 行，不影响别的表。）

### 4.2 `project_changes` —— 一行 = 一次改动里的一个实体

> **实施后的修订（3b 已按本节落地，见 `docs/MACHINING_BUSINESS_REFACTOR_PHASE3B.md`）**：
> 实现时按真实写入点补了三处，并改了 `CHECK` 的写法——下面这段 DDL 是**落地版**，
> 与最初设计的差异逐条写在 PHASE3B 文档第 2 节：
>
> 1. `entity` 多一个 **`history`**（版本履历本身就是页面上可增删改的一行）、
>    `action` 多一个 **`save`**（整份保存不是"改了哪一行"）；
> 2. 多一列 **`history_row_id → project_versions(id)`**：与 `version_id` 指同一张表，
>    但一个是"被改的那条履历行"、一个是"这一次保存的版本"，共用一个列会把两个意思搅在一起；
> 3. `CHECK` 从"**恰好**挂一个"改成"**最多**挂一个 + 挂上的必须与 `entity` 对应"：
>    五列都是 `ON DELETE SET NULL`，目标行被物理删掉时列会被置空，
>    "恰好一个"会把 `SET NULL` 这步顶掉（`IntegrityError: CHECK constraint failed`），
>    连"删掉一行"都做不成。"写入时必须挂上"由写入方保证，单测逐条断言。

```sql
CREATE TABLE IF NOT EXISTS project_changes(
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(id),
    version_id        TEXT REFERENCES project_versions(id) ON DELETE SET NULL,  -- 属于哪次保存
    sort_order        INTEGER NOT NULL DEFAULT 0,
    entity            TEXT NOT NULL DEFAULT 'process',
                      -- project|settings|process|tool|issue|selection|history（落地版七种）
    action            TEXT NOT NULL DEFAULT 'update',
                      -- create|update|delete|restore|reorder|photo|save（落地版七种）
    label             TEXT NOT NULL DEFAULT '',         -- 给人看的："工序 OP10 改名"、"刀具 T01 转速 n 3000→3500"
    extra_json        TEXT NOT NULL DEFAULT '{}',       -- 兜底：by/reason/cascade/has_asset/fields…
    -- 下面 5 列是真外键（谁被改了）；同一行最多一列有值，且必须与 entity 对应
    process_row_id    TEXT REFERENCES project_processes(id)   ON DELETE SET NULL,
    tool_row_id       TEXT REFERENCES project_process_tools(id) ON DELETE SET NULL,
    issue_row_id      TEXT REFERENCES project_issues(id)      ON DELETE SET NULL,
    selection_row_id  TEXT REFERENCES project_selections(id)  ON DELETE SET NULL,
    history_row_id    TEXT REFERENCES project_versions(id)    ON DELETE SET NULL,  -- 被改的履历行
    deleted_at        TEXT,
    deleted_by        TEXT NOT NULL DEFAULT '',
    deleted_reason    TEXT NOT NULL DEFAULT '',
    created           TEXT NOT NULL,
    updated           TEXT NOT NULL,
    CHECK (entity IN ('project','settings','process','tool','issue','selection','history')),
    CHECK (action IN ('create','update','delete','restore','reorder','photo','save')),
    CHECK ((process_row_id IS NULL) + (tool_row_id IS NULL) + (issue_row_id IS NULL)
           + (selection_row_id IS NULL) + (history_row_id IS NULL) >= 4),      -- 最多挂一个
    CHECK (process_row_id IS NULL OR entity='process'),                        -- 挂上的必须对应
    CHECK (tool_row_id IS NULL OR entity='tool'),
    CHECK (issue_row_id IS NULL OR entity='issue'),
    CHECK (selection_row_id IS NULL OR entity='selection'),
    CHECK (history_row_id IS NULL OR entity='history'),
    CHECK (entity NOT IN ('project','settings') OR
           (process_row_id IS NULL AND tool_row_id IS NULL AND issue_row_id IS NULL
            AND selection_row_id IS NULL AND history_row_id IS NULL))
);
```

**这就是"多态引用"的答案，也是本设计里唯一需要你拍板的技术点**：

| 方案 | 关联列 | 优点 | 代价 |
| --- | --- | --- | --- |
| **A（推荐）** 分列 | 5 列各自真外键 + `CHECK` 最多一列、必须对应 | **100% 真外键**，`PRAGMA foreign_key_check` 能查；按实体类型查很快 | 以后加实体种类要加一列（走一次小迁移） |
| B 一列多态 | `entity_id` 一列 + `entity` 类型列 | 加种类不用改表 | `entity_id` **没法建外键**（SQLite 外键只能指一张表），只能靠巡检脚本校验——**与"全部用真外键"的口径冲突** |

我按你的口径选 **A**（落地时按真实写入点扩到 5 列），并把它写进 `tools/audit_foreign_keys.py`
的"SET NULL"清单；五个实体种类覆盖现在所有行级写入点（`project`/`settings` 是整项目改动，不挂行）。

### 4.3 外键总账（本阶段新增）

| 表 | 列 | 指向 | 删目标行时 |
| --- | --- | --- | --- |
| `project_versions` | `project_id` | `projects(id)` | NO ACTION（项目不物理删） |
| `project_changes` | `project_id` | `projects(id)` | NO ACTION |
| `project_changes` | `version_id` | `project_versions(id)` | `SET NULL`（变更明细不挡版本行） |
| `project_changes` | `process_row_id` | `project_processes(id)` | `SET NULL` |
| `project_changes` | `tool_row_id` | `project_process_tools(id)` | `SET NULL` |
| `project_changes` | `issue_row_id` | `project_issues(id)` | `SET NULL` |
| `project_changes` | `selection_row_id` | `project_selections(id)` | `SET NULL` |
| `project_changes` | `history_row_id` | `project_versions(id)` | `SET NULL`（与 `version_id` 同表、语义不同） |

`SET NULL` 都不丢信息：外键置空时人还能看懂，因为 `label` 里存了"当时改的是谁、改成什么"（口径 4 的同一条思路）。

---

## 5. 读模型：`vh[]` 一个字都不能变

```python
LEGACY_HISTORY_KEYS = ("dt", "ver", "ds", "by")     # 与 addVH()/verRec() 的插入顺序一致

def compose_history(versions, project_id) -> list[dict] | None:
    rows = [r for r in versions.list_typed(project_id) if r["kind"] == "history"]   # 已排除逻辑删除
    if not rows:
        return None                                  # 表里没行 → 读模型回退 state_json.vh
    return [{key: row.get(key) or "" for key in LEGACY_HISTORY_KEYS} for row in rows]
```

* 顺序 = `sort_order, id`；迁移时 `sort_order` = 旧数组下标，**顺序与键序都不变**（逐字节校验）；
* 值原样字符串，不重算日期、不 `js_number`、不补键（旧行缺键就是 `""`——旧数据里 `addVH` 一定给 4 键，
  但外部导入的数据可能缺，缺键按空串补，与旧渲染 `String(v.ds||'')` 的观感一致）；
* 表里一行都没有 → `None` → 读模型继续用 `state_json.vh`（与 `pr`/`is` 同一套"表里有数据才是权威"）；
* `state_json.vh` 迁移后**继续留作影子副本**（和 `pr`/`is` 一样）：回滚 = 删版本键，立刻回到旧路径。

`/versions` 与 `?revision=N` 的读路径改为 `kind='save'` 行，对外字段保持
`{revision, name, created}`（多加一个 `id`，前端 `host.js` 不读它、不受影响）。

---

## 6. 迁移：`tools/migrate_project_versions.py`（默认干跑）

与 1b/2a/2b 的迁移工具同一套形状（`--status` / 干跑 / `--apply` / `--from`）：

1. **备份**整库到 `data/machining_dfm/backups/pre-project-history-<stamp>.sqlite3`；
2. 把 `revisions` 原表归档成 `revisions_legacy_v1`（只归档一次；迁移记录落库，便于回滚核对）；
3. 建 `project_versions` + `project_changes`（门禁等级 4 打开时才建表）；
4. `revisions` 现有 60 行 → `project_versions`：`kind='save'`、`revision/name/state_json/created` **原样**，
   新 `id` 用稳定规则生成（`f"{project_id}-v{revision}"`，重复跑得到同一行 → 幂等）；
5. `state_json.vh[]` → `project_versions`：`kind='history'`、`sort_order` = 数组下标、`dt/ver/ds/by` 原样，
   `id = f"{project_id}-h{index}"`；**不编造**任何键；
6. 版本键 `app_settings.project_history_version = 1` **最后**写。

只读校验（干跑里全部打印，任一不过就中止）：

* `GET /versions` 逐项等于迁移前（60 行 `revision/name/created`）；
* `?revision=N` 还原出的记录与迁移前**逐字节**相同（抽全部 60 个版本比 `state_json`）；
* `vh[]` 与迁移前**逐字节**相同（线上是 `[]`，所以这条现在必然通过，但以后别的库会用到）；
* `PRAGMA foreign_key_check` 干净；
* 副本上把 `state_json.vh` 清掉后读模型依旧（证明表是唯一权威）。

**幂等**：`kind='save'` 行按 `(project_id, revision)` 已存在就跳过；history 行按"该项目已有 N 行 history"整批跳过。

**回滚**：删 `app_settings.project_history_version` 即可（`revisions` 表原样留着，1 秒回到旧路径）。

---

## 7. 接口与前端接管

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/projects/{id}/versions` | 保存版本列表（改读 `project_versions` where `kind='save'`） |
| GET | `/projects/{id}/history` | 版本履历行（`kind='history'`，按 `sort_order`） |
| POST | `/projects/{id}/history` | 新增一行（`{dt,ver,ds,by}` 任意子集，缺的给默认） |
| PATCH | `/projects/{id}/history/{rid}` | 改一格（`dt`/`ver`/`ds`/`by` 任意子集） |
| DELETE | `/projects/{id}/history/{rid}` | **逻辑删除**（口径 2，行还在、回收站可恢复） |
| GET | `/projects/{id}/history/recycle` | 回收站 |
| POST | `/projects/{id}/history/{rid}/restore` | 恢复 |
| POST | `/projects/{id}/history/reorder` | `{ids:[…]}` 重排 |

外键校验与 1b/2a/2b 同一套：目标行不存在 → **422** 说人话；不属于该项目 → **404**；
门禁没开 → **409**；行已删除 → **410**。

前端新增 `static/machining_dfm/history_page.js`（`window.HistoryPage`，`enabled()` 看 `record.history_table`）：

* 接管 `legacy_app.js` 里那 **7 个写入点**（4 个 `onchange` + `addVH` + `delVH` + `verRec` 的 push）；
* 每个写入点写完重新拉一次列表、`MachiningDFMHost.adopt(record)`（与 2b 的写法一致）；
* 渲染**仍留在 `legacy_app.js`**（不重写界面）；
* 门禁关着时完全走旧路径（现在的行为一个字不变）。

`_record()` 增加 `history_table`（与 `process_table`/`issue_table`/`selection_table` 并列）。

---

## 8. 测试与验收

```powershell
.venv\Scripts\python.exe -m pytest tests -q                        # 新增 tests/test_machining_history.py（约 25 条）
.venv\Scripts\python.exe tools\check_process_wiring.py             # 新增 HISTORY_WRITE_POINTS：7 个写入点
.venv\Scripts\python.exe tools\migrate_project_versions.py         # 干跑（60 个版本 + vh 字节校验 + 外键体检）
.venv\Scripts\python.exe tools\audit_foreign_keys.py --with-process   # 外键总账（含新 7 个外键）
node tools\smoke_machining_page.mjs                                # 冒烟（版本履历关/开两态）
```

单测覆盖：DDL/外键存在性与 `ON DELETE`、CRUD 与行级语义、逻辑删除+回收站+恢复、重排、
`vh[]` 读模型逐字节、缺键补空、`/versions` 兼容、门禁三态（关/3/4）、
`revision` 哨兵 `CHECK`（数据库层拒绝 `kind='save'` 且 `revision=0`）、
`project_changes` 的"最多一列 + 必须对应" `CHECK` 与 5 个行外键的 `IntegrityError`
（3b 落地后一共 29 项，见 `tests/test_machining_changes.py`）。

---

## 9. 要你拍板的 3 件事（已拍板，记录在此）

1. **`project_changes` 的关联列**：→ **A 分列真外键**（落地时按真实写入点扩到 5 列）；
2. **历史 60 个版本的"改了什么"**：→ **留空**（不无中生有；迁移后流水表就是 0 行）；
3. **一次做完还是分两步**：→ **先 3a 再 3b**（两步都已落地）。

## 10. 明确不做的事

* 不物理删除任何版本/履历行（口径 2）；`delVH` 变成逻辑删除，回收站可恢复；
* 不重算 `vh` 里的日期/文本，不做"迁移时顺手美化"；
* 不改 `?revision=N` 的还原方式（历史快照仍按 JSON 还原，保持不可变）；
* 线上库在 1b/2a/2b 的 `--apply` 与本次迁移都**没有你的单独点头就不动**。
