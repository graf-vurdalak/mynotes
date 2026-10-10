"""Исходящая доставка уведомлений в Telegram через Bot API (ТЗ 4.2.8/4.3.5, вариант А).

Сервер шлёт ``sendMessage`` от имени того же бота, что и клиентские мастера:
токен — из settings (``TELEGRAM_*_BOT_TOKEN``), адресат — из ``BotChatBinding``,
поставленной гейтвеем. Нет токена/привязки/ответа API — тихий skip, флаг
``sent_via_telegram=False`` (уведомление остаётся в ящике и в email-канале).
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from .models import BotChatBinding

logger = logging.getLogger(__name__)

API_TIMEOUT = 10


def _token_for(bot: str) -> str:
    if bot == "vehicle":
        return settings.TELEGRAM_VEHICLE_BOT_TOKEN
    if bot == "planner":
        return settings.TELEGRAM_PLANNER_BOT_TOKEN
    return ""


def _derive_bot(notification) -> str | None:
    mapping = {"vehicles": "vehicle", "vehicle": "vehicle", "planner": "planner"}
    for source in (notification.entity_type, notification.type):
        prefix = (source or "").replace("_", ".").split(".")[0]
        if prefix in mapping:
            return mapping[prefix]
    return None


def send_telegram(user, notification, bot: str | None = None) -> bool:
    bot = bot or _derive_bot(notification)
    if bot is None:
        logger.warning("Уведомление %s: неизвестен бот-канал, Telegram пропущен", notification.pk)
        return False
    token = _token_for(bot)
    if not token:
        return False
    binding = BotChatBinding.objects.filter(user=user, bot=bot).first()
    if binding is None:
        return False
    text = f"{notification.title}\n{notification.message}".strip()
    proxy_kwargs = {}
    if settings.TELEGRAM_HTTP_PROXY:
        proxy_kwargs["proxies"] = {"https": settings.TELEGRAM_HTTP_PROXY}

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": binding.chat_id, "text": text},
            timeout=API_TIMEOUT,
            **proxy_kwargs,
        )
        ok = resp.status_code == 200 and bool(resp.json().get("ok"))
        if not ok:
            logger.warning("Telegram sendMessage %s: HTTP %s %s", notification.pk, resp.status_code, resp.text[:200])
        return ok
    except requests.RequestException:
        logger.exception("Telegram sendMessage %s не удалась", notification.pk)
        return False
