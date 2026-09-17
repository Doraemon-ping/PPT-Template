# 通用 PPT 模板工作台（workbench）

本分支是三服务拆分的**通用 PPT 工作台**独立版本：只包含模板导入、可视化绑定、
方案复用、真实预览与 PPT 生成所需的代码，可单独部署运行，不导入压铸/机加表单服务的代码。

- 入口：`app/services/workbench.py`（FastAPI 应用对象 `app`）
- 默认地址：`http://127.0.0.1:8003`
- 数据目录：`data/ppt_workbench/`（按数据源隔离的模板、方案、草稿、预览缓存）
- 数据源连接：`config/ppt-connections.json`（缺省时用 `config/ppt-connections.example.json` 的示例）

## 运行

```powershell
python -m pip install -r requirements.txt

python run_service.py                     # 默认 127.0.0.1:8003
python run_service.py --host 0.0.0.0      # 局域网可访问

# 或者直接用 uvicorn
.venv\Scripts\python.exe -m uvicorn app.services.workbench:app --host 0.0.0.0 --port 8003
```

- 数据源选择首页：<http://127.0.0.1:8003/ppt>
- 可视化绑定工作台：<http://127.0.0.1:8003/template-editor>

## 主要接口

| 路径 | 说明 |
| --- | --- |
| `GET /ppt` | 数据源选择页（`static/ppt_home.html`） |
| `GET /template-editor` | 模板可视化绑定工作台（`static/template_editor.html`） |
| `GET /api/ppt/sources` | 已配置的数据源（表单服务）列表与连接状态 |
| `/api/templates`、`/api/templates/upload`、`/api/templates/{id}` | 模板清单、上传、删除（按数据源隔离） |
| `POST /api/template/scan`、`/api/template/inspect` | 占位符清单、形状清单（绑定选择用） |
| `POST /api/template/generate` | Deck 编排生成（形绑定 + 占位符替换） |
| `POST /api/template/live-preview`、`GET /api/templates/{id}/slides/{n}/preview.png` | 真实数据预览（PowerPoint 渲染，缓存 PNG） |
| `POST /api/template/formula-preview` | 公式渲染预览（不依赖 Office） |
| `/api/schemes`、`/api/schemes/{name}`、`/api/schemes/{name}/generate`、`/api/schemes/{name}/versions` | 绑定方案的保存、复用、版本与一键生成 |
| `POST /api/ppt/preview-v2` | 旧版命名形状引擎预览（`DFM_PPT_V2_ENABLED=1` 时启用，自压铸表单服务迁入） |
| `GET /health` | 健康检查，返回 `{"service": "workbench", "contract_version": "1.0"}` |
| `GET /api/logs/tail`、`/api/logs/download` | 服务端日志（`data/ppt_workbench/logs/server.log`） |

环境变量：

- `PPT_PROVIDER_TOKEN`：调用表单服务数据源接口时携带的 Bearer 凭证
- `DFM_PPT_V2_ENABLED`、`DFM_PPT_V2_TEMPLATE`、`DFM_PPT_V2_SCHEMA_DIR`：旧版命名形状引擎预览开关与路径
- `DFM_APP_ROOT`：数据根目录（默认项目根，打包后为 exe 同级目录）

## 目录结构

```
app/
  settings.py               路径配置（BASE_DIR / APP_ROOT / DATA_DIR / STATIC_DIR）
  integration_contract.py   数据源契约模型（Snapshot / ReportContext）
  form_platform.py          表单平台存储（默认数据/字段目录，供无项目的模板试算）
  native_forms.py           原样 HTML 表单字段路径规范化（原生表单模板绑定用）
  html_literals.py          HTML 字段声明提取
  dfm/                      压铸报告领域模型（旧版命名形状引擎的输入）
  report/ppt/               渲染引擎：deck 编排、template_engine、OOXML 绑定层、
                            scheme_service、template_registry、slide_preview、校验器
  services/
    workbench.py            本服务入口（模板/方案/预览/生成 API）
    workbench_core.py       数据源连接与隔离存储（hub/scope/storage_root/install_api）
    observability.py        日志与 /api/logs/* 接口
static/                     ppt_home.html、template_editor.html、editor_models.js、editor_ux.js
templates/                  内置模板（demo / pilot / table-demo 等）
tools/                      模板构建与预览脚本（export_slide_preview.ps1 等）
config/ppt-connections.example.json  数据源连接配置示例
tests/                      引擎、绑定、方案、模板、分页、预览等 188 项测试
run_service.py              单服务启动脚本
```

## 测试

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

## 与其它服务的关系

- 工作台**不导入**表单服务的代码，也不直接读表单数据库；通过 HTTP 契约获取数据：
  - `GET /api/ppt-provider/v1/sources`：数据源列表；
  - `GET /api/ppt-provider/v1/sources/{id}/projects/{project_id}/snapshot`：项目快照 + 字段目录；
  - `POST /api/ppt-provider/v1/sources/{id}/normalize`：表单数据规范化。
- 表单页「按方案生成」由表单服务同源转发到本服务（`/api/schemes/*`）。
- 三服务架构与契约说明见 `docs/SERVICE_ARCHITECTURE.md`；同系列分支：
  `hpdc`（压铸表单服务，8001）、`machining`（机加表单服务，8002）、`New`（三服务合集 + 统一网关）。