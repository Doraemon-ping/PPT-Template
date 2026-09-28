import re
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx

from ..core.exceptions import (
    ApiAuthenticationError,
    ApiConfigurationError,
    ApiConnectionError,
    ApiRequestError,
    ApiResponseError,
)
from ..schemas.connector import ConnectorInspectRequest


TARGET_FIELDS = [
    {"key": "project_name", "label": "项目名称", "aliases": ["projectname", "project_name", "项目名称", "项目名", "reportname", "name"]},
    {"key": "customer", "label": "客户", "aliases": ["customer", "customername", "client", "客户", "客户名称"]},
    {"key": "part_name", "label": "零件名称", "aliases": ["part", "partname", "component", "componentname", "零件", "零件名称"]},
    {"key": "revision", "label": "数据版本", "aliases": ["revision", "version", "rev", "数据版本", "版本"]},
    {"key": "updated_at", "label": "更新时间", "aliases": ["updated", "updatedat", "update_time", "modified", "更新时间"]},
    {"key": "processes", "label": "工序列表", "aliases": ["processes", "process", "operations", "operation", "pr", "工序", "工序列表"]},
    {"key": "issues", "label": "问题列表", "aliases": ["issues", "problems", "defects", "is", "问题列表", "问题清单"]},
    {"key": "issue_title", "label": "问题标题", "aliases": ["issuetitle", "issue_title", "problemname", "problem_name", "title", "问题名称", "问题标题"]},
    {"key": "severity", "label": "严重等级", "aliases": ["severity", "level", "grade", "risk", "risklevel", "问题等级", "严重等级", "风险等级"]},
    {"key": "product_image", "label": "产品图片", "aliases": ["productimage", "partimage", "mainimage", "pi", "产品图片", "零件图片"]},
    {"key": "issue_image", "label": "问题图片", "aliases": ["image", "img", "picture", "photo", "screenshot", "issueimage", "问题图片", "问题截图"]},
    {"key": "description", "label": "问题描述", "aliases": ["description", "desc", "detail", "content", "问题描述", "问题详情"]},
    {"key": "status", "label": "处理状态", "aliases": ["status", "state", "result", "处理状态", "问题状态"]},
    {"key": "identifier", "label": "编号", "aliases": ["id", "code", "no", "number", "identifier", "编号", "序号"]},
]


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value.casefold())


def _tokens(value: str) -> list[str]:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return [token for token in re.split(r"[^a-zA-Z0-9\u4e00-\u9fff]+", separated.casefold()) if token]


def _recommend(name: str, path: str, value: Any, value_type: str) -> tuple[str | None, str | None, float]:
    candidate = _normalized(name)
    name_tokens = set(_tokens(name))
    context = _normalized(path)
    if isinstance(value, bool) or any(token in name_tokens for token in {"table", "enabled", "enable", "flag"}):
        return None, None, 0.0
    best: tuple[str | None, str | None, float] = (None, None, 0.0)
    for target in TARGET_FIELDS:
        for alias in target["aliases"]:
            normalized_alias = _normalized(alias)
            if candidate == normalized_alias:
                score = 1.0
            elif len(normalized_alias) >= 5 and set(_tokens(alias)).issubset(name_tokens):
                score = 0.9
            elif len(candidate) >= 5 and len(normalized_alias) >= 5:
                score = SequenceMatcher(None, candidate, normalized_alias).ratio() * 0.9
            else:
                score = 0.0
            if target["key"] == "identifier" and "[*]" in path:
                score = 0.0
            if target["key"] == "project_name" and normalized_alias == "name" and path != "$.name":
                score = 0.0
            if target["key"] == "issue_title" and normalized_alias == "title" and not any(
                token in context for token in ("issue", "problem", "defect", "问题")
            ):
                score = 0.0
            if target["key"] == "issue_image" and value_type == "image" and not any(
                token in context for token in ("issue", "problem", "defect", "问题")
            ):
                score *= 0.75
            if target["key"] in {"description", "status"} and not any(
                token in context for token in ("issue", "problem", "defect", "问题", "stateis")
            ):
                score = 0.0
            if target["key"] in {"processes", "issues"} and value_type != "collection":
                score = 0.0
            if score > best[2]:
                best = (target["key"], target["label"], score)
    return best if best[2] >= 0.78 else (None, None, best[2])


def _path_part(key: str) -> str:
    return "." + key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key) else "['" + key.replace("'", "\\'") + "']"


def _value_type(name: str, value: Any) -> str:
    text = str(value or "")
    normalized_name = _normalized(name)
    if normalized_name in {"pi", "productimage", "partimage", "mainimage"} or any(token in name.casefold() for token in ("image", "img", "photo", "picture", "screenshot", "图片", "截图")):
        return "image"
    if re.search(r"\.(png|jpe?g|gif|webp|bmp)(\?.*)?$", text, re.I) or text.startswith("data:image/"):
        return "image"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


def _group(name: str, path: str, value_type: str, recommended_target: str | None = None) -> str:
    text = (name + " " + path).casefold()
    if value_type == "image":
        return "图片"
    if recommended_target == "processes" or any(token in text for token in ("process", "operation", ".pr", "工序")):
        return "工序数据"
    if recommended_target == "issues" or any(token in text for token in ("issue", "problem", "defect", ".is", "问题", "风险")):
        return "问题列表"
    if "[*]" in path:
        return "列表数据"
    return "项目信息"


def discover_fields(payload: Any) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def walk(value: Any, path: str, name: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, path + _path_part(str(key)), str(key))
            return
        if isinstance(value, list):
            if not value:
                return
            collection_path = path + "[*]"
            if any(isinstance(child, dict) for child in value[:3]) and collection_path not in found:
                target_key, target_label, confidence = _recommend(name, collection_path, value, "collection")
                found[collection_path] = {
                    "source_path": collection_path,
                    "external_name": name,
                    "display_name": target_label or f"{name}（整组记录）",
                    "sample": f"{len(value)} 条记录",
                    "value_type": "collection",
                    "group": _group(name, collection_path, "collection", target_key),
                    "recommended_target": target_key,
                    "recommended_label": target_label,
                    "confidence": round(confidence, 2),
                    "selected": False,
                }
            for child in value[:3]:
                walk(child, collection_path, name)
            return
        if path not in found:
            value_type = _value_type(name, value)
            target_key, target_label, confidence = _recommend(name, path, value, value_type)
            sample = str(value) if value is not None else ""
            found[path] = {
                "source_path": path,
                "external_name": name,
                "display_name": target_label or name,
                "sample": sample[:300],
                "value_type": value_type,
                "group": _group(name, path, value_type, target_key),
                "recommended_target": target_key,
                "recommended_label": target_label,
                "confidence": round(confidence, 2),
                "selected": False,
            }

    walk(payload, "$", "data")
    fields = list(found.values())
    recommended = [field for field in fields if field["recommended_target"] and field["confidence"] >= 0.9]
    recommended.sort(key=lambda item: (-item["confidence"], item["source_path"].count("[*]"), len(item["source_path"])))
    used: set[str] = set()
    for field in recommended:
        target = field["recommended_target"]
        if target not in used:
            field["selected"] = True
            used.add(target)
    selected_collections = [
        field["source_path"] for field in fields if field["selected"] and field["value_type"] == "collection"
    ]
    for field in fields:
        if field["value_type"] != "collection" and any(
            field["source_path"].startswith(collection + ".") for collection in selected_collections
        ):
            field["selected"] = False
    return fields


def count_records(payload: Any) -> int:
    sizes: list[int] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            sizes.append(len(value))
            for child in value[:3]:
                visit(child)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)

    visit(payload)
    return max(sizes, default=1 if payload not in ({}, [], None) else 0)


def friendly_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ApiAuthenticationError):
        return "认证失败，请检查 API Key 是否正确", str(exc)
    if isinstance(exc, ApiConnectionError):
        return "无法连接到数据来源，请检查地址和网络", str(exc)
    if isinstance(exc, ApiResponseError):
        return "返回的数据无法识别，请确认接口返回 JSON 数据", str(exc)
    if isinstance(exc, ApiConfigurationError):
        return "接口或连接未启用，或请求参数没配齐，请先检查「2 接口」和「3 参数」", str(exc)
    if isinstance(exc, ApiRequestError):
        return "数据来源暂时无法访问，请检查接口地址和参数", str(exc)
    return "测试连接失败，请检查填写内容", str(exc)


async def inspect_source(request: ConnectorInspectRequest) -> dict[str, Any]:
    parsed = urlsplit(request.url)
    path = parsed.path or "/"
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    parameter = None
    if request.project_id:
        if "{project_id}" in path:
            path = path.replace("{project_id}", quote(request.project_id, safe=""))
            parameter = {"name": "project_id", "location": "path", "source_key": "project_id"}
        else:
            query["project_id"] = request.project_id
            parameter = {"name": "project_id", "location": "query", "source_key": "project_id"}
    test_url = urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query, doseq=True), ""))
    headers: dict[str, str] = {"Accept": "application/json"}
    if request.auth_type == "api_key":
        headers[request.api_key_name] = request.api_key_value or ""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.get(test_url, headers=headers)
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
        raise ApiConnectionError("连接外部 API 失败", details={"reason": str(exc)}) from exc
    if response.status_code in {401, 403}:
        raise ApiAuthenticationError("外部 API 认证失败", details={"upstream_status": response.status_code})
    if response.status_code >= 300:
        raise ApiRequestError("外部 API 返回错误状态", details={"upstream_status": response.status_code})
    try:
        payload = response.json()
    except ValueError as exc:
        raise ApiResponseError("外部 API 返回的内容不是有效 JSON") from exc

    fields = discover_fields(payload)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    static_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if parameter and parameter["location"] == "query":
        static_query.pop(parameter["name"], None)
    return {
        "ok": True,
        "message": "连接成功，已识别数据字段",
        "record_count": count_records(payload),
        "fields": fields,
        "targets": [{"key": item["key"], "label": item["label"]} for item in TARGET_FIELDS],
        "raw": payload,
        "configuration": {
            "base_url": origin,
            "path": parsed.path or "/",
            "method": "GET",
            "query_params": static_query,
            "parameter": parameter,
        },
    }
