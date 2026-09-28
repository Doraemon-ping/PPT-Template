"""Turn API contracts into editable PPT workbench connector drafts."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml

from ..core.exceptions import ApiConfigurationError, ApiConnectionError
from .connector_ux import discover_fields

MAX_SPEC_CHARS = 2_000_000
SUPPORTED_METHODS = {"get": "GET", "post": "POST"}


def _load_document(text: str) -> dict[str, Any]:
    if len(text) > MAX_SPEC_CHARS:
        raise ApiConfigurationError("API 文档超过 2 MB，无法导入")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ApiConfigurationError("API 文档不是有效的 JSON 或 YAML") from exc
    if not isinstance(data, dict):
        raise ApiConfigurationError("API 文档根节点必须是对象")
    version = str(data.get("openapi") or "")
    if not version.startswith("3."):
        raise ApiConfigurationError("目前只支持 OpenAPI 3.0/3.1 文档")
    if not isinstance(data.get("paths"), dict):
        raise ApiConfigurationError("OpenAPI 文档缺少 paths")
    return data


async def load_openapi_document(*, spec_text: str | None, spec_url: str | None) -> tuple[dict[str, Any], str]:
    if bool(spec_text and spec_text.strip()) == bool(spec_url and spec_url.strip()):
        raise ApiConfigurationError("请填写 API 文档 URL 或粘贴文档内容，两者选一个")
    if spec_url and spec_url.strip():
        parsed = urlsplit(spec_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ApiConfigurationError("API 文档 URL 必须是有效的 HTTP/HTTPS 地址")
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, trust_env=False) as client:
                response = await client.get(spec_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ApiConnectionError("无法下载 API 文档") from exc
        text = response.text
    else:
        text = (spec_text or "").strip()
    return _load_document(text), hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve(value: Any, document: dict[str, Any], seen: set[str] | None = None) -> Any:
    if not isinstance(value, dict) or "$ref" not in value:
        return value
    ref = value["$ref"]
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return value
    seen = seen or set()
    if ref in seen:
        return {}
    current: Any = document
    for part in ref[2:].split("/"):
        if not isinstance(current, dict):
            return {}
        current = current.get(part.replace("~1", "/").replace("~0", "~"))
    return _resolve(deepcopy(current), document, seen | {ref})


def _merged_schema(schema: Any, document: dict[str, Any]) -> dict[str, Any]:
    result = _resolve(schema, document)
    if not isinstance(result, dict):
        return {}
    for key in ("oneOf", "anyOf"):
        variants = result.get(key)
        if isinstance(variants, list) and variants:
            return _merged_schema(variants[0], document)
    if isinstance(result.get("allOf"), list):
        merged = {key: value for key, value in result.items() if key != "allOf"}
        properties: dict[str, Any] = dict(merged.get("properties") or {})
        for part in result["allOf"]:
            candidate = _merged_schema(part, document)
            properties.update(candidate.get("properties") or {})
            for key, value in candidate.items():
                if key not in {"properties", "required"}:
                    merged.setdefault(key, value)
        merged["properties"] = properties
        return merged
    return result


def _schema_sample(schema: Any, document: dict[str, Any], *, depth: int = 0) -> Any:
    if depth > 8:
        return ""
    schema = _merged_schema(schema, document)
    for key in ("example", "default"):
        if key in schema:
            return deepcopy(schema[key])
    examples = schema.get("examples")
    if isinstance(examples, dict) and examples:
        example = next(iter(examples.values()))
        if isinstance(example, dict) and "value" in example:
            return deepcopy(example["value"])
    if schema.get("enum"):
        return deepcopy(schema["enum"][0])
    kind = schema.get("type")
    if kind == "array" or "items" in schema:
        return [_schema_sample(schema.get("items", {}), document, depth=depth + 1)]
    properties = schema.get("properties")
    if kind == "object" or isinstance(properties, dict):
        return {str(key): _schema_sample(value, document, depth=depth + 1) for key, value in (properties or {}).items()}
    if kind in {"integer", "number"}:
        return 0
    if kind == "boolean":
        return False
    if schema.get("format") in {"uri", "url"}:
        return "https://example.invalid/value"
    return ""


def _base_url(document: dict[str, Any]) -> str:
    servers = document.get("servers")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], dict):
        raise ApiConfigurationError("OpenAPI 文档缺少 servers[0].url，请在高级配置中补充服务地址")
    value = str(servers[0].get("url") or "")
    variables = servers[0].get("variables") or {}
    for key, config in variables.items():
        default = config.get("default", "") if isinstance(config, dict) else ""
        value = value.replace("{" + str(key) + "}", str(default))
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ApiConfigurationError("servers[0].url 必须是有效的 HTTP/HTTPS 地址")
    return value.rstrip("/")


def _auth_options(document: dict[str, Any]) -> list[dict[str, Any]]:
    schemes = (document.get("components") or {}).get("securitySchemes") or {}
    declared = document.get("security") or []
    names: list[str] = []
    for item in declared:
        if isinstance(item, dict):
            names.extend(item.keys())
    if not names:
        names = list(schemes.keys())
    options = [] if names else [{"auth_type": "none", "label": "无认证", "config": {}}]
    for name in dict.fromkeys(names):
        scheme = _resolve(schemes.get(name), document)
        if not isinstance(scheme, dict):
            continue
        if scheme.get("type") == "apiKey":
            location = "query" if scheme.get("in") == "query" else "header"
            options.append({"auth_type": "api_key", "label": str(name), "config": {"name": scheme.get("name") or "X-API-Key", "location": location}})
        elif scheme.get("type") == "http" and scheme.get("scheme") == "bearer":
            options.append({"auth_type": "bearer", "label": str(name), "config": {}})
        elif scheme.get("type") == "http" and scheme.get("scheme") == "basic":
            options.append({"auth_type": "basic", "label": str(name), "config": {}})
    return options or [{"auth_type": "none", "label": "无认证", "config": {}}]


def _operation_parameters(path_item: dict[str, Any], operation: dict[str, Any], document: dict[str, Any]) -> list[dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*(path_item.get("parameters") or []), *(operation.get("parameters") or [])]:
        param = _resolve(raw, document)
        if not isinstance(param, dict) or param.get("in") not in {"path", "query", "header"}:
            continue
        name, location = str(param.get("name") or ""), str(param.get("in"))
        if not name:
            continue
        schema = _merged_schema(param.get("schema", {}), document)
        value = param.get("example", schema.get("default", schema.get("example")))
        source_type = "fixed" if value is not None else "input"
        indexed[(name, location)] = {
            "name": name, "location": location, "source_type": source_type,
            "source_key": None if source_type == "fixed" else name,
            "default_value": value,
            "required": bool(param.get("required")),
            "description": str(param.get("description") or ""),
        }
    body = operation.get("requestBody")
    if isinstance(body, dict):
        content = _resolve(body, document).get("content") or {}
        media = content.get("application/json") if isinstance(content, dict) else None
        if isinstance(media, dict):
            sample = _schema_sample(media.get("schema", {}), document)
            if isinstance(sample, dict):
                for name, value in sample.items():
                    indexed[(name, "body")] = {
                        "name": name, "location": "body", "source_type": "fixed",
                        "source_key": None, "default_value": value, "required": False, "description": "请求体字段",
                    }
    return list(indexed.values())


def _response_schema(operation: dict[str, Any], document: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    responses = operation.get("responses") or {}
    for status, response in responses.items():
        if not str(status).startswith("2"):
            continue
        resolved = _resolve(response, document)
        content = resolved.get("content") if isinstance(resolved, dict) else None
        if not isinstance(content, dict):
            continue
        media = content.get("application/json") or next((value for key, value in content.items() if "json" in str(key)), None)
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            return str(status), media["schema"]
    return None, {}


def _target_name(field: dict[str, Any], used: set[str], index: int) -> str:
    recommended = field.get("recommended_target")
    value_type = field.get("value_type")
    name = re.sub(r"[^A-Za-z0-9_]", "_", str(field.get("external_name") or "field")).strip("_") or f"field_{index + 1}"
    if name[0].isdigit():
        name = "field_" + name
    if recommended:
        target = str(recommended)
    elif value_type == "collection":
        target = "tables." + name
    elif value_type == "image":
        target = "images." + name
    else:
        target = "fields." + name
    candidate, suffix = target, 2
    while candidate in used:
        candidate = f"{target}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _schema_mappings(schema: dict[str, Any], document: dict[str, Any]) -> list[dict[str, Any]]:
    fields = discover_fields(_schema_sample(schema, document))
    collections = [field["source_path"] for field in fields if field.get("value_type") == "collection"]
    eligible = [
        field for field in fields
        if not (field.get("value_type") != "collection" and any(field["source_path"].startswith(path + ".") for path in collections))
    ]
    used: set[str] = set()
    mappings = []
    for index, field in enumerate(eligible):
        mappings.append({
            "source_path": field["source_path"],
            "target_field": _target_name(field, used, index),
            "transform_type": "none",
            "transform_config": {"display_name": field.get("display_name") or field.get("external_name"), "group": field.get("group")},
            "value_type": field.get("value_type"),
            "sample": field.get("sample"),
        })
    return mappings


def preview_openapi_import(document: dict[str, Any], document_hash: str) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    ignored: list[dict[str, str]] = []
    used_names: set[str] = set()
    for path, path_item in document.get("paths", {}).items():
        if not isinstance(path_item, dict) or not isinstance(path, str):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"} or not isinstance(operation, dict):
                continue
            if method.lower() not in SUPPORTED_METHODS:
                ignored.append({"method": method.upper(), "path": path, "reason": "当前工作台仅支持 GET、POST"})
                continue
            status, schema = _response_schema(operation, document)
            mappings = _schema_mappings(schema, document) if schema else []
            name = str(operation.get("summary") or operation.get("operationId") or f"{SUPPORTED_METHODS[method.lower()]} {path}")
            unique_name, suffix = name, 2
            while unique_name in used_names:
                unique_name = f"{name} {suffix}"
                suffix += 1
            used_names.add(unique_name)
            operations.append({
                "id": SUPPORTED_METHODS[method.lower()] + " " + path,
                "method": SUPPORTED_METHODS[method.lower()], "path": path,
                "name": unique_name,
                "description": str(operation.get("description") or ""),
                "response_status": status,
                "parameters": _operation_parameters(path_item, operation, document),
                "mappings": mappings,
            })
    if not operations:
        raise ApiConfigurationError("文档中没有可导入的 GET 或 POST 接口")
    info = document.get("info") or {}
    return {
        "document_hash": document_hash,
        "title": str(info.get("title") or "API 数据来源"),
        "version": str(info.get("version") or ""),
        "base_url": _base_url(document),
        "auth_options": _auth_options(document),
        "operations": operations,
        "ignored_operations": ignored,
    }
