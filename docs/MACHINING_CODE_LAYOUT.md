# 机加 DFM 服务 · 分层重构说明（代码骨架）

> 本文记录 **2026-09 分层重构** 之后 `app/` 的骨架、依赖规则，以及"旧路径 → 新路径"的对照表。
> 其它文档（尤其 `MACHINING_BUSINESS_REFACTOR_PHASE*.md`）是**各阶段的历史记录**，
> 里面的文件路径与行号是当时的写法；要对今天的代码，看本文。

---

## 1. 为什么重构

重构前 `app/machining_dfm.py` 是 **3655 行的单文件**：常量、通用工具、附件库、
基础库引擎、10 个业务域的表结构与 CRUD、**迁移**、**120 条路由**全挤在一起。
后果是具体的：

- **找不到东西**：想知道"改夹具库的校验要动哪"得先读三千行；
- **改不动**：路由和业务逻辑同一个文件，改一个接口就在改一个巨型模块；
- **边界糊**：`process.py` 反向 import `selection.py`，改一个域牵动另一个域；
- **不标准**：不是任何一本 FastAPI 教程里的结构，新人上手没有参照。

重构目标就是用户提的两条，本文字面兑现：

1. **符合标准 FastAPI 项目结构，中文备注清晰**；
2. **功能模块间职责清晰、边界规范，无双向依赖、反向依赖**。

---

## 2. 分层与依赖方向

```
        ┌──────────────────────────────────────────────┐
        │ app/main.py            create_app() 应用工厂 │  ← 组合根
        │ app/machining_dfm.py   兼容转发层（历史路径）  │
        └───────────────────────┬──────────────────────┘
                                │ 可以引用任意层
        ┌───────────────────────▼──────────────────────┐
        │ app/api/       HTTP 适配：路由 / 请求模型 / deps │
        └───────────────────────┬──────────────────────┘
        ┌───────────────────────▼──────────────────────┐
        │ app/services/  组合根 store、迁移、导出、种子、投影 │
        └───────────────────────┬──────────────────────┘
        ┌───────────────────────▼──────────────────────┐
        │ app/domains/   业务域：一域一张表一套规则        │
        └───────────────────────┬──────────────────────┘
        ┌───────────────────────▼──────────────────────┐
        │ app/db/        连接 / 共享表 DDL / 行 CRUD 原语  │
        └───────────────────────┬──────────────────────┘
        ┌───────────────────────▼──────────────────────┐
        │ app/core/      路径配置 / 通用工具 / 安全基元     │
        └──────────────────────────────────────────────┘
```

**规则一句话**：依赖只能**向下**，`core` 不认识任何人；同一层的**业务域之间零互引**。

### 各层的职责边界

| 层 | 该放什么 | **不该**放什么 |
| --- | --- | --- |
| `core/` | 路径配置、`stamp()`/`compact_json()`/`js_number()`、口令与令牌 | 任何表名、任何业务规则 |
| `db/` | SQLite 连接工厂、共享表 DDL、表名登记、行级 CRUD 基类、附件库 | 业务校验、项目编排 |
| `domains/` | 一个域的表结构（`FIELDS` 登记表）+ 校验 + 行级读写 + 该域的 DDL | 引用别的域、跨域编排、HTTP 概念 |
| `services/` | 跨域编排（store）、幂等迁移、导出、种子、报表投影、数据源契约 | 直接拼 HTTP 响应、写路由 |
| `api/` | 路由、请求体模型、依赖注入 | 业务规则、直接写 SQL |

### 为什么"域间零互引"这么严

域之间一旦互相 import，改一个域就得动另一个域，边界名存实亡。
原先真实的例子：`process.py` 为了拿选型数据而 import `selection.py`，
两边再各自 import 对方一次就成环。现在两个域都只往下依赖
`app/db/rows.py`（`ProjectRows` 公共基类）与 `app/db/tables.py`（表名），
跨域的事一律上提到 `services/store.py`。

这条规则**不是靠自觉**，而是 `tests/test_architecture.py` 里 11 条断言钉住的：

```
test_dependencies_only_point_downwards            依赖方向严格向下
test_domains_never_import_each_other              业务域之间零互引
test_only_composition_root_and_shim_touch_...     实现模块不许反向依赖兼容层
test_core_and_db_stay_free_of_business_layers     core/db 不含业务依赖
test_every_routers_module_exposes_register        路由模块统一 register() 入口
test_layers_exist_as_packages                     分层包齐备
test_app_entrypoints_are_importable_targets       标准入口 + 兼容入口都在
test_entrypoint_modules_actually_import[x4]       入口真能导入
```

这些断言**只读源码做 AST 分析**，不 import 被测模块 —— 所以哪怕哪天有人写出循环导入，
断言照样能跑出结论，而不是先被 `ImportError` 拦住。

---

## 3. 启动方式

```powershell
# 标准入口（推荐）
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8002

# 历史入口，仍然可用（app/services/machining.py 只是转发层）
.venv\Scripts\python.exe -m uvicorn app.services.machining:app --port 8002

# 单服务启动脚本
.venv\Scripts\python.exe run_service.py
```

`app/main.py` 里的 `create_app()` 是唯一组装点：挂路由 → 装数据源契约 → 装日志 → 挂静态页面。
`app.services.machining` 与 `app.machining_dfm` 都是**兼容转发层**，不再自己组装应用。

---

## 4. 请求进来之后发生什么

```
GET /api/machining-dfm/projects/{id}/processes
  │
  ├─ app/api/routers/process.py     解析路径/查询参数
  │     store = store_factory()     ← app/api/deps.py 按请求新建 store
  │
  ├─ app/services/store.py          store.project_processes(id)
  │     self.processes.list_rows(...)          ← 域引擎
  │     self._compose(...)                      ← 把各表拼回读模型（跨域编排）
  │
  ├─ app/domains/process.py         行级规则与校验
  ├─ app/db/rows.py                 ProjectRows：行 CRUD / 软删除 / sort_order
  ├─ app/db/library.py              TypedLibrary 底座
  ├─ app/db/connection.py           Database.connect()
  └─ app/core/utils.py              stamp() / js_number()
```

**每次请求都新建 store**（`app/api/deps.py`）：store 构造时会跑一遍幂等迁移，
所以后台改配置、`tools/migrate_*.py --apply` 跑完迁移之后**不用重启服务**，
下一个请求就切到新结构上。代价只是开一次 SQLite 连接。

---

## 5. 旧路径 → 新路径对照表

历史脚本（`tools/`、`_audit/`）与历史文档里写的是**左列**；
`app/machining_dfm.py` 这个兼容层让左列的 **import 写法继续有效**。

| 旧路径 | 新路径 | 说明 |
| --- | --- | --- |
| `app/settings.py` | `app/core/config.py` | 路径配置 |
| `app/machining_dfm.py`（3655 行） | 拆成下面全部 + `app/services/store.py` | 单文件已拆解 |
| ↳ 其中 `MachiningDFMStore` | `app/services/store.py` | 组合根 |
| ↳ 其中 `router_for` / 120 条路由 | `app/api/routers/*.py` | 按域分 12 个模块 |
| ↳ 其中 `_bearer` | `app/core/security.py::bearer_token` | 安全基元 |
| ↳ 其中 `_stamp` / `_compact` | `app/core/utils.py::stamp` / `compact_json` | 通用工具 |
| ↳ 其中 `SCHEMA` / `*_SCHEMA_VERSION` | `app/db/schema.py` | 共享表 DDL 与结构版本号 |
| ↳ 其中 `_migrate_*` / `_prepare_*` | `app/services/migrations.py` | 建表与幂等迁移 |
| ↳ 其中导出打包的纯函数 | `app/services/export.py` | 包名/引用识别/地址改写 |
| ↳ 其中 `_resolve_machine_ref` | `app/domains/machines.py::resolve_machine_ref` | 旧 `mi` 下标 → 设备 id |
| `app/machining_library.py` | `app/db/library.py` | 类型化基础库引擎 |
| `app/machining_assets.py` | `app/db/assets.py` | 附件库 |
| `app/machining_machines.py` | `app/domains/machines.py` | 设备库 |
| `app/machining_tools.py` | `app/domains/tools.py` | 刀具库 + 两张字典表 |
| `app/machining_fixtures.py` | `app/domains/fixtures.py` | 夹具库 + 模具中心字典 |
| `app/machining_gauges.py` | `app/domains/gauges.py` | 检具库 + 检具类别字典 |
| `app/machining_project.py` | `app/domains/project.py` | 项目信息（`G` 建模字段） |
| `app/machining_process.py` | `app/domains/process.py` | 工序 + 工序刀具行 |
| `app/machining_issue.py` | `app/domains/issue.py` | 问题清单 |
| `app/machining_selection.py` | `app/domains/selection.py` | 夹具/检具选型 |
| `app/machining_history.py` | `app/domains/history.py` | 版本履历 |
| `app/machining_changes.py` | `app/domains/changes.py` | 变更流水 |
| `app/machining_seed.py` | `app/services/seed.py` | 种子数据读取 |
| `app/machining_projection.py` | `app/services/projection.py` | 报表运行时投影 |
| `app/native_forms.py` | `app/services/forms.py` | HTML 表单解析/规范化 |
| `app/integration_contract.py` | `app/services/contract.py` | 数据源契约模型 |
| `app/html_literals.py` | **已删除** | 字段声明改由各域 `FIELDS` 登记表提供 |
| `app/dfm/`、`app/report/`、`scripts/` | **已删除** | 与本分支（机加单服务）无关的死代码 |

### 导入写法对照

```python
# 旧（仍可用，走兼容层）
from app.machining_dfm import MachiningDFMStore, router_for, PROJECT_ARRAYS

# 新（推荐）
from app.services.store import MachiningDFMStore
from app.api.routers import router_for
from app.db.schema import PROJECT_ARRAYS
```

`tools/` 下 30 多个历史迁移/审计脚本仍在用旧写法，**一个都不用改**。
新代码请用右列。

---

## 6. 新增一个业务域该怎么做

照着现成的域抄，五步：

1. **表名**：加进 `app/db/tables.py`（不要 import 别的域去借）。
2. **域模块**：新建 `app/domains/<域>.py`，定义 `XXX_FIELDS`（`LibraryField` 登记表）、
   `XXX_TABLE`、`XXX_VERSION`，以及一个 `ProjectRows` 子类（项目级多行表）
   或 `TypedLibrary` 子类（基础库）。
3. **迁移**：在 `app/services/migrations.py` 加一个幂等函数（按"结构版本号"判定，
   到位就 return），并在 store 的 `__init__` 里按序调用。
4. **接进 store**：在 `app/services/store.py.__init__` 造引擎实例，
   在 `schema` 段按依赖顺序建表（有外键的一定晚于被指向的表）。
5. **路由**：新建 `app/api/routers/<域>.py`，只导出 `register(router, store_factory)`；
   在 `app/api/routers/__init__.py` 的 `REGISTRARS` 里登记。**别忘**在
   `app/api/schemas.py` 加请求体模型（如果这个域需要）。

写完跑：

```powershell
.venv\Scripts\python.exe -m pytest tests -q                          # 全量测试
.venv\Scripts\python.exe tools_audit\graph_imports.py                # 确认没引入反向依赖
.venv\Scripts\python.exe tools_audit\dump_routes.py tools_audit\routes_after.json
```

---

## 7. 验收证据

重构是**行为不变**的搬迁，靠三样东西对账：

| 证据 | 工具 | 结果 |
| --- | --- | --- |
| **路由契约不变** | `tools_audit/dump_routes.py` 与 `routes_before.json` 逐条比对 | 139 条 → 139 条，**完全一致** |
| **测试全绿** | `.venv\Scripts\python.exe -m pytest tests -q` | 223 → **234 passed**（+11 条架构守卫） |
| **真机可用** | `tools_audit/smoke_live.py`（真库副本 + 真 HTTP） | 9 组共 40 项断言全部通过 |
| **分层成立** | `tools_audit/graph_imports.py` + `tests/test_architecture.py` | 依赖严格向下，域间零互引 |

> `smoke_live.py` 会把可写数据根指向临时目录（`DFM_APP_ROOT`），**不碰生产库**。
> 这条冒烟在重构中真抓出过一个只在生产路径上出现的缺陷：种子目录被误拼成
> `.../machining_dfm_seed/machining_dfm_seed.json`，测试因为各自传自己的种子目录而全部通过。

### 顺带修掉的真实缺陷

1. **`PROJECT_ARRAYS` 等常量下沉**：原先 `services` 与 `db` 都想用，若放错层会立刻
   形成反向依赖 —— 已归位到 `app/db/schema.py`。
2. **`stamp` 名字遮蔽**：把 `_stamp()` 统一改名 `stamp()` 后，两处
   `stamp = _stamp()` 会变成"局部变量遮蔽全局函数"，其中一处还会因
   "函数内赋值即局部"而直接 `UnboundLocalError`。已改名为 `created_at` / `saved_at`。
3. **重复定义**：`MachiningDFMStore` 里 `_table_exists` 被定义了两遍（后者遮蔽前者），
   已合并为一个并转发到 `app/db/connection.py`。
4. **`BASE_DIR` 少上溯一层**：`app/core/config.py` 从 `app/settings.py` 搬深一层后，
   `parent.parent` 会指到 `app/`，`DATA_DIR`/`SEED_DIR` 全错。已改为 `parent.parent.parent`。

---

## 8. 重构后各文件规模

| 文件 | 行数 | 备注 |
| --- | --- | --- |
| `app/services/store.py` | ~2400 | 组合根：接 14 个域引擎 + 118 个跨域编排方法 |
| `app/api/routers/*.py` | 12 个模块 | 原先挤在一个 `router_for()` 里 |
| `app/services/migrations.py` | ~460 | 原先散在 store 里（447 行） |
| `app/domains/*.py` | 10 个模块 | 每域一张表一套规则，互不引用 |
| `app/db/*.py` | 6 个模块 | 底座原语 |

原 `app/machining_dfm.py` 3655 行 → 拆成上面全部，自身只剩约 60 行再导出。
