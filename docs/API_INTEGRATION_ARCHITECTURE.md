# 两个 DFM 服务通过 API 接入 PPT 模板 —— 架构与接口设计

更新时间：2026-09-14。适用于 `api-hpdc` / `api-machining` / `api-workbench` 三条分支（各自独立部署）。

## 1. 目标与角色

| 角色 | 服务 | 职责 | 不做什么 |
| --- | --- | --- | --- |
| 数据提供方 | 压铸 DFM 表单（`api-hpdc`，8001）、机加 DFM 表单（`api-machining`，8002） | 拥有业务数据：项目、版本、设备/刀具/夹具/检具、计算结果；按契约对外提供**快照**与**字段目录** | 不做模板渲染、不存模板与方案 |
| 渲染与模板方 | 通用 PPT 工作台（`api-workbench`，8003） | 拥有模板、绑定方案、预览与生成能力；按契约主动拉取数据源 | 不读表单数据库、不复制业务规则 |

关键约束：**渲染引擎只消费 `f / t / i / derived / calc_results` 数据与字段目录**，不按业务字段名猜表单类型；
两个表单服务不导入任何渲染代码，工作台不导入任何表单代码，双方只通过 HTTP 契约耦合。

## 2. 接口契约（两层）

### 2.1 数据提供契约（表单服务 → 工作台，`/api/ppt-provider/v1`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/ppt-provider/v1/sources` | 数据源清单（id、名称、表单回链、契约版本） |
| `GET` | `/api/ppt-provider/v1/sources/{source_id}/projects` | 项目清单（id、名称、revision、更新时间） |
| `GET` | `/api/ppt-provider/v1/sources/{source_id}/projects/{project_id}/snapshot` | **项目快照**：`data`（业务数据）+ `catalog`（字段目录）；`project_id` 支持 `defaults`/`demo`/`legacy` |
| `POST` | `/api/ppt-provider/v1/sources/{source_id}/normalize` | 规范化：把原始表单数据转成引擎可消费的结构（含服务端计算） |

- 压铸侧 `source_id = dfm`（含表单平台导入的其它应用 id）；机加侧 `source_id = machining-dfm`。
- 可选鉴权：`PPT_PROVIDER_TOKEN` 设置后，以上接口要求 `Authorization: Bearer <token>`。

### 2.2 生成契约（工作台对外，`/api/ppt/*`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/ppt/contract` | **契约发现**：可用数据源 + 生成/目录/快照入口与参数说明 |
| `GET` | `/api/ppt/sources` | 数据源清单（含连接错误信息） |
| `GET` | `/api/ppt/sources/{source_id}/projects` | 某数据源的项目清单 |
| `GET` | `/api/ppt/sources/{source_id}/projects/{project_id}/snapshot` | 项目快照（数据 + 目录） |
| `GET` | `/api/ppt/sources/{source_id}/projects/{project_id}/catalog` | **字段目录**（绑定 UI 用，不含业务数据） |
| `POST` | `/api/ppt/generate` | **按「数据源 + 项目」生成 PPT**（调用方不传数据） |

`POST /api/ppt/generate` 请求体：

```json
{
  "source_id": "dfm",
  "project_id": "0bf8f983fd7d4b29807acd5c35578617",
  "scheme": "TP-DFM模板-v1.1",
  "output_mode": "deck",
  "missing": "keep"
}
```

也支持不走方案、直接给模板与页面绑定：

```json
{
  "source_id": "machining-dfm",
  "project_id": "defaults",
  "template": "table-demo",
  "slides": [{"source": 1, "bindings": {}}],
  "output_mode": "in_place"
}
```

响应：`pptx` 二进制流，附带诊断头
`X-DFM-Data-Source`、`X-DFM-Project`、`X-DFM-Project-Revision`、`X-DFM-Template`、`X-DFM-Scheme`、
`X-DFM-Slide-Count`、`X-DFM-Text-Replaced`、`X-DFM-Images-Bound`、`X-DFM-Bindings-Applied`。

### 2.3 表单侧便捷入口（同源转发，`/api/report/*`）

页面或内部脚本不必知道工作台地址与契约细节：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/report/options` | 返回工作台地址、生成入口、契约地址、目录地址 |
| `GET` | `/api/report/sources` | 转发工作台 `/api/ppt/contract`（数据源与契约版本） |
| `POST` | `/api/report/generate` | 同源转发到工作台 `/api/ppt/generate`，直接回传 pptx |

```bash
# 例：在机加表单服务上，为项目 X 用方案 S 出报告（无需传业务数据）
curl -X POST http://127.0.0.1:8002/api/report/generate \
     -H "Content-Type: application/json" \
     -d '{"project_id":"<proj>","scheme":"机加DFM方案"}' -o out.pptx
```

## 3. 数据流

```
表单页面/外部系统
   │ ① POST /api/report/generate {project_id, scheme|template+slides}
   ▼
表单服务（hpdc / machining）        ← 只做转发，不渲染
   │ ② POST /api/ppt/generate {source_id, project_id, …}
   ▼
PPT 工作台
   │ ③ GET /api/ppt-provider/v1/sources/{id}/projects/{pid}/snapshot   （+ Bearer 可选）
   ▼
表单服务（数据侧）→ data + catalog
   │ ④ 方案/模板 → TemplateEngine 渲染（deck 编排 + 形状绑定 + 占位符替换）
   ▼
pptx（含 X-DFM-* 诊断头）→ 原路返回调用方
```

绑定流程（人工）：工作台 `/template-editor?app_id=<来源>&project_id=<项目>` → 拉 `catalog` 显示中文字段 →
点击 PPT 形状/表格绑定字段 → 保存为方案（按数据源隔离存储）→ 以后按 `source_id + project_id + scheme` 一键生成。

## 4. 部署与环境变量

| 变量 | 位置 | 默认 | 说明 |
| --- | --- | --- | --- |
| `HPDC_PROVIDER_URL` / `MACHINING_PROVIDER_URL` | 工作台 | `http://127.0.0.1:8001` / `:8002` | 数据源地址（可指向远端主机） |
| `PPT_WORKBENCH_URL` | 表单服务 | `http://127.0.0.1:8003` | 转发目标工作台地址 |
| `PPT_PROVIDER_TOKEN` | 双方 | 空 | 设置后数据源接口要求 Bearer 令牌 |
| `DFM_APP_ROOT` | 全部 | 项目根 / exe 同级 | 数据目录（按服务隔离：`data/form_platform`、`data/machining_dfm`、`data/ppt_workbench`） |

启动顺序：先起两个表单服务，再起工作台；工作台不可用时，表单侧 `/api/report/generate` 返回 502 并提示"请启动工作台服务"。

## 5. 错误与边界

| 场景 | 行为 |
| --- | --- |
| 工作台未启动 / 网络不通 | 表单侧 502「PPT 工作台无法连接，请启动工作台服务」 |
| 数据源不可达 | 工作台 `/api/ppt/contract` 的 `errors` 列出该来源；生成时 502「读取数据源失败」 |
| 方案不存在 | 404（`SchemeError`） |
| 模板不存在 | 404（模板未注册，提示已知模板 id） |
| `output_mode` / `missing` 非法 | 422 |
| 项目已逻辑删除 | 数据源返回 410，快照/生成直接失败并透传原因 |
| 未绑定字段 | 由 `missing` 决定：`keep` 保留原占位符、`clear` 清空、`error` 报错；响应头 `X-DFM-*` 给出数量 |

## 6. 新增一个 DFM 服务（扩展方式）

1. 实现 `/api/ppt-provider/v1` 四个接口（`sources / projects / snapshot / normalize`），`snapshot.data` 用 `f/t/i/derived/calc_results`，`snapshot.catalog` 给中文字段目录；
2. 若需要页面一键出报告，把本仓 `install_report_bridge(app, source_id)` 复制过去（约 60 行，无渲染依赖）；
3. 在工作台环境变量中登记 `{ID}_PROVIDER_URL`，即可在 `/api/ppt/contract` 与编辑器数据源列表中看到；
4. 无需改动渲染引擎与模板格式。

## 7. 自测清单

```powershell
# 1) 契约发现
curl http://127.0.0.1:8003/api/ppt/contract
# 2) 字段目录（绑定 UI 用）
curl "http://127.0.0.1:8003/api/ppt/sources/dfm/projects/defaults/catalog"
# 3) 跨服务生成（工作台自行拉数据）
curl -X POST http://127.0.0.1:8003/api/ppt/generate -H "Content-Type: application/json" `
     -d '{"source_id":"machining-dfm","project_id":"defaults","template":"demo","slides":[{"source":1}]}' -o w.pptx
# 4) 表单侧同源生成（便捷入口）
curl -X POST http://127.0.0.1:8001/api/report/generate -H "Content-Type: application/json" `
     -d '{"project_id":"defaults","template":"demo","slides":[{"source":1}]}' -o f.pptx
```

三条分支的对应关系：`api-hpdc` = 数据提供方（压铸）、`api-machining` = 数据提供方（机加）、
`api-workbench` = 生成契约与渲染；三者合起来构成本文档描述的接入方式。
