# -*- coding: utf-8 -*-
"""夹具库 / 检具库，以及它们的两张类别字典（模具中心 / 检具类别）、附件下载、整库存档保存。

夹具库与检具库的行级接口**完全同构**（与设备库、刀具库同一套约定），所以用
``register_typed_library`` 生成两遍；类别字典同理走 ``register_named_dictionary``。
字典删除默认被引用就 409（内置项一律 409），要 ``cascade=1`` 才连同数据一起删。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from ...core.security import bearer_token as _bearer
from ..schemas import LibraryWrite


def register(router: APIRouter, store_factory) -> None:
    """挂上夹具/检具库、类别字典、附件下载与整库存档路由。"""

    def register_typed_library(name: str, singular: str, label: str, library_getter,
                               fields_getter, usage_getter) -> None:
        """夹具库/检具库共用的行级接口（与设备库、刀具库同一套约定）。"""

        @router.get(f"/api/machining-dfm/{name}/fields", name=f"{name}_fields")
        def library_fields():
            return fields_getter(store_factory())

        @router.get(f"/api/machining-dfm/{name}", name=f"list_{name}")
        def library_list():
            store = store_factory()
            library = library_getter(store)
            return {
                name: library.list_typed(),
                "fields": fields_getter(store),
                "count": library.count(),
            }

        @router.post(f"/api/machining-dfm/{name}/reorder", name=f"reorder_{name}")
        def library_reorder(payload: dict[str, Any], authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            ids = payload.get("ids")
            if not isinstance(ids, list):
                raise HTTPException(422, "排序请求必须包含 ids 数组")
            return {name: library_getter(store).reorder(ids)}

        @router.post(f"/api/machining-dfm/{name}", name=f"create_{name}")
        def library_create(payload: dict[str, Any], authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            library = library_getter(store)
            return {singular: library.create(payload), "count": library.count()}

        @router.patch(f"/api/machining-dfm/{name}/{{row_id}}", name=f"update_{name}")
        def library_update(row_id: str, payload: dict[str, Any], authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            return {singular: library_getter(store).update(row_id, payload)}

        @router.delete(f"/api/machining-dfm/{name}/{{row_id}}", name=f"delete_{name}")
        def library_delete(row_id: str, authorization: str | None = Header(None)):
            store = store_factory()
            role = store.authorize(_bearer(authorization), "admin")
            library = library_getter(store)
            row = library.find(row_id)
            usage = usage_getter(store, row) if row else []
            # 项目侧按名称拼的选择键引用本库，删除不阻塞，只回报哪些项目在用
            # 口径 2：逻辑删除（回收站可恢复），谁删的记在行上
            return {"removed": library.delete(row_id, by=role), "usage": usage}

        @router.put(f"/api/machining-dfm/{name}/{{row_id}}/photo", name=f"upload_{name}_photo")
        async def library_photo(row_id: str, request: Request, authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            data = await request.body()
            return {
                singular: library_getter(store).set_attachment(
                    row_id, "photo", data, request.headers.get("content-type")
                )
            }

        @router.delete(f"/api/machining-dfm/{name}/{{row_id}}/photo", name=f"clear_{name}_photo")
        def library_photo_clear(row_id: str, authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            return {singular: library_getter(store).clear_attachment(row_id, "photo")}

    def register_named_dictionary(name: str, label: str, dictionary_getter, usage_getter) -> None:
        """类别字典接口：增、改顺序、删（默认 409，带 cascade=1 连同数据一起删）。"""

        @router.get(f"/api/machining-dfm/{name}", name=f"list_{name}")
        def dictionary_list():
            store = store_factory()
            return {"rows": dictionary_getter(store).names(), "usage": usage_getter(store)}

        @router.post(f"/api/machining-dfm/{name}", name=f"create_{name}")
        def dictionary_create(payload: dict[str, Any], authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            return {"row": dictionary_getter(store).create(payload)}

        @router.patch(f"/api/machining-dfm/{name}/{{item}}", name=f"update_{name}")
        def dictionary_update(item: str, payload: dict[str, Any], authorization: str | None = Header(None)):
            store = store_factory()
            store.authorize(_bearer(authorization), "admin")
            return {"row": dictionary_getter(store).update(item, payload)}

        @router.delete(f"/api/machining-dfm/{name}/{{item}}", name=f"delete_{name}")
        def dictionary_delete(
            item: str, cascade: int = 0, authorization: str | None = Header(None)
        ):
            store = store_factory()
            role = store.authorize(_bearer(authorization), "admin")
            return {"removed": dictionary_getter(store).delete(
                item, cascade=bool(cascade), by=role)}

    register_typed_library(
        "fixtures",
        "fixture",
        "夹具",
        lambda store: store.fixtures,
        lambda store: store.fixture_fields(),
        lambda store, row: store.fixture_usage(row["center"], row["name"]),
    )
    register_typed_library(
        "gauges",
        "gauge",
        "检具",
        lambda store: store.gauges,
        lambda store: store.gauge_fields(),
        lambda store, row: store.gauge_usage(row["category"], row["name"], row["drawing"]),
    )
    register_named_dictionary(
        "fixture-centers", "模具中心", lambda store: store.fixture_centers,
        lambda store: store.fixture_centers.usage(),
    )
    register_named_dictionary(
        "gauge-categories", "检具类别", lambda store: store.gauge_categories,
        lambda store: store.gauge_categories.usage(),
    )

    @router.get("/api/machining-dfm/library-dictionaries")
    def library_dictionaries():
        return store_factory().library_dictionaries()

    @router.get("/api/machining-dfm/assets/{asset_id}")
    def get_asset(
        asset_id: str,
        download: bool = Query(False),
        if_none_match: str | None = Header(None),
    ):
        store = store_factory()
        record, path = store.asset(asset_id)
        etag = f'"{record["sha256"]}"'
        headers = {"cache-control": "private, max-age=86400", "etag": etag}
        # 内容寻址 + 内容 ETag：客户端带着同一个 ETag 回来即内容未变。
        if if_none_match and if_none_match.strip() in {etag, record["sha256"]}:
            return Response(status_code=304, headers=headers)
        if download:
            suffix = Path(record["path"]).suffix
            return FileResponse(
                path,
                media_type=record["mime"],
                filename=record["name"] or f"{asset_id}{suffix}",
                headers=headers,
            )
        return FileResponse(path, media_type=record["mime"], headers=headers)

    # ---------------- 兼容入口（整库保存：只为缓存了旧 JS 的页面保留） ----------------

    @router.get("/api/machining-dfm/libraries")
    def get_libraries():
        store = store_factory()
        libraries = store.libraries()
        return {
            "libraries": libraries,
            "counts": {
                "mdb": store.machines.count(),
                "tdb": store.tools.count(),
                "fdb": store.fixtures.count(),
                "idb": store.gauges.count(),
            },
        }

    @router.put("/api/machining-dfm/libraries")
    def update_libraries(req: LibraryWrite, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return {"ok": True, "counts": store.replace_libraries(req.model_dump())}
