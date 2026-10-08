# -*- coding: utf-8 -*-
"""Тесты authorized-прокси /media/<path> (План MinIO, шаг 3): приватная выдача файлов.

Механизм выбран вместо presigned-URL: браузер не должен знать S3 endpoint,
MinIO console/API не публикуется; перенос на другое S3-хранилище не меняет
ключи в БД и шаблоны (url() всегда /media/…).
"""

import base64

import pytest
from django.apps import apps
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models

from apps.accounts.models import User
from apps.api.models import BotUpload
from apps.core.media import MEDIA_FILE_OWNERS

# PNG 1x1.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def media_root(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


@pytest.fixture
def owner(db, media_root):
    user = User.objects.create_user(email="owner@test.ru", password="Passw0rd-123")
    user.avatar.save("me.png", ContentFile(PNG_BYTES), save=True)
    return user


@pytest.mark.django_db
class TestMediaProxy:
    def test_anonymous_redirected_to_login(self, client, owner):
        response = client.get(owner.avatar.url)
        assert response.status_code == 302
        assert "/login/" in response.headers["Location"]

    def test_owner_gets_file(self, client, owner):
        client.force_login(owner)
        response = client.get(owner.avatar.url)
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == PNG_BYTES
        assert response.headers["Content-Type"].startswith("image/png")

    def test_other_user_forbidden_404(self, client, owner):
        stranger = User.objects.create_user(email="x@test.ru", password="Passw0rd-123")
        client.force_login(stranger)
        assert client.get(owner.avatar.url).status_code == 404

    def test_unknown_path_404(self, client, owner):
        client.force_login(owner)
        assert client.get("/media/avatars/nope.png").status_code == 404

    def test_path_traversal_404(self, client, owner):
        client.force_login(owner)
        response = client.get("/media/../../etc/passwd")
        assert response.status_code == 404

    def test_staged_bot_upload_served_to_owner_then_deleted(self, client, owner):
        upload = BotUpload.objects.create(
            user=owner, file=ContentFile(PNG_BYTES, name="stage.png"), extension=".png"
        )
        client.force_login(owner)
        assert client.get(upload.file.url).status_code == 200
        default_storage.delete(upload.file.name)
        assert client.get(upload.file.url).status_code == 404

    def test_url_is_media_relative_never_provider(self, owner):
        assert owner.avatar.url.startswith("/media/")

    def test_registry_covers_all_model_file_fields(self):
        """Гарант: каждый FileField/ImageField прикладных моделей в реестре MEDIA_FILE_OWNERS."""
        registered = {(label, field) for label, field, _ in MEDIA_FILE_OWNERS}
        actual = set()
        for model in apps.get_models():
            if not model.__module__.startswith("apps."):
                continue
            for field in model._meta.get_fields():
                if isinstance(field, models.FileField):
                    actual.add((model._meta.label, field.name))
        missing = actual - registered
        assert not missing, f"не зарегистрированы в MEDIA_FILE_OWNERS: {missing}"
