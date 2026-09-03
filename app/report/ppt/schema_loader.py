# -*- coding: utf-8 -*-
"""Load, validate, and match declarative YAML slide schemas."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping

from ...dfm.models import SlidePlan, SlideType
from .exceptions import (
    SlideSchemaLoadError,
    SlideSchemaMissingError,
    SlideSchemaNotFoundError,
    SlideSchemaValidationError,
)
from .schema import SlideSchema

try:  # Production dependency; JSON-compatible YAML remains testable offline.
    import yaml
except ImportError:  # pragma: no cover - availability depends on runtime
    yaml = None


@dataclass(frozen=True)
class SlideSchemaRegistry:
    schemas: Mapping[SlideType, SlideSchema]
    template_version: str

    def get(self, slide_type: SlideType) -> SlideSchema:
        try:
            return self.schemas[slide_type]
        except KeyError as exc:
            raise SlideSchemaMissingError(slide_type.value) from exc

    def get_for_plan(self, plan: SlidePlan) -> SlideSchema:
        schema = self.get(plan.slide_type)
        if schema.template.strip().upper() != plan.template_key.strip().upper():
            raise SlideSchemaValidationError(
                plan.slide_type.value,
                f"plan template={plan.template_key} does not match schema template={schema.template}",
            )
        return schema


class SlideSchemaLoader:
    def load_file(self, path) -> SlideSchema:
        schema_path = Path(path)
        if not schema_path.is_file():
            raise SlideSchemaNotFoundError(schema_path)
        try:
            raw = schema_path.read_text(encoding="utf-8")
            data = self._parse(raw, schema_path)
        except SlideSchemaLoadError:
            raise
        except Exception as exc:
            raise SlideSchemaLoadError(schema_path, str(exc)) from exc
        return self._build_schema(data, str(schema_path))

    def load_directory(
        self,
        path,
        *,
        required_types: Iterable[SlideType] = (),
    ) -> SlideSchemaRegistry:
        directory = Path(path)
        if not directory.is_dir():
            raise SlideSchemaNotFoundError(directory)
        files = sorted((*directory.glob("*.yaml"), *directory.glob("*.yml")))
        if not files:
            raise SlideSchemaLoadError(directory, "no .yaml or .yml files found")

        schemas: Dict[SlideType, SlideSchema] = {}
        for schema_path in files:
            schema = self.load_file(schema_path)
            if schema.slide_type in schemas:
                raise SlideSchemaValidationError(
                    str(schema_path),
                    f"duplicate slide_type={schema.slide_type.value}",
                )
            schemas[schema.slide_type] = schema

        versions = {schema.template_version for schema in schemas.values()}
        if len(versions) != 1:
            raise SlideSchemaValidationError(str(directory), "template_version must be consistent")
        for slide_type in required_types:
            if slide_type not in schemas:
                raise SlideSchemaMissingError(slide_type.value)
        return SlideSchemaRegistry(schemas=schemas, template_version=versions.pop())

    @staticmethod
    def _parse(raw: str, source: Path):
        if yaml is not None:
            return yaml.safe_load(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SlideSchemaLoadError(
                source,
                "PyYAML is not installed and schema is not JSON-compatible YAML",
            ) from exc

    @staticmethod
    def _build_schema(data, source: str) -> SlideSchema:
        if not isinstance(data, dict):
            raise SlideSchemaValidationError(source, "top-level value must be a mapping")
        try:
            if hasattr(SlideSchema, "model_validate"):
                schema = SlideSchema.model_validate(data)
            else:  # Pydantic v1 compatibility
                schema = SlideSchema.parse_obj(data)
        except Exception as exc:
            raise SlideSchemaValidationError(source, str(exc)) from exc

        if not schema.fields:
            raise SlideSchemaValidationError(source, "fields must not be empty")
        shapes = [field.shape for field in schema.fields.values()]
        duplicates = sorted({name for name in shapes if shapes.count(name) > 1})
        if duplicates:
            raise SlideSchemaValidationError(
                source,
                "duplicate shape bindings: " + ", ".join(duplicates),
            )
        return schema
