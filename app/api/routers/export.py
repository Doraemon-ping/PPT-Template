# -*- coding: utf-8 -*-
"""导出文件包（阶段 5 · 口径 §7.0）。

便携单文件 HTML 已退休：导出改成两条能兑现的路 —— 前端「导出 JSON」（单文件、图内联）
与这条「导出文件包」（zip：``project.json`` + 本项目引用到的附件原图 + ``README.txt``）。

**只读**：GET、不落库、不写 ``data/``；项目已删除也能出包（与读同一口径）。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from ...services.export import content_disposition


def register(router: APIRouter, store_factory) -> None:
    """挂上导出文件包路由。"""

    @router.get("/api/machining-dfm/projects/{project_id}/export.zip")
    def export_project_package(project_id: str):
        """导出该项目为 zip 文件包（``project.json`` + ``assets/<id>.<ext>`` + ``README.txt``）。

        包内 ``project.json`` 与 ``GET /projects/{pid}`` 同一份形状，附件字段换成包内相对路径。
        """
        filename, payload = store_factory().export_package(project_id)
        return Response(
            content=payload,
            media_type="application/zip",
            headers={
                "content-disposition": content_disposition(filename),
                "cache-control": "no-store",
            },
        )
