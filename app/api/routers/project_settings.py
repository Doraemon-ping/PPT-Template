# -*- coding: utf-8 -*-
"""项目信息（``G`` 的建模字段）与项目图片。

项目信息已独立成表：逐字段读写在 ``project_settings`` 一行里，项目图片走附件库；
旧键 ``G`` 由读模型精确还原，所以老页面与 PPT 数据源契约一个字都不用改。

``PATCH`` 是"改一个格存一个格"，``PUT`` 是整份保存（旧页面/批量导入用）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request


def register(router: APIRouter, store_factory) -> None:
    """挂上项目信息与项目图片路由。"""

    @router.get("/api/machining-dfm/project-settings/fields")
    def project_settings_fields():
        return store_factory().project_settings_fields()

    @router.get("/api/machining-dfm/projects/{project_id}/settings")
    def get_project_settings(project_id: str):
        return store_factory().project_settings(project_id)

    @router.patch("/api/machining-dfm/projects/{project_id}/settings")
    def patch_project_settings(project_id: str, payload: dict[str, Any]):
        """改一个格存一个格：项目信息行级保存（同时递增项目版本并留快照）。"""
        return {"project": store_factory().save_project_settings(project_id, payload, partial=True)}

    @router.put("/api/machining-dfm/projects/{project_id}/settings")
    def put_project_settings(project_id: str, payload: dict[str, Any]):
        """整份项目信息保存（旧页面／批量导入用）。"""
        return {"project": store_factory().save_project_settings(project_id, payload, partial=False)}

    @router.put("/api/machining-dfm/projects/{project_id}/photos/{slot}")
    async def upload_project_photo(project_id: str, slot: str, request: Request):
        data = await request.body()
        return {
            "project": store_factory().set_project_photo(
                project_id, slot, data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/projects/{project_id}/photos/{slot}")
    def delete_project_photo(project_id: str, slot: str):
        return {"project": store_factory().clear_project_photo(project_id, slot)}
