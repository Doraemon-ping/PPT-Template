# -*- coding: utf-8 -*-
"""接口层：HTTP 适配（路由、请求模型、依赖、数据源契约出口）。

本层只做三件事：解析请求 → 调 ``app.services`` → 组装响应。**不放业务规则**，
也不直接写 SQL；依赖方向永远是 ``api → services → domains → db → core``。
"""
