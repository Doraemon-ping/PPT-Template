# -*- coding: utf-8 -*-
"""项目：列表 / 新建 / 读取（含指定版本）/ 保存 / 归档 / 逻辑删除 / 恢复 / 版本号列表。

「删除」在本服务里一律是**逻辑删除**（``archived=1``）：项目进"已删除项目"，随时可恢复，
永不物理删除（口径 2）。归档入口是旧版兼容路径，权限口径与新入口一致。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from ...core.security import bearer_token as _bearer
from ..schemas import ProjectWrite


def register(router: APIRouter, store_factory) -> None:
    """挂上项目相关路由。"""

    @router.get("/api/machining-dfm/projects")
    def list_projects(archived: bool = Query(False)):
        return {"projects": store_factory().list(archived)}

    @router.post("/api/machining-dfm/projects")
    def create_project(req: ProjectWrite):
        # 产品路径：新建/另存为带上来的整份读模型**直接拆进各域的表**（口径 7），
        # 新项目从第一秒起就是"表是最小单元"，页面上每行都有行 id、能行级保存
        return store_factory().create(req.name, req.state, import_tables=True)

    @router.get("/api/machining-dfm/projects/{project_id}")
    def get_project(project_id: str, revision: int | None = None, allow_archived: bool = False):
        return store_factory().get(project_id, revision, allow_archived=allow_archived)

    @router.put("/api/machining-dfm/projects/{project_id}")
    def update_project(project_id: str, req: ProjectWrite):
        return store_factory().update(project_id, req.name, req.state, req.revision)

    @router.post("/api/machining-dfm/projects/{project_id}/archive")
    def archive_project(project_id: str, archived: bool = Query(True),
                        authorization: str | None = Header(None)):
        """旧版归档/取消归档入口（页面已改用 ``DELETE /projects/{id}`` + ``/restore``）。

        留着只为兼容老调用方，但**权限口径与新入口一致**：归档等于把项目从列表里拿掉，
        不能让没登录的人干这事。
        """
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return store.archive(project_id, archived)

    @router.delete("/api/machining-dfm/projects/{project_id}")
    def delete_project(project_id: str, by: str = Query(""), reason: str = Query(""),
                       authorization: str | None = Header(None)):
        """项目"删除" = 逻辑删除（``archived=1``）：进"已删除项目"，随时可恢复。"""
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        return {"project": store.delete_project(project_id, by=by or role, reason=reason)}

    @router.post("/api/machining-dfm/projects/{project_id}/restore")
    def restore_project(project_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        return {"project": store.restore_project(project_id, by=role)}

    @router.get("/api/machining-dfm/projects/{project_id}/versions")
    def project_versions(project_id: str):
        return {"versions": store_factory().versions(project_id)}
