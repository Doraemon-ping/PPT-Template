from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Status = Literal["active", "inactive"]


class ConnectorSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ApiConnectionCreate(ConnectorSchema):
    name: str = Field(min_length=1, max_length=200)
    system_name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2000)
    auth_type: Literal["none", "bearer", "basic", "api_key"] = "none"
    auth_config: dict[str, Any] = Field(default_factory=dict)
    timeout: float = Field(default=30, gt=0, le=300)
    status: Status = "active"

    @field_validator("base_url")
    @classmethod
    def valid_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url 必须是有效的 HTTP/HTTPS 地址")
        return value.rstrip("/")


class ApiConnectionUpdate(ApiConnectionCreate):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    system_name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = None
    auth_type: Literal["none", "bearer", "basic", "api_key"] | None = None
    auth_config: dict[str, Any] | None = None
    timeout: float | None = Field(default=None, gt=0, le=300)
    status: Status | None = None


class ApiEndpointCreate(ConnectorSchema):
    connection_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=2000)
    method: Literal["GET", "POST"]
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    body_template: Any | None = None
    description: str = Field(default="", max_length=2000)
    status: Status = "active"

    @field_validator("method", mode="before")
    @classmethod
    def upper_method(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @field_validator("path")
    @classmethod
    def relative_path_only(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.startswith(("http://", "https://", "//")):
            raise ValueError("path 必须是相对路径，主机地址由 ApiConnection 管理")
        return "/" + value.lstrip("/")


class ApiEndpointUpdate(ApiEndpointCreate):
    connection_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    path: str | None = None
    method: Literal["GET", "POST"] | None = None
    headers: dict[str, str] | None = None
    query_params: dict[str, Any] | None = None
    description: str | None = Field(default=None, max_length=2000)
    status: Status | None = None


class ApiParameterCreate(ConnectorSchema):
    endpoint_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    location: Literal["path", "query", "header", "body"]
    source_type: Literal["fixed", "input", "context"]
    source_key: str | None = Field(default=None, max_length=500)
    default_value: Any | None = None

    @model_validator(mode="after")
    def validate_source(self):
        if self.source_type in {"input", "context"} and not self.source_key:
            raise ValueError("input/context 参数必须配置 source_key")
        if self.source_type == "fixed" and self.default_value is None:
            raise ValueError("fixed 参数必须配置 default_value")
        return self


class ApiParameterUpdate(ApiParameterCreate):
    endpoint_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    location: Literal["path", "query", "header", "body"] | None = None
    source_type: Literal["fixed", "input", "context"] | None = None

    @model_validator(mode="after")
    def validate_source(self):
        return self


class FieldMappingCreate(ConnectorSchema):
    endpoint_id: int = Field(gt=0)
    source_path: str = Field(min_length=1, max_length=2000)
    target_field: str = Field(min_length=1, max_length=500, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    transform_type: Literal["none", "enum"] = "none"
    transform_config: dict[str, Any] = Field(default_factory=dict)


class FieldMappingUpdate(FieldMappingCreate):
    endpoint_id: int | None = Field(default=None, gt=0)
    source_path: str | None = Field(default=None, min_length=1, max_length=2000)
    target_field: str | None = Field(default=None, min_length=1, max_length=500, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    transform_type: Literal["none", "enum"] | None = None
    transform_config: dict[str, Any] | None = None


class ConnectorTestRequest(ConnectorSchema):
    endpoint_id: int = Field(gt=0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class ConnectorDiscoverRequest(ConnectorSchema):
    """发现可选字段时的运行参数；只读调用，不写入 Dataset。"""

    parameters: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class ConnectorInspectRequest(ConnectorSchema):
    name: str = Field(min_length=1, max_length=200)
    system_type: Literal["api"] = "api"
    url: str = Field(min_length=1, max_length=2000)
    auth_type: Literal["none", "api_key"] = "none"
    api_key_name: str = Field(default="X-API-Key", min_length=1, max_length=200)
    api_key_value: str | None = Field(default=None, max_length=4000)
    project_id: str | None = Field(default=None, max_length=500)

    @field_validator("url")
    @classmethod
    def inspect_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("接口地址必须是有效的 HTTP/HTTPS 地址")
        return value

    @model_validator(mode="after")
    def inspect_auth(self):
        if self.auth_type == "api_key" and not self.api_key_value:
            raise ValueError("选择 API Key 后需要填写密钥")
        return self


class OpenApiImportPreviewRequest(ConnectorSchema):
    """One OpenAPI source, supplied either as text or a URL."""

    spec_text: str | None = Field(default=None, max_length=2_000_000)
    spec_url: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def exactly_one_source(self):
        if bool(self.spec_text and self.spec_text.strip()) == bool(self.spec_url and self.spec_url.strip()):
            raise ValueError("请填写 API 文档 URL 或粘贴文档内容，两者选一个")
        return self


class OpenApiImportCommitRequest(OpenApiImportPreviewRequest):
    document_hash: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=200)
    system_name: str | None = Field(default=None, min_length=1, max_length=200)
    auth_type: Literal["none", "bearer", "basic", "api_key"] = "none"
    auth_config: dict[str, Any] = Field(default_factory=dict)
    selected_operations: list[str] = Field(min_length=1, max_length=50)
    workspace_id: int | None = Field(default=None, gt=0)
    timeout: float = Field(default=30, gt=0, le=300)


class WorkspaceCreate(ConnectorSchema):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class WorkspaceSourceAttach(ConnectorSchema):
    connection_id: int = Field(gt=0)


class WorkspaceTemplateAttach(ConnectorSchema):
    template_id: str = Field(min_length=1, max_length=80)
    source_name: str = Field(default="", max_length=500)
    slide_count: int = Field(default=0, ge=0)
    size: int = Field(default=0, ge=0)
    placeholder_count: int = Field(default=0, ge=0)
    binding_target_count: int = Field(default=0, ge=0)


class WorkspaceTemplateBindingSave(ConnectorSchema):
    revision: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class BuiltRequest(ConnectorSchema):
    method: str
    url: str
    headers: dict[str, str]
    query: dict[str, Any]
    body: Any | None
