from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ApiConnection:
    id: int
    name: str
    system_name: str
    base_url: str
    auth_type: str
    auth_config: dict[str, Any]
    timeout: float
    status: str
    created_at: datetime
    updated_at: datetime
