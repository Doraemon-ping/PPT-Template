# 机加基础库拆分重构（设备库 + 刀具库 + 夹具库 + 检具库已完成）

> 目标：管理设置里的设备/刀具/夹具/检具库不再"一个库里存一个大 JSON 字段、整表覆盖保存"，
> 改成**一张表一行一条数据、字段独立成列、按行读写、附件走磁盘**。
> 设备库与刀具库已按此模式落地；夹具库/检具库照同一模板推进（第 10 节）。

## 0. 共用引擎

`app/machining_library.py` 是四个库共用的读写引擎（`LibraryField` 字段登记表、
`AttachmentSpec` 附件槽位、`TypedLibrary` 行级 CRUD/排序/附件/旧数据接入）。
每个库只声明"这个库长什么样"：

```python
class ToolLibrary(TypedLibrary):
    table = "tools"; table_label = "刀具"
    fields = TOOL_FIELDS            # 页面表头 = 建表 SQL = 校验规则 = 迁移依据
    attachments = TOOL_ATTACHMENTS  # 图片槽位 → assets 类别 → 列 → 旧读模型键
```

引擎负责：建表、`_typed`/`_legacy` 两套视图、`create/update/delete/reorder`、
附件上传/去重/释放、`insert_rows`（种子/迁移）、`replace_legacy`（旧整体保存兼容）、
兜底行（仅设备库 `supports_fallback=True`）。子类只写 `fields`、`attachments`
和少量钩子（`natural_key`、`display_keys`、`indexes`）。

## 1. 为什么改

旧实现把整个设备库序列化成一个 JSON 存进 `equipment.payload_json`：

| 问题 | 后果 |
| --- | --- |
| 无字段约束 | 前端输入什么就存什么，`rapid:"abc"`、缺字段、单位混用都能入库 |
| 图片 base64 混在行里 | 每台设备图片进快照与每个历史版本；17 台设备 = 每次保存都重复搬运几百 KB |
| 整表覆盖写 | 两个人同时维护不同的设备会互相覆盖；一次改动写全库 |
| 无外键 | 项目按数组下标 `pr[].mi` 引用设备，删掉一台设备后所有工序静默指向别的机型 |

拆分后的形态：**元数据进数据库表，文件进磁盘，引用用稳定 id**。

## 2. 表结构

`app/machining_machines.py` 是唯一字段登记处，表头与前端页面「设备数据库 / Machine DB」逐列对应：

| 页面列 | JSON/接口键 | 数据库列 | 类型 | 约束 |
| --- | --- | --- | --- | --- |
| 图片 Photo | `photo_url` / `photo_id` | `photo_id` | TEXT→assets.id | 附件，不是列 |
| 品牌 Brand | `brand` | `brand` | TEXT | ≤120 字 |
| 型号 Model | `model` | `model` | TEXT | ≤120 字 |
| XYZ行程 mm | `xyz` | `xyz` | TEXT | ≤60 字 |
| 定位精度 mm | `pa` | `pos_acc` | TEXT | ≤60 字 |
| 重复定位精度 mm | `rpa` | `rep_acc` | TEXT | ≤60 字 |
| 快移 Rapid m/min | `rapid` | `rapid` | REAL | ≥0，≤1000 |
| 换刀 TC s | `tc` | `tool_change` | REAL | ≥0，≤3600 |
| 转速 RPM | `spm` | `spindle_rpm` | REAL | ≥0，≤200000 |
| 刀库 ATC | `atc` | `atc` | INTEGER | ≥0，≤2000 |
| 价格(万¥) | `price` | `price` | REAL | ≥0，≤1,000,000 |
| 说明 Desc | `desc` | `remark` | TEXT | ≤500 字 |
| 上传资料 | `doc_url`/`doc_id`/`doc_name` | `doc_id`/`doc_name` | TEXT→assets.id | 附件，不是列 |

接口返回同时带 `id`、`sort_order`、`is_fallback`、`photo_url`、`doc_url`、`doc_name`
以及旧读模型键 `img`/`doc`/`docName`，因此旧前端与 PPT 目录绑定无需改动。

```sql
CREATE TABLE machines(
  id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL, is_fallback INTEGER NOT NULL DEFAULT 0,
  brand TEXT, model TEXT, xyz TEXT, pos_acc TEXT, rep_acc TEXT,
  rapid REAL, tool_change REAL, spindle_rpm REAL, atc INTEGER, price REAL, remark TEXT,
  photo_id TEXT REFERENCES assets(id), doc_id TEXT REFERENCES assets(id), doc_name TEXT,
  created TEXT, updated TEXT);
```

## 3. 附件：元数据在库、文件在磁盘

`app/machining_assets.py`

```sql
CREATE TABLE assets(
  id TEXT PRIMARY KEY, kind TEXT, mime TEXT, name TEXT, size INTEGER,
  sha256 TEXT, path TEXT, created TEXT);
CREATE UNIQUE INDEX ... ON assets(kind, sha256, name);   -- 去重
```

- 路径：`<数据目录>/assets/<kind>/<sha256 前两位>/<sha256><ext>`
- 类别：`machine_photo`（png/jpeg/webp/gif/bmp，≤8MB）、`machine_doc`（pdf/doc/docx/xls/xlsx/ppt/pptx/txt/csv/zip/rar/7z，≤2MB）、`tool_photo`（同图片白名单，≤8MB）
- 写入：临时文件 + `os.replace` 原子落盘；内容相同（`kind`+`sha256`+`name`）直接复用已有记录
- 读取：`GET /api/machining-dfm/assets/{id}`，带内容 `ETag`，`If-None-Match` 命中返回 304；`?download=1` 带原始文件名
- 删除：只在没有任何行引用该 `path` 时删文件（同图多机共用时不会误删）
- 启动时 `prune_orphans()` 清理无元数据的残留文件
- 备份 = `machining_dfm.sqlite3` + `assets/` 目录

## 4. 接口（`/api/machining-dfm`）

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/machines` | 公开（工艺设置选择器要用） | 列表 + 字段表 + `fallback_id` + 数量 |
| GET | `/machines/fields` | 公开 | 字段登记表（表头/单位/默认值） |
| POST | `/machines` | admin | 新增一台（未给字段取默认值） |
| PATCH | `/machines/{id}` | admin | **只更新提交的字段** |
| DELETE | `/machines/{id}` | admin | 被项目引用时 409 并列出项目；`?force=true` 强制删除 |
| POST | `/machines/reorder` | admin | 传完整 id 顺序数组 |
| PUT | `/machines/{id}/default` | admin | 设为兜底机型（互斥） |
| PUT/DELETE | `/machines/{id}/photo` | admin | 上传（原始字节）/ 清除图片 |
| PUT/DELETE | `/machines/{id}/doc` | admin | 上传（`?name=` 文件名）/ 清除资料 |
| GET | `/assets/{asset_id}` | 公开 | 附件（ETag / `?download=1`） |
| GET | `/tools` | 公开 | 刀具列表 + 字段表（含 `derived` 自动列）+ 数量 |
| GET | `/tools/fields` | 公开 | 刀具字段登记表（表头/单位/枚举/自动列） |
| POST | `/tools` | admin | 新增一件刀具 |
| PATCH | `/tools/{id}` | admin | **只更新提交的字段**（改库分类可同时带 `cat`） |
| DELETE | `/tools/{id}` | admin | 删除并回报按名称引用它的项目（不阻塞） |
| POST | `/tools/reorder` | admin | 传完整 id 顺序数组 |
| PUT/DELETE | `/tools/{id}/photo` | admin | 上传（原始字节）/ 清除图片 |
| PUT | `/libraries` | admin | 旧接口兼容：仍接受 `mdb`/`tdb`，按自然键匹配保留 id |

校验失败返回 422 且带中文原因（如「快移 Rapid不能为负数」），前端保存失败会回滚输入框。

## 5. 项目引用：`mid` 取代数组下标

- 写入：项目保存时把工序里的 `mi`（下标）解析成 `mid`（`machines.id`），`mi` 不再入库；
  下标越界 → 落到兜底机型。
- 读取：组合视图返回 `pr[].mid`，同时派生 `mi = 该设备在当前列表中的下标`，旧计算/导出代码零改动。
- 解析（`app/machining_projection.py::_machine_for`）：`mid` → 旧 `mi` 下标 → 兜底机型，三级兜底不丢数据。
- 删除被引用的设备需 `force=true`，指向它的工序自动改走兜底机型（不再静默错位到别的设备）。
- 兜底机型由 `is_fallback` 显式标记（种子数据里是"自定义"那台），取代旧的"数组最后一行"约定。

## 6. 数据迁移（首次启动自动执行）

`MachiningDFMStore._migrate_machine_library()`

1. 备份数据库到 `backups/pre-typed-machines.sqlite3`；
2. `equipment.payload_json` → `machines` 列：图片/资料的 base64 data URL 落盘成文件，行里改写为附件 id；
3. 复制原表到 `equipment_legacy_v1`（只读留档，便于回滚比对）；`equipment` 表保留但不再使用；
4. 重写所有项目与历史版本的 `pr[].mi` → `pr[].mid`；
5. 写入 `library_schema_version=2`，之后启动直接跳过（空库不会被初始数据填回来，`equipment` 为空也不再作为数据源）。

真实数据验证（27 台设备／17 张图片／15 个历史版本）：字段逐项比对 0 处差异，
17 张图片因两张字节相同去重为 16 个文件，历史版本数量与内容不变。

刀具库迁移（`_migrate_tool_library()`）同一套路，但分两步走完（v1 → v2 → v3）：
`tools` 表先按壳改名成 `tools_legacy_v1` 再建类型化表，761 行逐字段比对 0 处差异，
写 `tool_library_schema_version=2`；随后按第 7.1 节把库分类/类型拆成两张字典表，
把 `tools` 重建为"带字典外键"的版本，写 `tool_library_schema_version=3`。
迁移时对枚举列放宽校验，旧分类代码（如 `chamfer`）先按规则归一化，归一化不了的自动补录进类型字典。

## 7. 刀具库（已落地）

### 7.1 三张表：刀具本体 + 两张字典表

库分类与类型是**独立的两张字典表**，`tools` 里只存指向它们的文本码外键：

```sql
CREATE TABLE tool_groups(                      -- 库分类
  code TEXT PRIMARY KEY, label TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0, builtin INTEGER NOT NULL DEFAULT 1,
  created TEXT NOT NULL, updated TEXT NOT NULL);

CREATE TABLE tool_categories(                  -- 类型（工具类型/刀具分类）
  code TEXT PRIMARY KEY, label TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'cut',           -- cut 切削刀具 / nc 刀柄·配件
  sort_order INTEGER NOT NULL DEFAULT 0, builtin INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL DEFAULT 'seed',         -- seed 内置 / legacy 旧数据补录 / admin 管理员新增
  created TEXT NOT NULL, updated TEXT NOT NULL);

CREATE TABLE tools(
  id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL DEFAULT 0,
  tool_group TEXT NOT NULL DEFAULT 'hp' REFERENCES tool_groups(code),
  name TEXT NOT NULL DEFAULT '',
  category   TEXT NOT NULL DEFAULT 'other' REFERENCES tool_categories(code),
  diameter REAL, length REAL, spindle_rpm REAL, feed_rate REAL, life_minutes REAL, price REAL,
  photo_id TEXT REFERENCES assets(id), created TEXT NOT NULL, updated TEXT NOT NULL);
```

* `PRAGMA foreign_keys=ON`（连接层已开）真的兜底：往 `tools` 写字典里没有的码会被数据库拒绝，
  删被引用的字典项也会被挡住（接口先查引用数，返回 409 与更可读的提示）。
* 外键用**文本码**而不是自增 id：`grp`/`cat` 短码是页面、旧读模型、成本表与 PPT 共用的契约，
  用码做键可做到前后端零改动；代价是码不可改（改名只改 `label`，接口不接受改码）。
* 内置字典由种子灌入（`INSERT OR IGNORE`，只补不改）：管理员的改名、新增、排序都不会被覆盖；
  内置项不允许删除（否则下次启动又会被种子补回来），自定义项可以删。

| 页面列 | JSON/接口键 | 数据库列 | 类型 | 约束 |
| --- | --- | --- | --- | --- |
| 图片 | `photo_url` / `photo_id` | `photo_id` | TEXT→assets.id | 附件 `tool_photo`（旧读模型键 `tI`） |
| 库分类 | `grp` | `tool_group` | TEXT→tool_groups.code | 4 个内置分类，默认 `hp` |
| 型号 | `tp` | `name` | TEXT | ≤120 字 |
| 类型 | `cat` | `category` | TEXT→tool_categories.code | 47 个刀具分类 + `cn`/`im`，默认 `other` |
| D(mm) | `d` | `diameter` | REAL | ≥0，≤1000 |
| 长度L(mm) | `ln` | `length` | REAL | ≥0，≤5000 |
| 转速n(rpm) | `n` | `spindle_rpm` | REAL | ≥0，≤200000 |
| 进给vf(mm/min) | `vf` | `feed_rate` | REAL | ≥0，≤200000 |
| 寿命(min) | `life` | `life_minutes` | REAL | ≥0，≤1,000,000 |
| 价格(¥) | `price` | `price` | REAL | ≥0，≤10,000,000 |
| 每齿进给fz(自动) | `fz` | — | 派生 | `vf/n`，**不入库** |
| 线速度Vc(自动) | `vc` | — | 派生 | `π·d·n/1000`，**不入库** |

要点：

- **自动列不入库**：`fz`/`vc` 由页面现算，`GET /tools/fields` 用 `derived` 描述它们，
  避免"算出来的值被存死、改参数后不同步"。
- **枚举来自字典表**：`GET /tools/fields` 的 `fields[].choices` 是**从字典表实时读的**
  （`grp` 带 `label`、`cat` 多带一个 `scope`），页面表头与下拉都由它生成，
  前端不再各写一份分类字典（旧 `CATCN`/`GRPCN`/`HCATCN` 字面量已不参与渲染）。
  改一个中文名，刷新页面即可看到，前后端都不用改代码。
- **归属一致性**：`cat.scope=nc`（国内/进口）只能配 `hld`/`acc`；写接口返回 422，
  页面切换库分类时也会自动把类型改成 `cn`/`other`（与旧行为一致）。
  迁移与旧整体保存走"自动修正"而不是报错：`nc` 组配到切削类型就落 `cn`，反之落 `other`。
- **项目引用按名称**：工序刀具行自带参数快照，只在成本表按 `tp` 查 `price`/`life`，
  刀柄/配件按 `hld`/`acc` 名称查价 —— 不存数组下标，因此排序/删除刀具不会让项目数据错位；
  删除时接口只回报"哪些项目按名称引用过它"。
- **字典维护接口**（管理设置用，暂未做界面）：`GET /tool-dictionaries`（含各字典项被引用的次数）、
  `POST|PATCH|DELETE /tool-groups/{code}`、`POST|PATCH|DELETE /tool-categories/{code}`。
  校验：重复码 409、坏归属 422、被引用 409、内置项 409、改归属时已在使用 409。
- 迁移：
  1. v1 → v2：`tools.payload_json` → 类型化列，旧表归档 `tools_legacy_v1`，备份 `pre-typed-tools.sqlite3`；
  2. v2 → v3：建两张字典表 + 灌内置项 → 归一化表里已有的旧分类码、未知码补录进类型表 →
     **重建 `tools`**（SQLite 不能 ALTER 加外键：改名 → 建新表 → 搬数据 → 删旧表 → 重建索引），
     备份 `pre-tool-dictionaries.sqlite3`；判据是"两条字典外键是否都在"，不能只看
     `PRAGMA foreign_key_list` 是否非空（旧表本来就有指向 `assets` 的图片外键）。
     真实数据 761 行逐字段比对 0 处差异，二次启动幂等。
- 前端 `tools.js`（`window.ToolsPage`）逐字段 PATCH、图片粘贴/上传、增删/排序、
  库分类+类型筛选（`cut`/`nc` 由字典的 `scope` 决定），渲染后同步旧全局 `TDB`。

## 8. 夹具库 / 检具库（已落地）

### 8.1 表结构

| 表 | 说明 | 关键约束 |
| --- | --- | --- |
| `fixture_centers` | 模具中心字典（`name` 主键、`sort_order`、`builtin`、`source`） | 名称即主键，不可改名 |
| `fixtures` | 夹具本体 | `center → fixture_centers(name)`、`photo_id → assets(id)` |
| `gauge_categories` | 检具类别字典 | 同上 |
| `gauges` | 检具本体 | `category → gauge_categories(name)`、`photo_id → assets(id)` |

字段登记（对照页面表头，键是旧短键，列名是规范英文）：

| 库 | 键 → 列 | 类型/单位 |
| --- | --- | --- |
| 夹具 | `center→center` / `name→name` / `price→price` / `mc→process_days` / `rmk→remark` | ¥ ≤1e7 / 天 int ≤3650 / 备注 ≤300 |
| 检具 | `type→category` / `name→name` / `drw→drawing` / `prdSize→product_size` / `inspSize→inspection_size` / `price→price` / `dc→design_days` / `mc→process_days` | 图号 ≤80 / 尺寸文本 ≤80 / 万¥ ≤1e4 / 天 int ≤3650 |

### 8.2 类别字典：为什么用中文名作主键

项目快照里存的就是按名字拼的选择键（`G.fixQ[k]="模具中心|夹具名称"`、
`G.insp[k]="检具类别|名称|图号"`，成本表据此回查价格/设计周期/制造周期，且
`G.fixQC`/`G.inspQ` 与类别下标一一对齐）。用名称作外键可以让项目数据、成本表、
导出与页面全部零改动，代价是**类别不可改名**（`PATCH` 只接受 `sort_order`，改名返回 422），
只能"新增一个类别 → 搬迁数据 → 删掉旧类别"。

删除规则（`DELETE /fixture-centers/{名}`、`/gauge-categories/{名}`）：

- 内置类别（种子来的）→ **409 不可删**，带 `?cascade=1` 也不删（与刀具库分类一致）；
- 自定义类别、无数据 → 直接删；
- 自定义类别、有数据 → 409 并回报条数，带 `?cascade=1` 才连同该类数据一起删
  （前端会二次确认）。

种子：模具中心 `1025减震模具中心 / 1059轻合金模具中心 / 1929底盘模具中心 / 8107结构件模具中心`；
检具类别 `毛坯检具 / 成品机械检具 / 成品总成检具 / 成品电子检具 / 测量支架`。
种子只在迁移时写一次（`app_settings.fixture_categories` / `inspection_categories`，
即旧页面的 `G.fcnX` / `G.icnX`），所以删掉之后重启不会复活；数据里出现、字典里没有的
类别会在迁移时自动补录并记 `source='legacy'`。

### 8.3 迁移

`_migrate_fixture_library()` / `_migrate_gauge_library()`（版本键
`fixture_library_schema_version` / `gauge_library_schema_version`，当前都是 2）：

1. `_prepare_*_table()`：老 `fixtures` / `gauges` payload 表改名成
   `fixtures_legacy_v1` / `gauges_legacy_v1` 归档（**只建一次**），再建类型化表 + 外键 + 索引；
2. 种子字典（优先读 `app_settings` 里的旧类别列表，其次模块默认值）；
3. 逐行转列：`payload_json` → 字段列，`img` 里的 base64 落盘成 `assets` 行并回填 `photo_id`，
   类别缺失时补录字典；
4. 备份 `backups/pre-typed-fixtures.sqlite3` / `pre-typed-gauges.sqlite3`，写版本号。
   真实数据 177 条夹具 + 437 条检具逐字段比对 0 处差异；二次启动幂等。

### 8.4 接口

除与设备/刀具共用的行级接口外，新增：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/fixtures` `/gauges` | 行列表 + 字段登记表（含类别下拉与 `references`） |
| GET | `/fixtures/fields` `/gauges/fields` | 只取字段登记表 |
| POST/PATCH/DELETE | `/fixtures` `/fixtures/{id}` `/gauges` `/gauges/{id}` | 行级增改删（每次只提交变化的字段） |
| POST | `/fixtures/reorder` `/gauges/reorder` | 整组排序（必须提交全量 id） |
| PUT/DELETE | `/fixtures/{id}/photo` `/gauges/{id}/photo` | 图片上传/删除（`fixture_photo` / `gauge_photo`） |
| GET/POST | `/fixture-centers` `/gauge-categories` | 类别字典（名单 + 引用计数），新增类别 |
| PATCH/DELETE | `/fixture-centers/{名}` `/gauge-categories/{名}` | 只改 `sort_order`；删除带 `?cascade=1` |
| GET | `/library-dictionaries` | 两个字典 + 引用计数（前端一次取全） |

### 8.5 前端

- `static/machining_dfm/library_pages.js`：`createNamedLibraryPage(cfg)` 工厂——
  两个库的页面结构完全一样（按类别分组的多卡片表格），差异只有字段、分组键与接口，
  所以渲染/交互写一份，`fixtures.js` 与 `gauges.js` 只留配置（表头、默认行、说明文案）。
- 每行编辑只 `PATCH` 该行该字段；图片走 `armPaste` / `imgShrink` / `openImg`（复用旧页面工具），
  上传后把服务端返回的行合并回来；渲染后同步旧全局 `FDB` / `IDB` 与
  `G.fcnX` / `G.icnX`（报价选型、成本表、导出继续可用）。
- `legacy_app.js`：`bFixDB()` / `bInspDB()` 委托 `FixturesPage` / `GaugesPage`，
  `addFixClass`/`delFixClass`/`addInspClass`/`delInspClass`/`addF`/`addI` 也全部委托，
  本地兜底实现保留在后面（模块未加载时仍能跑）。
- `host.js`：`libraryState()` 返回 `{}`——四个基础库都是按行直存，
  不再有"整库保存"的内容；类别只在 `G.icnX` / `G.fcnX` 上做只读缓存（`categoryState()`）。
- 缓存版本号：`?v=library-v6`（`index.html` 与 `tools/integrate_machining_dfm.py` 同步）。

### 8.6 一条被实测抓到的坑：整库保存不能"提交里没有就删"

`PUT /libraries` 原来沿用"匹配到的更新、新的插入、缺失的删除"的整表覆盖语义。
夹具/检具接进来之后，这个语义在真实库上**一次就删掉了 177 条夹具 + 437 条检具**：
旧页面提交的是它内存里的数组，只要只带了一部分（或数组被新模块就地同步过），
其余数据就会被静默删除。现在这条兼容接口固定为**只增改不删**
（`replace_legacy(rows, prune=False)` 是默认值，`prune=True` 只留给维护脚本），
删除一律走行级 `DELETE /{库}/{id}`。回归用例：
`test_legacy_bulk_save_never_deletes_rows`；线上自检里的"部分提交不删数据"一条。

数据被删时靠三样东西恢复：`backups/pre-typed-*.sqlite3` 备份、
`*_legacy_v1` 归档表、以及 `tools/restore_fixture_gauge.py`（清空类型化表 + 删版本键，
让下一次启动按归档重新迁移，实测把 177 + 437 行原样重建）。

### 8.7 前端改造踩到的第二个坑：动作之后没人换画面（已修）

四个库的模块各自有一个 `render()`，但它**只负责拼 HTML 字符串**——旧页面的
`bFixDB()`/`bMachDB()` 拿到字符串后由 `legacy_app.js` 的整页 `render()` 塞进
`#mainPanels`。改造时模块内部的动作（新增/删除/换图/加删类别/字段提交）也跟着调
自己的 `render()`，于是数据写进库了、状态栏也提示"已新增"，**屏幕上的表格却一直没变**，
看起来就是"点了没反应"。

修法：每个模块加一个 `repaint()`（`library_pages.js` / `machines.js` / `tools.js` 各一份），
动作成功后调它，由它去调旧的整页 `window.render()`；模块的 `render()` 保持不变，
避免 `render → repaint → render` 递归。

- 回归自检：`node tools/smoke_machining_page.mjs`——用最小 DOM 垫片把整页脚本按
  `index.html` 的顺序真跑一遍（直连服务取真实数据，写请求被拦下不落库），
  逐个页签渲染，并对夹具库/设备库/刀具库的"字段保存、新增、删除、新增类别"
  断言 `#mainPanels` 的 HTML **确实变了**（旧代码在这里会红）。同时扫描
  `undefined` / `NaN` / `[object Object]` 是否漏进页面。
- 另有一个对照脚本 `node tools/compare_library_pages.mjs`：用改造前的
  `legacy_app.js` 备份渲染同一份数据，对比新旧页面的 `<th>` 表头、卡片标题、
  按钮文案，确认重构没有悄悄丢列丢按钮（实测表头完全一致）。

## 9. 前端约定（设备 / 刀具）

- `static/machining_dfm/machines.js`：设备库独立模块（`window.MachinesPage`），
  负责表格渲染、逐字段 PATCH、图片粘贴/上传、资料上传、增删、排序、设兜底；
  改完立即把服务端返回的行同步进旧全局 `MDB`，流程图/工序下拉/PPT 导出继续可用。
- **模块 `render()` 只生成 HTML，动作后一律 `repaint()`**（见 8.7）：模块的
  `render()` 由 `legacy_app.js` 的页签函数调用；动作路径要换画面必须走 `repaint()`。
- `legacy_app.js`：`bMachDB()` / `bToolDB()` 只做权限检查后委托 `MachinesPage` / `ToolsPage`；
  设备解析统一走 `gm(pi)`（按 `mid`，兼容旧 `mi`）；工序设备下拉的值改为设备 id
  （`setProcMachine`）；新增工序默认取兜底机型。夹具/检具的委托见 8.5。
- `host.js`：四个基础库都按行直存，`libraryState()` 返回空对象；只保留
  `MachiningDFMHost.token('admin')` 供各库直存与 `categoryState()` 供类别缓存。
- 缓存：`index.html` 静态资源版本号统一 `?v=library-v6`，改前端务必同步改版本号
  （`tools/integrate_machining_dfm.py` 里的模板同步改），否则浏览器会拿旧脚本、
  出现"改了没生效"的假故障。`tools/check_served_page.py` 可核对线上页面版本与静态资源 200。
- 样式表：`app.css`（表单）与 `host.css`（顶部项目条 `#serverProjectBar`、后台配置弹窗
  `.server-dialog*`、库计数 `.server-counts`）。`host.css` 在分支拆分时被删掉过一次，
  而 `index.html` 一直挂着 `<link>`，浏览器拿 404，顶部与弹窗等于没样式——已按拆分前的版本
  恢复；`tools/check_host_css.py` 专门盯这件事（class 有没有样式、样式表会不会 404、版本号是否统一）。

## 10. 已知边界

- **导出**：`exportData()`（JSON 备份）与 `exportDFM()`（页面内 PPT）在导出前会调用
  `inlineSheetImages()` 把 `assets` URL 换回 data URL，离线文件仍带图 ✓。
  但「另存为单文件 HTML」(`buildPortableHTML()`) 早在本轮改造之前就已经失效：
  静态化拆分后 `index.html` 里没有 `<!-- DATA_MARKER -->`，且导出的 HTML 引用的是
  `/static/machining_dfm/*.js` 绝对路径。`host.js` 已把 `window.exportHTML` 指向
  `exportData`，所以界面上的导出按钮走的是 JSON 路径；要恢复单文件导出需要把
  CSS/JS 一并内联，列为后续任务。
- **项目内图片**（`G.pI` 等）仍是快照里的 data URL，尚未走 `AssetStore`（第二步）。
- **`/libraries`** 仅作为旧前端兼容层保留，新前端不再使用（见 10.5 的"只增改不删"约定）。
## 11. 后续

1. **项目内图片**（`G.pI`，单张 base64 约 60 KB）搬到 `AssetStore`，与设备/刀具/夹具一致；
2. 「另存为单文件 HTML」导出恢复（内联 CSS/JS）；
3. 分支 `machining` 合并回 `api-machining`。
