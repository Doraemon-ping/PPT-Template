# -*- coding: utf-8 -*-
"""应用工厂：``create_app()`` 组装 FastAPI 应用。

启动方式（二选一，等价）::

    uvicorn app.main:app --port 8002          # 推荐（标准入口）
    uvicorn app.services.machining:app --port 8002   # 历史入口，仍然可用

``app.services.machining`` 是本模块的**兼容转发层**：老文档、老脚本、`run_services.py`
都还在用那个导入路径，所以它继续存在，但只做转发与再导出，不再自己组装应用。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api.deps import build_store
from .api.routers import router_for
from .core.config import STATIC_DIR
from .services.observability import install as install_logging
from .services.provider_api import install_machining

SERVICE_TITLE = "机加 DFM 表单服务"
SERVICE_CONTRACT_VERSION = "1.0"


def _guard_logs(authorization: str | None) -> None:
    """服务日志里有项目名、项目 id 和全部请求路径，只给管理员看（与后台配置同一套密码）。"""
    from .core.security import bearer_token

    build_store().authorize(bearer_token(authorization), "admin")


def create_app() -> FastAPI:
    """构造机加 DFM 应用：路由 + 数据源契约 + 日志 + 静态页面。"""
    application = FastAPI(title=SERVICE_TITLE, version="2.0")
    application.state.log_file = install_logging(application, "machining_dfm", _guard_logs)
    application.include_router(router_for(build_store, STATIC_DIR))
    install_machining(application, build_store)

    @application.get("/")
    def home():
        return RedirectResponse("/machining-dfm")

    @application.get("/health")
    def health():
        return {"service": "machining", "contract_version": SERVICE_CONTRACT_VERSION}

    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return application


#: ASGI 入口：``uvicorn app.main:app``
app = create_app()

__all__ = ["create_app", "app", "SERVICE_TITLE", "SERVICE_CONTRACT_VERSION"]
