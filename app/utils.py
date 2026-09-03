# -*- coding: utf-8 -*-
"""通用工具函数（对应原 HTML 中的 num / fmt / esc / T 等）。"""
import math


def num(v):
    """JS parseFloat 语义：可解析为有限数则返回 float，否则 0。"""
    try:
        n = float(v)
        return n if math.isfinite(n) else 0.0
    except (TypeError, ValueError):
        return 0.0


def fmt(v, d=2):
    """JS toFixed 语义：不可解析返回 '-'，否则保留 d 位小数。"""
    try:
        n = float(v)
        if not math.isfinite(n):
            return "-"
        return f"{n:.{d}f}"
    except (TypeError, ValueError):
        return "-"


def esc(s):
    """HTML 转义（与原 JS esc 一致：& < > \"）。"""
    if s is None:
        s = ""
    s = str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def T(f, k, d="—"):
    """取字段值；空值返回占位符（默认 '—'）。"""
    v = f.get(k, "")
    if v is None:
        v = ""
    v = str(v).strip()
    return v if v != "" else d


def sstr(v):
    """JS String() 语义：整数值的浮点显示为整数（如 10.0 -> '10'）。"""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def N(f, k):
    """取字段数值。"""
    return num(f.get(k, ""))


def V(f, k):
    v = f.get(k, "")
    return "" if v is None else v
