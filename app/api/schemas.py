# -*- coding: utf-8 -*-
"""请求体模型（Pydantic）。

只声明**传输形状与边界**（长度、范围），字段含义与业务约束由 domain/service 层负责：
这里宽松、下层严格，报错才是说人话的中文 ``HTTPException``（422），而不是 pydantic 的英文校验文本。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectWrite(BaseModel):
    """整份项目读写（``POST`` 新建 / ``PUT`` 保存）。"""

    name: str = Field(min_length=1, max_length=160)
    state: dict[str, Any]
    revision: int | None = None


class LibraryWrite(BaseModel):
    """整库存档保存（兼容入口，只为缓存了旧 JS 的页面保留）。

    ``mdb`` / ``tdb`` 已独立成表：仍然接受旧页面的整体保存，映射到类型化表。
    """

    mdb: list[dict[str, Any]] | None = None
    tdb: list[dict[str, Any]] | None = None
    fdb: list[dict[str, Any]]
    idb: list[dict[str, Any]]
    icnX: list[str] = Field(default_factory=list)
    fcnX: list[str] = Field(default_factory=list)


class LoginRequest(BaseModel):
    """后台登录。"""

    role: str
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    """改密（新口令至少 6 位）。"""

    role: str
    password: str = Field(min_length=6, max_length=256)


class SettingsWrite(BaseModel):
    """后台配置。"""

    site_title: str = Field(min_length=1, max_length=100)
    autosave_ms: int = Field(ge=500, le=10_000)
