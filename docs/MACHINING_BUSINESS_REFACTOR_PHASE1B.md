# 1b 阶段设计：工序 + 工序刀具行 落表（待拍板）

> 上游口径见 `docs/MACHINING_BUSINESS_REFACTOR.md`（第一阶段「项目信息」已落地，见该文第 10 节）。
> 本文只讲**工序（`pr[]`）与工序刀具行（`pr[].tl[]`）**这一块：表结构、引用改造、迁移口径、验收。
> 本文数字全部来自线上库与前端源码的实测（工具：`tools/show_business_shape.py`、
> `tools/show_name_lookups.py`、`tools/analyze_tool_name_matching.py`、`tools/check_tool_life_price.py`）。

---

## 1. 实测现状（线上库 1 个项目）

| 数组 | 行数 | 键（实测，键集合完全一致） |
|---|---|---|
| `pr[]` 工序 | 2 | `nm` 工序名 · `mc` 台数 · `mid` 设备 id · `cI` 夹具示意图图片 · `nc` 六个计数 · `tl` 刀具行 · `fixP` 夹具费 · `eqP` 设备费 · `mi`（读模型补的下标，派生） |
| `pr[].tl[]` 刀具行 | 25 | `id` 工序内序号(`T01`) · `tp` 刀具名 · `ds` 说明 · `d` 直径 · `n` 转速 · `vf` 进给 · `ln` 切削长度 · `ps` 次数 · `cn` 刃数 · `bg` 粗/精 · `td` 单件时间 · `fi` · `tt` 辅助时间 · `sd` · `cat` 类别 · `hld` 刀柄名 · `acc` 配件名 · `_ct/_vc/_vf/_fz`（前端算的派生值） |
| `nc` 计数 | — | `{cc:2, co:2, mc_:2, sc:2, ac:1, it:5}` —— 六个固定计数，不是自由字典 |
| `is[]` 问题清单 | 2 | `tp/pr/ds/fx/cr/st/bI/aI`，其中 **`pr` 是工序名字**（实测两行都指向 `机加工序-OP10`） |
| `vh[]` 版本履历 | 0 | 空 |

派生值公式（`legacy_app.js` 的 `calcT()`，读时算，**不落库**）：

```
_ct = vf>0 ? (ln/vf*60)*ps*cn : 0      // 切削时间 min
_vc = round(π*d*n/1000)                // 线速度 m/min
_vf = vf
_fz = n>0 ? vf/n : 0                   // 每齿进给
```

### 1.1 四处实测出来的缺陷 / 隐患（这就是要改的理由）

1. **刀具行与刀具库之间只有名字**：`tl[].id` 是工序内编号（`T01`），不是刀具库 id；
   前端 6 处按 `TDB[j].tp===…` 找库行（`toolCost()`、刀具价格表、刀柄、配件、`atT()`）。
   **刀具库 761 行里有 26 个重名**（例：`D18R0.8*30*L105*SD18`、`PCD-HSK63A-D30-150`）。
   现在这 25 行恰好都是唯一名（没踩到），但**一旦用到重名刀具，`toolCost()` 静默取第一行**——
   报价与寿命可能取到另一个规格，且不报错。改名同理：`toolCost()` 匹配不到就 `return 0`，静默漏算。
   （实测：`tools/analyze_tool_name_matching.py` → 重名命中 0 行、找不到 0 行，**隐患尚未发生**。）
2. **"价格快照"其实已经有雏形，只是没人用**：`atT(pi,i,tp)`（选中刀具时触发）本来就会把库里的
   `d/n/vf/ln/cat/life/price/grp` **拷进刀具行**——但 `toolCost()` 不用行内的 `t.price/t.life`，
   而是再按名字去库里查一遍；且当前 25 行**根本没有 `price/life/grp` 这三个键**
   （实测：`sorted({k for ...})` 为空），说明这条快照路径在现有数据上从未生效。
   结论：1b 不用新造机制，只要**把行内快照变成唯一口径**并把 `atT` 改成按 id 拷贝。
3. **价格数据本身是空的**：刀具库 761 行 `life` 与 `price` **全部是 0**；设备库那台 `S500Z1` 的
   `price` 也是 **0.0**（`setProcMachine` 只在 `price>0` 时才写 `eqP`，所以工序里 `eqP=[0,0]`）。
   → 报表里"刀具单件成本"与"设备成本"今天是空的。夹具库是真有价的（`16000.0`），检具库也有（`9.0` 万）。
4. **问题清单按工序名引用**：`is[].pr` 存的是 `机加工序-OP10`。工序改名/删除后，问题清单会静默指向不存在的工序。
   另外夹具引用 `fixByKey("中心|名称")`（5 处）、检具引用 `inspByKey("类型|名称|图号")`（6 处）都是复合名引用。

> 已排除的怀疑：**派生值 `_ct/_vc/_vf/_fz` 没有过期**。用前端 `calcT()` 公式把 25 行重算一遍，
> 与库里存的值**逐行一致（0 行不一致）**，见 `tools/capture_process_cost_baseline.py` 的诊断段。

> 补充：`cI` **不是**夹具引用，是"工序夹具示意图"（data URL 图片，前端 `armPaste`/`pickImg` 维护、
> >150000 字符会被压）；`mid` 已经在用设备 id（`MachinesPage`），说明 id 引用这条路本项目已经走通过。

### 1.2 成本基线（1b 验收的比对基准）

`tools/capture_process_cost_baseline.py` 已冻结改造前的成本数字到
`tools/baselines/process_cost_baseline.json`（16.9 KB，指纹 **`a1baaace6bf031ab`**）：

```
工序 2 道 · 刀具行 25 行
刀具单件成本合计 = 0.0 元/min（库价全 0）
夹具选型合计     = 0.0（本项目未选型）
检具选型合计     = 0.0（本项目未选型）
诊断：派生值过期 0 行 · 按名字找不到库行 0 行 · 库价/寿命为 0 的刀具行 25 行
```

改造后用 `python tools/capture_process_cost_baseline.py --check` 比对，**指纹必须不变**；
指纹变了就逐项列出是哪道工序、哪一行刀具的成本动了。基线里图片只存 sha256 与字符数（不塞 data URL）。

---

## 2. 表设计

### 2.1 `project_processes`（工序，行级）

| 列 | 类型 | 来源 / 说明 |
|---|---|---|
| `id` | TEXT PK | 新 uuid（旧数据没有行 id） |
| `project_id` | TEXT NOT NULL | → `projects.id`，删除级联用逻辑删除 |
| `sort_order` | INTEGER | 工序顺序（原来的数组下标；导入/排序都靠它） |
| `name` | TEXT | `nm` 工序名（唯一性不做约束：允许两序同名，但界面提示） |
| `machine_id` | TEXT | `mid` → 设备库 id（可空：库里没有的设备允许空） |
| `machine_snapshot` | TEXT(JSON) | 选中设备时的 品牌/型号/行程/转速 快照，库改或删了报表仍可读 |
| `machine_count` | INTEGER | `mc` 台数 |
| `fixture_photo_id` | TEXT | `cI` 夹具示意图 → `assets`（**本阶段就归位**，见第 8 节问题 3） |
| `fixture_price` | REAL | `fixP` 夹具费（手填） |
| `equipment_price` | REAL | `eqP` 设备费（手填） |
| `count_json` | TEXT(JSON) | `nc` 六个计数（固定六键，铺成 6 列收益不大，且以后加键不用迁移） |
| `note` | TEXT | 预留备注（旧数据没有，空着） |
| `deleted_at/deleted_by/deleted_reason` | | 逻辑删除三列（口径 2：永不物理删除） |
| `created/updated` | TEXT | 时间戳 |

`nc` 为什么用 JSON：它只有六个固定计数（`cc/co/mc_/sc/ac/it`），报表按这六个名字取值，
铺成六列除了让 SQL 好看没有别的收益，反而以后加一个计数就要迁移一次。

### 2.2 `project_process_tools`（工序刀具行，行级）

| 列 | 类型 | 来源 / 说明 |
|---|---|---|
| `id` | TEXT PK | 新 uuid |
| `process_id` | TEXT NOT NULL | → `project_processes.id` |
| `project_id` | TEXT NOT NULL | 冗余一列，按项目查刀具行不用 join |
| `sort_order` | INTEGER | 工序内顺序 |
| `code` | TEXT | `id` = `T01` 这种工序内编号（报表按它排/引用，保留） |
| `tool_id` | TEXT | `tp` → **刀具库 id**（可空，口径 8：允许一次性刀具） |
| `tool_name` | TEXT | 刀具名（快照，也是"库里没有"时手填的名字） |
| `tool_category` | TEXT | `cat`（快照，报表按它分组） |
| `tool_group` | TEXT | 选中刀具时的 `grp`（hp/dp…，快照） |
| `tool_price_snapshot` | REAL | **选型当时的刀具价格**（口径 4） |
| `tool_life_snapshot` | REAL | **选型当时的刀具寿命** |
| `handle_id` / `handle_name` / `handle_price_snapshot` | TEXT/TEXT/REAL | `hld` 刀柄（现在是名字，改 id + 快照） |
| `accessory_id` / `accessory_name` / `accessory_price_snapshot` | TEXT/TEXT/REAL | `acc` 配件（同上） |
| `description` | TEXT | `ds` |
| `diameter` / `spindle_rpm` / `feed_rate` / `cut_length` | REAL | `d/n/vf/ln` |
| `passes` / `flutes` | INTEGER | `ps/cn` |
| `roughing` | INTEGER(0/1) | `bg` |
| `cut_time` / `aux_time` / `depth` | REAL | `td/tt/sd` |
| `fixture_ref` | TEXT | `fi`（旧数据全是 null，保留键不丢） |
| `deleted_at/...` `created/updated` | | 同上 |

> 落地时的两处小改：`fi`（刀具行图片）**做成附件槽**（`tool_photo_id` → `assets`）而不是文本列
> —— 前端本来就用 `armPaste`/`pickImg` 往里塞 data URL；`ds`（加工特征）与 `hld`/`acc` 在页面
> 表头里叫"加工内容/刀柄选型/配件选型"，字段标签按页面口径写。

**不落库**：`_ct/_vc/_vf/_fz`（读时按 `calcT()` 公式算；`compose()` 照旧把它们塞回 `tl[]`，前端与报表零改动）。

**快照语义**（要写进界面提示）：
- 选中刀具时把库里的 `price/life` 拷进快照列；**之后库改价不影响已存行**（口径 4）。
- 刀具详情里并列显示"选型快照价 / 库当前价"，不一致时给出"库价已变"黄条，提供"用库价刷新"按钮（点一下才改快照）。
- 库价是 0 时明确提示"库价未填（当前刀具库 761 行价格全为 0）"，不再静默当成 0 参与报价。

---

## 3. 引用改造（名字 → id + 快照），双写过渡

改法照抄已经在用的设备引用（`mid` → `MachinesPage`）：

| 位置 | 现在 | 改成 | 过渡期 |
|---|---|---|---|
| 刀具行 → 刀具库 | `TDB[j].tp===t.tp`（6 处） | `tool_id` 直接命中；`compose()` 仍输出 `tp/tool_name` | 新表为准，旧键由 compose 生成 |
| 刀柄 / 配件 | 按名字存在 `hld/acc` | `handle_id/accessory_id` + 名字快照 | 同上 |
| 问题清单 → 工序 | `is[].pr` = 工序名（第 2 阶段） | `process_id`；`compose()` 仍输出 `pr` = 工序名 | 第 2 阶段执行 |
| 夹具/检具选型 | `fixByKey("中心\|名称")` / `inspByKey("类型\|名称\|图号")` | `fixture_id` / `gauge_id` + 快照价（第 2 阶段） | 第 2 阶段执行 |

原则：**一个阶段只切一处**；每次切换都要求"报价表数字逐位不变"（见第 6 节验收）。

---

## 4. 迁移口径

沿用第一阶段那套（已在线上跑通过）：

1. 归档：新建 `processes_legacy_v1(project_id, revision, state_json, archived_at)`，把迁移前的 `pr[]` 原样存一份；
2. 备份：`backups/pre-project-business.sqlite3`（只建一次）；
3. 写表：`pr[]` → `project_processes`（`sort_order` 按下标），`pr[].tl[]` → `project_process_tools`
   （`code` 存 `T01`，`tool_id` 按刀具名反查库 id —— **在同一把刀在库里重名时按 `grp` + 直径匹配，仍不唯一则留空并写进迁移报告**，不猜）；
4. 快照价：迁移时把库里当前 `price/life` 写进快照列（这一版库价全是 0，等价于"未填"）；
5. `projects.state_json` 变成 `{is, vh}`（问题清单第 2 阶段再搬）；
6. 幂等：`app_settings.project_business_version = 1`，重启不重复迁、不覆盖已改数据；
7. 逐键验证：`tools/verify_process_migration.py`（副本干跑）——迁移前后 `compose()` 的
   `pr[]`（含 `tl[]`、含重算的派生值）逐键一致，历史版本快照原样可还原。

---

## 5. 接口（新增，`/api/machining-dfm` 下）

```
GET    /projects/{pid}/processes                     # 工序列表（含刀具行，含派生值）
POST   /projects/{pid}/processes                     # 新增工序（默认结构照抄 addProc）
PATCH  /projects/{pid}/processes/{id}                # 行级保存（逐字段）
POST   /projects/{pid}/processes/reorder             # {ids:[...]} 排序
DELETE /projects/{pid}/processes/{id}                # 逻辑删除（刀具行一并逻辑删除）
POST   /projects/{pid}/processes/{id}/tools          # 新增刀具行
PATCH  /projects/{pid}/tools/{id}                    # 行级保存（逐字段）
POST   /projects/{pid}/processes/{id}/tools/reorder
DELETE /projects/{pid}/tools/{id}                    # 逻辑删除
PUT    /projects/{pid}/processes/{id}/photo          # 夹具示意图（cI → assets）
DELETE /projects/{pid}/processes/{id}/photo
```

写接口沿用现有鉴权口径；每次保存照样 `revision +1` + 一条快照（口径 1）。

---

## 6. 前端改造

- 新增 `static/machining_dfm/process_page.js`：`bProcess(i)` 委托给它（照第一阶段 `bSetup()` 的写法），
  复用已跑通的约定：`render()` 只生成 HTML、动作后 `repaint()`、保存后用 `MachiningDFMHost.adopt(record)` 接管内存；
- 工序页签里：工序名/台数/设备（下拉取设备库 id）/夹具费/设备费/六个计数 → 逐字段 PATCH；
  夹具示意图 → `PUT .../photo`；刀具行表格 → 增删改 + 上移下移（reorder）；
- 刀具行里的"刀具"改为下拉选库里 id（显示 名字 · 类型 · 直径），选完带出快照价；
  允许"手填一次性刀具"（口径 8），此时 `tool_id` 为空并存名字；
- `compose()` 继续输出旧键（`nm/mc/mid/cI/fixP/eqP/nc/tl` 与 `tl[].tp/hld/acc/_ct…`），
  所以导出、PPT、报价、选型页零改动。

---

## 7. 验收清单（每一条都要有可执行命令与输出）

| # | 验收 | 命令 / 判据 |
|---|---|---|
| 1 | 单测全绿 | `pytest tests -q`（新增：工序/刀具行 CRUD、逐字段 PATCH、重名刀具按 id 命中、快照价不随库改、逻辑删除、迁移幂等） |
| 2 | 迁移逐键一致 | `python tools/verify_process_migration.py --from <迁移前备份>`：`pr[]`/`tl[]`（含派生值）逐键一致 |
| 3 | 成本数字逐位不变 | `python tools/capture_process_cost_baseline.py --check`：与改造前基线**指纹一致**（基线已冻结：`tools/baselines/process_cost_baseline.json`，指纹 `a1baaace6bf031ab`） |
| 4 | 线上 e2e | `python tools/live_process_e2e.py`：增删改工序与刀具行、传夹具示意图、跑完还原 |
| 5 | 页面 | `node tools/smoke_machining_page.mjs`：工序页签渲染、字段保存、刀具行增删后重绘 |
| 6 | 报表链路 | `python tools/live_report_snapshot_check.py`：`pr_*`/`pr_tl_*` 绑定行数与字段不变 |
| 7 | 文档 | 本文与 `README.md` 更新，`docs/MACHINING_BUSINESS_REFACTOR.md` 第 8 节阶段表勾掉 1b |

---

## 8. 需要你拍板（带我的建议）

1. **刀具库 761 行的价格/寿命全是 0**，而且**设备库的设备价也是 0**（`S500Z1` → `price: 0.0`），
   所以报表里"刀具单件成本"和"设备成本"今天都是空的。这次要不要**一起把"填价格/寿命"做进刀具库与设备库页面**
   （比如批量导入/逐行填），还是先只做快照列、价格你以后再录？
   建议：**先做快照列 + 明确提示"库价未填"**，录入顺带在刀具库/设备库页各做一次（不阻塞 1b）。
2. **重名刀具怎么选**：库里 26 个重名。刀具行绑定 id 之后不存在歧义；但迁移时"按名字反查 id"会歧义。
   建议：**按 `grp` + 直径匹配；仍不唯一就留空 + 迁移报告列出这几行**，人工确认后再绑，绝不猜。
3. **`cI` 夹具示意图**要不要这次就搬进附件库（走 `assets`）？
   建议：**这次一起搬**（它跟工序绑定、正好在 1b 的改动范围内），否则 `state_json` 还会留着图片。
4. **`nc` 六个计数**：JSON 一列，还是铺六列？
   建议：**JSON 一列**（固定六键，铺列没有收益，以后加键不用迁移）。
5. **设备是否允许为空**（现在新建工序默认带一台设备）？
   建议：**允许为空**并提示"未选设备"，原因是迁就"库里没有这台设备"的真实场景。

---

## 9. 风险

- **报价链路**是最大风险：`toolCost()` 一旦从"按名"改"按 id"，任何 id 绑定错误都会算成 0 或算错。
  对策：验收 3 要求成本基线**指纹逐位不变**（`tools/baselines/process_cost_baseline.json`）；
  迁移报告列出所有"未能绑定 id"的行。
- **派生值两处算**：现在只有前端 `calcT()` 算（实测与库里存的值一致）；落表后建议**服务端 compose 也按同一公式算**
  并比对（前端算、服务端算、报表读的必须是同一个数），差异直接报错而不是静默。
- **逻辑删除的刀具行**在报价里必须排除；`compose()` 要按 `deleted_at IS NULL` 过滤，回收站单独给接口。
- **性能**：2 工序 / 25 行，量级极小；761 行刀具库仍是一次 compose 读模型，不变。

---

## 10. 工序页签的前端改造面（实测，供实现时照抄）

工具：`tools/show_process_page_surface.py`、`tools/show_tool_row_gateway.py`、`tools/show_tool_setters.py`。

### 10.1 写入口一览（全部要由 `process_page.js` 接管）

| 入口 | 现状实现 | 1b 之后 |
|---|---|---|
| `bProcess(pi)` | 工序页整页 HTML | 委托 `ProcessPage.render(pi)` |
| `bToolTable(pi,tl,rs,tc)` | 刀具行表格（31 列表头：刀号/类型/刀具型号/刀柄选型/配件选型/加工特征/加工内容/D/n/vf/fz/Vc/L/次/件/大刀/快移距/…/t切/非切削/总时间） | 委托 `ProcessPage.toolTable(pi)` |
| `sS(pi,i,field,value)` | `PR[pi].tl[i][f]=v;render()` —— 文本字段唯一入口（`id/cat/hld/acc/ds`） | PATCH 单字段 |
| `sN(pi,i,field,value)` | `parseFloat(v)||0`（`d/n/vf/ln/ps/cn/td/tt/sd`） | PATCH 单字段（数字） |
| `sB(pi,i,checked)` | `bg` 布尔 | PATCH 单字段 |
| `atT(pi,i,tp)` | 按名字在刀具库找（带 `grp` 过滤）并把 `d/n/vf/ln/cat/life/price/grp` **拷进行内** | 改为按 **id** 拷贝，快照列落库 |
| `updNC(pi,field,val)` | 六个计数 `cc/co/mc_/sc/ac/it` | PATCH `count_json` |
| `setProcMachine(p,mid)` | 写 `mid` + `mi`，并在设备库 `price>0` 时带出 `eqP` | PATCH `machine_id`（`mi` 由读模型算） |
| `refEqPrice()` | 用设备库价格刷新所有工序的 `eqP` | 保留为"按库价刷新设备费"，并写审计 |
| `addProc()` / `delProc(pi)` | 数组 push/splice（`delProc` 有 `PR.length<=1` 保护） | POST / DELETE（逻辑删除） |
| `addTool(pi)` / `delTool(pi,i)` | 数组 push/splice（默认结构见下） | POST / DELETE（逻辑删除） |
| `cI` 图片 | `armPaste` / `pickImg` → `PR[p].cI=u;render()` | `PUT/DELETE /projects/{pid}/processes/{id}/photo` |

其他相关：`gm(pi)` 取设备（`mid` → `MachinesPage.machineById`）、`gR(pi)` 快移速度、`gTC(pi)` 换刀时间、
`getNCperTool(pi,i)` 非切削时间、`procToolCost(pi)` 工序刀具成本、`calcT/st` 派生值。
`addTool` 的默认新行结构（照抄即可）：

```js
{id:"T"+(n+1), tp:"", ds:"新特征", d:10, n:3000, vf:1200, ln:50, ps:1, cn:1,
 bg:false, td:500, fi:null, tt:2, sd:1, cat:"other", hld:"", acc:""}
```

### 10.2 实现时要守的两条老规矩

1. `render()` 只生成 HTML；动作（增删/改字段/换图）之后必须 `repaint()` → 整页 `window.render()`；
2. 保存成功后用 `MachiningDFMHost.adopt(record)` 接管当前项目与指纹，避免旧的整份保存把新值覆盖回去
   （第一阶段踩过，见 `docs/MACHINING_BUSINESS_REFACTOR.md` 第 10.4 节）。

---

## 11. 设计自证：往返映射无损（写代码之前先证明表结构不漏键）

工具 `tools/check_process_mapping_roundtrip.py`：把本文的表结构拿去和线上真实数据做**双向映射**——
旧键 → 列名 → 旧键，要求键与值都能回到原样；派生值（`mi` 与 `_ct/_vc/_vf/_fz`）不落库，
但要求**按公式重算与原值逐位相同**。结果（线上 1 个项目、2 工序、25 刀具行）：

```
往返检查 441 个键 · 工序 2 行 · 刀具行 25 行
派生值重算不一致       : 0 处（25 行 × 4 个值）
工序 mi 重算不一致     : 0 处（mid → 设备库下标，[1,1]）
迁移时可直接绑刀具 id  : 25 行
需要人工确认（重名且规格不同）: 0 行
库里没有这把刀         : 0 行
√ 设计往返无损：真实数据里的每一个键都有去处，派生值可原样重算
```

**结论**：本文第 8 节的问题 2（重名刀具怎么绑）**对现有数据不构成阻塞**——25 行全部能唯一绑定；
它只在以后新增刀具行时才需要规则，所以按建议（`grp`+直径，仍不唯一则留空并报告）执行即可，
不需要停下来等人确认。真正需要你拍板的是**问题 1（价格数据是空的）**。

---

## 12. 映射演练（用生产模块在副本上跑，不改线上）

工具 `tools/rehearse_project_processes.py`：在线上库的**临时副本**上打开工序开关、建表，
用生产代码 `app/machining_process.py` 的 `apply_split` 把真项目逐行落表，再用 `store.get()`
读回来与迁移前**逐字节**比对。最近一次结果（项目 v41 / 2 道工序 / 25 行刀具行）：

```
工序 2 道 · 刀具行 25 行 · pr[] 共 6648 字节
落表：工序行 2 行 · 刀具行 25 行
绑库：唯一 25 · 直径消歧 0 · 重名未绑 0 · 库里没有 0
快照价/寿命为 0（库里没录价）的刀具行：25
√ pr[] 与迁移前**逐字节相同**（6648 字节，含键序）
√ 成本基线：tool_cost_per_min 0.0 → 0.0 · process_count 2 → 2 · tool_row_count 25 → 25
√ 演练通过
```

### 12.1 演练抓出来的硬规则：数字序列化必须跟 JS 一致

第一次演练失败在 14 个派生值上：库里存的 `_ct` 是**整数** `32`，而按公式在 Python 里重算得到
**浮点** `32.0`。原因是前端 `calcT()` 在 JS 里算完后 `JSON.stringify(32.0)` 就是 `32`，落库即整数。

写生产模块时又发现这条规则**不止适用于派生值**：`REAL` 列取回来是 `50.0`，而旧 JSON 是 `50`；
`bg` 存的是 `INTEGER 0/1`，而旧 JSON 是 `false/true`。所以定成一条硬规则：

> **读模型里所有数字都按 JS 的序列化规则归一**（整数值不带小数点：`50.0` → `50`；`6.5` 保持 `6.5`），
> 布尔字段（`bg`）给回布尔。这样"迁移前后逐键一致"才是真的逐字节一致，
> 成本基线指纹、历史快照 diff、报表绑定都不会出现假差异。

实现：`js_number()` + `NUMERIC_LEGACY_KEYS` / `BOOLEAN_LEGACY_KEYS`（见 `app/machining_process.py`）。

### 12.2 另外两条"不无中生有"的规则

1. **`nc` 不凭空补**：旧数据里没有 `nc` 的工序，读模型也不该多出这个键（否则逐键一致不成立）。
   整份缺失/空对象 → 存 `{}` → 读时省略；只给了某一个计数（如 `{"cc":5}`）才把其余补默认，
   与页面 `updNC` 的语义一致。
2. **`compose()` 不多不少地输出今天的键集合**：`life/price/grp` 这类新快照列**不塞进旧读模型**
   （否则基线指纹会变、报表绑定也可能跟着变）。旧键集合固定为 `LEGACY_PROCESS_KEYS` /
   `LEGACY_TOOL_KEYS`；快照通过行级接口与前端新模块读取。

### 12.3 基线比对是"数值比对"，迁移验收是"字节比对"

`capture_process_cost_baseline.py` 用 `1e-6` 容差比数字（对 `32` vs `32.0` 不敏感，符合业务含义）；
迁移验收（`rehearse_project_processes.py` 与后续的 `verify_process_migration.py`）用字节比对，
所以必须守 12.1 的规则。

---

## 13. 1b 服务端已落地（开关默认**关**，线上数据未动）

`app/machining_process.py`（新增，约 700 行）：

| 内容 | 说明 |
|---|---|
| `ProjectProcesses` / `ProjectProcessTools` | 两张项目级多行表：`project_id` 作用域、行级 `PATCH`、`reorder`、**逻辑删除 + 回收站 + 恢复** |
| `js_number` / `calc_derived` | 派生值 `_ct/_vc/_vf/_fz` 读时算、按 JS 规则归一（口径 5：不落库） |
| `clean_count` / `clean_snapshot` | `nc` 六个计数与设备快照的 JSON 列校验（不无中生有） |
| `set_machine` / `set_attachment_value` | 选设备写 id + 快照；图片槽走 `assets`（换图先改行、再回收旧图） |
| `compose_processes` / `legacy_processes` | 表行 → 旧 `pr[]`（老短键、老结构、键序一致）；表里没数据时返回 `None`，调用方回退 `state_json` |
| `split_state` / `apply_split` / `bind_tool` | 反向：旧 `pr[]` → 表行；按名字绑库 id，重名用 `grp`+直径消歧，仍不唯一就**留空 + 报告**，绝不猜 |

接入 `MachiningDFMStore`（**显式开关**，默认关）：

* `self.processes` / `self.process_tools` 与 store 一起构造；
* 只有 `app_settings.project_business_version >= 1`（迁移工具写）或环境变量
  `MACHINING_PROJECT_BUSINESS=1` 时才**建表**；
* `compose(..., processes=...)` 与 `_record()` 在有表数据时用表数据，否则照旧用 `state_json`
  —— 所以**代码可以先上线，线上行为一模一样**（已实测：线上库没多出这两张表、读模型与基线指纹不变）。

测试：`tests/test_machining_process.py`（19 个）覆盖开关、行级 CRUD、逻辑删除与回收站恢复、
重排、快照价不随库变、派生值不落库、快照键不外泄、绑定报告（唯一/消歧/重名/缺失）、
稀疏老数据的归一、以及"拆分→还原逐字节相等"。

### 13.5 迁移工具：`tools/migrate_project_processes.py`

**默认干跑**：整库复制到临时目录，在副本上跑完整迁移并逐字节核对，跑完删掉副本
（`--keep` 保留）。只有 `--apply` 才动线上库，动之前先整库备份。

```
python tools/migrate_project_processes.py --status   # 只读：现在迁到哪一步
python tools/migrate_project_processes.py            # 干跑（在副本上跑，不动线上）
python tools/migrate_project_processes.py --apply    # 真迁移（先备份）
python tools/live_process_e2e.py                     # 迁完之后：对着服务验表↔读模型
```

执行顺序（每一步都可以原样重跑）：

1. **备份** → `backups/pre-project-business-<时间戳>.sqlite3`（只有 `--apply` 才写）；
2. **归档** → `processes_legacy_v1(id,name,revision,state_json,archived_at)`，
   存迁移前那一份 `state_json`，回滚/审计用；
3. **拆表** → 逐项目 `apply_split`：工序进 `project_processes`、刀具行进
   `project_process_tools`，按名字绑刀具库 id（重名用组+直径消歧，仍不唯一就**留空并报告**，
   绝不猜），顺手写价格/寿命快照；
4. **写开关** → `app_settings.project_business_version = 1`（写在最后，前面任何一步失败
   都不会出现"开关开着但数据没搬"的状态）；
5. **验证** → 重新 `MachiningDFMStore(...)`（不带环境变量，纯靠版本键启用）逐项目核对
   `pr[]` 与迁移前**逐字节相同**（含键序）、`state_json.pr` 被清掉也不影响读模型、
   只凭两张表能完整还原、成本基线指纹不变。

三个值得记下的坑：

- **干跑第一次就抓到两个真问题**：① 绑刀具库用的是 `state_json`，
  但库里数据早在 1a 就搬进独立表了，`state_json` 里没有 `tdb` → 25 行全报"库里没有"；
  正确做法是拿**读模型**里的 `tdb`/`mdb`。② 拿 `state_json` 的 `pr` 当比对基准会假报不一致：
  读模型会给每道工序补一个 `mi`（设备在设备库里的下标，**读时现算、不落库**）。
- **`mi` 是派生的**：`split_state` 根本不存 `mi`，`compose` 每次按 `self.machines.ids()`
  的位置重算，所以"表单独还原 `pr`"的比对必须忽略 `mi`，否则会误判。
- **`state_json.pr` 不删**：它是影子副本。好处是回滚极简——删掉版本键，开关就关上了，
  读模型立刻回到迁移前那一份（单测里专门验了这条），表里的行原样留着不丢。

**迁完要不要重启服务？不用。** `router_for` 每个请求都新造一个 store，
`project_business` 在构造时从 `app_settings` 现读，所以 `--apply` 之后**下一个请求就切到表**。
（这一轮重启服务是因为代码本身变了：老进程里没有这 15 条工序路由，会返回 404。）

**幂等与崩溃恢复**：`apply_split` 发现项目在表里已经有行（**含已逻辑删除的**）就整段跳过并报
`skipped`，绝不用"先清空再灌"——口径 2 不允许物理删除。所以迁移中途崩了可以原样重跑，
不会灌成两份；工具本身发现开关已经开着就直接收手。

### 13.3 前端已接管（`static/machining_dfm/process_page.js`）

做法：**不动页面结构与 DOM**，只把"写入点"接过来。旧页面的工序表（31 列、粘贴图片、
选设备、从刀具库选刀、派生列）全部保留，画面仍由 `legacy_app.js` 的 `bProcess()` 出，
所以视觉与操作习惯零变化；变的是"写到哪里去"。

```js
function ppOn(){return typeof ProcessPage!=='undefined'&&ProcessPage.enabled();}
function sN(pi,i,f,v){if(ppOn()){ProcessPage.setToolNumber(pi,i,f,v);return;}PR[pi].tl[i][f]=parseFloat(v)||0;render();}
```

| 写入点 | 行级接口 |
|---|---|
| 新增/删除工序 | `POST /processes`、`DELETE /processes/{id}`（逻辑删除，二次确认） |
| 工序名、台数、设备费（工艺设置页三处输入框） | `PATCH /processes/{id}` |
| 非加工时间六键 | `PATCH /processes/{id}` `{nc:{六键}}`（与 `updNC` 语义一致） |
| 换设备 / 一键刷新设备成本 | `PATCH /processes/{id}` `{mid}` / 逐道 `{eqP}` |
| 夹具示意图 cI（粘贴/上传/删除） | `PUT|DELETE /processes/{id}/photo` → `assets` |
| 刀具文本/数字/大刀标记 | `PATCH /tools/{id}`（只发改动的那一个字段） |
| 删除/新增刀具行 | `DELETE /tools/{id}`、`POST /processes/{id}/tools` |
| 从刀具库选刀 | `PATCH /tools/{id}` + `tool_id/tool_grp/tool_price/tool_life` 快照 |
| 刀柄/配件选型 | `PATCH /tools/{id}` + `hld_id/hld_price`、`acc_id/acc_price` 快照 |
| 刀具图片 fi | `PUT|DELETE /tools/{id}/photo` → `assets` |

三条实现约定：

1. **行 id 不缓存**：每次写之前先 `GET /processes` 拿最新行列表，再用页面下标取行 id；
   列表长度与页面不一致就提示"列表已变化，正在刷新"并重绘，**绝不按下标硬写**（写错行比不写更糟）。
2. **不无中生有的快照**：选刀时才写 `tool_price/tool_life`；库里价格为 0 就存 0，
   并在状态栏提示"刀具库未录价格，这把刀的成本按 0 计"；库价与行内快照不一致时提示
   "行内仍是选型时的快照 X 元，重选该刀具才会更新"。
3. **保存后交给服务端接管**：`MachiningDFMHost.adopt(record)` → 重绘。因为 `adopt` 会重算指纹，
   旧的"整份保存"（`PUT /projects/{id}`）在行级保存之后**不会再发**——不会一次编辑存两遍，
   也不会拿旧内存把表里的新值盖回去（冒烟自检里专门有一条断言这个）。

`host.js` 为此多暴露了一个 `status`（模块想写顶部状态栏，不必自己造元素）。

### 13.4 新增的两道前端检查

1. `tools/check_process_wiring.py`：**写入点清单**（`tools/process_wiring.py`）逐条核对
   "行级保存"与"旧路径"都在，然后扫一遍 `legacy_app.js` 找**漏网**的直接赋值
   （`PR[...]=` / `PR.push` / `PR.splice`），豁免项必须写明原因。
   这道检查第一次跑就抓到一个真漏点：**工艺设置页成本表里的"设备价格"输入框**
   （`onchange="PR[p].eqP=…"`）——漏了它就会出现"界面上改了、表里没变"。
2. `tools/smoke_machining_page.mjs`（冒烟自检）新增"工序落表"两段：
   开关关着时"改字段只动内存、不发行级写请求"（证明**代码先上线不改行为**）；
   开关打开后跑完 8 组动作，逐条断言请求方法、URL（**必须是行 id**）、载荷、
   快照键、版本号递增、界面重绘，以及"行级保存后没有多余的整份保存"。
   冒烟里的假后端会真的把行级写落到"表"里再同步回 `pr[]`，所以下标对齐、
   删除后重新对齐这类逻辑是真的跑过一遍的。

### 13.1 接口层已完成（15 条路由）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/projects/{pid}/processes` | 工序列表（含刀具行、回收站、字段登记表），`?include_deleted=1` |
| POST | `/projects/{pid}/processes` | 新增工序（给了 `mid` 会自动补设备快照） |
| PATCH | `/projects/{pid}/processes/{id}` | 行级保存；带 `mid` 时连快照一起换 |
| DELETE | `/projects/{pid}/processes/{id}` | **逻辑删除**，刀具行一并进回收站，`?by=&reason=` |
| POST | `/projects/{pid}/processes/{id}/restore` | 回收站恢复（连带恢复"随工序删除"的刀具行） |
| POST | `/projects/{pid}/processes/reorder` | `{ids:[…]}` 排序 |
| PUT / DELETE | `/projects/{pid}/processes/{id}/photo` | 夹具示意图（旧 `cI` → `assets`） |
| POST | `/projects/{pid}/processes/{id}/tools` | 新增刀具行 |
| POST | `/projects/{pid}/processes/{id}/tools/reorder` | 刀具行排序 |
| PATCH | `/projects/{pid}/tools/{id}` | 刀具行级保存（含快照价列） |
| DELETE | `/projects/{pid}/tools/{id}` | 逻辑删除 |
| POST | `/projects/{pid}/tools/{id}/restore` | 回收站恢复 |
| PUT / DELETE | `/projects/{pid}/tools/{id}/photo` | 刀具图（旧 `fi` → `assets`） |

写接口的规矩与项目信息一致（同一个项目区域内不加额外鉴权，与现有 `/projects/{pid}/settings`
保持同一口径；`/libraries` 那类全局写接口仍要 admin）：

* **每次写都递增 `projects.revision` 并留一个版本快照**（口径 1）；
* 返回整个项目记录，前端用 `MachiningDFMHost.adopt(record)` 接管内存与指纹；
* 行必须属于该项目，否则 404（防止拿 A 项目的 id 改 B 项目的数据）；
* 开关关着时返回 **409 + 明确文案**，而不是 500；
* 附件库新增种类 `process_photo`（工序夹具示意图与刀具图共用）。

### 13.2 落表后发现并处理的两个坑

1. **版本快照必须从表里取 `pr`**：`_snapshot` 原本直接从 `state_json` 复制业务数组。
   迁移后 `state_json.pr` 就过期了，若照旧复制，**版本历史会记下错误的工序数据**——
   而版本历史正是"改错了怎么回去"的依靠（口径 1/2）。现在 `_snapshot_arrays()` 在工序落表启用时
   用 `legacy_processes()` 从两张表还原 `pr` 再写快照（测试 `test_every_save_leaves_a_version_snapshot_with_process_data`
   断言快照里有改后的值）。
2. **快照数据要在写事务之前读**：SQLite 的写事务会拿锁，在事务里再开连接去读表既慢又可能等锁超时。
   现在 `_bump_project()` / `save_project_settings()` 都先读好 `general` 与 `arrays`，
   再进写事务做 `UPDATE + INSERT`（`_write_snapshot`）。
3. 顺带：附件编号（裸 id）以前不被识别，只能传 data URL/URL；`_resolve_asset()` 现在也认附件编号，
   上传接口手上拿到的就是刚入库的编号。
