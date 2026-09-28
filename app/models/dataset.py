from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Dataset:
    id: str
    source: str
    schema_version: str
    data: dict[str, Any]
    created_at: datetime
    connection_id: int | None = None
    endpoint_id: int | None = None
    parameters: dict[str, Any] | None = None
