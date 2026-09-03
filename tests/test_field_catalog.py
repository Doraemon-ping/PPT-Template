# -*- coding: utf-8 -*-
"""验证字段中文目录（static/dfm_catalog.js）由表单 Schema 生成且覆盖完整。"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "static" / "dfm_catalog.js"
INDEX = ROOT / "static" / "index.html"


def load_catalog() -> dict:
    text = CATALOG.read_text(encoding="utf-8")
    start, end = text.index("{"), text.rindex("}")
    return json.loads(text[start:end + 1])


def schema_field_keys() -> set:
    """从 index.html MODULES 区域提取字面量字段描述符（排除表格列 cols 与 FLOW_ITEMS 行）。"""
    import re

    html = INDEX.read_text(encoding="utf-8")
    start = html.index("var MODULES = [")
    marker = html.index("状态与渲染引擎", start)
    region = html[: html.rindex("/* ===", marker)]
    keys = set()
    for descriptor in re.findall(r"\{k:'([A-Za-z0-9_]+)',\s*t:'[^']*'(.*?)\}", region):
        key, rest = descriptor
        # 表格列带 w:、模流项行带 tip:，均非表单字段描述符
        if ", w:" in rest or ", tip:" in rest:
            continue
        keys.add(key)
    return keys


class FieldCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_field_hierarchy_example(self):
        entry = next(x for x in self.catalog["fields"] if x["path"] == "f.partNo")
        self.assertEqual("项目信息", entry["module"])
        self.assertEqual("封面信息", entry["group"])
        self.assertEqual("零件号", entry["label"])
        self.assertEqual("项目信息.封面信息.零件号", ".".join(
            (entry["module"], entry["group"], entry["label"])))

    def test_example_fields_translated(self):
        examples = {
            "f.projName": ("项目信息", "封面信息", "项目名称"),
            "f.wFinish": ("产品信息", "产品信息总表", "成品重量"),
            "f.leakReq": ("产品信息", "产品信息总表", "气密要求"),
        }
        for path, (module, group, label) in examples.items():
            entry = next(x for x in self.catalog["fields"] if x["path"] == path)
            self.assertEqual((module, group, label), (entry["module"], entry["group"], entry["label"]))

    def test_catalog_scale(self):
        self.assertGreaterEqual(len(self.catalog["fields"]), 140)
        self.assertGreaterEqual(len(self.catalog["tables"]), 8)
        self.assertGreaterEqual(len(self.catalog["images"]), 20)
        self.assertIn("rForce", self.catalog["results"])

    def test_table_columns_labeled(self):
        issues = self.catalog["tables"]["issues"]
        self.assertEqual("问题描述", issues["columns"]["desc"])
        self.assertEqual("修改方案 / 建议", issues["columns"]["prop"])
        self.assertEqual("状态", issues["columns"]["st"])

    def test_catalog_covers_schema_keys(self):
        literal_keys = schema_field_keys()
        table_keys = set(self.catalog["tables"])
        image_keys = set(self.catalog["images"])
        field_keys = {x["path"][2:] for x in self.catalog["fields"]}
        missing = literal_keys - field_keys - table_keys - image_keys
        self.assertEqual(set(), missing, f"Schema 字段未进入目录: {sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
