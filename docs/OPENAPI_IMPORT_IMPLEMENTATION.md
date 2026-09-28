# OpenAPI 数据来源导入：实现方案

## 目标

把一份 OpenAPI 3.0/3.1 JSON 或 YAML 文档转换成 PPT 工作台可编辑的 API 数据来源草稿。用户只需要选择要用于报告的接口、填写凭据并确认字段用途，不再逐项录入连接、路径、参数和 JSONPath。

## 首个版本范围

- 支持粘贴文档内容、上传 JSON/YAML 文件和填写文档 URL。Postman Collection 在后续版本通过同一导入抽屉接入。
- 解析 OpenAPI `servers`、`paths`、`operationId`、`summary`、参数、请求体、响应 Schema 和安全方案。
- 仅导入工作台当前可执行的 `GET`、`POST` 操作；其他方法在预览中说明未导入。
- 支持 `http bearer`、`http basic`、`apiKey` 和无认证；文档只描述认证位置，密钥由用户在确认页填写，绝不从文档或预览回传密钥。
- 将响应 Schema 展开为 JSONPath 字段草稿：标量为文字字段，对象数组为表格字段，`format: uri`、`format: binary` 及常见图片字段名为图片字段。
- 复用现有字段推荐规则，预填项目名称、问题列表、问题图片等 PPT 目标字段；任何自动推荐均允许编辑或删除。

## 用户流程

1. 在“新增数据来源”中选择“从 API 文档导入”。
2. 输入 OpenAPI 文档 URL、粘贴内容或选择本地 JSON/YAML 文件，点击“解析文档”。
3. 在预览中选择一个或多个 `GET`/`POST` 接口，查看系统识别的参数、认证方式和响应字段。
4. 填写数据来源名称及认证凭据，确认后一次性导入。
5. 工作台创建连接、接口、参数和字段映射；用户仍可在高级配置中修改，并可用现有“读取可选参数”通过真实响应补全字段。

## 后端设计

### 解析服务

新增 `app/services/openapi_importer.py`：

- `parse_openapi_document` 解析 JSON/YAML 并验证 OpenAPI 版本。
- `preview_openapi_import` 生成无副作用的连接和操作草稿。
- 处理本地 `#/components/...` 引用、`allOf`、`oneOf`/`anyOf` 的首个可用 Schema、数组和常用 example/default。
- 文档 URL 的下载限制为 HTTP/HTTPS、2 MB，并使用短超时；解析错误以面向用户的中文信息返回。

### API

- `POST /api/connectors/imports/openapi/preview`：接收 `spec_text` 或 `spec_url`，返回连接建议、支持的操作和字段草稿，不写数据库。
- `POST /api/connectors/imports/openapi/commit`：接收预览中经用户确认的操作、连接名称和认证配置，批量创建配置。

提交接口不重新信任前端传来的 Schema；只接收已经展开的、受 Pydantic 校验的连接、操作、参数和映射草稿。

### 数据一致性

新增 `ConnectorDatabase.import_openapi`，使用一个 SQLite 事务完成连接、接口、参数、映射和工作空间关联。任意一项失败时回滚，避免原普通向导中逐项保存造成的半成品配置。

## 前端设计

新增独立的“导入 API 文档”抽屉：

- 输入页：文档 URL、粘贴内容或文件上传。
- 预览页：接口多选、参数数量、字段数量和响应状态码；不支持操作清晰标识。
- 确认页：来源名称、认证凭据和导入摘要。

导入后刷新当前工作空间的数据来源列表，并跳转到高级配置，以便继续验证真实接口与调整字段。

## 验证

- 单元测试覆盖 JSON/YAML、`$ref`、安全方案、数组字段、参数默认值及不支持方法过滤。
- API 测试确认预览不写库，确认导入会创建完整配置，参数或映射冲突时整个事务回滚。
- 运行既有连接器测试，确保原有普通向导和字段发现不受影响。
