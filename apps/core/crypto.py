"""Шифрование чувствительных полей на уровне приложения (ТЗ 8.5): Fernet.

Ключ — ``settings.FERNET_KEY`` (base64-строка 32 байта); пусто — детерминированная
производная от SECRET_KEY (только dev, как у BOT_TOKEN_PEPPER). Fernet
недетерминирован (случайный IV): точное равенство в БД по зашифрованным полям
недоступно, такие поля пригодны только для чтения/отображения.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings

_fernet_cache: dict[str, Fernet] = {}


def _get_fernet() -> Fernet:
    key = (settings.FERNET_KEY or "").strip()
    if not key:
        digest = hashlib.sha256(f"fernet|{settings.SECRET_KEY}".encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    fernet = _fernet_cache.get(key)
    if fernet is None:
        fernet = _fernet_cache[key] = Fernet(key)
    return fernet


def encrypt_value(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()
