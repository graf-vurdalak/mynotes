import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _


class OwnedModel(models.Model):
    """Абстрактная база сущностей Записной книжки (ТЗ 5.1).

    UUID PK, привязка к пользователю, soft-delete и отметки времени.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="%(app_label)s_%(class)ss"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        self.is_deleted = True
        self.save(update_fields=["is_deleted", "updated_at"])

    def hard_delete(self, *args, **kwargs):
        return super().delete(*args, **kwargs)


class Scope(OwnedModel):
    """Скоуп Записной книжки: «Личное» или «Рабочее» (ТЗ 5.4, изолированы)."""

    PERSONAL = "personal"
    WORK = "work"
    CODES = [(PERSONAL, _("Личное")), (WORK, _("Рабочее"))]

    code = models.CharField(max_length=20, choices=CODES)
    name = models.CharField(max_length=50)

    class Meta:
        db_table = "planner_scope"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "code"], name="uniq_user_scope_code"),
        ]

    def __str__(self):
        return self.name


class Project(OwnedModel):
    """Проект — группировка событий/задач внутри скоупа (ТЗ 4.3.4)."""

    PRESET_COLORS = ["#3B82F6", "#10B981", "#F59E0B", "#8B5CF6", "#EC4899", "#F43F5E", "#64748B"]

    scope = models.ForeignKey(Scope, on_delete=models.CASCADE, related_name="projects")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default="#3B82F6")
    is_archived = models.BooleanField(default=False)

    class Meta:
        db_table = "planner_project"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "scope", "is_deleted"])]

    def __str__(self):
        return self.title


class Status(OwnedModel):
    """Статус рабочей задачи (ТЗ 4.3.3). Системные — стартовые 5 из ТЗ."""

    SYSTEM_CODES = [
        ("new", "Новый", "#94A3B8"),
        ("estimate", "Оценка", "#3B82F6"),
        ("in_progress", "В работе", "#F59E0B"),
        ("testing", "Тестирование", "#F97316"),
        ("done", "Готово", "#10B981"),
    ]

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default="#94A3B8")
    sort_order = models.IntegerField(default=0)
    is_system = models.BooleanField(default=False)

    class Meta:
        db_table = "planner_status"
        ordering = ["sort_order", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "code"], name="uniq_user_status_code"),
        ]

    def __str__(self):
        return self.name


class Event(OwnedModel):
    """Событие/задача — универсальная сущность (ТЗ 5.4)."""

    EVENT_TYPES = [
        ("task", _("Задача")),
        ("meeting", _("Встреча")),
        ("reminder", _("Напоминание")),
        ("milestone", _("Веха")),
    ]
    PRIORITIES = [
        ("low", _("Низкий")),
        ("normal", _("Обычный")),
        ("high", _("Высокий")),
        ("urgent", _("Срочный")),
    ]
    SOURCES = [("web", _("Веб")), ("telegram", _("Telegram"))]

    scope = models.ForeignKey(Scope, on_delete=models.CASCADE, related_name="events")
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, default="task")
    status = models.ForeignKey(
        Status, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="normal")
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    estimated_minutes = models.IntegerField(null=True, blank=True)
    actual_minutes = models.IntegerField(null=True, blank=True)
    tags = ArrayField(
        base_field=models.CharField(max_length=50), size=None, default=list, blank=True
    )
    # Повторение: подмножество iCal RRULE — 'daily', 'weekly', 'monthly', 'yearly',
    # 'weekly:BYDAY=MO,WE,FR', 'interval:FREQ=DAILY;INTERVAL=3'
    recurrence_rule = models.CharField(max_length=100, blank=True)
    recurrence_count = models.IntegerField(null=True, blank=True)
    recurrence_end = models.DateTimeField(null=True, blank=True)
    parent_event = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="instances"
    )
    # Напоминание: NULL — глобальный дефолт из UserSettings, 0 — выключено
    reminder_minutes_before = models.IntegerField(null=True, blank=True)
    reminder_sent = models.BooleanField(default=False)
    # Якорь для повторяющихся событий: на какой экземпляр уже сработало напоминание (ТЗ 4.3.5)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=SOURCES, default="web")

    class Meta:
        db_table = "planner_event"
        ordering = ["start_at", "created_at"]
        indexes = [
            models.Index(fields=["user", "scope", "is_deleted"]),
            models.Index(fields=["user", "status"]),
            models.Index(fields=["start_at"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_recurring(self) -> bool:
        return bool(self.recurrence_rule)


class EventAttachment(OwnedModel):
    """Вложение к событию или комментарию (ТЗ 5.4, до 10 МБ, проверка MIME — в форме)."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey(
        "Comment", on_delete=models.CASCADE, null=True, blank=True, related_name="attachments"
    )
    file = models.FileField(upload_to="planner/%Y/%m/")
    file_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.IntegerField(default=0)

    class Meta:
        db_table = "planner_event_attachment"
        ordering = ["created_at"]

    def save(self, *args, **kwargs):
        if not self.file_name and self.file:
            self.file_name = self.file.name.split("/")[-1]
        if self.file and not self.size_bytes:
            self.size_bytes = self.file.size
        super().save(*args, **kwargs)

    def __str__(self):
        return self.file_name or str(self.id)


class Comment(OwnedModel):
    """Комментарий к задаче (ТЗ 4.3.3)."""

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="planner_comment_ownerships"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="planner_comments"
    )
    text = models.TextField()

    class Meta:
        db_table = "planner_comment"
        ordering = ["created_at"]

    def __str__(self):
        return self.text[:60]


class StatusHistory(models.Model):
    """Автоматическая история смен статусов задачи (ТЗ 5.4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.ForeignKey(
        Status, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to_status = models.ForeignKey(
        Status, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    comment = models.TextField(blank=True)

    class Meta:
        db_table = "planner_status_history"
        ordering = ["changed_at"]

    def __str__(self):
        f = self.from_status.name if self.from_status else "—"
        t = self.to_status.name if self.to_status else "—"
        return f"{f} → {t}"
