# -*- coding: utf-8 -*-
"""**兼容转发层（历史导入路径）** —— 只做再导出，不实现任何逻辑。

2026-09 的分层重构把原来的单文件 ``app/machining_dfm.py``（3655 行）拆成了标准 FastAPI
分层结构。这个模块**只为兼容而保留**：``tools/`` 下 30 多个历史迁移/审计脚本、
``tests/`` 里的老导入、以及 ``_audit/`` 下的探针都还在写 ``from app.machining_dfm import …``，
所以这里把旧名字原样再导出一遍，让它们一行都不用改。

**新代码请直接用真实位置**：

===============================  ================================================
旧名字（本模块）                  真实位置
===============================  ================================================
``MachiningDFMStore``            ``app.services.store``
``router_for``                   ``app.api.routers``
``_bearer``                      ``app.core.security.bearer_token``
``PROJECT_ARRAYS``/``SCHEMA``    ``app.services.store`` / ``app.db.schema``
``LEGACY_*``/``*_SCHEMA_VERSION`` ``app.db.schema``
``BUSINESS_VERSION`` 等版本号     各自的 ``app.domains.*`` 模块
===============================  ================================================

依赖方向不变：本模块在最外层，**任何实现模块都不许反过来导入它**。
"""
from __future__ import annotations

# ---- 组合根：项目 / 基础库 / 后台数据 ----
from .db.schema import (  # noqa: F401
    FIXTURE_SCHEMA_VERSION,
    GAUGE_SCHEMA_VERSION,
    LEGACY_LIBRARY_TABLES,
    LEGACY_REVISIONS_SCHEMA,
    LIBRARY_KEYS,
    MACHINE_SCHEMA_VERSION,
    PROJECT_SCHEMA_VERSION,
    SCHEMA,
    TOOL_SCHEMA_VERSION,
)
from .api.routers import router_for  # noqa: F401
from .core.security import DEFAULT_PASSWORDS, PASSWORD_ITERATIONS, bearer_token as _bearer  # noqa: F401
from .domains.changes import CHANGES_VERSION  # noqa: F401
from .domains.history import HISTORY_VERSION  # noqa: F401
from .domains.issue import ISSUE_VERSION  # noqa: F401
from .domains.process import BUSINESS_VERSION  # noqa: F401
from .domains.selection import LEGACY_SELECTION_TABLE, SELECTION_VERSION  # noqa: F401
from .services.store import MAX_STATE_BYTES, PROJECT_ARRAYS, MachiningDFMStore  # noqa: F401

__all__ = [
    "MachiningDFMStore", "router_for", "PROJECT_ARRAYS", "MAX_STATE_BYTES",
    "SCHEMA", "LEGACY_REVISIONS_SCHEMA", "LEGACY_LIBRARY_TABLES", "LIBRARY_KEYS",
    "LEGACY_SELECTION_TABLE", "CHANGES_VERSION", "HISTORY_VERSION", "ISSUE_VERSION",
    "SELECTION_VERSION", "BUSINESS_VERSION", "MACHINE_SCHEMA_VERSION",
    "TOOL_SCHEMA_VERSION", "FIXTURE_SCHEMA_VERSION", "GAUGE_SCHEMA_VERSION",
    "PROJECT_SCHEMA_VERSION", "DEFAULT_PASSWORDS", "PASSWORD_ITERATIONS", "_bearer",
]
