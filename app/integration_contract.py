"""PPT data provider v1: JSON-only, independent of either form implementation."""
from typing import Any, Literal
from pydantic import BaseModel, Field

class ReportContext(BaseModel):
    f: dict[str, Any] = Field(default_factory=dict)
    t: dict[str, Any] = Field(default_factory=dict)
    i: dict[str, Any] = Field(default_factory=dict)
    derived: dict[str, Any] = Field(default_factory=dict)
    calc_results: dict[str, Any] = Field(default_factory=dict)
    ppt: dict[str, Any] = Field(default_factory=dict)

class FieldCatalog(BaseModel):
    fields: list[dict[str, Any]] = Field(default_factory=list)
    tables: dict[str, Any] = Field(default_factory=dict)
    images: dict[str, Any] = Field(default_factory=dict)
    derived: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)

class Snapshot(BaseModel):
    contract_version: Literal['1.0'] = '1.0'
    source_id: str
    project_id: str
    revision: int | str
    name: str
    form_url: str
    data: ReportContext
    catalog: FieldCatalog

def snapshot(source_id, project_id, revision, name, form_url, data, catalog):
    return Snapshot(source_id=source_id, project_id=project_id, revision=revision,
                    name=name, form_url=form_url, data=data, catalog=catalog).model_dump()
