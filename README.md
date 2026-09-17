# 机加 DFM 表单服务（machining）

本分支是三服务拆分的**机加表单服务**独立版本：只包含机加 DFM 表单所需的代码，
可单独部署运行，不依赖压铸表单服务与 PPT 工作台服务。

- 入口：`app/services/machining.py`（FastAPI 应用对象 `app`）
- 默认地址：`http://127.0.0.1:8002`
- 数据目录：`data/machining_dfm/`（SQLite：项目、版本、设备/刀具/夹具/检具、后台配置）
- 种子数据：`app/resources/machining_dfm_seed.json`（首次运行自动建库）

## 运行

```powershell
python -m pip install -r requirements.txt

python run_service.py                     # 默认 127.0.0.1:8002
python run_service.py --host 0.0.0.0      # 局域网可访问
python run_service.py --port 8012 --reload

# 或者直接用 uvicorn
.venv\Scripts\python.exe -m uvicorn app.services.machining:app --host 0.0.0.0 --port 8002
```

浏览器打开 <http://127.0.0.1:8002/machining-dfm> 使用机加 DFM 表单。

## 主要接口

| 路径 | 说明 |
| --- | --- |
| `GET /` | 跳转到 `/machining-dfm` |
| `GET /machining-dfm` | 机加 DFM 单页应用（静态资源在 `static/machining_dfm/`） |
| `GET /health` | 健康检查，返回 `{"service": "machining", "contract_version": "1.0"}` |
| `/api/machining-dfm/*` | 表单数据接口：bootstrap、项目增删改查、历史版本、后台配置、设备/刀具/夹具/检具库、登录与改密 |
| `GET /api/integration/services` | 跨服务链接（表单中心 / 机加表单） |
| `GET /api/integration/workbench-link` | 生成 PPT 工作台跳转地址（默认 `http://127.0.0.1:8003`） |
| `/api/ppt-provider/v1/*` | 数据源契约：`sources`、`projects`、`snapshot`、`normalize`（供 PPT 工作台拉取项目快照） |
| `GET /api/logs/tail` | 服务端日志尾部（由 `app/services/observability.py` 提供） |

环境变量：

- `MACHINING_PUBLIC_URL`：对外公布的本服务地址（快照回链、跨服务导航用）
- `PPT_WORKBENCH_URL`：PPT 工作台地址，默认 `http://127.0.0.1:8003`
- `PPT_PROVIDER_TOKEN`：设置后 `/api/ppt-provider/v1/*` 需要 `Authorization: Bearer <token>`
- `DFM_APP_ROOT`：数据根目录（默认项目根，打包后为 exe 同级目录）

## 目录结构

```
app/
  settings.py               路径配置（BASE_DIR / APP_ROOT / DATA_DIR / STATIC_DIR）
  machining_dfm.py          机加表单存储与路由（SQLite，含鉴权与后台配置）
  machining_projection.py   机加数据 → 报告运行时投影（工序时间、节拍、月产能）
  native_forms.py           原样 HTML 表单解析/规范化（保存与快照共用）
  html_literals.py          HTML 内字段声明提取
  integration_contract.py   数据源契约模型（Snapshot / ReportContext）
  services/
    machining.py            本服务入口
    provider_api.py         数据源导出 API + 跨服务链接（本分支只含机加部分）
    observability.py        日志与 /api/logs/* 接口
static/machining_dfm/       机加表单前端（index.html + host.js + legacy_app.js + PptxGenJS）
tests/test_machining_dfm.py 机加服务测试
run_service.py              单服务启动脚本
```

## 测试

```powershell
.venv\Scripts\python.exe -m unittest tests.test_machining_dfm -v
```

## 与其它服务的关系

- 机加表单**不导入**压铸表单或 PPT 工作台的代码；跨服务只通过 HTTP：
  - 表单页「进入 PPT 工作台」→ `/api/integration/workbench-link` 返回工作台地址；
  - PPT 工作台通过 `/api/ppt-provider/v1/sources/machining-dfm/projects/{id}/snapshot` 拉取项目快照与字段目录。
- 三服务架构与契约说明见 `docs/SERVICE_ARCHITECTURE.md`；同系列分支：
  `hpdc`（压铸表单服务，8001）、`workbench`（通用 PPT 工作台，8003）、`New`（三服务合集 + 统一网关）。
