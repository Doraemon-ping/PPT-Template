# -*- coding: utf-8 -*-
"""Resolve schema source paths from Pydantic models or plain dictionaries."""

from collections.abc import Mapping
from typing import Any

from .exceptions import SlideSchemaDataMissingError
from .schema import SchemaField


_MISSING = object()
_NO_DEFAULT = object()


class SchemaValueResolver:
    def resolve_field(self, data: Any, field_name: str, field: SchemaField) -> Any:
        value = self.resolve(data, field.source, default=_MISSING)
        if value is _MISSING:
            if field.required:
                raise SlideSchemaDataMissingError(field_name, field.source)
            return None
        return value

    def resolve(self, data: Any, path: str, *, default: Any = _NO_DEFAULT) -> Any:
        current = data
        for segment in path.split("."):
            if isinstance(current, Mapping):
                current = current.get(segment, _MISSING)
            elif isinstance(current, (list, tuple)) and segment.isdigit():
                index = int(segment)
                current = current[index] if index < len(current) else _MISSING
            else:
                current = getattr(current, segment, _MISSING)
            if current is _MISSING:
                if default is _NO_DEFAULT:
                    raise SlideSchemaDataMissingError(path, path)
                return default
        return current
