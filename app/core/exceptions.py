from typing import Any


class ApiConnectorError(Exception):
    """Base error exposed by the connector execution boundary."""

    code = "api_connector_error"
    http_status = 502

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


class ApiConnectionError(ApiConnectorError):
    code = "api_connection_error"


class ApiAuthenticationError(ApiConnectorError):
    code = "api_authentication_error"


class ApiRequestError(ApiConnectorError):
    code = "api_request_error"


class ApiResponseError(ApiConnectorError):
    code = "api_response_error"


class ApiConfigurationError(ApiConnectorError):
    code = "api_configuration_error"
    http_status = 422


class ConnectorRecordNotFound(ApiConnectorError):
    code = "connector_record_not_found"
    http_status = 404
