from __future__ import annotations

import logging

from django.core.mail import EmailMessage
from django.utils import timezone

from .models import BotChatBinding, Notification

logger = logging.getLogger(__name__)

VALID_BOTS = {c for c, _ in BotChatBinding.BOTS}


def bind_chat(user, bot: str, chat_id: str) -> BotChatBinding | None:
    """Upsert привязки чата к пользователю (заголовки гейтвея от бота)."""
    chat_id = (chat_id or "").strip()
    if bot not in VALID_BOTS or not chat_id.isdigit() or len(chat_id) > 64:
        return None
    binding, _ = BotChatBinding.objects.update_or_create(
        user=user, bot=bot, defaults={"chat_id": chat_id}
    )
    return binding


def notify(
    user,
    type: str,
    title: str,
    message: str = "",
    entity=None,
    channels: tuple[str, ...] = ("email",),
    dedup_within=None,
    bot: str | None = None,
) -> Notification | None:
    """Создать уведомление и доставить по каналам (ТЗ 5.5).

    Дедуп: если за последние ``dedup_within`` уже есть уведомление того же
    ``type`` для той же сущности у этого пользователя — новое не создаётся
    (перескан не должен спамить). Возвращает запись или ``None`` при дедупе.
    """
    entity_type = entity._meta.label_lower if entity is not None else ""
    entity_id = entity.pk if entity is not None else None

    if dedup_within is not None:
        since = timezone.now() - dedup_within
        exists = Notification.objects.filter(
            user=user, type=type, entity_type=entity_type, entity_id=entity_id,
            created_at__gte=since,
        ).exists()
        if exists:
            return None

    notification = Notification.objects.create(
        user=user, type=type, title=title, message=message,
        entity_type=entity_type, entity_id=entity_id,
    )

    if "email" in channels and user.email:
        notification.sent_via_email = _send_email(notification)
    if "telegram" in channels:
        from .telegram import send_telegram

        notification.sent_via_telegram = send_telegram(user, notification, bot=bot)
    notification.save(update_fields=["sent_via_email", "sent_via_telegram"])
    return notification


def _send_email(notification: Notification) -> bool:
    try:
        EmailMessage(
            subject=notification.title,
            body=notification.message,
            from_email=None,
            to=[notification.user.email],
        ).send()
        return True
    except Exception:
        logger.exception("Email-доставка уведомления %s не удалась", notification.pk)
        return False
