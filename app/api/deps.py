# -*- coding: utf-8 -*-
"""接口层依赖：按请求造 store。

**为什么每次请求都新建 store**：store 的构造会跑一遍幂等迁移（并读一次能力级别开关），
所以后台改配置、``tools/migrate_*.py --apply`` 跑完迁移之后**不用重启服务**，
下一个请求就切到新结构上。代价只是开一次 SQLite 连接 —— 相对单页应用的请求量可以忽略。

各路由不直接用 ``Depends(get_store)``，而是仍然接收 ``store_factory`` 可调用对象：
这样 ``router_for(store_factory, static_dir)`` 与拆分前签名一致，测试里
``app.include_router(router_for(lambda: store, tmp_path / "static"))`` 照旧能跑。
"""
from __future__ import annotations

from pathlib import Path

from ..core.config import BASE_DIR, DATA_DIR, SEED_DIR
from ..services.store import MachiningDFMStore

#: 运行期数据目录（``data/machining_dfm/``）：库文件与附件都在这里
ROOT_DIR = DATA_DIR / "machining_dfm"
#: 首次建库用的种子数据。``SEED_DIR`` 是**拆分成文件的种子目录**
#: （``project.json`` / ``machines.json`` / ``categories.json`` …）；
#: ``SeedBundle`` 也认老的单文件种子，那时按老口径翻译 ``pr[].mi`` 下标。
SEED_FILE = SEED_DIR


def build_store(root: Path | None = None, seed: Path | None = None) -> MachiningDFMStore:
    """造一个 store（默认指向运行期数据目录与种子文件）。"""
    return MachiningDFMStore(root or ROOT_DIR, seed or SEED_FILE)


def get_store_dependency():
    """FastAPI 依赖形式：``Depends(store_dependency)``。"""
    return build_store()


#: 传给 ``router_for`` 的工厂：每次调用造一个新 store（见模块 docstring）
store_factory = build_store


def resolve_seed() -> Path:
    """种子文件的绝对路径（供启动自检与文档用）。"""
    return Path(SEED_FILE).resolve()


__all__ = ["ROOT_DIR", "SEED_FILE", "BASE_DIR", "build_store", "store_factory",
           "get_store_dependency", "resolve_seed"]
