from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ApiParameter:
    id: int
    endpoint_id: int
    name: str
    location: str
    source_type: str
    source_key: str | None
    default_value: Any | None
