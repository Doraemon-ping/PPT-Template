# -*- coding: utf-8 -*-
"""后台配置与登录：站点标题 / 自动保存间隔、登录、改密。

后台配置与登录**共用一套口令**（``auth_settings`` 表按角色存 PBKDF2 摘要），
登录成功后签发 8 小时 HMAC 令牌；后续写接口靠 ``Authorization: Bearer`` 过 ``authorize``。
"""
from __future__ import annotations

from fastapi import APIRouter, Header

from ...core.security import bearer_token as _bearer
from ..schemas import LoginRequest, PasswordChange, SettingsWrite


def register(router: APIRouter, store_factory) -> None:
    """挂上后台配置与登录路由。"""

    @router.get("/api/machining-dfm/config")
    def get_config():
        return store_factory().public_settings()

    @router.put("/api/machining-dfm/config")
    def update_config(req: SettingsWrite, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        return store.update_settings(req.site_title, req.autosave_ms)

    @router.post("/api/machining-dfm/auth/login")
    def login(req: LoginRequest):
        return store_factory().login(req.role, req.password)

    @router.put("/api/machining-dfm/auth/password")
    def change_password(req: PasswordChange, authorization: str | None = Header(None)):
        store = store_factory()
        store.authorize(_bearer(authorization), "admin")
        store.change_password(req.role, req.password)
        return {"ok": True, "role": req.role}
