# -*- coding: utf-8 -*-
"""**兼容转发层（历史启动入口）** —— 应用本身在 ``app.main``。

历史命令 ``uvicorn app.services.machining:app --port 8002`` 与老文档、``run_service.py``、
``_audit/`` 下的探针都还在用这个路径，所以这里继续暴露 ``app``，但**只是转发**：
应用的组装（路由、数据源契约、日志、静态页面）全在 ``app.main.create_app()``。

新命令请用 ``uvicorn app.main:app --port 8002``。
"""
from __future__ import annotations

from ..main import SERVICE_CONTRACT_VERSION, SERVICE_TITLE, app, create_app  # noqa: F401

__all__ = ["app", "create_app", "SERVICE_TITLE", "SERVICE_CONTRACT_VERSION"]
