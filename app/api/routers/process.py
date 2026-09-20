# -*- coding: utf-8 -*-
"""工序与工序刀具行（1b）行级接口。

与项目信息同一套写法：行级 PATCH、排序、逻辑删除（回收站可恢复），每次写都递增项目版本
并留一个版本快照；返回整个项目记录给前端 adopt。

**设备是每道工序自己的一格**：单独两个接口（选定 / 清空），不混在工序行级保存里，
页面上的"设备选择"下拉框就打这两个。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request


def register(router: APIRouter, store_factory) -> None:
    """挂上工序、工序设备选择、工序图片与工序刀具行路由。"""

    @router.get("/api/machining-dfm/projects/{project_id}/processes")
    def list_project_processes(project_id: str, include_deleted: bool = Query(False)):
        return store_factory().project_processes(project_id, include_deleted=include_deleted)

    @router.post("/api/machining-dfm/projects/{project_id}/processes")
    def create_project_process(project_id: str, payload: dict[str, Any]):
        return {"project": store_factory().create_project_process(project_id, payload)}

    @router.patch("/api/machining-dfm/projects/{project_id}/processes/{process_id}")
    def patch_project_process(project_id: str, process_id: str, payload: dict[str, Any]):
        """改一个格存一个格：工序行级保存。"""
        return {"project": store_factory().update_project_process(project_id, process_id, payload)}

    @router.delete("/api/machining-dfm/projects/{project_id}/processes/{process_id}")
    def delete_project_process(project_id: str, process_id: str, by: str = Query(""),
                               reason: str = Query("")):
        """逻辑删除（永不物理删除）：刀具行一并进回收站，可恢复。"""
        return {"project": store_factory().delete_project_process(project_id, process_id,
                                                                 by=by, reason=reason)}

    @router.post("/api/machining-dfm/projects/{project_id}/processes/{process_id}/restore")
    def restore_project_process(project_id: str, process_id: str):
        return {"project": store_factory().restore_project_process(project_id, process_id)}

    @router.put("/api/machining-dfm/projects/{project_id}/processes/{process_id}/machine")
    def set_project_process_machine(project_id: str, process_id: str, payload: dict[str, Any]):
        """选设备：``{"machine_id": "..."}``（也认老的 ``{"mid": "..."}``）。"""
        return {"project": store_factory().set_project_process_machine(
            project_id, process_id, payload)}

    @router.delete("/api/machining-dfm/projects/{project_id}/processes/{process_id}/machine")
    def clear_project_process_machine(project_id: str, process_id: str):
        """清空这道工序的设备选择（读模型退回兜底机型）。"""
        return {"project": store_factory().clear_project_process_machine(project_id, process_id)}

    @router.post("/api/machining-dfm/projects/{project_id}/processes/reorder")
    def reorder_project_processes(project_id: str, payload: dict[str, Any]):
        ids = payload.get("ids")
        if not isinstance(ids, list):
            raise HTTPException(422, "排序请求必须包含 ids 数组")
        return {"project": store_factory().reorder_project_processes(project_id, ids)}

    @router.put("/api/machining-dfm/projects/{project_id}/processes/{process_id}/photo")
    async def upload_process_photo(project_id: str, process_id: str, request: Request):
        data = await request.body()
        return {
            "project": store_factory().set_process_photo(
                project_id, process_id, "layout", data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/projects/{project_id}/processes/{process_id}/photo")
    def delete_process_photo(project_id: str, process_id: str):
        return {"project": store_factory().clear_process_photo(project_id, process_id)}

    @router.post("/api/machining-dfm/projects/{project_id}/processes/{process_id}/tools")
    def create_project_tool(project_id: str, process_id: str, payload: dict[str, Any]):
        return {"project": store_factory().create_project_tool(project_id, process_id, payload)}

    @router.post("/api/machining-dfm/projects/{project_id}/processes/{process_id}/tools/reorder")
    def reorder_project_tools(project_id: str, process_id: str, payload: dict[str, Any]):
        ids = payload.get("ids")
        if not isinstance(ids, list):
            raise HTTPException(422, "排序请求必须包含 ids 数组")
        return {"project": store_factory().reorder_project_tools(project_id, process_id, ids)}

    @router.patch("/api/machining-dfm/projects/{project_id}/tools/{tool_id}")
    def patch_project_tool(project_id: str, tool_id: str, payload: dict[str, Any]):
        """改一个格存一个格：工序刀具行级保存（含快照价）。"""
        return {"project": store_factory().update_project_tool(project_id, tool_id, payload)}

    @router.delete("/api/machining-dfm/projects/{project_id}/tools/{tool_id}")
    def delete_project_tool(project_id: str, tool_id: str, by: str = Query(""),
                            reason: str = Query("")):
        return {"project": store_factory().delete_project_tool(project_id, tool_id,
                                                              by=by, reason=reason)}

    @router.post("/api/machining-dfm/projects/{project_id}/tools/{tool_id}/restore")
    def restore_project_tool(project_id: str, tool_id: str):
        return {"project": store_factory().restore_project_tool(project_id, tool_id)}

    @router.put("/api/machining-dfm/projects/{project_id}/tools/{tool_id}/photo")
    async def upload_tool_photo(project_id: str, tool_id: str, request: Request):
        data = await request.body()
        return {
            "project": store_factory().set_tool_photo(
                project_id, tool_id, data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/projects/{project_id}/tools/{tool_id}/photo")
    def delete_tool_photo(project_id: str, tool_id: str):
        return {"project": store_factory().clear_tool_photo(project_id, tool_id)}
