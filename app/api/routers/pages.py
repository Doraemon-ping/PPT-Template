# -*- coding: utf-8 -*-
"""页面与引导：单页应用入口、启动引导、项目默认值。

``bootstrap`` 是页面打开时的第一条请求：一次拿全"当前项目 + 项目列表 + 后台配置"，
省得前端再串三次请求。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


def register(router: APIRouter, store_factory, static_dir: Path) -> None:
    """挂上页面与引导路由。"""

    @router.get("/machining-dfm")
    def machining_dfm_page():
        return FileResponse(Path(static_dir) / "machining_dfm" / "index.html")

    @router.get("/api/machining-dfm/bootstrap")
    def bootstrap(project_id: str | None = None):
        store = store_factory()
        active = store.list(False)
        if not active:
            raise HTTPException(409, "没有可打开的项目，请先恢复一个已删除项目")
        selected = project_id or active[0]["id"]
        return {
            "project": store.get(selected), "projects": active,
            "config": store.public_settings(), "data_dir": str(store.root),
        }

    @router.get("/api/machining-dfm/defaults")
    def project_defaults():
        return store_factory().defaults()
