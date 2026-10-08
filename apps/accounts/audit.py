"""Аудит-сервис (ТЗ 5.5, 8.5): единая точка записи AuditLog и журнала входов."""

from __future__ import annotations

import ipaddress

from .models import AuditLog, AuthSessionLog


def client_ip(request) -> str | None:
    """IP клиента за обратным прокси nginx.

    nginx дописывает реальный пир в конец X-Forwarded-For
    ($proxy_add_x_forwarded_for), поэтому идём СПРАВА налево и берём первый
    валидный адрес — левые элементы подделываются клиентом. Тот же источник
    используется rate-limit ключом (ТЗ 8.4) и аудитом, чтобы они не расходились.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    for hop in reversed(forwarded.split(",")):
        hop = hop.strip()
        if _is_ip(hop):
            return hop
    remote = request.META.get("REMOTE_ADDR") or ""
    return remote if _is_ip(remote) else None


def _is_ip(value: str) -> bool:
    if not value:
        return False
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def record_login(request, user, provider: str) -> AuthSessionLog:
    """Фиксация входа: journal (ТЗ 4.1.2 «история входов») + audit (ТЗ 8.5)."""
    log = AuthSessionLog.objects.create(
        user=user,
        # ip_address NOT NULL: при полностью невалидных заголовках — sentinel
        # 0.0.0.0 (иначе psycopg inet упадёт на мусоре из XFF)
        # PostgreSQL inet sentinel only; never used as a bind target.
        ip_address=client_ip(request) or "0.0.0.0",  # nosec B104
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        provider=provider,
    )
    log_action(request, "login", user=user, new={"provider": provider})
    return log


def log_action(
    request,
    action: str,
    *,
    user=None,
    entity_type: str = "",
    entity_id: str = "",
    old: dict | None = None,
    new: dict | None = None,
) -> AuditLog | None:
    """Запись критичного действия; user/IP/UA берутся из request, если не переданы."""
    actor = user if user is not None else getattr(request, "user", None)
    if actor is not None and not actor.is_authenticated:
        actor = None
    ip = client_ip(request) if request is not None else None
    ua = request.META.get("HTTP_USER_AGENT", "") if request is not None else ""
    return AuditLog.objects.create(
        user=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        old=old,
        new=new,
        ip_address=ip,
        user_agent=ua,
    )
