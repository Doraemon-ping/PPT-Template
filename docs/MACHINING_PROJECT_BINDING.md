# 机加 DFM 项目 id → PPT 工作台绑定（现行实现）

更新：2026-09-20。面向「机加 DFM 表单保存后跳转工作台、按项目 id 取工序/设备/工艺/问题并绑定」这条链路，
记录**已经生效的配置、数据契约和验证方法**，以及目前还达不到的部分。

相关文档：[三服务架构](SERVICE_ARCHITECTURE.md)（v1 提供方契约）、[当前开发上下文](DEVELOPMENT_CONTEXT_CURRENT.md)。

## 1. 链路

```text
机加 DFM 表单（8002）                         PPT 工作台（8003）
   │  项目已保存（服务端数据库）                    │
   │  GET /api/integration/workbench-link          │
   │      ?app_id=machining-dfm&project_id=<id>    │
   ├──────────────────────────────────────────────►│  /template-editor
   │                                               │      ?app_id=machining-dfm&project_id=<id>
   │  GET /api/ppt-provider/v1/sources             │
   │◄──────────────────────────────────────────────┤  解析数据源 → 连接
   │  GET  .../sources/machining-dfm/projects      │
   │◄──────────────────────────────────────────────┤  项目下拉（默认选中 URL 里的 id）
   │  GET  .../projects/<id>/snapshot              │
   │◄──────────────────────────────────────────────┤  data（f/t/i）+ catalog（中文目录）
   │                                               │  点选 PPT 对象 → 选字段/表格列 → 保存绑定
   │                                               │  POST /api/template/generate?app_id=...
```

跳转 URL 由表单服务拼好（`app/services/provider_api.py` 的 `install_link`），表单页按钮在
`static/machining_dfm/host.js` 的 `openPptWorkbench()`；`app_id` 固定为 `machining-dfm`。
**工作台不读表单数据库**，只通过上面的 v1 快照接口取数；因此表单必须先保存再跳转。

## 2. 启动

两个服务、两个仓库，各自一个进程（本机默认端口）：

```powershell
# 机加 DFM 表单服务（machining 分支）
cd C:\Users\26257\Desktop\工作计划\6-DFM自动生成
.\.venv\Scripts\python.exe run_service.py                 # http://127.0.0.1:8002

# 通用 PPT 工作台（本仓库）
cd C:\Users\26257\Desktop\工作计划\11-重构\1-ppt编辑台\PPT-Template-workbench
python run_service.py                                     # http://127.0.0.1:8003
```

## 3. 工作台侧配置：数据源连接

工作台**默认不内置任何业务数据源**（`ProviderHub.connections()` 读不到文件就返回空），
必须配置连接文件，否则 `/api/ppt/sources` 为空、编辑器只显示空数据源：

`data/ppt_workbench/connections.json`（或用环境变量 `PPT_CONNECTIONS_FILE` 指向别处）：

```json
{
  "connections": [
    { "id": "machining", "base_url": "http://127.0.0.1:8002" }
  ]
}
```

- `id` 是连接标识（任意），数据源 `source_id`（这里是 `machining-dfm`）由提供方 `/sources` 返回。
- 文件按请求读取，改完不需要重启工作台。
- 表单服务若配置了 `PPT_PROVIDER_TOKEN`，连接里加 `"token_env": "<环境变量名>"`。
- 自检：`GET http://127.0.0.1:8003/api/ppt/sources` 应返回
  `{"sources":[{"id":"machining-dfm", "name":"机加 DFM", ...}], "errors": []}`。

## 4. 模板也要按数据源注册

工作台的模板、方案、草稿、预览缓存都按 `source_id` 隔离（`data/ppt_workbench/sources/<source_id>/`）。
表单跳转带的是 `app_id=machining-dfm`，所以**上传模板时也必须带这个 `app_id`**，否则编辑器里模板列表是空的：

```powershell
curl.exe -X POST "http://127.0.0.1:8003/api/templates/upload?app_id=machining-dfm&template_id=dfm----20260305" `
  -F "file=@DFM模版更新20260305.pptx"
```

本机已注册：`dfm----20260305`（17 页，来自 `DFM模版更新20260305.pptx`，sha256 `55556cb0…`）。
它没有 `{占位符}`，绑定全部走「点选对象 → 显式绑定」，与本工作台的设计一致。

## 5. 项目 id 能取到什么

`GET /api/ppt/sources/machining-dfm/projects/<项目 id>/snapshot` 返回 `data`（`f`/`t`/`i`）和
`catalog`。实测（项目「原文件集成 · 蓄电池支架」，版本 110）：

| 业务信息 | 快照位置 | 实测 |
| --- | --- | --- |
| 项目信息（客户/零件/尺寸/重量/产能/检具报价…） | `f.G_<键>_<哈希>` + `i.G_<图片>_<哈希>` | 49 个标量、23 个图片槽 |
| **工序** | `t.pr_0510eddd78`（列 `nm`/`mc`/`cI`/`fixP`/`eqP`/`mid`/`mi`） | 2 行 |
| **工序选定的设备**（已 join 进工序行） | 同上的 `machine_brand`/`machine_model`/`machine_xyz`/`machine_pa`/`machine_rpa`/`machine_rapid`/`machine_tc`/`machine_spm`/`machine_atc`/`machine_price`/`machine_desc`/`machine_id`/`machine_selected`，照片有则 `i.pr_<行号>_machine_img_<哈希>` | 实测 `兄弟(Brother) S700Z2N`、`CFV1000Lite` |
| **工艺**（每道工序的刀具/加工参数） | `t.pr_tl_4ccf869fdf`（`id`/`tp`/`ds`/`d`/`n`/`vf`/`ln`/`ps`/`cn`/`_ct`/`_vc`…） | 25 行 |
| **设备**（整库，供选型/对比） | `t.mdb_a8584e4d63`（`id`/`brand`/`model`/`xyz`/`pa`/`rpa`/`rapid`/`spm`/`atc`/`price`…） | 27 行 |
| **问题** | `t.is_fa51fd49ab`（`tp`/`pr`/`ds`/`fx`/`cr`/`st` + `bI`/`aI` 图片槽） | 2 行 |
| 工序节拍/月产能（服务端算好） | `t.computed_processes_c782c2a4cc` + `f.computed_*` | 2 行 |
| 刀具库 / 夹具库 / 检具库 | `t.tdb_*` / `t.fdb_*` / `t.idb_*` | 761 / 177 / 437 行 |

要点：

- 表键 = 数据路径 + 前 10 位哈希（`pr` → `pr_0510eddd78`），**只跟路径有关，不跟项目有关**，
  所以同一套绑定方案可以跨项目复用；换项目只需换 URL 上的 `project_id`。
- 目录里的 `module`/`group` 就是中文业务名（工序/设备库/问题清单…），编辑器「表格数据来源」下拉按它显示。
- 快照不含密码、后台配置等敏感数据；设备图片由提供方内联成 data URL。
- `machine_*` 由机加提供方在投影时按 `pr[].mid`（退 `mi`、再退兜底机型，与页面 `gm()`/节拍计算同一套解析）
  从设备库 join 进工序行，**不落库、不改旧键**：所以「一页一工序」的模板可以直接绑
  `t.pr_<哈希>[0].machine_model`（固定第一条）或在 `repeat` 工序表后按当前行绑 `machine_model`，
  也能只绑 `machine_selected` 为真的那些工序。`machine_selected=false` 表示这道工序其实没选设备，
  显示的是兜底机型。提供方侧实现：`app/services/projection.py` 的 `attach_machines`
  （不需要的调用方传 `report_runtime(state, with_machines=False)`）。

## 6. 在编辑器里怎么绑

`http://127.0.0.1:8003/template-editor?app_id=machining-dfm&project_id=<项目 id>`：

1. 左上「模板」选 `dfm----20260305` 一类的机加模板；数据来源已自动落在 URL 上的项目。
2. 点画布上的对象 → 选绑定：
   - 文本对象 → 选 `项目信息…/客户`、`零件号` 等字段；
   - 图片对象 → 选 `i.` 图片槽（产品图、检具图、设备图、问题前后对比图）；
   - **表格对象** → 选「表格数据来源」（工序 / 设备库 / 问题清单 / 刀具明细…）→ 逐列映射 PPT 列 ← 表单列
     → 设「保留表头行数」「每页行数」→ 保存；
   - 重复页：页面 `repeat` 选 `t.pr_…` 时，页内字段可直接用该行的列（`nm`/`mc`…）。
3. 「保存方案」把模板 + 全部绑定存成一个方案；之后换项目只需带新 `project_id` 打开或按方案生成。
4. 生成：编辑器内直接生成下载，或 `POST /api/schemes/<方案名>/generate?app_id=machining-dfm`（body 带快照 `data`）。

## 7. 一键校验

```powershell
python scripts/check_machining_binding.py                       # 取最近更新的项目
python scripts/check_machining_binding.py --project <项目 id> --template dfm----20260305
python scripts/check_machining_binding.py --save-scheme 机加-工序-校验   # 额外验证方案保存+复用
```

脚本只读业务数据，会依次校验：数据源已连接 → 项目列表 → 快照里 工序/设备/工艺/问题 的覆盖与行数、
每道工序 join 到的设备 → 真实生成一次（封面字段 + 产品图 + 工序整表 + 这道工序的设备 + 问题文字）
→ 解包 PPTX 确认文字真的写进页面。输出以 `[失败]`/`[警告]` 开头的那一行就是断点。

> 改了机加提供方（`app/services/projection.py` 等）后要**重启 8002**：`run_service.py` 不带热重载，
> 不重启的话工作台拿到的还是旧快照。

## 8. 现状边界（还没做的）

1. **表格列名是短键**：目录里工序/设备/问题的列名还是 `mc`/`fixP`/`eqP`/`mid`/`tp`/`ds` 这种旧短键
   （join 进来的设备列是 `machine_*`，同样按短键显示），编辑器里显示为「名称（nm）」「mc（mc）」。
   原因是 `labels` 通道（`forms.py::_normalize_dfm` 接受 `runtime['labels']`）只有导入型 HTML 表单
   在浏览器侧填充，机加是服务端原生表单，没有提供方标注；且现有 `labels` 只按**末级键**匹配，
   无法区分 `tp`（刀具类型 / 问题类型）。要做需要在机加提供方补一份「路径 → 中文名」的表，
   并让 `caption()`/`columns` 支持按路径取标签（属于 machining 分支的改动）。
2. **图片槽位按行号固定**：`i.pr_1_machine_img_<哈希>` 里的 `1` 是工序数组行序、`i.mdb_11_img_<哈希>`
   里的 `11` 是设备库行序；库/工序排序一变槽位就变，重复页里也没法用「当前行」的图片
   （所以设备照片目前适合"一页一工序"的模板按行号绑，不适合重复页）。
3. 原页/实时预览仍依赖本机安装桌面版 PowerPoint；生成 PPTX 不需要。
