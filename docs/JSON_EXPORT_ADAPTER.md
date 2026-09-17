# 通用 JSON 原样表单适配器

适用于自身已经能够导出、导入 JSON 的 HTML 工具。平台把完整 JSON 作为项目事实源保存，字段、表格和图片目录由数据快照自动生成，不需要维护逐字段映射。

## HTML 侧契约

在原 HTML 中暴露一个全局对象：

```html
<script>
window.__DFM_BRIDGE__ = {
  version: '2026.09',

  // 必须返回对象、数组、JSON 字符串或 Promise。
  exportData() {
    return buildExportObject();
  },

  // 接收上次 exportData() 返回的完整数据，用于打开项目和恢复历史版本。
  importData(data) {
    applyImportedData(data);
    renderPage();
  },

  // 可选：只改善字段目录显示，不改变原始 JSON。
  labels: {
    project: '项目信息',
    'project.customer': '客户名称',
    processes: '工序'
  },

  // 可选：大 JSON 只投影业务需要的分支。被排除的数据仍保留在 raw 中。
  rules: {
    include: ['project', 'processes', 'issues'],
    exclude: ['audit.logs', 'cache']
  }
};
</script>
```

如果页面已经存在全局 `exportData()` 和 `importData()`、`applyData()` 或 `loadData()`，平台也会自动识别。推荐仍显式提供 `__DFM_BRIDGE__`，接口意图更明确，后期修改页面内部函数名时不会影响平台。

如果旧的 `exportData()` 只触发文件下载而没有返回值，需要把构建出的对象 `return` 出来，或者在 `__DFM_BRIDGE__.exportData()` 中返回同一对象。平台不会读取用户下载目录中的文件。

## 自动投影规则

- 对象中的字符串、数字、布尔值和 `null` 自动成为文字字段。
- `data:image/...` 自动成为图片字段；其他 data URL 只保留在原始数据中。
- 对象数组自动成为一张明细表；增删或调整行顺序不会改变绑定路径。
- 基础值数组自动成为只有 `value` 列的明细表。
- 嵌套对象数组会以 `parent_index` 记录所属父行。
- 稳定参数标识根据 JSON 路径生成；只要路径不变，数据内容和行数变化不会破坏已有 PPT 绑定。

服务端每个项目版本只持久化一次完整 `runtime.raw`。`f/t/i` 投影在读取项目、生成字段目录和生成 PPT 时重建，避免三万行 JSON 在数据库中重复存储。

## 更新约定

后续工具版本可以自由新增 JSON 字段；平台下次保存项目时会自动出现在字段目录。删除或重命名已绑定路径属于破坏性变更，应通过以下任一方式兼容：

- 导出时继续保留旧路径一段过渡期；
- 在工具导出函数中把新结构转换为稳定的对接结构；
- 提升 `version`，并在 `importData()` 中迁移旧快照。

JSON 顶层必须是对象或数组，单项目最大 80 MB；自动投影最多遍历 150,000 个节点、24 层。超出时用 `rules.include/exclude` 缩小投影范围，原始数据仍完整保存。
