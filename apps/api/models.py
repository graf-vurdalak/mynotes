import uuid

from django.db import models


def staged_upload_path(instance, filename):
    """Нормализованное имя staged-файла: UUID + безопасное расширение (ТЗ 8.4)."""
    return f"bots/uploads/{instance.id}{instance.extension}"


class BotUpload(models.Model):
    """Временное хранилище файлов, загруженных ботом до привязки к сущности.

    Бот сначала грузит фото через ``POST /api/v1/bot/upload`` (получает ``upload_id``),
    затем вызывает ``/ingest`` со списком ``upload_ids`` — при создании сущности файлы
    переносятся в неё, staged-запись удаляется.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="bot_uploads"
    )
    file = models.FileField(upload_to=staged_upload_path, max_length=255)
    mime_type = models.CharField(max_length=100, blank=True)
    extension = models.CharField(max_length=10, default=".bin")
    size_bytes = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "api_bot_upload"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Upload {self.id} ({self.mime_type})"
