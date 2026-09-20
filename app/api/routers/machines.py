# -*- coding: utf-8 -*-
"""设备库：字段表 + 行级读写 + 兜底机型 + 图片/资料。

设备是**基础库**（全局共享，不属于任何项目）：页面上一行一台设备，按行业库口径行级读写。
删除是逻辑删除（回收站可恢复），但**被项目引用时会先提示**：工序靠 ``pr[].mid`` 引用设备，
删掉被引用的设备会让那些工序改用兜底机型，所以默认拦住、要 ``force=true`` 才真删。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request

from ...core.security import bearer_token as _bearer


def register(router: APIRouter, store_factory) -> None:
    """挂上设备库路由。"""

    @router.get("/api/machining-dfm/machines/fields")
    def machine_fields():
        return {"fields": store_factory().machine_fields()}

    @router.get("/api/machining-dfm/machines")
    def list_machines():
        store = store_factory()
        return {
            "machines": store.machines.list_typed(),
            "fields": store.machine_fields(),
            "fallback_id": store.machines.default_ref(),
            "count": store.machines.count(),
        }

    @router.post("/api/machining-dfm/machines/reorder")
    def reorder_machines(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        ids = payload.get("ids")
        if not isinstance(ids, list):
            raise HTTPException(422, "排序请求必须包含 ids 数组")
        return {
            "machines": store.machines.reorder(ids),
            "fallback_id": store.machines.default_ref(),
        }

    @router.post("/api/machining-dfm/machines")
    def create_machine(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"machine": store.machines.create(payload), "count": store.machines.count()}

    @router.patch("/api/machining-dfm/machines/{machine_id}")
    def update_machine(machine_id: str, payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"machine": store.machines.update(machine_id, payload)}

    @router.delete("/api/machining-dfm/machines/{machine_id}")
    def delete_machine(
        machine_id: str,
        force: bool = Query(False),
        authorization: str | None = Header(None),
    ):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        usage = store.machine_usage(machine_id)
        if usage and not force:
            projects = "、".join(sorted({item["project"] for item in usage}))
            raise HTTPException(409, f"该设备已被项目引用（{projects}），删除后这些工序将改用默认机型。确认请加 force=true")
        # 口径 2：逻辑删除（回收站可恢复），删除人与原因记在行上
        return {"removed": store.machines.delete(machine_id, by=role), "usage": usage}

    @router.put("/api/machining-dfm/machines/{machine_id}/default")
    def set_default_machine(machine_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {
            "machines": store.machines.set_fallback(machine_id),
            "fallback_id": store.machines.default_ref(),
        }

    @router.put("/api/machining-dfm/machines/{machine_id}/photo")
    async def upload_machine_photo(
        machine_id: str,
        request: Request,
        authorization: str | None = Header(None),
    ):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        data = await request.body()
        return {
            "machine": store.machines.set_attachment(
                machine_id, "photo", data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/machines/{machine_id}/photo")
    def delete_machine_photo(machine_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"machine": store.machines.clear_attachment(machine_id, "photo")}

    @router.put("/api/machining-dfm/machines/{machine_id}/doc")
    async def upload_machine_doc(
        machine_id: str,
        request: Request,
        name: str = Query(""),
        authorization: str | None = Header(None),
    ):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        data = await request.body()
        filename = name or str(request.headers.get("x-file-name") or "")
        return {
            "machine": store.machines.set_attachment(
                machine_id, "doc", data, request.headers.get("content-type"), filename
            )
        }

    @router.delete("/api/machining-dfm/machines/{machine_id}/doc")
    def delete_machine_doc(machine_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"machine": store.machines.clear_attachment(machine_id, "doc")}
