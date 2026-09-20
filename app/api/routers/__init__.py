# -*- coding: utf-8 -*-
"""机加 DFM 表单路由聚合。

一个业务域一个模块，每个模块只导出 ``register(router, store_factory)``；
本模块只负责**按顺序把它们挂到同一个 APIRouter 上**，是所有 ``/api/machining-dfm/*``
路径的唯一清单（想知道"这个接口在哪"，看这里再去对应模块）。

``router_for(store_factory, static_dir)`` 的签名与拆分前**完全一致**，
所以 ``app/services/machining.py``、测试与 ``tools/list_machining_routes.py`` 都不用改。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from . import (
    admin,
    export,
    issue,
    libraries,
    machines,
    pages,
    process,
    project_settings,
    projects,
    selection,
    tools,
    trash,
)

#: 注册顺序 = 路由匹配顺序。路径互不重叠，顺序只影响 ``/docs`` 里的展示次序。
REGISTRARS = (
    pages,             # 单页入口 + 引导 + 项目默认值
    projects,          # 项目列表 / 新建 / 读写 / 归档 / 删除 / 恢复 / 版本号
    trash,             # 回收站
    export,            # 导出文件包
    project_settings,  # 项目信息与项目图片
    issue,             # 问题清单
    selection,         # 夹具/检具选型 + 版本履历 + 变更流水
    process,           # 工序 / 工序设备 / 工序图片 / 工序刀具行
    machines,          # 设备库
    tools,             # 刀具库 + 刀具字典
    libraries,         # 夹具库 / 检具库 + 类别字典 + 附件下载 + 整库存档
    admin,             # 后台配置 + 登录 + 改密
)


def router_for(store_factory, static_dir: Path) -> APIRouter:
    """组装机加 DFM 的全部路由。

    ``store_factory`` 是"按请求造一个 store"的可调用对象（见 ``app/api/deps.py``）：
    每次请求都用新连接读一次库，所以后台改配置、跑完迁移**不用重启服务**。
    """
    router = APIRouter()
    for module in REGISTRARS:
        if module is pages:
            module.register(router, store_factory, static_dir)
        else:
            module.register(router, store_factory)
    return router


__all__ = ["router_for", "REGISTRARS"]
