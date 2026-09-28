from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    schema_version: str
    data: dict[str, Any]
    created_at: datetime
    connection_id: int | None = None
    endpoint_id: int | None = None
    parameters: dict[str, Any] | None = None
