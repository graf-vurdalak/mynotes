import uuid

from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Запись уведомления (ТЗ 5.5).

    Источник истины для почтового ящика в UI; флаги ``sent_via_*`` фиксируют,
    дошли ли каналы email/Telegram.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=50)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    entity_type = models.CharField(max_length=50, blank=True)
    entity_id = models.UUIDField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    sent_via_email = models.BooleanField(default=False)
    sent_via_telegram = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "type", "entity_id"]),
        ]

    def __str__(self):
        return f"{self.type}: {self.title}"


class BotChatBinding(models.Model):
    """Привязка Telegram-чата к пользователю и боту (вариант А, ТЗ 4.2.8/4.3.5).

    Ставится API-гейтвеем из заголовков ``X-Bot-Name`` / ``X-Telegram-Chat-Id``:
    бот — клиент и знает чат, сервер — нет. На один бота хранится последний чат.
    """

    BOTS = [("vehicle", "Бот Бортжурнала"), ("planner", "Бот Записной книжки")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_bindings"
    )
    bot = models.CharField(max_length=20, choices=BOTS)
    chat_id = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bot_chat_binding"
        constraints = [
            models.UniqueConstraint(fields=["user", "bot"], name="uniq_user_bot_chat"),
        ]

    def __str__(self):
        return f"{self.bot}:{self.chat_id}"
