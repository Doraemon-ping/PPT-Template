# -*- coding: utf-8 -*-
"""导出文件包用到的纯函数（阶段 5 · 口径 §7.0）。

读模型里"指向附件的字段"全是 ``/api/machining-dfm/assets/<id>`` 相对地址（库里 0 行 base64）。
出包时把它们换成**包内相对路径** ``assets/<id>.<ext>``，并把真引用到的附件原始字节一起打进去：
这份包脱离服务也能看懂、能存档、能转发（便携单文件 HTML 已按 §7.0 退休）。

包结构（由 ``app/services/store.py`` 的 ``export_package`` 组装）::

    DFM_<项目名>.zip
    ├── project.json      与 GET /projects/{pid} 同一份形状的读模型 + 顶层 _export 说明块
    ├── assets/<id>.<ext> 只放本项目**真引用到**的附件原图
    └── README.txt        UTF-8 说明

本模块只管"名字怎么起、引用怎么认、地址怎么换"，不碰数据库与 zip 写入，
所以可以脱离 store 单测（见 ``tests/test_machining_export_package.py``）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..db.assets import DOCUMENT_MIMES, IMAGE_MIMES

#: 包格式标识与版本（写进 ``project.json`` 的顶层 ``_export`` 块）
PACKAGE_FORMAT = "machining-dfm-package"
PACKAGE_VERSION = 1
#: README.txt 里写明"这份包由哪个服务哪个版本导出"
PACKAGE_SERVICE = "机加 DFM 项目工作台（app/services/machining.py · FastAPI · 契约 1.0）"
#: 只在**整个字段值**就是一个附件地址时才算引用（形状由 check_export_assets.mjs 钉住）
ASSET_URL_PATTERN = re.compile(r"^/api/machining-dfm/assets/([A-Za-z0-9]+)(?:[?#].*)?$")
#: 文件名里不能出现的字符（Windows 更严：\/:*?"<>| 与控制字符）
FILENAME_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def package_extension(record: dict[str, Any]) -> str:
    """``assets/<id>.<ext>`` 的后缀：先看 ``assets.path``，取不到就用 ``mime`` 推。"""
    suffix = Path(str(record.get("path") or "")).suffix
    if suffix and re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix):
        return suffix.lower()
    mime = str(record.get("mime") or "").split(";", 1)[0].strip().lower()
    for table in (IMAGE_MIMES, DOCUMENT_MIMES):
        if mime in table:
            return table[mime]
    return ".bin"


def package_filename(name: str) -> str:
    """``DFM_<项目名>.zip``：清掉非法字符、空白折成 ``_``、限长（空名兜底 ``project``）。"""
    cleaned = FILENAME_ILLEGAL.sub("_", str(name or ""))
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    cleaned = cleaned.strip("._") or "project"
    return f"DFM_{cleaned[:60]}.zip"


def content_disposition(filename: str) -> str:
    """RFC 6266：ASCII 兜底 ``filename`` + UTF-8 的 ``filename*``（响应头不能直接放中文）。"""
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.encode("ascii", "replace").decode("ascii"))
    fallback = re.sub(r"_{2,}", "_", fallback).strip("_") or "DFM_project.zip"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def iter_asset_ids(node: Any) -> list[str]:
    """读模型里所有附件引用（按出现顺序去重），路径不限层级。"""
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            hit = ASSET_URL_PATTERN.match(value)
            if hit and hit.group(1) not in found:
                found.append(hit.group(1))
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(node)
    return found


def rewrite_package_assets(node: Any, mapping: dict[str, str]) -> Any:
    """深拷贝读模型，把附件地址就地换成包内相对路径（``mapping`` 里没有的原样留着）。"""
    if isinstance(node, str):
        hit = ASSET_URL_PATTERN.match(node)
        return mapping[hit.group(1)] if hit and hit.group(1) in mapping else node
    if isinstance(node, list):
        return [rewrite_package_assets(item, mapping) for item in node]
    if isinstance(node, dict):
        return {key: rewrite_package_assets(value, mapping) for key, value in node.items()}
    return node
