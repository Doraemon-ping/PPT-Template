# -*- coding: utf-8 -*-
"""通用工具：时间戳与 JSON 序列化口径。

这里只放**与业务无关**的小工具，而且必须是"全项目只有一种做法"的那几个：
时间戳怎么取、JSON 怎么序列化、数字怎么写。放在 ``app/core/`` 里，任何一层都能往下引用它。

**为什么不各写各的**：同一个值（尤其是 ``created``/``updated`` 这类时间戳，以及算出来的数字）
如果用不同口径写进库，读模型字节就会悄悄变化，历史快照 diff 与成本基线比对会出现假差异。
所以统一到这里，改就一起改。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def stamp() -> str:
    """当前时间：UTC ISO-8601 字符串（库里所有 ``created``/``updated`` 列统一用它）。

    统一用 UTC 而不是本地时间：不会因为时区漂移或夏令时产生"看起来倒退"的时间戳，
    历史快照与审计流水才能按字符串直接排序比对。
    """
    return datetime.now(timezone.utc).isoformat()


def compact_json(value: Any) -> str:
    """紧凑 JSON（不转义中文、无多余空格）—— 写进库的 JSON 一律用它。

    ``ensure_ascii=False``：中文按原字符存，库文件人能直接读，体积也更小。
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def js_number(value: Any) -> Any:
    """按 JS 的 JSON 数字序列化规则归一：整数值不带小数点（``32.0`` → ``32``）。

    前端算出来的 ``_ct`` 在 JS 里 ``JSON.stringify(32.0)`` 就是 ``32``；服务端若原样写 ``32.0``，
    数值相同但读模型字节会变，历史快照 diff 与成本基线比对会出现假差异。
    """
    if isinstance(value, float) and value.is_integer() and abs(value) < 2 ** 53:
        return int(value)
    return value
