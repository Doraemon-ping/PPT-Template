# -*- coding: utf-8 -*-
"""选型（阶段 2b）：夹具选型 ``fixtures`` / 检具选型 ``gauges``，以及版本履历与变更流水。

坐标是 **(格子下标)**，格子顺序 = 类别字典顺序（夹具按模具中心、检具按检具类别）。
两条路径完全同构，所以用同一段生成逻辑挂两遍，不再有 ``kind`` 参数满天飞。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ...domains.selection import KIND_FIXTURE, KIND_GAUGE


def register(router: APIRouter, store_factory) -> None:
    """挂上选型路由（两个页签各打各的 + 一个老的"两类一起给"兼容入口）。"""

    def _selection_routes(kind: str, path: str, label: str, id_key: str) -> None:
        @router.get(f"/api/machining-dfm/projects/{{project_id}}/{path}")
        def list_selection(project_id: str, _kind: str = kind):
            return store_factory().project_selection(project_id, _kind)

        @router.put(f"/api/machining-dfm/projects/{{project_id}}/{path}/{{slot}}")
        def put_selection(project_id: str, slot: int, payload: dict[str, Any], _kind: str = kind):
            """选一格：``{id_key: …}``（库行 id）或 ``{"legacy_key": "类别|名称"}``。"""
            return {"project": store_factory().save_project_selection(
                project_id, _kind, slot, payload)}

        # 兼容语义：有的前端习惯用 PATCH 表达"改这一格的某一个字段"（例如只改"是否报价"）
        @router.patch(f"/api/machining-dfm/projects/{{project_id}}/{path}/{{slot}}")
        def patch_selection(project_id: str, slot: int, payload: dict[str, Any], _kind: str = kind):
            return {"project": store_factory().save_project_selection(
                project_id, _kind, slot, payload)}

        @router.delete(f"/api/machining-dfm/projects/{{project_id}}/{path}/{{slot}}")
        def delete_selection(project_id: str, slot: int, _kind: str = kind):
            """清空一格（行保留，"是否报价"的勾选也留着，历史在版本里可查）。"""
            return {"project": store_factory().clear_project_selection(project_id, _kind, slot)}

    _selection_routes(KIND_FIXTURE, "fixtures", "夹具选型", "fixture_id")
    _selection_routes(KIND_GAUGE, "gauges", "检具选型", "gauge_id")

    # 老接口：两类一起给（``slots`` 按 kind 分组），页面已改成两个页签各打各的
    @router.get("/api/machining-dfm/projects/{project_id}/selections")
    def list_project_selections(project_id: str):
        return store_factory().project_selections(project_id)

    # ---- 版本履历（3a）：一行 = 页面上那四个格子（日期/版本号/变更内容/变更人） ----

    @router.get("/api/machining-dfm/projects/{project_id}/history")
    def list_project_history(project_id: str, recycle: bool = Query(False)):
        """在用的履历行；``recycle=true`` 给回收站（逻辑删除的行）。"""
        return store_factory().project_history(project_id, recycle=recycle)

    @router.post("/api/machining-dfm/projects/{project_id}/history")
    def create_project_history(project_id: str, payload: dict[str, Any] | None = None):
        return {"project": store_factory().create_project_history(project_id, payload)}

    @router.patch("/api/machining-dfm/projects/{project_id}/history/{record_id}")
    def patch_project_history(project_id: str, record_id: str, payload: dict[str, Any]):
        """改一个格存一个格：``{"dt": "2026-09-18"}`` / ``{"ds": "改了什么"}``。"""
        return {"project": store_factory().save_project_history(project_id, record_id, payload)}

    @router.delete("/api/machining-dfm/projects/{project_id}/history/{record_id}")
    def delete_project_history(project_id: str, record_id: str, by: str = Query(""),
                               reason: str = Query("")):
        """逻辑删除（永不物理删除）：进回收站，可恢复。"""
        return {"project": store_factory().delete_project_history(project_id, record_id,
                                                                 by=by, reason=reason)}

    @router.post("/api/machining-dfm/projects/{project_id}/history/{record_id}/restore")
    def restore_project_history(project_id: str, record_id: str):
        return {"project": store_factory().restore_project_history(project_id, record_id)}

    @router.post("/api/machining-dfm/projects/{project_id}/history/reorder")
    def reorder_project_history(project_id: str, payload: dict[str, Any]):
        return {"project": store_factory().reorder_project_history(
            project_id, payload.get("ids") or [])}

    # ---- 变更流水（阶段 3b，只读）：一行 = 一次改动里的一个实体，由行级写入点自动记录 ----

    @router.get("/api/machining-dfm/projects/{project_id}/changes")
    def list_project_changes(project_id: str, limit: int = Query(200), entity: str = Query(""),
                             action: str = Query(""), recycle: bool = Query(False)):
        return store_factory().project_changes(project_id, limit=limit, entity=entity,
                                               action=action, recycle=recycle)
