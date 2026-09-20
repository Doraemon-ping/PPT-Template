# -*- coding: utf-8 -*-
"""回收站（阶段 4）：逻辑删除的行怎么查、怎么恢复。

**永不物理删除**是本服务的硬口径：项目"删除"= ``archived=1``，业务行"删除"= 写
``deleted_at/by/reason``。因此回收站有两条读路径与一个恢复入口：

* ``GET /projects/{pid}/trash``：**本项目**被逻辑删除的业务行（工序/刀具行/问题/选型/履历）；
* ``GET /trash``：全局 —— 已删除项目 + 8 张基础库与字典表的已删行，每条带被几个项目引用；
* ``POST /trash/{table}/{id}/restore``：按表名白名单恢复（**仅管理员**）。

没有"彻底删除"，也没有保留期（口径 2）。
"""
from __future__ import annotations

from fastapi import APIRouter, Header

from ...core.security import bearer_token as _bearer


def register(router: APIRouter, store_factory) -> None:
    """挂上回收站路由（查看给两个角色，恢复只给管理员）。"""

    @router.get("/api/machining-dfm/projects/{project_id}/trash")
    def project_trash(project_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "process")
        return store.project_trash(project_id)

    @router.get("/api/machining-dfm/trash")
    def library_trash(authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "process")
        return store.library_trash()

    @router.post("/api/machining-dfm/trash/{table}/{record_id}/restore")
    def restore_trash_row(table: str, record_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        return {"restored": store.restore_trash_row(table, record_id, by=role)}
