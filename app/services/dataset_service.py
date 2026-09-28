from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..db.connector_database import ConnectorDatabase
from ..models import Dataset


class DatasetService:
    def __init__(self, database: ConnectorDatabase):
        self.database = database

    def create(
        self, *, source: str, data: dict[str, Any], schema_version: str = "1.0",
        connection_id: int | None = None, endpoint_id: int | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> Dataset:
        dataset = Dataset(
            id=str(uuid4()),
            source=source,
            schema_version=schema_version,
            data=data,
            created_at=datetime.now(timezone.utc),
            connection_id=connection_id,
            endpoint_id=endpoint_id,
            parameters=parameters or {},
        )
        return self.database.create_dataset(dataset)
