# 三服务架构与新项目接入

更新：2026-09-17。本文是拆分后的架构、启动和接入规范；旧文档的单体路径仅作历史参考。

## 1. 服务边界

| 服务 | 独立入口 | 默认地址 | 拥有的数据/职责 |
| --- | --- | --- | --- |
| 压铸表单（兼容已有导入表单） | `app.services.hpdc:app` | http://127.0.0.1:8001 | 项目、版本、逻辑删除、压铸计算；`data/form_platform/` |
| 机加表单 | `app.services.machining:app` | http://127.0.0.1:8002 | 项目、版本、设备/刀具/夹具/检具、后台配置、密码哈希；`data/machining_dfm/` |
| 通用 PPT 工作台 | `app.services.workbench:app` | http://127.0.0.1:8003 | 数据源连接、模板、方案、工作台草稿、预览与生成；`data/ppt_workbench/` |

数据流：表单保存项目 → 工作台通过 HTTP 拉取项目快照与字段目录 → 绑定模板 → 生成 PPTX。

- 工作台不导入表单数据库、机加工艺、压铸计算；计算结果由所属表单服务输出。
- 机加快照包含服务端计算的工序切削/非切削时间、节拍、月产能，不依赖浏览器是否先计算。
- 渲染引擎只消费 `f/t/i/derived/calc_results/ppt`，不根据业务字段名猜测表单类型。
- 两套前端依然是静态 HTML/JS，通过同源 FastAPI 调用；跨服务数据交换在后端完成，无须浏览器跨域放开权限。
- 旧固定版 PPT 导出作为各表单的兼容功能保留；新模板、方案与通用生成均由工作台负责。
- 代码目前保留在同一仓库，三个 FastAPI 应用可分别运行、停止、部署；不是三个复制仓库。

## 2. 启动与停止

在项目根目录执行（首次先安装依赖）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_services.py
```

这会启动三个独立进程，默认仅监听本机。按 Ctrl+C 只停止本次启动的三个子进程；不扫描/强杀其他 Python 服务。端口被占用时拒绝启动并提示，避免误连旧版本。启动器不要与下列独立命令同时使用。

分别启动时，在三个终端执行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.services.hpdc:app --host 127.0.0.1 --port 8001
.\.venv\Scripts\python.exe -m uvicorn app.services.machining:app --host 127.0.0.1 --port 8002
.\.venv\Scripts\python.exe -m uvicorn app.services.workbench:app --host 127.0.0.1 --port 8003
```

每个服务都提供 `/health`、`/docs`、`/api/logs/tail`、`/api/logs/download`。日志按服务存储在各自目录下的 `logs/server.log`（压铸为 `data/hpdc/logs/`）。

保留单端口兼容入口：`python -m uvicorn app.main:app --port 8000`。它只负责分发请求，使用相同 JSON 协议通过 ASGI HTTP 连接表单服务；不需要另起 8001–8003。原 exe 的源码入口也保留，但旧打包成品不会自动更新，需重新构建。

## 3. 存储与迁移

```text
data/
  form_platform/platform.sqlite3       # 压铸及已有导入表单项目，不移动
  machining_dfm/machining_dfm.sqlite3   # 机加项目、库、配置、密码，不移动
  ppt_workbench/
    connections.json                   # 可选；省略时默认连接 8001/8002
    workbench.sqlite3                  # 独立工作台草稿、乐观锁版本
    sources/<source_id>/
      templates/                       # 上传模板与注册表
      schemes/                         # 方案及版本
      .migrated-v1                     # 旧数据复制迁移标记
```

首次访问某数据源的模板/方案时，从旧 `data/templates`、`data/schemes`、`data/machining_dfm/data/` 或导入应用目录复制其模板与方案；首次访问草稿时从旧平台库复制草稿。迁移保留原文件/原记录，不删除、不覆盖已存在的新文件。迁移完成后新修改只写工作台目录，旧数据不是实时镜像。

部署前建议备份整个 `data`。回退旧程序不会自动获得迁移后新增的方案/草稿；需要单独导出或恢复工作台备份。跨机器部署时应把旧模板/方案目录随工作台数据一起迁移，工作台不通过网络直接读取表单数据库。

`DFM_APP_ROOT` 可设置各进程的独立可写根目录（其下自动创建 `data`），内置静态文件和模板仍从代码/打包资源目录加载。实际 HTTP 集成测试使用三个不同根目录验证无共享数据库依赖。

## 4. 新项目只需实现 v1 数据提供接口

工作台连接配置：把 `config/ppt-connections.example.json` 复制到 `data/ppt_workbench/connections.json`，或设置环境变量 `PPT_CONNECTIONS_FILE` 指向配置文件。配置为服务端受信文件，不提供任意 URL 的公开注册接口。

```json
{"connections":[
  {"id":"hpdc","base_url":"http://127.0.0.1:8001"},
  {"id":"machining","base_url":"http://127.0.0.1:8002"},
  {"id":"my-project","base_url":"http://127.0.0.1:8010"}
]}
```

`id` 是连接标识；一个连接可发布多个 `source_id`，但所有数据源标识必须全局唯一，只用字母、数字、下划线、短横线，最长 80 字符。连接文件按请求读取，更新无须修改或重启工作台。

新项目实现三类接口：

| 方法/路径（前缀 `/api/ppt-provider/v1`） | 返回内容 |
| --- | --- |
| `GET /sources` | `contract_version: "1.0"` 和 `sources: [{id,name,form_url,contract_version}]` |
| `GET /sources/{source_id}/projects` | `projects: [{id,name,revision}]`，只列未删除项目 |
| `GET /sources/{source_id}/projects/{project_id}/snapshot` | 下列原子快照，目录与数据来自同一项目版本 |

```json
{
  "contract_version":"1.0", "source_id":"inspection", "project_id":"sample",
  "revision":1, "name":"检验项目", "form_url":"http://127.0.0.1:8010/",
  "data":{
    "f":{"part":"A001"},
    "t":{"checks":[{"item":"直径","value":20.01}]},
    "i":{}, "derived":{}, "calc_results":{}, "ppt":{}
  },
  "catalog":{
    "fields":[{"path":"f.part","label":"零件号","module":"检验","group":"基本信息"}],
    "tables":{"checks":{"label":"检验明细","module":"检验","group":"尺寸","columns":{"item":"项目","value":"实测值"}}},
    "images":{}, "derived":{}, "results":{}
  }
}
```

`f` 为标量字段，`t` 为明细数组，`i` 为图片数组（建议 data URI，避免依赖表单服务器本地路径），其余为服务端已计算结果。只输出报告所需数据，禁止把密码、访问令牌或后台认证配置放进快照。字段路径要稳定；新增字段只更新提供方目录，无须改工作台。删改路径前迁移旧绑定方案。

直接可运行示例：`python -m uvicorn tools.example_ppt_provider:app --port 8010`，配合示例连接配置即可显示“质量检验（接入示例）”。示例不导入本项目代码，证明接入不依赖 Python 内部实现。

表单打开工作台：`http://127.0.0.1:8003/template-editor?app_id=inspection&project_id=sample`。应先保存表单，再跳转，工作台加载的是数据库已保存版本，不读取原页面 localStorage。

工作台面向客户端提供 `/api/ppt/sources`、`/api/ppt/sources/{id}/projects`、`/api/ppt/sources/{id}/projects/{project}/snapshot`；快照 `data` 自动标注 `_ppt_context_version: 1`。通过 `/api/template/generate?app_id=...` 或 `/api/schemes/{name}/generate?app_id=...` 生成时，完整传回此 `data`。

仅为兼容旧调用方，现有两个提供方还实现 `POST /sources/{id}/normalize`，接收 `{data,binding_sources}`。新项目使用快照接口即可，不必实现 normalize。无项目的提供方如需“默认数据”，应支持快照 `project_id=defaults`。

## 5. 配置与安全边界

- `PPT_WORKBENCH_URL`：表单跳转及旧方案生成代理的工作台地址，默认 8003。
- `HPDC_PROVIDER_URL`、`MACHINING_PROVIDER_URL`：没有连接配置文件时的工作台后端连接地址。
- `HPDC_PUBLIC_URL`、`MACHINING_PUBLIC_URL`：用户浏览器可访问的表单地址；跨机器部署必须配置，不能给远程用户返回 `127.0.0.1`。
- `PPT_PROVIDER_TOKEN`：在各表单进程配置后，提供方 API 要求 `Authorization: Bearer ...`。工作台连接可添加 `token_env`，指向工作台进程中保存对应令牌的环境变量。令牌不写前端或连接 JSON。
- 默认是受信本机/内网工具，不是完整多租户系统。工作台本身、表单项目 API 及日志接口没有统一用户鉴权；不得直接暴露公网。对外部署需反向代理鉴权、HTTPS、权限隔离和限流。
- 某个数据源离线时 `/api/ppt/sources` 会返回 `errors`，其他数据源仍可用；不能把加载失败当作空项目覆盖。
- 原 PNG 实时预览仍依赖系统 PowerPoint/既有渲染环境；服务拆分不会自动安装此依赖。PPTX 生成不依赖该实时预览。

## 6. 验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/*.test.cjs
```

`test_service_integration.py` 验证项目版本、归档、模板隔离、草稿冲突、旧文件迁移和生成；`test_service_http.py` 启动独立进程、使用独立数据根目录，验证两套现有表单与全新提供方经真实 HTTP 生成 PPT、跳转和服务离线隔离，退出时关闭测试进程。
