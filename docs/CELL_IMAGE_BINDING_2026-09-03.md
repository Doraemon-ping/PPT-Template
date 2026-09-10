# 单元格图片绑定修复

> 本文记录 2026-09-03 的专项修复；当前整体能力与后续变更见 [项目更新记录](CHANGELOG.md)。

## 原因与修复

- 用户四页方案最后一页 `表格 8 / shape_id=11 / row=3,column=1` 绑定了 `i.productRunnerFrontImg[0]`，但旧编辑台存成 `table_cell` 文本类型。该位置实际为合并单元格的延续区域，无 `a:t`，因此出现 `slide88.xml: shape has no text node to bind`。slide88 是重建包的内部部件编号，并非用户报告第 88 页。
- 编辑台现在提供「在所选单元格区域放入图片」；点击图片字段时自动采用 `image_region` 并保留 row/column、默认 contain，不再降级为 table_cell。
- 生成时兼容历史 `table_cell + i.*` 或实际图片 data URI，运行时转换，不改写已保存方案；缺图保留模板，坏图明确报错。
- `VisualBindingFiller.fill_table_region` 根据表格列宽、行高定位所选网格区域，生成独立图片，与表格并列放在同一父容器中；保留边线、表格、列宽、合并关系、其他对象。不合并的目标格清空原文字；合并格保留锚点文字，不扩展替换整个合并区域。既有较高层级的其他对象仍可能遮挡图片，应通过最终预览确认位置。

## 同次定位的跨模板资源引用问题

旧 `SlideImporter` 按 XML 内容哈希跨模板复用布局/母版。相同 XML 内的 rId 在不同源文件可以指向不同依赖，导致多个外部模板合并后无法被 PowerPoint 打开。现在有依赖的资源按源包及部件路径缓存，只有不带关系的媒体按内容去重。新增测试验证相同布局/母版 XML、不同主题内容的两个模板各自保持正确引用链。

## 验证

- `tests/test_cell_image_binding.py`：新旧绑定兼容、缺图、坏图、越界、用户模板真实合并格和原文字保留。
- `tests/test_slide_import_graph.py`：跨源同 XML 不同依赖隔离。
- 前端模型测试新增图片字段类型自动选择（含尚未上传图片）。
- `python -m scripts.check_cell_image_binding --all`：只读当前 `TP-DFM模板-v1.0` 方案，以示例数据和示例 LOGO 代替图片测试输入，生成四页并调用 PowerPoint 导出；不替换用户实际图片、不保存方案。
- 测试输出在 `output/cell-image-check/`，是排障样本，不是正式交付报告。
