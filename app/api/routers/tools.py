# -*- coding: utf-8 -*-
"""刀具库与它依赖的两张字典表（库分类 / 类型）。

刀具是基础库：行级读写、图片走附件库、删除是逻辑删除。删除被引用的刀具**不阻塞**
（项目工序行自带刀具参数快照，只有刀柄/配件价格按名称查库），仅回一个 ``usage`` 提示。

字典表可以在管理设置里改名称、调顺序、加类型；**内置项删不掉**（409），被刀具引用的项也删不掉。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from ...core.security import bearer_token as _bearer


def register(router: APIRouter, store_factory) -> None:
    """挂上刀具库与刀具字典路由。"""

    @router.get("/api/machining-dfm/tools/fields")
    def tool_fields():
        return store_factory().tool_fields()

    @router.get("/api/machining-dfm/tools")
    def list_tools():
        store = store_factory()
        return {
            "tools": store.tools.list_typed(),
            "fields": store.tool_fields(),
            "count": store.tools.count(),
        }

    @router.post("/api/machining-dfm/tools/reorder")
    def reorder_tools(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        ids = payload.get("ids")
        if not isinstance(ids, list):
            raise HTTPException(422, "排序请求必须包含 ids 数组")
        return {"tools": store.tools.reorder(ids)}

    @router.post("/api/machining-dfm/tools")
    def create_tool(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"tool": store.tools.create(payload), "count": store.tools.count()}

    @router.patch("/api/machining-dfm/tools/{tool_id}")
    def update_tool(tool_id: str, payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"tool": store.tools.update(tool_id, payload)}

    @router.delete("/api/machining-dfm/tools/{tool_id}")
    def delete_tool(tool_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        row = store.tools.find(tool_id)
        # 项目工序行自带刀具参数，只有刀柄/配件价格按名称查库：删除不阻塞，仅提示引用。
        usage = store.tool_usage(row["name"], row["tool_group"]) if row is not None else []
        return {"removed": store.tools.delete(tool_id, by=role), "usage": usage}

    @router.put("/api/machining-dfm/tools/{tool_id}/photo")
    async def upload_tool_photo(tool_id: str, request: Request, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        data = await request.body()
        return {
            "tool": store.tools.set_attachment(
                tool_id, "photo", data, request.headers.get("content-type")
            )
        }

    @router.delete("/api/machining-dfm/tools/{tool_id}/photo")
    def delete_tool_photo(tool_id: str, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"tool": store.tools.clear_attachment(tool_id, "photo")}

    @router.get("/api/machining-dfm/tool-dictionaries")
    def tool_dictionaries():
        store = store_factory()
        return store.tool_dictionaries()

    @router.post("/api/machining-dfm/tool-groups")
    def create_tool_group(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"group": store.tool_dict.create_group(payload)}

    @router.patch("/api/machining-dfm/tool-groups/{code}")
    def update_tool_group(code: str, payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"group": store.tool_dict.update_group(code, payload)}

    @router.delete("/api/machining-dfm/tool-groups/{code}")
    def delete_tool_group(code: str, authorization: str | None = Header(None)):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        return {"removed": store.tool_dict.delete_group(code, by=role)}

    @router.post("/api/machining-dfm/tool-categories")
    def create_tool_category(payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"category": store.tool_dict.create_category(payload)}

    @router.patch("/api/machining-dfm/tool-categories/{code}")
    def update_tool_category(code: str, payload: dict[str, Any], authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"category": store.tool_dict.update_category(code, payload)}

    @router.delete("/api/machining-dfm/tool-categories/{code}")
    def delete_tool_category(code: str, authorization: str | None = Header(None)):
        store = store_factory()
        role = store.authorize(_bearer(authorization), "admin")
        return {"removed": store.tool_dict.delete_category(code, by=role)}
