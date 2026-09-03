# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from app.dfm.models import DFMIssue, DFMProject, DFMReport, DFMSummary, SlideType
from app.report.ppt import SchemaValueResolver, SlidePlanner, SlideSchemaLoader
from app.report.ppt.exceptions import (
    SlideSchemaDataMissingError,
    SlideSchemaMissingError,
    SlideSchemaValidationError,
)


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "app" / "report" / "ppt" / "schemas"


class SlideSchemaTests(unittest.TestCase):
    def test_loads_all_builtin_schemas_with_one_template_version(self):
        registry = SlideSchemaLoader().load_directory(
            SCHEMA_DIR,
            required_types=list(SlideType),
        )

        self.assertEqual("1", registry.template_version)
        self.assertEqual(set(SlideType), set(registry.schemas))
        self.assertEqual("ISSUE_TITLE", registry.get(SlideType.ISSUE_STANDARD).fields["title"].shape)

    def test_every_default_slide_plan_matches_a_schema_template(self):
        report = DFMReport(
            project=DFMProject(part_number="P-001"),
            summary=DFMSummary(total=2),
            issues=[
                DFMIssue(id="1"),
                DFMIssue(id="2", images={"before": "a.png", "after": "b.png"}),
            ],
        )
        registry = SlideSchemaLoader().load_directory(SCHEMA_DIR)

        schemas = [registry.get_for_plan(plan) for plan in SlidePlanner().plan(report)]

        self.assertEqual(5, len(schemas))
        self.assertEqual("ISSUE_STANDARD", schemas[2].template)
        self.assertEqual("ISSUE_COMPARE", schemas[3].template)

    def test_value_resolver_supports_models_dicts_and_enum_attributes(self):
        issue = DFMIssue(
            id="DFM-001",
            severity="Critical",
            images={"main": "image.png"},
        )
        schema = SlideSchemaLoader().load_file(SCHEMA_DIR / "issue_standard.yaml")
        resolver = SchemaValueResolver()

        self.assertEqual("Critical", resolver.resolve_field(issue, "severity", schema.fields["severity"]))
        self.assertEqual("image.png", resolver.resolve_field(issue, "image", schema.fields["image"]))
        self.assertEqual("value", resolver.resolve({"a": {"b": "value"}}, "a.b"))

    def test_optional_missing_value_resolves_to_none(self):
        issue = DFMIssue(id="DFM-001")
        field = SlideSchemaLoader().load_file(SCHEMA_DIR / "issue_standard.yaml").fields["image"]
        self.assertIsNone(SchemaValueResolver().resolve_field(issue, "image", field))

    def test_required_missing_value_has_field_and_source_context(self):
        schema = SlideSchemaLoader().load_file(SCHEMA_DIR / "issue_compare.yaml")
        with self.assertRaisesRegex(
            SlideSchemaDataMissingError,
            "field=before; source=images.before",
        ):
            SchemaValueResolver().resolve_field(DFMIssue(id="1"), "before", schema.fields["before"])

    def test_duplicate_shape_binding_is_rejected(self):
        data = {
            "schema_version": 1,
            "template_version": "1",
            "slide_type": "cover",
            "template": "COVER",
            "fields": {
                "a": {"source": "a", "shape": "SAME", "renderer": "text"},
                "b": {"source": "b", "shape": "SAME", "renderer": "text"},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.yaml"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(SlideSchemaValidationError, "duplicate shape bindings"):
                SlideSchemaLoader().load_file(path)

    def test_registry_rejects_mixed_template_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, slide_type, version in (("a", "cover", "1"), ("b", "summary", "2")):
                data = {
                    "schema_version": 1,
                    "template_version": version,
                    "slide_type": slide_type,
                    "template": slide_type.upper(),
                    "fields": {"x": {"source": "x", "shape": f"X_{name}", "renderer": "text"}},
                }
                (Path(directory) / f"{name}.yaml").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(SlideSchemaValidationError, "template_version must be consistent"):
                SlideSchemaLoader().load_directory(directory)

    def test_missing_required_schema_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            data = {
                "schema_version": 1,
                "template_version": "1",
                "slide_type": "cover",
                "template": "COVER",
                "fields": {"x": {"source": "x", "shape": "X", "renderer": "text"}},
            }
            (Path(directory) / "cover.yaml").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SlideSchemaMissingError):
                SlideSchemaLoader().load_directory(directory, required_types=[SlideType.SUMMARY])


if __name__ == "__main__":
    unittest.main()
