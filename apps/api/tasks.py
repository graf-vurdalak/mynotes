"""Celery-зачистка незавершённых staged-загрузок ботов (План MinIO/S3, приёмка).

BotUpload — временные файлы шлюза: бот загружает файл, затем привязывает его к
сущности через ingest (handlers._move_staged), который удаляет staging. Если
пользователь прервал диалог, объект остаётся в хранилище вечно — Task снимает
staged-записи старше STAGED_UPLOAD_TTL_HOURS (файл из storage + строку).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.core.files.storage import default_storage
from django.utils import timezone

from .models import BotUpload

logger = logging.getLogger(__name__)

STAGED_UPLOAD_TTL_HOURS = 24


@shared_task(name="api.cleanup_staged_uploads")
def cleanup_staged_uploads():
    cutoff = timezone.now() - timedelta(hours=STAGED_UPLOAD_TTL_HOURS)
    stale = BotUpload.objects.filter(created_at__lt=cutoff)
    removed = 0
    for upload in stale.iterator():
        name = upload.file.name
        try:
            upload.file.delete(save=False)
        except Exception:
            # Файла уже нет в хранилище (или endpoint недоступен) — строку всё
            # равно снимаем: без ключа файл не восстановить, висячая запись хуже.
            logger.exception("staged file delete failed, dropping row anyway")
            if default_storage.exists(name):
                continue
        upload.delete()
        removed += 1
    logger.info("cleanup_staged_uploads: removed %s", removed)
    return removed
