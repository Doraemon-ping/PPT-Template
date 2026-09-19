# 阶段 2a + 2b 设计 + 落地：问题清单（`project_issues`）与选型报价（`project_selections`）落表

> 前半篇（§1–§8）是 **2a 问题清单**；**2b 选型报价**见 §9 起。

> 口径来源：`docs/MACHINING_BUSINESS_REFACTOR.md` §2.4；本次新增的一条总要求是
> **「有关联的数据结构全部使用外键约束」**——凡是"指向别的表里的行"的列，一律用真外键
> （`REFERENCES`），不做"存个字符串自己心里有数"的软引用。本文第 3 节把这条要求逐列对账，
> 并说明哪几列**故意**不建外键、为什么。

## 1. 实测现状（线上 1 个项目，v60）

```
is[] 共 2 行，键集完全一致（8 键）：
  {"tp":"尺寸","pr":"机加工序-OP10","ds":"","fx":"","cr":"","st":"进行中","bI":null,"aI":null}
  {"tp":"尺寸","pr":"机加工序-OP10","ds":"","fx":"","cr":"","st":"进行中","bI":null,"aI":null}
```

旧结构的三个问题（都是"数据里存的是显示值"造成的）：

1. **`pr` 存工序名字**：工序一改名，这条问题就"指向一道不存在的工序"——界面上看不出错，
   但导出的 DFM 报告与工序对不上号；名字重复时更没法判断指的是哪一道；
2. **`bI`/`aI` 存整张图的 data URL**：图片跟着 `state_json` 一起膨胀，每存一次版本就复制一份；
3. **整份覆盖保存**：改一个格 = 提交整个项目状态，两个人同时改会互相盖掉（1b 已经处理工序，
   问题清单这一段还是老路）。

## 2. 表设计

```sql
CREATE TABLE IF NOT EXISTS project_issues(
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    process_id TEXT REFERENCES project_processes(id),      -- 可空：项目级问题
    sort_order INTEGER NOT NULL DEFAULT 0,
    issue_type TEXT NOT NULL DEFAULT '',                   -- 旧 tp
    description TEXT NOT NULL DEFAULT '',                  -- 旧 ds
    fix_plan TEXT NOT NULL DEFAULT '',                     -- 旧 fx
    customer_reply TEXT NOT NULL DEFAULT '',               -- 旧 cr
    status TEXT NOT NULL DEFAULT '进行中',                  -- 旧 st（进行中 / 已完成）
    process_name_snapshot TEXT NOT NULL DEFAULT '',        -- 迁移/新建当时的工序名
    extra_json TEXT NOT NULL DEFAULT '{}',                 -- 兜底：登记表没覆盖的旧键整份留着
    before_photo_id TEXT REFERENCES assets(id),            -- 旧 bI
    after_photo_id TEXT REFERENCES assets(id),             -- 旧 aI
    deleted_at TEXT, deleted_by TEXT NOT NULL DEFAULT '', deleted_reason TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL, updated TEXT NOT NULL
);
```

索引：`(project_id, sort_order, id)`、`(process_id, sort_order, id)`。

**为什么留 `process_name_snapshot`**：外键是权威、名字是显示。工序改名要让问题清单跟着走
（这是修 bug），但工序被**逻辑删除**后外键还在、名字读不到，这时回退到快照——
历史导出照样说得清"当时指的是哪道工序"。

**为什么留 `extra_json`**：旧数据里将来出现登记表没覆盖的键时一个都不丢（与 `project_settings`
同一套做法）；也保证"只凭这张表就能还原迁移前的 `is[]`"。

## 3. 外键对账（用户要求的「全部使用外键约束」）

### 3.1 已经用真外键表达的关联

| 表 | 列 | 指向 | 备注 |
| --- | --- | --- | --- |
| `project_settings` | `project_id` | `projects(id)` | 1a 落地 |
| `project_settings` | 4 个图片列 | `assets(id)` | 1a 落地 |
| `project_processes` | `project_id` | `projects(id)` | 1b 落地 |
| `project_processes` | `fixture_photo_id` | `assets(id)` | 1b 落地 |
| **`project_processes`** | **`machine_id`（页面键 `mid`）** | **`machines(id)`** | **本次，`ON DELETE SET NULL`** |
| `project_process_tools` | `project_id` | `projects(id)` | 1b 落地 |
| `project_process_tools` | `process_id` | `project_processes(id)` | 1b 落地，NOT NULL |
| `project_process_tools` | `tool_photo_id` | `assets(id)` | 1b 落地 |
| **`project_process_tools`** | **`tool_id` / `handle_id` / `accessory_id`** | **`tools(id)`** | **本次，`ON DELETE SET NULL`** |
| **`project_issues`** | **`project_id`** | **`projects(id)`** | **本次** |
| **`project_issues`** | **`process_id`** | **`project_processes(id)`** | **本次，可空** |
| **`project_issues`** | **`before_photo_id` / `after_photo_id`** | **`assets(id)`** | **本次** |
| `revisions` | `project_id` | `projects(id)` | 版本历史 |
| `tools` | `photo_id` | `assets(id)` | 1a |
| `tools` | `category` / `tool_group` | `tool_categories` / `tool_groups` | 1a |
| `fixtures` | `photo_id` / `center` | `assets(id)` / `fixture_centers` | 1a |
| `gauges` | `photo_id` / `category` | `assets(id)` / `gauge_categories` | 1a |
| `machines` | `photo_id` / `doc_id` | `assets(id)` | 1a |

一条命令可复核：`python tools/audit_foreign_keys.py --with-process`
（副本上把新表建出来后，逐表打印外键、并对账"有没有欠着的外键"）。

### 3.2 共享库的引用也改成真外键（`ON DELETE SET NULL`，本轮定稿）

原先这 4 列是"id + 快照"的软引用，理由是"共享库会被整表重建，真外键会把行卡住或清空"。
**按你的口径定稿：有关联就用真外键**，所以它们已经全部改成真外键 + `ON DELETE SET NULL`：

| 列 | 指向 | 删库行时 | 项目里的数据怎么保住 |
| --- | --- | --- | --- |
| `project_processes.machine_id` | `machines(id)` | `SET NULL` | `machine_snapshot`（型号/班次/价格）；读模型的 `mid` 按快照回退 |
| `project_process_tools.tool_id` | `tools(id)` | `SET NULL` | `tool_price` / `tool_life` 快照 |
| `project_process_tools.handle_id`（页面键 `hld_id`） | `tools(id)` | `SET NULL` | `hld_price` 快照 |
| `project_process_tools.accessory_id`（页面键 `acc_id`） | `tools(id)` | `SET NULL` | `acc_price` 快照 |

原来担心的"库重建把行卡住"用两件事解决，不用牺牲外键：

1. **改名不改写引用**：基础库迁移是"改名 → 建同名新表 → 搬数据 → 删旧表"，
   `ALTER TABLE … RENAME` 默认会把**别的表**里指向它的 `REFERENCES` 一起改写
   （`tools` → `tools_pre_foreign_keys`），删掉旧表后子表的外键就指向不存在的表。
   改名那一步现在包在 `MachiningDFMStore._rename_compat()`（`PRAGMA legacy_alter_table=ON`）里。
2. **空 = NULL，不是空串**：外键列在 DDL 里由外键那一份声明建（可空 TEXT + `REFERENCES`），
   `_clean_foreign()` 把空值统一写 `NULL`——空串在 SQLite 里是一个真值，会踩外键。
   这几列同时登记在字段表里（`mid` → `machine_id`、`hld_id` → `handle_id`、`acc_id` → `accessory_id`），
   `_clean_foreign()` **列名与字段键都认**，所以页面提交 `mid` 也能通过外键校验。

对外行为**一点没变**：字段形态的外键列在类型化视图里仍旧是空串（旧形态就是 `NOT NULL DEFAULT ''`），
纯外键列（`fixture_id`/`gauge_id`/`process_id`）是 `None`；`mid` 在库行被删后按
`machine_snapshot.id` 回退，读模型不会因为"库里删了一台设备"就少一个字段。

**现在软引用那一栏是空的**——项目业务数据里有关联的列全部是真外键，
`tools/audit_foreign_keys.py --with-process` 的输出里"故意保持软引用的列"会打印
"（没有：有关联的列现在全是真外键）"，并且这一节下面第 3.3 条把每个 `SET NULL` 列的原因逐条列出。

### 3.3 唯一的例外：`project_changes.entity_id`（多态，阶段 3 再定）

`entity_id` 要指向"工序 / 刀具行 / 问题 / 选型"四种行里的一种，SQLite 的外键**只能指一张表**，
所以它保持"类型列 + 逻辑校验"（详见阶段 3 的设计文档）。除此之外没有软引用了。

另外，`assets` 的回收判断已经改成**按外键元数据全库扫**
（`app/machining_library.py::asset_used_elsewhere`）：换图/清图时只要还有**任何**表
（含新表、含别的表的同名图）指着这张图就不删附件行——以前只扫自己那张表。

## 4. 读模型：`is[]` 一个字都不能变

`compose_issues()` 输出的键顺序与线上完全一致：`tp, pr, ds, fx, cr, st, bI, aI`。
`pr` 取**当前工序名**（外键 → 工序表），取不到用 `process_name_snapshot`。
`bI/aI` 给附件 URL（`inline_assets=True` 时给 data URL，导出用）。

`legacy_issues()`：这个项目表里一行都没有就返回 `None`，读模型回退 `state_json.is`
（与 1b 的 `legacy_processes` 同一套"表里有数据才是权威"的规则）。

## 5. 迁移（`tools/migrate_project_processes.py`，一次做完 1b + 2a）

顺序：**整库备份 → `state_json` 归档进 `processes_legacy_v1` → 拆工序/刀具行 →
拆问题清单（按工序当前名字绑外键）→ 写 `project_business_version = 2` → 重新打开逐字节验证**。

绑外键的规则是**不猜**：名字唯一对上才写 `process_id`；找不到 / 同名多道都留空、
只存名字快照，并在报告里列出来（本次线上数据：2/2 唯一对上，0 找不到、0 同名多道）。

验证项（干跑与 `--apply` 都跑）：

```
√ pr[] 与迁移前逐字节相同（6974 字节，含键序）
√ 只凭两张表就能完整还原 pr（表是唯一权威，不用看 state_json）
√ （副本上）把 state_json.pr 清掉后读模型依旧
√ is[] 与迁移前逐字节相同（236 字节，含键序）
√ 只凭问题清单表就能完整还原 is（表是唯一权威）
√ （副本上）把 state_json.is 清掉后读模型依旧
√ 成本基线 process_count 2 → 2 ／ tool_row_count 25 → 25
```

回滚：删掉 `project_business_version` 这一个键即可（`state_json` 全程没被动过），
读模型立刻回到迁移前那一份，表里的行原样留着。

## 6. 接口与前端

接口见 README（7 条 `issues` 路由）。两条口径：

* 开关没开（版本 < 2）→ **409**；行不属于该项目 → **404**；外键指向的行不存在/已删除 → **422**；
* 每个写操作都递增项目版本并留一个版本快照（口径 1），返回整个项目记录给前端 `adopt(record)`。

前端 `static/machining_dfm/issue_page.js` 接管 10 个写入点（与 1b 同一套写法）：

* 写前先 `GET /issues` 拿最新行列表再按下标取行 id，长度对不上就提示刷新、不硬写；
* 工序那一栏落表后是**下拉选工序行**（写 `process_id`），开关关着时仍是文本框；
* 图片粘贴 → 先落附件库再写 `before_photo_id`/`after_photo_id`；
* 删除走逻辑删除接口（回收站可恢复），与旧 `delIssue` 同名入口；
* 保存后 `adopt(record)` 对齐指纹，不会再冒出一次整份保存。

两个明确的显示规则（都是"表是权威"的自然结果）：

* **逻辑删除的行不进读模型**：页面上点"删除"，这一条就从 `is[]` 与 DFM 报告里消失；
  行还在表里、回收站能恢复（全删光时读模型是空数组，**不会**回退 `state_json.is` 把删掉的又显示出来）；
* **工序下拉选「未指定」= 解除绑定**：显示名一并清空（`pr` 变空）；
  之前那个名字仍留在历史版本快照里（口径 1：每次保存都留版本）。

排序口径：问题清单在页面上是一张平表，序号在**整个项目**内递增
（`order_scope = "project"`）。刀具行仍然是"每道工序内各自一条序列"。

## 7. 验收命令

```powershell
.venv\Scripts\python.exe -m pytest tests -q                       # 119 passed（含 2a 的 18 条 + 2b 的 29 条 + 外键 5 条）
.venv\Scripts\python.exe tools\check_process_wiring.py            # 32 个写入点全部"行级保存 + 旧路径"
.venv\Scripts\python.exe tools\migrate_project_processes.py       # 干跑（副本，含 pr/is/选型四个数组的字节校验）
.venv\Scripts\python.exe tools\audit_foreign_keys.py --with-process   # 外键总清单
node tools\smoke_machining_page.mjs                               # 冒烟（含 2a/2b 关/开两态）
```

干跑副本上另外做过两次体检（结果都干净）：

```powershell
# 副本库里：外键零违规，且 25 行刀具行全部绑上真刀具、2 道工序都绑上真设备
PRAGMA foreign_key_check;   -- 空 = 干净
SELECT COUNT(tool_id), COUNT(*) FROM project_process_tools;   -- 25 / 25
```

`--keep` 可以把副本留下来人工复核（默认跑完就删）。

## 8. 已知的下一步

* 阶段 3：版本履历（`vh[]` + `revisions`）合并成 `project_versions` + `project_changes`；
* 阶段 4：回收站界面（接口已经具备）；
* 阶段 5：剩余附件归项目。

---

# 阶段 2b：选型报价落表（`project_selections`）

## 9. 实测现状（线上 1 个项目，v60）

| 事实 | 值 |
| --- | --- |
| `G.fixQ`（夹具选型） | `["","","",""]` —— 4 格，全空 |
| `G.fixQC`（夹具是否报价） | `[1,1,1,1]` |
| `G.insp`（检具选型） | `["","","","",""]` —— 5 格，全空 |
| `G.inspQ`（检具是否报价） | `[1,1,1,1,1]` |
| 模具中心字典 `fixture_centers` | 4 行（`name` 是主键 + `sort_order`，没有 id 列） |
| 检具类别字典 `gauge_categories` | 5 行（同上） |
| 夹具库 `fixtures` / 检具库 `gauges` | 177 / 437 行；`fixtures.center`、`gauges.category` 都指向字典 |

四个数组的**下标就是类别在字典里的顺序**（页面上 `fixClasses()` / `inspClasses()` 的顺序），
元素是拼出来的字符串：`中心|夹具名称`、`检具类别|产品尺寸|检具尺寸`。
旧结构的老毛病：库里改名之后数组里还是老名字，**这一格就指向了不存在的夹具**。

## 10. 表设计

```sql
CREATE TABLE project_selections (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),          -- 真外键
  kind TEXT NOT NULL CHECK (kind IN ('fixture','gauge')),
  fixture_center TEXT REFERENCES fixture_centers(name) ON DELETE SET NULL,
  gauge_category TEXT REFERENCES gauge_categories(name) ON DELETE SET NULL,
  fixture_id TEXT REFERENCES fixtures(id) ON DELETE SET NULL,
  gauge_id  TEXT REFERENCES gauges(id)   ON DELETE SET NULL,
  legacy_key TEXT NOT NULL DEFAULT '',                       -- 旧字符串（迁移逐字节的保险）
  name_snapshot TEXT NOT NULL DEFAULT '',                    -- 口径 4：按选型当时的价/名算
  drawing_snapshot TEXT NOT NULL DEFAULT '',
  price_snapshot REAL NOT NULL DEFAULT 0,
  days_snapshot REAL NOT NULL DEFAULT 0,
  design_days_snapshot REAL NOT NULL DEFAULT 0,
  quoted INTEGER NOT NULL DEFAULT 1,                          -- fixQC / inspQ 那一格
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
  CHECK (kind <> 'fixture' OR (gauge_category IS NULL AND gauge_id IS NULL)),
  CHECK (kind <> 'gauge'   OR (fixture_center IS NULL AND fixture_id IS NULL)),
  CHECK (quoted IN (0,1))
)
```

**一行 = 一个格子**（类别 + 下标），不是"一个选型"：

* **未选型的格子也要有行** —— 否则"是否报价"的勾选没地方存（线上现在就是 9 个格子全都有值）；
* 一个格子一行也保证了"同一类别不会有两条选型"，不需要额外唯一索引；
* `order_scope = "project"`：全项目一条序列（与问题清单同一套），
  拆迁时用 `order=slot` 显式把下标写进去（不靠自增顺序）。

为什么是**两个类别列 + 两个库行列**而不是一个多态 `library_id`：
多态列没法建外键，而这次的要求是"有关联的数据结构全部使用外键约束"。
分成四列之后每一列都是真外键，`CHECK` 保证同一行只挂一边。

## 11. 外键对账（本次新增）

| 表 | 列 | 指向 | ON DELETE | 说明 |
| --- | --- | --- | --- | --- |
| `project_selections` | `project_id` | `projects(id)` | NO ACTION | 项目没了选型就没意义 |
| `project_selections` | `fixture_center` | `fixture_centers(name)` | SET NULL | 字典用名字做主键 |
| `project_selections` | `gauge_category` | `gauge_categories(name)` | SET NULL | 同上 |
| `project_selections` | `fixture_id` | `fixtures(id)` | SET NULL | 库行删掉不挡删除，价格走快照（口径 4） |
| `project_selections` | `gauge_id` | `gauges(id)` | SET NULL | 同上 |

四个外键列都建了索引（`index_ddl()` 自动覆盖每个外键列）。
`tools/audit_foreign_keys.py` 里登记了这 4 列，并单独一节输出
"是真外键、但按口径用 SET NULL 的列"（现在这一节里有 8 列：选型 4 列 + 工序/刀具行 4 列）。

## 12. 读模型：`fixQ/fixQC/insp/inspQ` 一个字都不能变

`compose_selection_arrays()` 按**当前字典顺序**铺格子，再逐行填：

* 名称/图号**优先取当前库行**（库里改名后选型跟着走 —— 这是修 bug 的地方）；
* 库行不在了（SET NULL）才用 `name_snapshot`/`drawing_snapshot`；都没有就退回 `legacy_key` 原样；
* `quoted` 直接来自行，未选型的格子默认 `1`（与旧页面 `push(1)` 的行为一致）；
* 行所属类别已从字典里删掉 → 这一行**不再出现在数组里**（数组长度跟着字典变），行留着当历史。

类别归属的判定规则（迁移与写入共用 `resolve_category()`）：
**旧串自己带的类别优先，它不在字典里才退回格子所在类别**。
理由：正常数据里两者永远一致（页面就是按格子类别拼的串）；
万一不一致，以串为准才能让"表是唯一权威"之后读模型仍然原样还给旧值 —— 同时迁移报告里会列出来让人看见。

`legacy_selection_arrays()`：这个项目表里一行都没有 → 返回 `None` → 读模型回退 `extra_json`
（与 `legacy_processes` / `legacy_issues` 同一套"表里有数据才是权威"的规则）。

## 13. 迁移（同一个工具，一次做完 1b + 2a + 2b）

新增第 5 步 **`apply_selection_split`**：按格子拆成 4 + 5 = 9 行，
按旧串在库里找**唯一**那一条绑 `fixture_id`/`gauge_id`（重名不猜、库里没有就只留旧串 + 快照），
最后一步才写 `project_business_version = 3`。

选型部分的验证项（干跑实测输出）：

```
√ 选型四个数组与迁移前一致（105 字节，含键序）
√ 只凭选型表就能完整还原选型与报价勾选（表是唯一权威）
√ （副本上）把 extra_json 里的四个旧数组清掉后读模型依旧
```

"缺键"的老项目（`G` 上压根没有这四个键）按**页面默认值**比对：
页面 `applyData`/`init` 会给它们补 `["",…]` / `[1,…]`，所以迁移后是"全空串 / 全 1"不算差异，
工具会单独打一行说明，不算失败。

回滚口径与 2a 完全一致：**删掉 `project_business_version` 这一个键**即可（`state_json` 与
`extra_json` 全程没被动过），读模型立刻回到迁移前那一份（四个数组逐字节相同），表里的行原样留着。

## 14. 接口与前端

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/projects/{id}/selections` | 格子清单：`slots`（类别 + 下标）、`arrays`（四个数组）、行列表 |
| PUT | `/projects/{id}/selections/{kind}/{slot}` | 选一格：`{legacy_key}` 空串 = 清空这一格 |
| PATCH | `/projects/{id}/selections/{kind}/{slot}` | 只改"是否报价"：`{quoted}` |
| DELETE | `/projects/{id}/selections/{kind}/{slot}` | 清空这一格（**行保留**，只解绑 + 快照清零） |

口径：

* 开关没开（版本 < 3）→ **409**；`kind` 不是 `fixture`/`gauge` 或下标越界 → **404/422**；
* `legacy_key` 里带的类别与库里那条对不上（选了别类别的夹具）→ **422**，不硬塞；
* 库里同名多条 → **422**，提示"直接选具体的行"（不猜）；
* 每次写都递增项目版本并留版本快照（口径 1），返回整个项目记录给 `MachiningDFMHost.adopt(record)`。

前端 `static/machining_dfm/selection_page.js` 接管 4 个写入点：

* `setFixSel(k,v)` / `setInspSel(k,v)` → `SelectionPage.setSelection('fixture'|'gauge', k, v)`
  （提交旧格式字符串，**绑库由服务端做**，页面不需要知道库行 id）；
* 两个"是否报价"勾选框的 `onchange` 改由 `fxQuoteCall(k)` / `iqQuoteCall(k)` 生成
  → `SelectionPage.setQuoted(kind, k, this.checked)`；
* 写前先 `GET /selections` 确认这一格还在（字典可能刚被改过）：
  不在就提示"这一格已经不在了"并刷新，**不发写请求**（不猜）；
* 开关关着时 `spOn()` 为假，四个写入点一律走原来那一句（改内存 + 整份保存），老行为一字不变；
* 画面仍由 `legacy_app.js` 的 `fixQuoteTable()` / `inspQuoteTable()` 出，本模块只写不画。

## 15. 2b 的测试与冒烟

`tests/test_machining_selection.py`（29 条）覆盖：三档开关、DDL 的 `PRAGMA foreign_key_list`（含每个
`on_delete`）、绕过应用层直接写库时外键真的会报 `IntegrityError`、外键列都有索引、
"拆 → 还原"逐字节相同、未选型的格子也有行、幂等、快照、库里改名后选型跟着走、
库行删掉后按快照回退、字典删除/插队后按类别名定位不串位、按 id / 按旧串保存、
只改勾选、选错类别 422、下标越界 422、清空语义、列表接口、每次保存留版本。

冒烟（`tools/smoke_machining_page.mjs`）新增一节 `选型报价落表（2b）`：
开关关着 → 只动内存、勾选框还是旧写法；开关打开 → PUT 到
`/selections/fixture/0`（载荷是旧格式字符串）、勾选 PATCH 同一格、检具走 `/selections/gauge/2`、
清空走 DELETE 且**行还在**、下标越界**不发写请求**并给出提示、保存后没有多余的整份保存。

