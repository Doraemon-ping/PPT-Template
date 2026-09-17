# 压铸 DFM 表单服务（hpdc）

本分支是三服务拆分的**压铸表单服务**独立版本：只包含压铸 DFM 表单、表单平台与
传统报告导出所需的代码，可单独部署运行，不导入机加表单或 PPT 工作台的代码。

- 入口：`app/services/hpdc.py`（FastAPI 应用对象 `app`）
- 默认地址：`http://127.0.0.1:8001`
- 数据目录：`data/form_platform/`（表单平台项目库 SQLite）、`data/project.json`（旧版单项目存档）

## 运行

```powershell
python -m pip install -r requirements.txt

python run_service.py                     # 默认 127.0.0.1:8001
python run_service.py --host 0.0.0.0      # 局域网可访问
python run_service.py --port 8011 --reload

# 或者直接用 uvicorn
.venv\Scripts\python.exe -m uvicorn app.services.hpdc:app --host 0.0.0.0 --port 8001
```

- 压铸 DFM 表单：<http://127.0.0.1:8001/>
- 表单中心（项目/版本管理、导入 HTML 表单）：<http://127.0.0.1:8001/forms>

## 主要接口

| 路径 | 说明 |
| --- | --- |
| `GET /` | 压铸 DFM 表单页（`static/index.html`） |
| `GET /forms` | 表单中心（`static/form_center.html`） |
| `POST /api/calc` | 压铸工艺计算（派生值 + 机型填充 + 全部结果） |
| `POST /api/ppt` | 传统 47 页报告导出（python-pptx 直接生成） |
| `GET /api/demo` | 示例数据 |
| `GET/POST /api/project/load`、`/api/project/save` | 旧版单项目存档（保存会写入表单平台项目库） |
| `/api/form-apps/*` | 表单平台：HTML 导入、原样运行桥接、命名项目/版本/草稿、字段目录 |
| `/api/integration/services`、`/api/integration/workbench-link` | 跨服务链接与 PPT 工作台跳转地址 |
| `/api/schemes*` | 「按方案生成」：同源转发到独立的 PPT 工作台服务（默认 `http://127.0.0.1:8003`） |
| `/api/ppt-provider/v1/*` | 数据源契约：`sources`、`projects`、`snapshot`、`normalize`（供 PPT 工作台拉取压铸项目快照与字段目录） |
| `GET /health` | 健康检查，返回 `{"service": "hpdc", "contract_version": "1.0"}` |
| `GET /api/logs/tail`、`/api/logs/download` | 服务端日志（`data/form_platform/logs/server.log`） |

环境变量：

- `HPDC_PUBLIC_URL`：对外公布的本服务地址（快照回链、跨服务导航用）
- `PPT_WORKBENCH_URL`：PPT 工作台地址，默认 `http://127.0.0.1:8003`
- `PPT_PROVIDER_TOKEN`：设置后 `/api/ppt-provider/v1/*` 需要 `Authorization: Bearer <token>`
- `DFM_APP_ROOT`：数据根目录（默认项目根，打包后为 exe 同级目录）

> 说明：旧版命名形状引擎预览（原 `POST /api/ppt/preview-v2`）已随拆分移至 PPT 工作台服务；
> 本服务只保留传统 47 页 `/api/ppt` 导出。

## 目录结构

```
app/
  settings.py            路径配置（BASE_DIR / APP_ROOT / DATA_DIR / STATIC_DIR）
  calc.py                压铸工艺计算（速度/压力/锁模力/节拍等）
  machines.py            机型库与选型
  utils.py               数值/格式化工具
  demo.py                示例数据与默认 logo
  ppt.py                 传统 47 页报告生成（python-pptx）
  form_platform.py       表单平台：应用/项目/版本/草稿 + SQLite 存储
  native_forms.py        原样 HTML 表单解析与规范化（计算桥接）
  html_literals.py       HTML 内字段声明提取
  provider_context.py    表单数据 → 报告运行时上下文（公式字段、结论）
  integration_contract.py 数据源契约模型（Snapshot / ReportContext）
  dfm/                   压铸 DFM 领域模型与旧版报告适配器
  report/ppt/openxml/    OOXML 包编辑（模板导入校验、形状与占位符扫描、表格绑定）
  services/
    hpdc.py              本服务入口
    provider_api.py      数据源导出 API + 跨服务链接（本分支只含压铸部分）
    observability.py     日志与 /api/logs/* 接口
static/                  表单页、表单中心、原生桥接、字段目录（dfm_catalog.js）
tools/build_field_catalog.js  字段中文目录生成脚本（schema 变更后重新生成）
tests/                   表单平台、原生表单、字段目录、领域模型、日志接口测试
run_service.py           单服务启动脚本
```

## 测试

```powershell
.venv\Scripts\python.exe -m unittest tests.test_form_platform tests.test_native_forms tests.test_field_catalog tests.test_dfm_report tests.test_legacy_dfm_adapter tests.test_logging_api -v
```

## 与其它服务的关系

- 压铸表单**不导入**机加表单或 PPT 工作台的代码；跨服务只通过 HTTP：
  - 表单页「按方案生成」→ `/api/schemes/*` 转发到工作台服务（8003）；
  - 表单页「进入 PPT 工作台」→ `/api/integration/workbench-link` 返回工作台地址；
  - PPT 工作台通过 `/api/ppt-provider/v1/sources/dfm/projects/{id}/snapshot` 拉取项目快照与字段目录。
- 三服务架构与契约说明见 `docs/SERVICE_ARCHITECTURE.md`；同系列分支：
  `machining`（机加表单服务，8002）、`workbench`（通用 PPT 工作台，8003）、`New`（三服务合集 + 统一网关）。