from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ApiEndpoint:
    id: int
    connection_id: int
    name: str
    path: str
    method: str
    headers: dict[str, str]
    query_params: dict[str, Any]
    body_template: Any | None
    description: str
    status: str
