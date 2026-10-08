"""Сервис токенов для Telegram-ботов (ТЗ 4.1.3, 8.2).

В БД хранится только HMAC-SHA256 от токена с пепром-солью; оригинал показывается
один раз при создании. Проверка выполняется по индексируемому уникальному хэшу.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import AuthToken

# ТЗ 8.2: 64-символьные случайные строки (secrets.token_urlsafe(48) → ~64 символа).
TOKEN_BYTES = 48


def _pepper() -> bytes:
    """Соль-пепр для хэширования токенов: отдельный секрет, иначе SECRET_KEY."""
    return settings.BOT_TOKEN_PEPPER.encode("utf-8")


def digest_token(plain: str) -> str:
    """HMAC-SHA256(пепр, токен) — детерминированный ключевой хэш для поиска."""
    return hmac.new(_pepper(), plain.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_token(user, name: str, expires_in_days: int | None = None):
    """Создаёт токен; возвращает (plaintext_один_раз, AuthToken).

    Plaintext нигде не сохраняется (ТЗ 4.1.3, 8.2).
    """
    plain = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = (
        timezone.now() + timedelta(days=expires_in_days) if expires_in_days else None
    )
    token = AuthToken.objects.create(
        user=user,
        token_hash=digest_token(plain),
        name=name,
        expires_at=expires_at,
    )
    return plain, token


def verify_token(plain: str, ip: str | None = None) -> AuthToken | None:
    """Проверяет токен по хэшу; обновляет last_used_at/last_used_ip.

    Возвращает ``None``, если токен неизвестен, отозван, просрочен или
    пользователь неактивен.
    """
    if not plain:
        return None
    token = AuthToken.objects.filter(token_hash=digest_token(plain)).first()
    if token is None or not token.is_active:
        return None
    if token.expires_at and token.expires_at <= timezone.now():
        return None
    if not token.user.is_active:
        return None
    AuthToken.objects.filter(pk=token.pk).update(
        last_used_at=timezone.now(), last_used_ip=ip
    )
    return token


def revoke_token(token: AuthToken) -> AuthToken:
    """Отзывает токен (is_active=False); не удаляет запись (аудит)."""
    if token.is_active:
        AuthToken.objects.filter(pk=token.pk).update(is_active=False)
        token.is_active = False
    return token
