# -*- coding: utf-8 -*-
"""Зачистка незавершённых staged-загрузок (План MinIO/S3, приёмка): файл+строка, TTL."""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from apps.accounts.models import User
from apps.api.models import BotUpload
from apps.api.tasks import STAGED_UPLOAD_TTL_HOURS, cleanup_staged_uploads

# pytest-django: datetime-аргументы update() требуют aware-значения при USE_TZ.
pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return User.objects.create_user(email="cleanup@test.ru", password="Passw0rd-123")


def _make_upload(user, age_hours):
    upload = BotUpload.objects.create(
        user=user, file=ContentFile(b"x", name="s.bin"), extension=".bin"
    )
    BotUpload.objects.filter(pk=upload.pk).update(
        created_at=timezone.now() - timedelta(hours=age_hours)
    )
    return upload


def _stored_name(upload):
    # queryset.update() ниже обходит auto_now_add pre_save; ключ файла не меняется.
    return BotUpload.objects.get(pk=upload.pk).file.name


def test_fresh_upload_is_kept(user):
    upload = _make_upload(user, age_hours=1)
    name = _stored_name(upload)
    assert cleanup_staged_uploads() == 0
    assert default_storage.exists(name)


def test_stale_upload_file_and_row_removed(user):
    upload = _make_upload(user, age_hours=STAGED_UPLOAD_TTL_HOURS + 1)
    name = _stored_name(upload)
    assert default_storage.exists(name)
    assert cleanup_staged_uploads() == 1
    assert not default_storage.exists(name)
    assert not BotUpload.objects.filter(pk=upload.pk).exists()


def test_task_idempotent(user):
    _make_upload(user, age_hours=STAGED_UPLOAD_TTL_HOURS + 5)
    assert cleanup_staged_uploads() == 1
    assert cleanup_staged_uploads() == 0
