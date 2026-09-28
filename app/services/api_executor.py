import base64
import copy
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

from ..core.exceptions import (
    ApiAuthenticationError,
    ApiConfigurationError,
    ApiConnectionError,
    ApiRequestError,
)
from ..db.connector_database import ConnectorDatabase
from ..models import ApiConnection, ApiParameter
from ..schemas.connector import BuiltRequest

_MISSING = object()


def _lookup(values: dict[str, Any], key: str | None) -> Any:
    if not key:
        return _MISSING
    if key in values:
        return values[key]
    current: Any = values
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set_nested(target: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


class ApiExecutor:
    def __init__(self, database: ConnectorDatabase, *, transport: httpx.AsyncBaseTransport | None = None):
        self.database = database
        self.transport = transport

    def build_request(
        self,
        endpoint_id: int,
        runtime_parameters: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> BuiltRequest:
        endpoint = self.database.get_endpoint(endpoint_id)
        connection = self.database.get_connection(endpoint.connection_id)
        if connection.status != "active" or endpoint.status != "active":
            raise ApiConfigurationError("API连接或接口未启用", details={"endpoint_id": endpoint_id})

        runtime_parameters = runtime_parameters or {}
        context = context or {}
        path = endpoint.path
        headers: dict[str, str] = {str(k): str(v) for k, v in endpoint.headers.items()}
        query = copy.deepcopy(endpoint.query_params)
        body = copy.deepcopy(endpoint.body_template)
        if body is None:
            body = {}

        for parameter in self.database.list_parameters(endpoint_id):
            value = self._parameter_value(parameter, runtime_parameters, context)
            if parameter.location == "path":
                marker = "{" + parameter.name + "}"
                if marker not in path:
                    raise ApiConfigurationError(
                        f"路径参数 {parameter.name} 未出现在接口 path 中",
                        details={"endpoint_id": endpoint_id, "parameter": parameter.name},
                    )
                path = path.replace(marker, quote(str(value), safe=""))
            elif parameter.location == "query":
                query[parameter.name] = value
            elif parameter.location == "header":
                headers[parameter.name] = str(value)
            elif parameter.location == "body":
                if not isinstance(body, dict):
                    raise ApiConfigurationError("配置 body 参数时 body_template 必须是 JSON 对象")
                _set_nested(body, parameter.name, value)

        unresolved = re.findall(r"\{([^{}]+)\}", path)
        if unresolved:
            raise ApiConfigurationError(
                "接口路径存在未配置的 path 参数",
                details={"parameters": unresolved, "endpoint_id": endpoint_id},
            )

        self._apply_auth(connection, headers, query)
        url = connection.base_url.rstrip("/") + "/" + path.lstrip("/")
        return BuiltRequest(
            method=endpoint.method,
            url=url,
            headers=headers,
            query=query,
            body=body if endpoint.method == "POST" else None,
        )

    async def execute(
        self,
        endpoint_id: int,
        runtime_parameters: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> httpx.Response:
        endpoint = self.database.get_endpoint(endpoint_id)
        connection = self.database.get_connection(endpoint.connection_id)
        request = self.build_request(endpoint_id, runtime_parameters, context)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=connection.timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.request(
                    request.method,
                    request.url,
                    headers=request.headers,
                    params=request.query,
                    json=request.body if request.method == "POST" else None,
                )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise ApiConnectionError(
                "无法连接外部 API",
                details={"endpoint_id": endpoint_id, "reason": str(exc)},
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiConnectionError(
                "外部 API 调用失败",
                details={"endpoint_id": endpoint_id, "reason": str(exc)},
            ) from exc

        if response.status_code in {401, 403}:
            raise ApiAuthenticationError(
                "外部 API 认证失败",
                details={"endpoint_id": endpoint_id, "upstream_status": response.status_code},
            )
        if response.status_code >= 300:
            raise ApiRequestError(
                "外部 API 返回错误状态",
                details={"endpoint_id": endpoint_id, "upstream_status": response.status_code},
            )
        return response

    @staticmethod
    def _parameter_value(
        parameter: ApiParameter,
        runtime_parameters: dict[str, Any],
        context: dict[str, Any],
    ) -> Any:
        if parameter.source_type == "fixed":
            value = parameter.default_value
        elif parameter.source_type == "input":
            value = _lookup(runtime_parameters, parameter.source_key)
        else:
            value = _lookup(context, parameter.source_key)
        if value is _MISSING:
            value = parameter.default_value if parameter.default_value is not None else _MISSING
        if value is _MISSING:
            raise ApiRequestError(
                f"缺少请求参数：{parameter.source_key or parameter.name}",
                details={"parameter": parameter.name, "location": parameter.location},
            )
        return value

    @staticmethod
    def _secret(config: dict[str, Any], name: str) -> str | None:
        value = config.get(name)
        env_name = config.get(name + "_env")
        if env_name:
            value = os.environ.get(str(env_name))
        return None if value is None else str(value)

    def _apply_auth(
        self,
        connection: ApiConnection,
        headers: dict[str, str],
        query: dict[str, Any],
    ) -> None:
        config = connection.auth_config
        if connection.auth_type == "none":
            return
        if connection.auth_type == "bearer":
            token = self._secret(config, "token")
            if not token:
                raise ApiAuthenticationError("Bearer token 未配置")
            headers["Authorization"] = "Bearer " + token
            return
        if connection.auth_type == "basic":
            username = self._secret(config, "username")
            password = self._secret(config, "password")
            if username is None or password is None:
                raise ApiAuthenticationError("Basic Auth 用户名或密码未配置")
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            headers["Authorization"] = "Basic " + encoded
            return
        if connection.auth_type == "api_key":
            key = self._secret(config, "key")
            name = str(config.get("name") or "X-API-Key")
            location = config.get("location", "header")
            if not key or location not in {"header", "query"}:
                raise ApiAuthenticationError("API Key 配置无效")
            (headers if location == "header" else query)[name] = key
            return
        raise ApiAuthenticationError(f"不支持的认证类型：{connection.auth_type}")
