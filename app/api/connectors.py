import json
import sqlite3
import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ..core.exceptions import ApiConnectorError
from ..db.connector_database import ConnectorDatabase, get_connector_database
from ..schemas.connector import (
    ApiConnectionCreate,
    ApiConnectionUpdate,
    ApiEndpointCreate,
    ApiEndpointUpdate,
    ApiParameterCreate,
    ApiParameterUpdate,
    ConnectorTestRequest,
    ConnectorInspectRequest,
    ConnectorDiscoverRequest,
    FieldMappingCreate,
    FieldMappingUpdate,
    OpenApiImportCommitRequest,
    OpenApiImportPreviewRequest,
    WorkspaceCreate,
    WorkspaceSourceAttach,
    WorkspaceTemplateAttach,
    WorkspaceTemplateBindingSave,
)
from ..schemas.dataset import DatasetResponse
from ..services.api_executor import ApiExecutor
from ..services.dataset_service import DatasetService
from ..services.mapping_service import MappingService
from ..services.response_parser import ResponseParser
from ..services.connector_ux import (
    TARGET_FIELDS,
    count_records,
    discover_fields,
    friendly_error,
    inspect_source,
)
from ..services.connector_binding import build_workspace_combined_binding_context
from ..services.openapi_importer import load_openapi_document, preview_openapi_import

router = APIRouter(prefix="/api/connectors", tags=["external-api-connectors"])

#: 回传给前端的预览数据上限；超过就不回传，前端退回只用字段样例值预览。
PREVIEW_MAX_CHARS = 400_000


def preview_payload(payload: Any) -> Any | None:
    """把外部响应裁成可安全回传的预览数据；过大时返回 None。"""
    if payload is None:
        return None
    try:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
    return payload if len(serialized) <= PREVIEW_MAX_CHARS else None


def _values(model, *, nullable: set[str] | None = None) -> dict:
    nullable = nullable or set()
    return {
        key: value
        for key, value in model.model_dump(exclude_unset=True).items()
        if value is not None or key in nullable
    }


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(body: WorkspaceCreate, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.create_workspace(body.model_dump())


@router.get("/workspaces")
def list_workspaces(db: ConnectorDatabase = Depends(get_connector_database)):
    return {"items": db.list_workspaces()}


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: int, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.get_workspace(workspace_id)


@router.post("/workspaces/{workspace_id}/refresh")
async def refresh_workspace_data(
    workspace_id: int,
    db: ConnectorDatabase = Depends(get_connector_database),
):
    """Refresh all active endpoints attached to a workspace.

    Every endpoint reuses the parameters from its latest successful Dataset.
    Failures are isolated, so one unavailable system does not discard fresh
    data returned by the other systems.
    """
    workspace = db.get_workspace(workspace_id)
    jobs = []
    for source in workspace["sources"]:
        for endpoint in db.list_endpoints(source["id"]):
            if endpoint.status != "active":
                continue
            latest = db.latest_endpoint_dataset(endpoint.id)
            jobs.append((source, endpoint, (latest.parameters if latest else {}) or {}))
    if not jobs:
        raise HTTPException(status_code=409, detail="工作空间没有可刷新的 API 接口")

    async def run(job):
        source, endpoint, parameters = job
        try:
            response = await ApiExecutor(db).execute(endpoint.id, parameters, {})
            payload = ResponseParser.parse_json(response)
            mapped = MappingService().map(payload, db.list_mappings(endpoint.id))
            dataset = DatasetService(db).create(
                source=source["system_name"], data=mapped,
                connection_id=source["id"], endpoint_id=endpoint.id,
                parameters=parameters,
            )
            return {
                "ok": True, "connection_id": source["id"], "endpoint_id": endpoint.id,
                "endpoint": endpoint.name, "dataset_id": dataset.id,
                "record_count": count_records(mapped),
            }
        except ApiConnectorError as exc:
            message, technical = friendly_error(exc)
            return {
                "ok": False, "connection_id": source["id"], "endpoint_id": endpoint.id,
                "endpoint": endpoint.name, "message": message, "technical_detail": technical,
            }

    results = await asyncio.gather(*(run(job) for job in jobs))
    for source in workspace["sources"]:
        own = [item for item in results if item["connection_id"] == source["id"]]
        failed = [item for item in own if not item["ok"]]
        db.record_source_status(
            source["id"], status="failed" if failed else "normal",
            reason_code="workspace_refresh_failed" if failed else None,
            reason_message=failed[0]["message"] if failed else None,
            record_count=sum(item.get("record_count", 0) for item in own),
        )
    errors = [item for item in results if not item["ok"]]
    return {
        "ok": not errors,
        "workspace_id": workspace_id,
        "refreshed": sum(1 for item in results if item["ok"]),
        "failed": len(errors),
        "items": results,
    }


@router.post("/workspaces/{workspace_id}/sources")
def attach_workspace_source(
    workspace_id: int,
    body: WorkspaceSourceAttach,
    db: ConnectorDatabase = Depends(get_connector_database),
):
    return db.attach_workspace_source(workspace_id, body.connection_id)


@router.post("/workspaces/{workspace_id}/templates")
def attach_workspace_template(
    workspace_id: int,
    body: WorkspaceTemplateAttach,
    db: ConnectorDatabase = Depends(get_connector_database),
):
    return db.attach_workspace_template(workspace_id, body.model_dump())


@router.get("/workspaces/{workspace_id}/templates/{template_id}/binding-context")
def get_workspace_template_binding_context(
    workspace_id: int,
    template_id: str,
    db: ConnectorDatabase = Depends(get_connector_database),
):
    workspace = db.get_workspace(workspace_id)
    template = next(
        (item for item in workspace["templates"] if item["template_id"] == template_id),
        None,
    )
    if template is None:
        raise HTTPException(status_code=404, detail="工作空间中的 PPT 模板不存在")
    binding_sources = db.get_workspace_binding_sources(workspace_id)
    data, catalog, datasets = build_workspace_combined_binding_context(binding_sources)
    primary = binding_sources[0]["dataset"]
    return {
        "workspace": {
            "id": workspace["id"],
            "name": workspace["name"],
            "description": workspace["description"],
        },
        "template": template,
        "dataset": {
            "id": primary.id if len(datasets) == 1 else "combined",
            "source": primary.source if len(datasets) == 1 else f"{len(datasets)} 个系统接口",
            "created_at": max(item["created_at"] for item in datasets),
        },
        "datasets": datasets,
        "data": data,
        "catalog": catalog,
        "binding": db.get_workspace_template_binding(workspace_id, template_id),
    }


@router.put("/workspaces/{workspace_id}/templates/{template_id}/binding")
def save_workspace_template_binding(
    workspace_id: int,
    template_id: str,
    body: WorkspaceTemplateBindingSave,
    db: ConnectorDatabase = Depends(get_connector_database),
):
    saved = db.save_workspace_template_binding(
        workspace_id,
        template_id,
        expected_revision=body.revision,
        payload=body.payload,
    )
    if saved is None:
        raise HTTPException(
            status_code=409,
            detail="绑定配置已在其他页面更新，请刷新后继续",
        )
    return saved


@router.post("/connections", status_code=status.HTTP_201_CREATED)
def create_connection(body: ApiConnectionCreate, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.create_connection(body.model_dump())


@router.get("/connections")
def list_connections(db: ConnectorDatabase = Depends(get_connector_database)):
    return {"items": db.list_connections()}


@router.get("/connections/{connection_id}")
def get_connection(connection_id: int, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.get_connection(connection_id)


@router.patch("/connections/{connection_id}")
def update_connection(connection_id: int, body: ApiConnectionUpdate, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.update_connection(connection_id, _values(body))


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(connection_id: int, db: ConnectorDatabase = Depends(get_connector_database)):
    db.delete_connection(connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/endpoints", status_code=status.HTTP_201_CREATED)
def create_endpoint(body: ApiEndpointCreate, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.create_endpoint(body.model_dump())


@router.get("/endpoints")
def list_endpoints(connection_id: int | None = None, db: ConnectorDatabase = Depends(get_connector_database)):
    return {"items": db.list_endpoints(connection_id)}


@router.get("/endpoints/{endpoint_id}")
def get_endpoint(endpoint_id: int, db: ConnectorDatabase = Depends(get_connector_database)):
    endpoint = db.get_endpoint(endpoint_id)
    return {
        **asdict(endpoint),
        "parameters": db.list_parameters(endpoint_id),
        "mappings": db.list_mappings(endpoint_id),
    }


@router.patch("/endpoints/{endpoint_id}")
def update_endpoint(endpoint_id: int, body: ApiEndpointUpdate, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.update_endpoint(endpoint_id, _values(body, nullable={"body_template"}))


@router.delete("/endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_endpoint(endpoint_id: int, db: ConnectorDatabase = Depends(get_connector_database)):
    db.delete_endpoint(endpoint_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/parameters", status_code=status.HTTP_201_CREATED)
def create_parameter(body: ApiParameterCreate, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.create_parameter(body.model_dump())


@router.get("/parameters")
def list_parameters(endpoint_id: int = Query(gt=0), db: ConnectorDatabase = Depends(get_connector_database)):
    db.get_endpoint(endpoint_id)
    return {"items": db.list_parameters(endpoint_id)}


@router.get("/parameters/{parameter_id}")
def get_parameter(parameter_id: int, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.get_parameter(parameter_id)


@router.patch("/parameters/{parameter_id}")
def update_parameter(parameter_id: int, body: ApiParameterUpdate, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.update_parameter(parameter_id, _values(body, nullable={"source_key", "default_value"}))


@router.delete("/parameters/{parameter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_parameter(parameter_id: int, db: ConnectorDatabase = Depends(get_connector_database)):
    db.delete_parameter(parameter_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/mappings", status_code=status.HTTP_201_CREATED)
def create_mapping(body: FieldMappingCreate, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.create_mapping(body.model_dump())


@router.get("/mappings")
def list_mappings(endpoint_id: int = Query(gt=0), db: ConnectorDatabase = Depends(get_connector_database)):
    db.get_endpoint(endpoint_id)
    return {"items": db.list_mappings(endpoint_id)}


@router.get("/mappings/{mapping_id}")
def get_mapping(mapping_id: int, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.get_mapping(mapping_id)


@router.patch("/mappings/{mapping_id}")
def update_mapping(mapping_id: int, body: FieldMappingUpdate, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.update_mapping(mapping_id, _values(body))


@router.delete("/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_mapping(mapping_id: int, db: ConnectorDatabase = Depends(get_connector_database)):
    db.delete_mapping(mapping_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test", response_model=DatasetResponse)
async def execute_connector(body: ConnectorTestRequest, db: ConnectorDatabase = Depends(get_connector_database)):
    endpoint = db.get_endpoint(body.endpoint_id)
    connection = db.get_connection(endpoint.connection_id)
    try:
        response = await ApiExecutor(db).execute(body.endpoint_id, body.parameters, body.context)
        payload = ResponseParser.parse_json(response)
        mapped = MappingService().map(payload, db.list_mappings(body.endpoint_id))
        dataset = DatasetService(db).create(
            source=connection.system_name,
            data=mapped,
            connection_id=connection.id,
            endpoint_id=endpoint.id,
            parameters=body.parameters,
        )
    except ApiConnectorError as exc:
        message, _technical = friendly_error(exc)
        db.record_source_status(
            connection.id,
            status="failed",
            reason_code=exc.code,
            reason_message=message,
        )
        raise
    db.record_source_status(
        connection.id,
        status="normal",
        record_count=count_records(mapped),
    )
    return dataset


@router.post("/endpoints/{endpoint_id}/discover")
async def discover_endpoint_fields(
    endpoint_id: int,
    body: ConnectorDiscoverRequest | None = None,
    db: ConnectorDatabase = Depends(get_connector_database),
):
    """读取一次外部接口，列出返回 JSON 里的全部可选字段。

    「4 字段」页用它把接口真实返回的参数一次列全，用户挑字段而不是手写 JSONPath。
    只读：不创建 Dataset，也不改写来源状态。
    """
    endpoint = db.get_endpoint(endpoint_id)
    connection = db.get_connection(endpoint.connection_id)
    runtime = body or ConnectorDiscoverRequest()
    try:
        response = await ApiExecutor(db).execute(endpoint_id, runtime.parameters, runtime.context)
        payload = ResponseParser.parse_json(response)
    except ApiConnectorError as exc:
        message, technical = friendly_error(exc)
        return JSONResponse(
            status_code=exc.http_status,
            content={"detail": {
                "code": exc.code,
                "message": message,
                "technical_detail": technical,
            }},
        )
    preview = preview_payload(payload)
    return {
        "ok": True,
        "endpoint_id": endpoint_id,
        "connection_id": connection.id,
        "record_count": count_records(payload),
        "fields": discover_fields(payload),
        "targets": [{"key": item["key"], "label": item["label"]} for item in TARGET_FIELDS],
        "mapped_paths": [mapping.source_path for mapping in db.list_mappings(endpoint_id)],
        "raw": preview,
        "raw_truncated": preview is None and payload is not None,
    }


@router.get("/sources")
def source_summaries(
    workspace_id: int | None = None,
    db: ConnectorDatabase = Depends(get_connector_database),
):
    return {"items": db.list_source_summaries(workspace_id)}


@router.post("/wizard/inspect")
async def inspect_connector(body: ConnectorInspectRequest):
    try:
        return await inspect_source(body)
    except ApiConnectorError as exc:
        message, technical = friendly_error(exc)
        return JSONResponse(
            status_code=exc.http_status,
            content={"detail": {
                "code": exc.code,
                "message": message,
                "technical_detail": technical,
                **exc.details,
            }},
        )


@router.post("/imports/openapi/preview")
async def preview_openapi_connector(body: OpenApiImportPreviewRequest):
    """Parse an API contract without creating any connector records."""
    document, document_hash = await load_openapi_document(
        spec_text=body.spec_text,
        spec_url=body.spec_url,
    )
    return preview_openapi_import(document, document_hash)


@router.post("/imports/openapi/commit", status_code=status.HTTP_201_CREATED)
async def commit_openapi_connector(
    body: OpenApiImportCommitRequest,
    db: ConnectorDatabase = Depends(get_connector_database),
):
    """Reparse the reviewed document and atomically create selected operations."""
    document, document_hash = await load_openapi_document(
        spec_text=body.spec_text,
        spec_url=body.spec_url,
    )
    if document_hash != body.document_hash:
        raise HTTPException(status_code=409, detail="API 文档已变化，请重新解析后再导入")
    preview = preview_openapi_import(document, document_hash)
    candidates = {operation["id"]: operation for operation in preview["operations"]}
    selected_ids = list(dict.fromkeys(body.selected_operations))
    missing = [operation_id for operation_id in selected_ids if operation_id not in candidates]
    if missing:
        raise HTTPException(status_code=422, detail="选择的接口不在当前 API 文档中")
    supported_auth = {item["auth_type"] for item in preview["auth_options"]}
    if body.auth_type not in supported_auth:
        raise HTTPException(status_code=422, detail="选择的认证方式不在 API 文档声明中")
    if body.auth_type == "api_key" and not body.auth_config.get("key"):
        raise HTTPException(status_code=422, detail="请填写 API Key")
    if body.auth_type == "bearer" and not body.auth_config.get("token"):
        raise HTTPException(status_code=422, detail="请填写 Bearer Token")
    if body.auth_type == "basic" and (not body.auth_config.get("username") or not body.auth_config.get("password")):
        raise HTTPException(status_code=422, detail="请填写 Basic Auth 用户名和密码")
    option = next(item for item in preview["auth_options"] if item["auth_type"] == body.auth_type)
    auth_config = {**option.get("config", {}), **body.auth_config}
    system_name = body.system_name or "OPENAPI-" + document_hash[:12].upper()
    result = db.import_openapi(
        {
            "name": body.name,
            "system_name": system_name,
            "base_url": preview["base_url"],
            "auth_type": body.auth_type,
            "auth_config": auth_config,
            "timeout": body.timeout,
        },
        [candidates[operation_id] for operation_id in selected_ids],
        workspace_id=body.workspace_id,
    )
    return result


@router.get("/datasets")
def list_datasets(
    source: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: ConnectorDatabase = Depends(get_connector_database),
):
    return {"items": db.list_datasets(source, limit)}


@router.get("/datasets/{dataset_id}", response_model=DatasetResponse)
def get_dataset(dataset_id: str, db: ConnectorDatabase = Depends(get_connector_database)):
    return db.get_dataset(dataset_id)


def install_connector_api(app: FastAPI) -> None:
    async def connector_error_handler(_request, exc: ApiConnectorError):
        return JSONResponse(status_code=exc.http_status, content={"detail": jsonable_encoder(exc.as_detail())})

    async def integrity_error_handler(_request, exc: sqlite3.IntegrityError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": {"code": "connector_configuration_conflict", "message": str(exc)}},
        )

    app.add_exception_handler(ApiConnectorError, connector_error_handler)
    app.add_exception_handler(sqlite3.IntegrityError, integrity_error_handler)
    app.include_router(router)
