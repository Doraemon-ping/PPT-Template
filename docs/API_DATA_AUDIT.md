# 压铸 DFM / 机加 DFM 前后端分离核对与接口清单

本文件由脚本抓取**真实运行中**的两个服务生成（临时数据目录、全新数据库），用于人工复核。

- 压铸 DFM 表单服务：`hpdc` 分支，`app/services/hpdc.py`，默认 8001
- 机加 DFM 表单服务：`machining` 分支，`app/services/machining.py`，默认 8002
- 抓取方式：`python run_service.py` 启动后逐个调用接口；数据目录通过 `DFM_APP_ROOT` 指向临时目录，不影响真实数据

## 结论（分离程度）

**已分离（数据全部来自后端接口）**：压铸项目/版本/草稿/字段目录、机加项目/版本/设备·刀具·夹具·检具库/后台配置/默认数据/登录鉴权、
两服务的计算结果（压铸 `/api/calc`，机加由 `/api/machining-dfm/bootstrap` 等返回）、以及给 PPT 工作台用的数据源快照与字段目录。

**仍未完全分离（需收敛）**：

| 位置 | 内容 | 影响 | 建议 |
| --- | --- | --- | --- |
| 压铸 `static/index.html`（约 713 行） | 机型库 `var MACHINES = [{brand:'力劲 LK',model:'DCC7200',ton:7200}, …]` 与默认机型 `'力劲 LK DCC3000'` 硬编码在前端 | 机型台账改一处要改前端；与服务端 `app/machines.py` 的选型逻辑可能不一致 | 增加 `GET /api/machines` 接口，前端改为拉取；服务端 machines.py 作为唯一来源 |
| 压铸 `static/dfm_catalog.js`（29 KB） | 字段中文目录作为**前端资产**存在，且服务端 `provider_api` 直接读该文件生成目录 | 数据文件放在前端目录，服务端依赖前端资产 | 目录改为服务端生成/存储（如 `data/` 或数据库），前端通过接口获取 |
| 压铸 `static/index.html` | 表单结构（MODULES schema）与计算触发规则仍在前端；`localStorage` 自动保存草稿 | 表单"结构"未服务端化；草稿本地与服务端项目库并存两份 | 结构如需服务端化，可复用表单平台 schema；草稿统一走 `/api/form-apps/{id}/drafts/{key}` |
| 机加 `static/machining_dfm/legacy_app.js`（175 KB） | 原工具业务规则、i18n 文案、页面渲染逻辑 | 属"逻辑/文案"而非业务数据；但库表结构、字段定义仍由前端决定 | 逐步把库字段定义与校验规则下沉服务端（当前库数据已服务端化） |
| 机加 `static/machining_dfm/host.js` | 登录令牌存放 `sessionStorage` | 令牌本地缓存（非业务数据），可接受 | 如需更强约束可改为 HttpOnly Cookie |

**已确认没有的问题**：机加前端未发现明文口令常量（口令校验走 `POST /api/machining-dfm/auth/login`，服务端 PBKDF2 哈希）；
设备/刀具/夹具/检具库数据来自 `GET /api/machining-dfm/libraries`（不再内嵌）；两服务的静态资源只引用接口，不含项目业务数据。

## 一、压铸 DFM 表单服务（`hpdc`，端口 8001）

- 入口：`app/services/hpdc.py`；启动：`python run_service.py`（工作目录为该服务分支的仓库根）

### 页面与健康

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `GET` | `/` | — |
| `GET` | `/forms` | — |
| `GET` | `/health` | — |

### 压铸计算与传统导出

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `POST` | `/api/calc` | 请求体 JSON |
| `GET` | `/api/demo` | — |
| `POST` | `/api/ppt` | 请求体 JSON |
| `GET` | `/api/ppt-provider/v1/sources` | authorization(header) |
| `POST` | `/api/ppt-provider/v1/sources/{source_id}/normalize` | source_id(path,必填), authorization(header) |
| `GET` | `/api/ppt-provider/v1/sources/{source_id}/projects` | source_id(path,必填), authorization(header) |
| `GET` | `/api/ppt-provider/v1/sources/{source_id}/projects/{project_id}/snapshot` | source_id(path,必填), project_id(path,必填), authorization(header) |

### 表单平台（应用/项目/版本/草稿/目录）

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `GET` | `/api/form-apps` | archived(query) |
| `POST` | `/api/form-apps` | 请求体 JSON |
| `POST` | `/api/form-apps/dfm/import-legacy-project` | — |
| `POST` | `/api/form-apps/discover` | 请求体 JSON |
| `POST` | `/api/form-apps/import-native` | 请求体 JSON |
| `GET` | `/api/form-apps/{app_id}` | app_id(path,必填) |
| `POST` | `/api/form-apps/{app_id}/archive` | app_id(path,必填), archived(query) |
| `GET` | `/api/form-apps/{app_id}/catalog` | app_id(path,必填), project_id(query) |
| `GET` | `/api/form-apps/{app_id}/defaults` | app_id(path,必填) |
| `GET` | `/api/form-apps/{app_id}/drafts/{draft_key}` | app_id(path,必填), draft_key(path,必填) |
| `PUT` | `/api/form-apps/{app_id}/drafts/{draft_key}` | app_id(path,必填), draft_key(path,必填) |
| `GET` | `/api/form-apps/{app_id}/projects` | app_id(path,必填), archived(query) |
| `POST` | `/api/form-apps/{app_id}/projects` | app_id(path,必填) |
| `GET` | `/api/form-apps/{app_id}/projects/{project_id}` | app_id(path,必填), project_id(path,必填), revision(query) |
| `PUT` | `/api/form-apps/{app_id}/projects/{project_id}` | app_id(path,必填), project_id(path,必填) |
| `POST` | `/api/form-apps/{app_id}/projects/{project_id}/archive` | app_id(path,必填), project_id(path,必填), archived(query) |
| `GET` | `/api/form-apps/{app_id}/projects/{project_id}/export` | app_id(path,必填), project_id(path,必填) |
| `GET` | `/api/form-apps/{app_id}/projects/{project_id}/versions` | app_id(path,必填), project_id(path,必填) |
| `GET` | `/api/form-apps/{app_id}/runtime-source` | app_id(path,必填) |

### 项目存档（旧版单项目）

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `GET` | `/api/project/load` | — |
| `POST` | `/api/project/save` | 请求体 JSON |

### 数据源契约（供 PPT 工作台）

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `GET` | `/api/ppt-provider/v1/sources` | authorization(header) |
| `POST` | `/api/ppt-provider/v1/sources/{source_id}/normalize` | source_id(path,必填), authorization(header) |
| `GET` | `/api/ppt-provider/v1/sources/{source_id}/projects` | source_id(path,必填), authorization(header) |
| `GET` | `/api/ppt-provider/v1/sources/{source_id}/projects/{project_id}/snapshot` | source_id(path,必填), project_id(path,必填), authorization(header) |

### 跨服务链接与方案代理

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `GET` | `/api/integration/services` | — |
| `GET` | `/api/integration/workbench-link` | project_id(query), app_id(query) |
| `GET` | `/api/schemes` | — |
| `POST` | `/api/schemes` | — |
| `DELETE` | `/api/schemes/{scheme_path}` | — |
| `GET` | `/api/schemes/{scheme_path}` | — |
| `POST` | `/api/schemes/{scheme_path}` | — |

### 服务日志

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `GET` | `/api/logs/download` | — |
| `GET` | `/api/logs/tail` | lines(query) |

### 真实返回示例（临时数据目录、全新数据库下的抓取结果）

**GET /health** → HTTP 200

```json
{
  "service": "hpdc",
  "contract_version": "1.0"
}
```

**GET /api/demo** → HTTP 200

```json
{
  "f": {
    "projName": "某新能源汽车后纵梁支架",
    "partNo": "TP-HPDC-2026-0087",
    "partName": "Rear Longitudinal Bracket",
    "custName": "XXXX 汽车",
    "version": "A1",
    "dfmDate": "2026-09-01",
    "maker": "工艺工程师",
    "checker": "压铸工艺部经理",
    "approver": "技术总监",
    "company": "TUOPU · 压铸工艺部",
    "machineId": "力劲 LK DCC3000",
    "wFinish": "3.85",
    "wCast": "4.20",
    "wRunner": "2.60",
    "wOverflow": "1.10",
    "wall": "3.0",
    "wallMax": "28.5",
    "moldStructure": "1出1",
    "dimL": "486",
    "dimW": "212",
    "dimH": "138",
    "cav": "1",
    "castP": "80",
    "material": "AlSi10MnMg",
    "annual": "120000",
    "aPart": "820",
    "aRunner": "210",
    "aOver": "130",
    "aSlider": "260",
    "sliderForceAngle": "10",
    "lockSafetyFactor": "1.1",
    "pMax2": "80",
    "exOff": "35",
    "eyOff": "-20",
    "aDyn": "128162",
    "aFix": "72827",
    "alpDyn": "1.5",
    "alpFix": "1.5",
    "ejZone": "4",
    "ejDia": "10"
  },
  "t": {
    "dfmHist": {
      "__count__": 2,
      "__first__": [
        {
          "ver": "A0",
          "date": "2026-08-18",
          "author": "工艺工程师",
          "content": "首次发布 DFM 报告",
          "remark": ""
        },
        {
          "ver": "A1",
          "date": "2026-09-01",
          "author": "工艺工程师",
          "content": "补充挤压销与点冷优化方案",
          "remark": "客户评审后更新"
        }
      ]
    },
    "fileStat": {
      "__count__": 6,
      "__first__": [
        {
          "name": "2D 图纸",
          "code": "",
          "ver": "",
          "state": "待提供",
          "date": "",
          "remark": ""
        },
        {
          "name": "3D 数据",
          "code": "",
          "ver": "",
          "state": "待提供",
          "date": "",
          "remark": ""
        }
      ]
    },
    "mech": {
      "__count__": 4,
      "__first__": [
        {
          "zone": "本体（一般区域）",
          "rm": "≥ 240 MPa",
          "rp": "≥ 140 MPa",
          "elong": "≥ 1.5 %",
          "hb": "",
          "remark": ""
        },
        {
          "zone": "高强区域 / 受力区",
          "rm": "",
          "rp": "",
          "elong": "≥ 2.0 %",
          "hb": "",
          "remark": ""
        }
      ]
    },
    "matList": {
      "__count__": 6,
      "__first__": [
        {
          "no": "1",
          "part": "定模芯",
          "grade": "1.2343",
          "hard": "HRC 46~48",
          "supplier": "",
          "size": "",
          "weight": ""
        },
        {
          "no": "2",
          "part": "动模芯",
          "grade": "1.2343",
          "hard": "HRC 46~48",
          "sup
  …（已截断）
```

**GET /api/form-apps** → HTTP 200

```json
{
  "apps": {
    "__count__": 1,
    "__first__": {
      "id": "dfm",
      "name": "高压压铸 DFM",
      "builtin": true
    }
  }
}
```

**GET /api/form-apps/dfm** → HTTP 200

```json
{
  "id": "dfm",
  "name": "高压压铸 DFM",
  "builtin": true
}
```

**GET /api/form-apps/dfm/catalog** → HTTP 200

```json
{
  "fields": {
    "__count__": 158,
    "__first__": [
      {
        "path": "f.projName",
        "module": "项目信息",
        "group": "封面信息",
        "label": "项目名称"
      },
      {
        "path": "f.partNo",
        "module": "项目信息",
        "group": "封面信息",
        "label": "零件号"
      }
    ]
  },
  "tables": {
    "dfmHist": {
      "module": "项目信息",
      "group": "DFM 履历表（可增行）",
      "label": "dfmHist",
      "columns": {
        "ver": "版本",
        "date": "日期",
        "author": "编制/修订",
        "content": "主要修改内容",
        "remark": "备注"
      }
    },
    "fileStat": {
      "module": "项目信息",
      "group": "文件状态录入（2D / 3D / ESOW …）",
      "label": "fileStat",
      "columns": {
        "name": "文件名称",
        "code": "文件编号",
        "ver": "版本",
        "state": "状态",
        "date": "接收日期",
        "remark": "备注"
      }
    },
    "mech": {
      "module": "产品信息",
      "group": "机械性能要求（各区域）",
      "label": "mech",
      "columns": {
        "zone": "区域/位置",
        "rm": "抗拉强度 Rm",
        "rp": "屈服强度 Rp0.2",
        "elong": "延伸率 A%",
        "hb": "硬度 HB",
        "remark": "备注（取样方式/频次）"
      }
    },
    "matList": {
      "module": "模具结构",
      "group": "材料备料表",
      "label": "matList",
      "columns": {
        "no": "序号",
        "part": "部件",
        "grade": "牌号",
        "hard": "硬度",
        "supplier": "供应商",
        "size": "尺寸",
        "weight": "重量 kg"
      }
    },
    "asm": {
      "module": "模具结构",
      "group": "总装尺寸",
      "label": "asm",
      "columns": {
        "item": "项目",
        "l": "长 L",
        "w": "宽 W",
        "h": "高 H",
        "wt": "重量 kg",
        "remark": "备注"
      }
    },
    "seal": {
      "module": "浇排与工艺系统",
      "group": "密封方案（8 项）",
      "label": "seal",
      "columns": {
        "no": "序号",
        "item": "密封位置",
        "type": "密封形式",
        "spec": "规格",
        "remark": "说明"
      }
    },
    "spr1Table": {
      "module": "质量策划",
      "group": "SPR 点位分析（第 1 页）",
      "label": "spr1Table",
      "columns": {
        "no": "点位",
        "pos": "位置描述",
        "thick": "局部壁厚 mm",
        "risk": "风险评估",
        "act": "措施"
      }
    },
    "tol": {
      "module": "质量策划",
      "group": "图纸公差可行性评估与修改建议",
      "label": "tol",
      "columns": {
        "no": "序号",
        "item": "公差项",
        "req": "图纸要求",
        "cap": "工艺能力",
        "feas": "可行性",
        "prop": "修改建议"
      }
    },
    "issues": {
      "module": "问题清单",
      "group": "开口问题清单（可增行）",
      "label": "issues",
      "columns": {
        "no": "序号",
        "desc": "问题描述",
        "pr
  …（已截断）
```

**GET /api/form-apps/dfm/defaults** → HTTP 200

```json
{
  "f": {
    "projName": "某新能源汽车后纵梁支架",
    "partNo": "TP-HPDC-2026-0087",
    "partName": "Rear Longitudinal Bracket",
    "custName": "XXXX 汽车",
    "version": "A1",
    "dfmDate": "2026-09-01",
    "maker": "工艺工程师",
    "checker": "压铸工艺部经理",
    "approver": "技术总监",
    "company": "TUOPU · 压铸工艺部",
    "machineId": "力劲 LK DCC3000",
    "wFinish": "3.85",
    "wCast": "4.20",
    "wRunner": "2.60",
    "wOverflow": "1.10",
    "wall": "3.0",
    "wallMax": "28.5",
    "moldStructure": "1出1",
    "dimL": "486",
    "dimW": "212",
    "dimH": "138",
    "cav": "1",
    "castP": "80",
    "material": "AlSi10MnMg",
    "annual": "120000",
    "aPart": "820",
    "aRunner": "210",
    "aOver": "130",
    "aSlider": "260",
    "sliderForceAngle": "10",
    "lockSafetyFactor": "1.1",
    "pMax2": "80",
    "exOff": "35",
    "eyOff": "-20",
    "aDyn": "128162",
    "aFix": "72827",
    "alpDyn": "1.5",
    "alpFix": "1.5",
    "ejZone": "4",
    "ejDia": "10"
  },
  "t": {
    "dfmHist": {
      "__count__": 2,
      "__first__": [
        {
          "ver": "A0",
          "date": "2026-08-18",
          "author": "工艺工程师",
          "content": "首次发布 DFM 报告",
          "remark": ""
        },
        {
          "ver": "A1",
          "date": "2026-09-01",
          "author": "工艺工程师",
          "content": "补充挤压销与点冷优化方案",
          "remark": "客户评审后更新"
        }
      ]
    },
    "fileStat": {
      "__count__": 6,
      "__first__": [
        {
          "name": "2D 图纸",
          "code": "",
          "ver": "",
          "state": "待提供",
          "date": "",
          "remark": ""
        },
        {
          "name": "3D 数据",
          "code": "",
          "ver": "",
          "state": "待提供",
          "date": "",
          "remark": ""
        }
      ]
    },
    "mech": {
      "__count__": 4,
      "__first__": [
        {
          "zone": "本体（一般区域）",
          "rm": "≥ 240 MPa",
          "rp": "≥ 140 MPa",
          "elong": "≥ 1.5 %",
          "hb": "",
          "remark": ""
        },
        {
          "zone": "高强区域 / 受力区",
          "rm": "",
          "rp": "",
          "elong": "≥ 2.0 %",
          "hb": "",
          "remark": ""
        }
      ]
    },
    "matList": {
      "__count__": 6,
      "__first__": [
        {
          "no": "1",
          "part": "定模芯",
          "grade": "1.2343",
          "hard": "HRC 46~48",
          "supplier": "",
          "size": "",
          "weight": ""
        },
        {
          "no": "2",
          "part": "动模芯",
          "grade": "1.2343",
          "hard": "HRC 46~48",
          "sup
  …（已截断）
```

**GET /api/form-apps/dfm/projects** → HTTP 200

```json
{
  "projects": []
}
```

**GET /api/integration/services** → HTTP 200

```json
{
  "hpdc": "http://127.0.0.1:8001/forms",
  "machining": "http://127.0.0.1:8002/machining-dfm"
}
```

**GET /api/ppt-provider/v1/sources** → HTTP 200

```json
{
  "contract_version": "1.0",
  "sources": {
    "__count__": 1,
    "__first__": {
      "id": "dfm",
      "name": "压铸 DFM",
      "form_url": "http://127.0.0.1:8031/",
      "contract_version": "1.0"
    }
  }
}
```

**GET /api/ppt-provider/v1/sources/dfm/projects** → HTTP 200

```json
{
  "projects": []
}
```

**GET /api/ppt-provider/v1/sources/dfm/projects/defaults/snapshot** → HTTP 200

```json
{
  "contract_version": "1.0",
  "source_id": "dfm",
  "project_id": "defaults",
  "revision": 0,
  "name": "默认数据",
  "form_url": "http://127.0.0.1:8031/",
  "data": {
    "f": {
      "projName": "某新能源汽车后纵梁支架",
      "partNo": "TP-HPDC-2026-0087",
      "partName": "Rear Longitudinal Bracket",
      "custName": "XXXX 汽车",
      "version": "A1",
      "dfmDate": "2026-09-01",
      "maker": "工艺工程师",
      "checker": "压铸工艺部经理",
      "approver": "技术总监",
      "company": "TUOPU · 压铸工艺部",
      "machineId": "力劲 LK DCC3000",
      "wFinish": "3.85",
      "wCast": "4.20",
      "wRunner": "2.60",
      "wOverflow": "1.10",
      "wall": "3.0",
      "wallMax": "28.5",
      "moldStructure": "1出1",
      "dimL": "486",
      "dimW": "212",
      "dimH": "138",
      "cav": "1",
      "castP": "80",
      "material": "AlSi10MnMg",
      "annual": "120000",
      "aPart": "820",
      "aRunner": "210",
      "aOver": "130",
      "aSlider": "260",
      "sliderForceAngle": "10",
      "lockSafetyFactor": "1.1",
      "pMax2": "80",
      "exOff": "35",
      "eyOff": "-20",
      "aDyn": "128162",
      "aFix": "72827",
      "alpDyn": "1.5",
      "alpFix": "1.5",
      "ejZone": "4",
      "ejDia": "10"
    },
    "t": {
      "dfmHist": {
        "__count__": 2,
        "__first__": [
          {
            "ver": "A0",
            "date": "2026-08-18",
            "author": "工艺工程师",
            "content": "首次发布 DFM 报告",
            "remark": ""
          },
          {
            "ver": "A1",
            "date": "2026-09-01",
            "author": "工艺工程师",
            "content": "补充挤压销与点冷优化方案",
            "remark": "客户评审后更新"
          }
        ]
      },
      "fileStat": {
        "__count__": 6,
        "__first__": [
          {
            "name": "2D 图纸",
            "code": "",
            "ver": "",
            "state": "待提供",
            "date": "",
            "remark": ""
          },
          {
            "name": "3D 数据",
            "code": "",
            "ver": "",
            "state": "待提供",
            "date": "",
            "remark": ""
          }
        ]
      },
      "mech": {
        "__count__": 4,
        "__first__": [
          {
            "zone": "本体（一般区域）",
            "rm": "≥ 240 MPa",
            "rp": "≥ 140 MPa",
            "elong": "≥ 1.5 %",
            "hb": "",
            "remark": ""
          },
          {
            "zone": "高强区域 / 受力区",
            "rm": "",
            "rp": "",
            "elong": "≥ 2.0 %",
            "hb": "",
            "remark": ""
          }
        ]
      },
      "matList
  …（已截断）
```

**GET /api/project/load** → HTTP 200

```json
{
  "f": {},
  "t": {},
  "i": {}
}
```

**GET /api/logs/tail?lines=2** → HTTP 200

```json
{
  "file": "C:\\Users\\26257\\AppData\\Local\\Temp\\dfm_audit\\data_hpdc\\data\\hpdc\\logs\\server.log",
  "lines": {
    "__count__": 2,
    "__first__": [
      "2026-09-17 17:19:17,774 INFO GET /api/ppt-provider/v1/sources/dfm/projects/defaults/snapshot -> 200 …(共119字)",
      "2026-09-17 17:19:17,776 INFO GET /api/project/load -> 200 0ms [61a063a31761]\n"
    ]
  }
}
```

**POST /api/calc** → HTTP 200

```json
{
  "derived": {
    "wPour": "",
    "cwM": "",
    "aTotal2": "",
    "pMax2": ""
  },
  "machine_fill": null,
  "results": {
    "rForce": {
      "html": "<h4>胀型力 / 锁模力校核</h4><div class=\"hint\">请先在 2.1 / 2.2 中填写投影面积与铸造压力。</div>",
      "verdict": ""
    },
    "rTieBar": {
      "html": "<h4>哥林柱受力分布与平衡度 <span class=\"st\"><span class=\"pill p-ok\">平衡度 0.0%</span></span></h4><div class=\"kv\">…(共1587字)",
      "verdict": "🟢 四柱受力平衡度 0.0% ≤ 10%，偏载小，模具与哥林柱受力均匀。"
    },
    "rHold": {
      "html": "<h4>包紧力计算</h4><div class=\"hint\">请填写动/定模侧包紧面积。</div>",
      "verdict": ""
    },
    "rEject": {
      "html": "<h4>顶杆顶出力</h4><div class=\"hint\">请先在 3.1 完成包紧力计算。</div>",
      "verdict": ""
    },
    "rSqueeze": {
      "html": "<h4>挤压销计算</h4><div class=\"hint\">请填写挤压区域尺寸 L / h / w 与挤压销直径。</div>",
      "verdict": ""
    },
    "rSlider": {
      "html": "<h4>滑块油缸缸径</h4><div class=\"hint\">请填写滑块成型包紧面积。</div>",
      "verdict": ""
    },
    "rVacuum": {
      "html": "<h4>抽真空计算</h4><div class=\"hint\">请填写型腔容积、压室尺寸等参数。</div>",
      "verdict": ""
    },
    "rCool": {
      "html": "<h4>冷却水计算</h4><div class=\"hint\">请填写每次浇注金属量（由 2.1 自动带出）。</div>",
      "verdict": ""
    },
    "rInject": {
      "html": "<h4>压射系统参数</h4><div class=\"hint\">请填写冲头直径与内浇口面积。</div>",
      "verdict": ""
    },
    "rPQ2": {
      "html": "<h4>PQ² 工艺窗口</h4><div class=\"hint\">请先在 5.3 填写冲头直径、内浇口面积、型腔体积与填充时间。</div>",
      "verdict": ""
    },
    "rMachine": {
      "html": "<h4>当前机型参数自动填充 <span class=\"st\"><span class=\"pill p-info\">力劲 LK DCC3000</span></span></h4><table cla…(共982字)",
      "verdict": ""
    },
    "rMachList": {
      "html": "<h4>压铸机参数库对照表</h4><table class=\"ro\"><thead><tr><th>品牌</th><th>型号</th><th>吨位 T</th><th>锁模力 kN</th><th…(共3253字)",
      "verdict": ""
    },
    "rGateSpeed": {
      "html": "<table class=\"ro\"><thead><tr><th>铸件壁厚 mm</th><th>内浇口速度 m/s</th><th>说明</th></tr></thead><tbody><tr><t…(共542字)",
      "verdict": ""
    }
  }
}
```

## 二、机加 DFM 表单服务（`machining`，端口 8002）

- 入口：`app/services/machining.py`；启动：`python run_service.py`（工作目录为该服务分支的仓库根）

### 页面与健康

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `GET` | `/` | — |
| `GET` | `/health` | — |
| `GET` | `/machining-dfm` | — |

### 机加表单数据（项目/版本/配置/库）

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `POST` | `/api/machining-dfm/auth/login` | 请求体 JSON |
| `PUT` | `/api/machining-dfm/auth/password` | authorization(header) |
| `GET` | `/api/machining-dfm/bootstrap` | project_id(query) |
| `GET` | `/api/machining-dfm/config` | — |
| `PUT` | `/api/machining-dfm/config` | authorization(header) |
| `GET` | `/api/machining-dfm/defaults` | — |
| `GET` | `/api/machining-dfm/libraries` | — |
| `PUT` | `/api/machining-dfm/libraries` | authorization(header) |
| `GET` | `/api/machining-dfm/projects` | archived(query) |
| `POST` | `/api/machining-dfm/projects` | 请求体 JSON |
| `GET` | `/api/machining-dfm/projects/{project_id}` | project_id(path,必填), revision(query), allow_archived(query) |
| `PUT` | `/api/machining-dfm/projects/{project_id}` | project_id(path,必填) |
| `POST` | `/api/machining-dfm/projects/{project_id}/archive` | project_id(path,必填), archived(query) |
| `GET` | `/api/machining-dfm/projects/{project_id}/versions` | project_id(path,必填) |

### 数据源契约（供 PPT 工作台）

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `GET` | `/api/ppt-provider/v1/sources` | authorization(header) |
| `POST` | `/api/ppt-provider/v1/sources/{source_id}/normalize` | source_id(path,必填), authorization(header) |
| `GET` | `/api/ppt-provider/v1/sources/{source_id}/projects` | source_id(path,必填), authorization(header) |
| `GET` | `/api/ppt-provider/v1/sources/{source_id}/projects/{project_id}/snapshot` | source_id(path,必填), project_id(path,必填), authorization(header) |

### 跨服务链接

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `GET` | `/api/integration/services` | — |
| `GET` | `/api/integration/workbench-link` | project_id(query), app_id(query) |

### 服务日志

| 方法 | 路径 | 参数 |
| --- | --- | --- |
| `GET` | `/api/logs/download` | — |
| `GET` | `/api/logs/tail` | lines(query) |

### 真实返回示例（临时数据目录、全新数据库下的抓取结果）

**GET /health** → HTTP 200

```json
{
  "service": "machining",
  "contract_version": "1.0"
}
```

**GET /api/machining-dfm/bootstrap** → HTTP 200

```json
{
  "project": {
    "id": "f6eaf368e9d04194bf7792280ad99de9",
    "name": "原文件集成 · 蓄电池支架 Battery Bracket",
    "revision": 1,
    "created": "2026-09-17T09:19:18.070388+00:00",
    "updated": "2026-09-17T09:19:18.070388+00:00",
    "archived": false,
    "customer": "赛力斯 SERES",
    "part": "蓄电池支架 Battery Bracket",
    "state": {
      "mdb": {
        "__count__": 27,
        "__first__": [
          {
            "brand": "兄弟(Brother)",
            "model": "S500Z1",
            "rapid": 56,
            "tc": 1.2,
            "spm": 16000,
            "atc": 22,
            "desc": "5轴联动",
            "xyz": "500×400×300",
            "pa": "±0.005",
            "rpa": "±0.003"
          },
          {
            "brand": "兄弟(Brother)",
            "model": "S700Z2N",
            "rapid": 56,
            "tc": 1.5,
            "spm": 10000,
            "atc": 22,
            "desc": "BT30主轴",
            "xyz": "700×400×300",
            "pa": "±0.005",
            "rpa": "±0.003"
          }
        ]
      },
      "tdb": {
        "__count__": 761,
        "__first__": [
          {
            "tp": "D50盘铣刀",
            "d": 50,
            "n": 3000,
            "vf": 3000,
            "cat": "f"
          },
          {
            "tp": "D50盘铣刀(精)",
            "d": 50,
            "n": 2500,
            "vf": 2000,
            "cat": "f"
          }
        ]
      },
      "fdb": {
        "__count__": 177,
        "__first__": [
          {
            "center": "1025减震模具中心",
            "name": "两点式拉杆四轴机加夹具（外购件费用约1万以内）",
            "price": 16000
          },
          {
            "center": "1025减震模具中心",
            "name": "三点式控制臂/H臂/转向节/FORK臂/弹簧臂四轴机加夹具（外购件费用约1~3万）",
            "price": 40500
          }
        ]
      },
      "idb": {
        "__count__": 437,
        "__first__": [
          {
            "type": "成品总成检具",
            "name": "控制器壳体总成检具",
            "drw": "9081000615-01",
            "prdSize": "347*326*86",
            "inspSize": "1000X800X940",
            "price": 9,
            "dc": 0,
            "mc": 0,
            "img": null
          },
          {
            "type": "成品总成检具",
            "name": "控制器壳体总成检具",
            "drw": "9081000615-02",
            "prdSize": "347*326*86",
            "inspSize": "1000X800X940",
            "price": 9,
            "dc": 0,
            "mc": 0,
            "img": null
          }
        ]
      },
      "G": {
        "cust": "赛力斯 SERES",
        "part": "蓄电池支架 Battery Bracket",
        "hpd": 22,
        "sft": 2,
        "dpm": 28,
        "avl": 0.85,
  
  …（已截断）
```

**GET /api/machining-dfm/config** → HTTP 200

```json
{
  "site_title": "机加 DFM 项目工作台",
  "autosave_ms": 1200
}
```

**GET /api/machining-dfm/defaults** → HTTP 200

```json
{
  "mdb": {
    "__count__": 27,
    "__first__": [
      {
        "brand": "兄弟(Brother)",
        "model": "S500Z1",
        "rapid": 56,
        "tc": 1.2,
        "spm": 16000,
        "atc": 22,
        "desc": "5轴联动",
        "xyz": "500×400×300",
        "pa": "±0.005",
        "rpa": "±0.003"
      },
      {
        "brand": "兄弟(Brother)",
        "model": "S700Z2N",
        "rapid": 56,
        "tc": 1.5,
        "spm": 10000,
        "atc": 22,
        "desc": "BT30主轴",
        "xyz": "700×400×300",
        "pa": "±0.005",
        "rpa": "±0.003"
      }
    ]
  },
  "tdb": {
    "__count__": 761,
    "__first__": [
      {
        "tp": "D50盘铣刀",
        "d": 50,
        "n": 3000,
        "vf": 3000,
        "cat": "f"
      },
      {
        "tp": "D50盘铣刀(精)",
        "d": 50,
        "n": 2500,
        "vf": 2000,
        "cat": "f"
      }
    ]
  },
  "fdb": {
    "__count__": 177,
    "__first__": [
      {
        "center": "1025减震模具中心",
        "name": "两点式拉杆四轴机加夹具（外购件费用约1万以内）",
        "price": 16000
      },
      {
        "center": "1025减震模具中心",
        "name": "三点式控制臂/H臂/转向节/FORK臂/弹簧臂四轴机加夹具（外购件费用约1~3万）",
        "price": 40500
      }
    ]
  },
  "idb": {
    "__count__": 437,
    "__first__": [
      {
        "type": "成品总成检具",
        "name": "控制器壳体总成检具",
        "drw": "9081000615-01",
        "prdSize": "347*326*86",
        "inspSize": "1000X800X940",
        "price": 9,
        "dc": 0,
        "mc": 0,
        "img": null
      },
      {
        "type": "成品总成检具",
        "name": "控制器壳体总成检具",
        "drw": "9081000615-02",
        "prdSize": "347*326*86",
        "inspSize": "1000X800X940",
        "price": 9,
        "dc": 0,
        "mc": 0,
        "img": null
      }
    ]
  },
  "G": {
    "cust": "赛力斯 SERES",
    "part": "蓄电池支架 Battery Bracket",
    "hpd": 22,
    "sft": 2,
    "dpm": 28,
    "avl": 0.85,
    "pI": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAxQAAAHrCAIAAADZukwjAAAQAElEQVR4Aey9CXxb1Zn3fyTZ8hJnX0…(共60638字)",
    "pf": null,
    "showFlow": 1,
    "bInspPrice": 0,
    "fInspPrice": 0,
    "msInspPrice": 0,
    "custVer": "",
    "dfmDate": "",
    "prj": "hp",
    "insp": {
      "__count__": 5,
      "__first__": [
        "",
        ""
      ]
    },
    "fixQ": {
      "__count__": 4,
      "__first__": [
        "",
        ""
      ]
    },
    "fixQC": {
      "__count__": 4,
      "__first__": [
        1,
        1
      ]
    },
    "inspQ": {
      "__count__": 5,
      "__first__": [
        1,
        1
      ]
    },
    "lang": "zh",
    "icnX": {
      "__count__": 5,
      "__fi
  …（已截断）
```

**GET /api/machining-dfm/libraries** → HTTP 200

```json
{
  "libraries": {
    "mdb": {
      "__count__": 27,
      "__first__": [
        {
          "brand": "兄弟(Brother)",
          "model": "S500Z1",
          "rapid": 56,
          "tc": 1.2,
          "spm": 16000,
          "atc": 22,
          "desc": "5轴联动",
          "xyz": "500×400×300",
          "pa": "±0.005",
          "rpa": "±0.003"
        },
        {
          "brand": "兄弟(Brother)",
          "model": "S700Z2N",
          "rapid": 56,
          "tc": 1.5,
          "spm": 10000,
          "atc": 22,
          "desc": "BT30主轴",
          "xyz": "700×400×300",
          "pa": "±0.005",
          "rpa": "±0.003"
        }
      ]
    },
    "tdb": {
      "__count__": 761,
      "__first__": [
        {
          "tp": "D50盘铣刀",
          "d": 50,
          "n": 3000,
          "vf": 3000,
          "cat": "f"
        },
        {
          "tp": "D50盘铣刀(精)",
          "d": 50,
          "n": 2500,
          "vf": 2000,
          "cat": "f"
        }
      ]
    },
    "fdb": {
      "__count__": 177,
      "__first__": [
        {
          "center": "1025减震模具中心",
          "name": "两点式拉杆四轴机加夹具（外购件费用约1万以内）",
          "price": 16000
        },
        {
          "center": "1025减震模具中心",
          "name": "三点式控制臂/H臂/转向节/FORK臂/弹簧臂四轴机加夹具（外购件费用约1~3万）",
          "price": 40500
        }
      ]
    },
    "idb": {
      "__count__": 437,
      "__first__": [
        {
          "type": "成品总成检具",
          "name": "控制器壳体总成检具",
          "drw": "9081000615-01",
          "prdSize": "347*326*86",
          "inspSize": "1000X800X940",
          "price": 9,
          "dc": 0,
          "mc": 0,
          "img": null
        },
        {
          "type": "成品总成检具",
          "name": "控制器壳体总成检具",
          "drw": "9081000615-02",
          "prdSize": "347*326*86",
          "inspSize": "1000X800X940",
          "price": 9,
          "dc": 0,
          "mc": 0,
          "img": null
        }
      ]
    },
    "icnX": {
      "__count__": 5,
      "__first__": [
        "毛坯检具",
        "成品机械检具"
      ]
    },
    "fcnX": {
      "__count__": 4,
      "__first__": [
        "1025减震模具中心",
        "1059轻合金模具中心"
      ]
    }
  },
  "counts": {
    "mdb": 27,
    "tdb": 761,
    "fdb": 177,
    "idb": 437
  }
}
```

**GET /api/machining-dfm/projects** → HTTP 200

```json
{
  "projects": {
    "__count__": 1,
    "__first__": {
      "id": "f6eaf368e9d04194bf7792280ad99de9",
      "name": "原文件集成 · 蓄电池支架 Battery Bracket",
      "revision": 1,
      "created": "2026-09-17T09:19:18.070388+00:00",
      "updated": "2026-09-17T09:19:18.070388+00:00",
      "archived": false,
      "customer": "赛力斯 SERES",
      "part": "蓄电池支架 Battery Bracket"
    }
  }
}
```

**GET /api/integration/services** → HTTP 200

```json
{
  "hpdc": "http://127.0.0.1:8001/forms",
  "machining": "http://127.0.0.1:8002/machining-dfm"
}
```

**GET /api/ppt-provider/v1/sources** → HTTP 200

```json
{
  "contract_version": "1.0",
  "sources": {
    "__count__": 1,
    "__first__": {
      "id": "machining-dfm",
      "name": "机加 DFM",
      "form_url": "http://127.0.0.1:8032/machining-dfm",
      "contract_version": "1.0"
    }
  }
}
```

**GET /api/ppt-provider/v1/sources/machining-dfm/projects** → HTTP 200

```json
{
  "projects": {
    "__count__": 1,
    "__first__": {
      "id": "f6eaf368e9d04194bf7792280ad99de9",
      "name": "原文件集成 · 蓄电池支架 Battery Bracket",
      "revision": 1,
      "created": "2026-09-17T09:19:18.070388+00:00",
      "updated": "2026-09-17T09:19:18.070388+00:00",
      "archived": false,
      "customer": "赛力斯 SERES",
      "part": "蓄电池支架 Battery Bracket"
    }
  }
}
```

**GET /api/ppt-provider/v1/sources/machining-dfm/projects/defaults/snapshot** → HTTP 200

```json
{
  "contract_version": "1.0",
  "source_id": "machining-dfm",
  "project_id": "defaults",
  "revision": 0,
  "name": "默认数据",
  "form_url": "http://127.0.0.1:8032/machining-dfm?project_id=defaults",
  "data": {
    "f": {
      "G_cust_90e189f4eb": "赛力斯 SERES",
      "G_part_04c8d7562b": "蓄电池支架 Battery Bracket",
      "G_hpd_b200d50f76": 22,
      "G_sft_66d6fbb2e9": 2,
      "G_dpm_a1166afba3": 28,
      "G_avl_e0dc8426f7": 0.85,
      "G_showFlow_c38bed69b4": 1,
      "G_bInspPrice_438869fbc6": 0,
      "G_fInspPrice_883ca50fbb": 0,
      "G_msInspPrice_3adef8535d": 0,
      "G_custVer_38c5628b3e": "",
      "G_dfmDate_fb220dc5eb": "",
      "G_prj_c1db45a098": "hp",
      "G_insp_1_e838e22e87": "",
      "G_insp_2_8502c46348": "",
      "G_insp_3_e81cd3fd06": "",
      "G_insp_4_c264e0942d": "",
      "G_insp_5_eaa7e30851": "",
      "G_fixQ_1_b067024c2e": "",
      "G_fixQ_2_41dd9fb00e": "",
      "G_fixQ_3_8e00594d50": "",
      "G_fixQ_4_79006a01db": "",
      "G_fixQC_1_7847427fa8": 1,
      "G_fixQC_2_3588ea0b8b": 1,
      "G_fixQC_3_f681ac8d60": 1,
      "G_fixQC_4_9e75c9fbf4": 1,
      "G_inspQ_1_4ffa2254fa": 1,
      "G_inspQ_2_375ffb2a0a": 1,
      "G_inspQ_3_afde1511b7": 1,
      "G_inspQ_4_05eca69a54": 1,
      "G_inspQ_5_b8cdf02f9f": 1,
      "G_lang_4fad49222c": "zh",
      "G_icnX_1_e3892c0638": "毛坯检具",
      "G_icnX_2_3c0eeb5e81": "成品机械检具",
      "G_icnX_3_bf9a171d3a": "成品总成检具",
      "G_icnX_4_bbe488377f": "成品电子检具",
      "G_icnX_5_c0f2926cb0": "测量支架",
      "G_fcnX_1_c168ee723c": "1025减震模具中心",
      "G_fcnX_2_16a92a73b5": "1059轻合金模具中心",
      "G_fcnX_3_f3f8c0fe2a": "1929底盘模具中心"
    },
    "t": {
      "pr_0510eddd78": {
        "__count__": 2,
        "__first__": [
          {
            "nm": "机加工序-OP10",
            "mi": 1,
            "mc": 1,
            "cI": null,
            "nc": {
              "cc": 2,
              "co": 2,
              "mc_": 2,
              "sc": 2,
              "ac": 1,
              "it": 5
            },
            "tl": {
              "__count__": 22,
              "__first__": [
                {
                  "id": "T01",
                  "tp": "D50盘铣刀",
                  "ds": "大面开粗",
                  "d": 50,
                  "n": 3000,
                  "vf": 3000,
                  "ln": 1600,
                  "ps": 1,
                  "cn": 1,
                  "bg": false,
                  "td": 700,
                  "fi": null,
                  "tt": 2,
                  "sd": 1,
                  "_ct": 32.0,
                  "_vc": 471,
                  "_vf": 3000.0,

  …（已截断）
```

**GET /api/logs/tail?lines=2** → HTTP 200

```json
{
  "file": "C:\\Users\\26257\\AppData\\Local\\Temp\\dfm_audit\\data_machining\\data\\machining_dfm\\logs\\server.log",
  "lines": {
    "__count__": 2,
    "__first__": [
      "2026-09-17 17:19:18,258 INFO GET /api/ppt-provider/v1/sources/machining-dfm/projects -> 200 7ms [979…(共111字)",
      "2026-09-17 17:19:18,323 INFO GET /api/ppt-provider/v1/sources/machining-dfm/projects/defaults/snapsh…(共130字)"
    ]
  }
}
```

## 三、复核方法（可自行重跑）

```powershell
git worktree add ..\audit-hpdc hpdc          # 或直接在对应分支的仓库根
cd ..\audit-hpdc
$env:DFM_APP_ROOT = "$env:TEMP\dfm_check"    # 用临时数据目录，避免污染真实数据
python run_service.py --port 8031
# 浏览器打开 http://127.0.0.1:8031/docs 查看交互式 OpenAPI（所有接口与参数）
```

- 交互式接口文档：`http://127.0.0.1:<端口>/docs`（Swagger UI）与 `/openapi.json`
- 机加表单页：`http://127.0.0.1:8002/machining-dfm`；压铸表单页/表单中心：`http://127.0.0.1:8001/` 与 `/forms`
- 数据源契约（工作台视角）：`GET /api/ppt-provider/v1/sources`、`…/projects/{id}/snapshot`
