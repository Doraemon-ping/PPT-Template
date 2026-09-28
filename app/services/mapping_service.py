from typing import Any
from urllib.parse import urljoin

from ..core.exceptions import ApiConfigurationError
from ..models import FieldMapping
from .response_parser import ResponseParser


def _set_nested(target: dict[str, Any], path: str, value: Any) -> None:
    current = target
    parts = path.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


class MappingService:
    def __init__(self, parser: ResponseParser | None = None):
        self.parser = parser or ResponseParser()

    def map(self, payload: Any, mappings: list[FieldMapping]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for mapping in mappings:
            matches = self.parser.extract(payload, mapping.source_path)
            # A wildcard path represents a collection even when the current
            # response happens to contain only one item. This keeps Dataset
            # field types stable across executions.
            keeps_collection = "[*]" in mapping.source_path or "[?" in mapping.source_path
            value: Any = None if not matches else matches if keeps_collection or len(matches) > 1 else matches[0]
            value = self._transform(value, mapping)
            _set_nested(result, mapping.target_field, value)
        return result

    def _transform(self, value: Any, mapping: FieldMapping) -> Any:
        if mapping.transform_type == "none":
            base_url = mapping.transform_config.get("url_base")
            if isinstance(base_url, str) and base_url:
                return self._resolve_urls(value, base_url)
            return value
        if mapping.transform_type != "enum":
            raise ApiConfigurationError(f"不支持的转换类型：{mapping.transform_type}")
        enum_map = mapping.transform_config.get("mapping", {})
        if not isinstance(enum_map, dict):
            raise ApiConfigurationError("enum transform_config.mapping 必须是对象")

        def convert(item: Any) -> Any:
            key = str(item)
            if key in enum_map:
                return enum_map[key]
            if "default" in mapping.transform_config:
                return mapping.transform_config["default"]
            return item

        return [convert(item) for item in value] if isinstance(value, list) else convert(value)

    @staticmethod
    def _is_url_field(key: Any) -> bool:
        normalized = str(key).casefold().replace("-", "_")
        return (
            normalized in {"url", "uri", "src", "href", "image", "img", "photo", "icon"}
            or normalized.endswith(("_url", "_uri", "_src", "_href", "_image", "_img", "_photo", "_icon"))
        )

    def _resolve_urls(self, value: Any, base_url: str, *, url_field: bool = True) -> Any:
        if isinstance(value, list):
            return [self._resolve_urls(item, base_url, url_field=url_field) for item in value]
        if isinstance(value, dict):
            # Table mappings can carry ``url_base`` so image columns work in
            # the PPT renderer. Resolve only URL-shaped leaves; names, types
            # and foreign-key values must remain unchanged.
            return {
                key: self._resolve_urls(
                    item,
                    base_url,
                    url_field=self._is_url_field(key) if not isinstance(item, (dict, list)) else False,
                )
                for key, item in value.items()
            }
        if url_field and isinstance(value, str) and value and not value.startswith(("http://", "https://", "data:", "//")):
            return urljoin(base_url.rstrip("/") + "/", value)
        return value
