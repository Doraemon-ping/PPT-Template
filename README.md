# 通用 PPT 模板工作台（workbench）

本分支是独立的**通用 PPT 工作台**：外部数据通过可配置 API Connector 接入并转换为
Dataset，同时保留模板导入、绑定与预览能力。生产代码不包含任何内置表单数据。

- 入口：`app/services/workbench.py`（FastAPI 应用对象 `app`）
- 默认地址：`http://127.0.0.1:8003`
- 数据目录：`data/ppt_workbench/`（按数据源隔离的模板、方案、草稿、预览缓存）
- API 连接配置：`data/ppt_workbench/workbench.sqlite3`（首次启动为空）

## 运行

```powershell
python -m pip install -r requirements.txt

python run_service.py                     # 默认 127.0.0.1:8003
python run_service.py --host 0.0.0.0      # 局域网可访问

# 或者直接用 uvicorn
.venv\Scripts\python.exe -m uvicorn app.services.workbench:app --host 0.0.0.0 --port 8003
```

- API 连接器控制台：<http://127.0.0.1:8003/ppt>
- 可视化绑定工作台：<http://127.0.0.1:8003/template-editor>

### 表单跳转：按项目 id 取数并绑定

机加 DFM 表单保存后跳转 `http://127.0.0.1:8003/template-editor?app_id=machining-dfm&project_id=<项目 id>`，
工作台据此拉取该项目的工序/设备/工艺/问题并允许绑定。需要两步配置：

1. 数据源连接 `data/ppt_workbench/connections.json`（默认不存在＝没有数据源）：

   ```json
   { "connections": [ { "id": "machining", "base_url": "http://127.0.0.1:8002" } ] }
   ```

2. 模板按数据源隔离，上传模板时要带同一个 `app_id`：
   `POST /api/templates/upload?app_id=machining-dfm&template_id=<模板 id>`。

自检：`GET /api/ppt/sources` 有 `machining-dfm`；`python scripts/check_machining_binding.py`
会跑完「快照取数 → 真实生成 → 解包校验」整条链路。细节与已知边界见
[机加 DFM 项目 id → 工作台绑定](docs/MACHINING_PROJECT_BINDING.md)。

## 主要接口

| 路径 | 说明 |
| --- | --- |
| `GET /ppt` | 外部 API 连接器控制台（`static/ppt_home.html` + `api_connectors.js`） |
| `GET /template-editor` | 模板可视化绑定工作台（`static/template_editor.html`） |
| `GET /api/ppt/sources` | 已配置的数据源（表单服务）列表与连接状态 |
| `/api/templates`、`/api/templates/upload`、`/api/templates/{id}` | 模板清单、上传、删除（按数据源隔离） |
| `POST /api/template/scan`、`/api/template/inspect` | 占位符清单、形状清单（绑定选择用） |
| `POST /api/template/generate` | Deck 编排生成（形绑定 + 占位符替换） |
| `POST /api/template/live-preview`、`GET /api/templates/{id}/slides/{n}/preview.png` | 真实数据预览（PowerPoint 渲染，缓存 PNG） |
| `POST /api/template/formula-preview` | 公式渲染预览（不依赖 Office） |
| `/api/schemes`、`/api/schemes/{name}`、`/api/schemes/{name}/generate`、`/api/schemes/{name}/versions` | 绑定方案的保存、复用、版本与一键生成 |
| `POST /api/ppt/preview-v2` | 旧版命名形状引擎预览（`DFM_PPT_V2_ENABLED=1` 时启用，自压铸表单服务迁入） |
| `/api/connectors/connections` | 外部 API 连接配置 CRUD |
| `/api/connectors/endpoints` | 外部 API 接口配置 CRUD |
| `/api/connectors/parameters`、`/api/connectors/mappings` | 动态参数与 JSONPath 字段映射 CRUD |
| `POST /api/connectors/test` | 执行已配置接口、映射响应并持久化 Dataset |
| `GET /api/connectors/datasets`、`/api/connectors/datasets/{id}` | 查询已生成的内部 Dataset |
| `POST /api/connectors/workspaces/{id}/refresh` | 并行刷新工作空间内全部启用接口，分别记录 Dataset 来源，单个接口失败不影响其它接口 |
| `GET /health` | 健康检查，返回 `{"service": "workbench", "contract_version": "1.0"}` |
| `GET /api/logs/tail`、`/api/logs/download` | 服务端日志（`data/ppt_workbench/logs/server.log`） |

环境变量：

- `PPT_PROVIDER_TOKEN`：调用表单服务数据源接口时携带的 Bearer 凭证
- `DFM_PPT_V2_ENABLED`、`DFM_PPT_V2_TEMPLATE`、`DFM_PPT_V2_SCHEMA_DIR`：旧版命名形状引擎预览开关与路径
- `DFM_APP_ROOT`：数据根目录（默认项目根，打包后为 exe 同级目录）

外部 API 连接器配置保存在 `data/ppt_workbench/workbench.sqlite3`。服务首次使用连接器时会自动执行
`app/db/migrations/` 中尚未应用的迁移；外部响应仅按 JSON 解析，字段映射使用 JSONPath。

一个工作空间可以关联多个外部系统，每个系统也可以配置多个接口。Dataset 会记录连接、接口和取数参数，
编辑台只把同一接口的数据交给该接口自己的映射规则。多个来源合并时保留旧的 `f/t/i` 别名以兼容历史绑定，
同时在 `f._systems.source_<连接 id>`、`t._systems.source_<连接 id>` 和
`i._systems.source_<连接 id>` 下提供互不覆盖的来源命名空间；当一个连接包含多个接口时，命名空间会继续包含接口 id。
对于项目型系统，优先配置“当前项目 + 分类接口”，把 `project_id` 作为路径参数分别执行；不要用整包接口替代分类接口，
也不要为了补充名称而直接拉取整套公共库。整行表映射会保留关联所需的外键列，编辑台按接口类别展示字段、表格和图片。

## 目录结构

```
app/
  settings.py               路径配置（BASE_DIR / APP_ROOT / DATA_DIR / STATIC_DIR）
  integration_contract.py   数据源契约模型（Snapshot / ReportContext）
  form_platform.py          旧表单平台兼容存储（无内置应用或默认数据）
  native_forms.py           原样 HTML 表单字段路径规范化（原生表单模板绑定用）
  html_literals.py          HTML 字段声明提取
  dfm/                      压铸报告领域模型（旧版命名形状引擎的输入）
  report/ppt/               渲染引擎：deck 编排、template_engine、OOXML 绑定层、
                            scheme_service、template_registry、slide_preview、校验器
  services/
    workbench.py            本服务入口（模板/方案/预览/生成 API）
    workbench_core.py       数据源连接与隔离存储（hub/scope/storage_root/install_api）
    observability.py        日志与 /api/logs/* 接口
static/                     连接器控制台、模板编辑器及其前端脚本
templates/                  内置模板（demo / pilot / table-demo 等）
tools/                      模板构建与预览脚本（export_slide_preview.ps1 等）
config/ppt-connections.example.json  空的旧提供方连接配置模板
tests/                      连接器、引擎、绑定、方案、模板、分页、预览等测试
run_service.py              单服务启动脚本
```

## 测试

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

## 与其它服务的关系

- 工作台**不导入**表单服务的代码，也不直接读表单数据库。只有请求显式携带 `app_id`
  时，才会通过旧 HTTP 契约访问表单提供方：
  - `GET /api/ppt-provider/v1/sources`：数据源列表；
  - `GET /api/ppt-provider/v1/sources/{id}/projects/{project_id}/snapshot`：项目快照 + 字段目录；
  - `POST /api/ppt-provider/v1/sources/{id}/normalize`：表单数据规范化。
- 表单页「按方案生成」由表单服务同源转发到本服务（`/api/schemes/*`）。
- 三服务架构与契约说明见 `docs/SERVICE_ARCHITECTURE.md`；同系列分支：
  `hpdc`（压铸表单服务，8001）、`machining`（机加表单服务，8002）、`New`（三服务合集 + 统一网关）。
