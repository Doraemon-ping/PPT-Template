from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldMapping:
    id: int
    endpoint_id: int
    source_path: str
    target_field: str
    transform_type: str
    transform_config: dict[str, Any]
