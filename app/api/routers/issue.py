# -*- coding: utf-8 -*-
"""问题清单（阶段 2a）行级接口。

与工序同一套写法：行级 PATCH、排序、逻辑删除（回收站可恢复）、图片走附件库；
每次写都递增项目版本并留一个版本快照。外键：``process_id`` → ``project_processes``。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request


def register(router: APIRouter, store_factory) -> None:
    """挂上问题清单路由。"""

    @router.get("/api/machining-dfm/projects/{project_id}/issues")
    def list_project_issues(project_id: str, include_deleted: bool = Query(False)):
        return store_factory().project_issues(project_id, include_deleted=include_deleted)

    @router.post("/api/machining-dfm/projects/{project_id}/issues")
    def create_project_issue(project_id: str, payload: dict[str, Any]):
        return {"project": store_factory().create_project_issue(project_id, payload)}

    @router.patch("/api/machining-dfm/projects/{project_id}/issues/{issue_id}")
    def patch_project_issue(project_id: str, issue_id: str, payload: dict[str, Any]):
        """改一个格存一个格：问题清单行级保存。"""
        return {"project": store_factory().update_project_issue(project_id, issue_id, payload)}

    @router.delete("/api/machining-dfm/projects/{project_id}/issues/{issue_id}")
    def delete_project_issue(project_id: str, issue_id: str, by: str = Query(""),
                             reason: str = Query("")):
        """逻辑删除（永不物理删除）：进回收站，可恢复。"""
        return {"project": store_factory().delete_project_issue(project_id, issue_id,
                                                                by=by, reason=reason)}

    @router.post("/api/machining-dfm/projects/{project_id}/issues/{issue_id}/restore")
    def restore_project_issue(project_id: str, issue_id: str):
        return {"project": store_factory().restore_project_issue(project_id, issue_id)}

    @router.post("/api/machining-dfm/projects/{project_id}/issues/reorder")
    def reorder_project_issues(project_id: str, payload: dict[str, Any]):
        return {"project": store_factory().reorder_project_issues(
            project_id, payload.get("ids") or [])}

    @router.put("/api/machining-dfm/projects/{project_id}/issues/{issue_id}/photo/{slot}")
    async def upload_issue_photo(project_id: str, issue_id: str, slot: str, request: Request):
        data = await request.body()
        return {
            "project": store_factory().set_issue_photo(
                project_id, issue_id, slot, data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/projects/{project_id}/issues/{issue_id}/photo/{slot}")
    def delete_issue_photo(project_id: str, issue_id: str, slot: str):
        return {"project": store_factory().clear_issue_photo(project_id, issue_id, slot)}
