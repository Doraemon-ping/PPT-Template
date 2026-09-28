"""Evaluate the JSONPath expressions stored on field mappings.

用 ``jsonpath_ng.ext`` 而不是基础解析器：基础版只支持字段、``[*]`` 和 ``[0]`` 下标，
过滤器 ``[?(@.设备=="设备1")]`` 和切片 ``[1:]`` 会直接词法报错，而这两者正是
"接口返回一组数据、只取其中一条"的常用写法。
"""
from typing import Any

import httpx
from jsonpath_ng.ext import parse
from jsonpath_ng.exceptions import JSONPathError

from ..core.exceptions import ApiResponseError


class ResponseParser:
    """Parse JSON responses and evaluate configured JSONPath expressions."""

    @staticmethod
    def parse_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise ApiResponseError(
                "外部 API 返回的内容不是有效 JSON",
                details={"content_type": response.headers.get("content-type", "")},
            ) from exc

    @staticmethod
    def extract(payload: Any, expression: str) -> list[Any]:
        try:
            compiled = parse(expression)
        except (JSONPathError, TypeError, ValueError) as exc:
            raise ApiResponseError(
                "字段映射包含无效 JSONPath",
                details={"source_path": expression},
            ) from exc
        return [match.value for match in compiled.find(payload)]
