# -*- coding: utf-8 -*-
"""安全基元：口令哈希、后台令牌（签发/校验）、角色判定。

只做**密码学与角色**，不碰数据库：读账号行的活儿在 ``app/services/store.py``
（``login`` / ``authorize`` / ``change_password``）里，本模块是可单测的纯函数。

令牌口径：``base64url(JSON{role,exp,nonce})`` + ``"."`` + ``HMAC-SHA256(密钥, 前半段)``。
密钥存在 ``app_settings.token_secret``（首次建库随机生成，不进 ``public_settings``），
所以令牌**不能跨库复用**；有效期 8 小时，过期要求重新登录。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import HTTPException

#: PBKDF2 迭代次数（新口令与改密都用它；老库里各角色自己的迭代次数仍按行读取）
PASSWORD_ITERATIONS = 260_000

#: 内置角色与出厂口令；角色集合就是这张表的键
DEFAULT_PASSWORDS = {"process": "TP123456", "admin": "TP23456"}

#: 后台令牌有效期：8 小时
TOKEN_TTL_SECONDS = 8 * 60 * 60

#: 权限级别 → 哪些角色够格
REQUIRED_ROLES = {
    "admin": {"admin"},
    "process": {"process", "admin"},
}

ROLE_LABELS = {"admin": "管理员", "process": "工艺设置"}


def password_digest(password: str, salt: bytes,
                    iterations: int = PASSWORD_ITERATIONS) -> str:
    """PBKDF2-HMAC-SHA256 口令摘要（盐由调用方给，逐账号独立）。"""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def bearer_token(authorization: str | None) -> str | None:
    """从 ``Authorization`` 头里取出 Bearer 令牌；不是 Bearer 就当没给。"""
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value if scheme.lower() == "bearer" and value else None


def issue_token(secret_hex: str, role: str) -> dict[str, Any]:
    """签发一个后台令牌（返回令牌本身、角色与过期时间戳）。"""
    expires = int(time.time()) + TOKEN_TTL_SECONDS
    payload = json.dumps({"role": role, "exp": expires, "nonce": secrets.token_hex(8)},
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(bytes.fromhex(secret_hex), encoded.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    return {"token": f"{encoded}.{signature}", "role": role, "expires_at": expires}


def read_token(secret_hex: str, token: str) -> str:
    """校验令牌并返回角色；签名不符、格式坏了或过期一律 401（不区分原因，免得给探测线索）。"""
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(bytes.fromhex(secret_hex), encoded.encode("utf-8"),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if int(payload["exp"]) < int(time.time()):
            raise HTTPException(401, "后台登录已过期，请重新登录")
        role = str(payload["role"])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(401, "后台登录凭证无效") from exc
    return role


def check_role(role: str, required: str) -> str:
    """角色够不够格；不够就 403（消息说人话：缺的是"管理员"还是"工艺设置"）。

    ``required`` 不在 :data:`REQUIRED_ROLES` 里就**不设限**（与改造前一致：
    只有 ``admin`` / ``process`` 两个已知级别参与判定）。
    """
    allowed = REQUIRED_ROLES.get(required)
    if allowed is not None and role not in allowed:
        raise HTTPException(403, f"需要{ROLE_LABELS.get(required, required)}权限")
    return role


def new_salt() -> bytes:
    """一个新的 16 字节盐。"""
    return secrets.token_bytes(16)


def new_secret_hex() -> str:
    """一个新的令牌签名密钥（32 字节 → 64 位十六进制）。"""
    return secrets.token_hex(32)
