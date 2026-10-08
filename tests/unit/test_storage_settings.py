# -*- coding: utf-8 -*-
"""Тесты выбора storage-backend (План MinIO/S3, приёмка): local vs S3 и фолбэки.

base.py переключает default-backend на import-time по S3_ENDPOINT — проверяем reload'ом.
django.conf.settings активного модуля reload не затрагивает, тест изолирован.
"""

import importlib

import pytest
from django.conf import settings as active_settings


@pytest.fixture
def reload_base(monkeypatch):
    import config.settings.base as base_mod

    def _reload(**env):
        for k in ("S3_ENDPOINT", "S3_BUCKET", "S3_REGION", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        # read_env в base подмешивает .env (setdefault) — isolating: env file отсутствует в tmp-раннере CI,
        # в dev-контейнере значения os.environ из compose имеют приоритет над .env (setdefault).
        return importlib.reload(base_mod)

    yield _reload
    importlib.reload(base_mod)


def test_without_s3_endpoint_default_is_filesystem(reload_base):
    base = reload_base(S3_ENDPOINT="")
    assert base.STORAGES["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
    assert base.STORAGES["staticfiles"]["BACKEND"] == "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"


def test_with_s3_endpoint_default_switches_to_private_s3(reload_base):
    base = reload_base(
        S3_ENDPOINT="http://s3:8333",
        S3_BUCKET="b",
        S3_REGION="us-east-1",
        S3_ACCESS_KEY="ak",
        S3_SECRET_KEY="sk",
    )
    backend = base.STORAGES["default"]
    assert backend["BACKEND"] == "apps.core.storages.PrivateS3Storage"
    assert backend["OPTIONS"]["endpoint_url"] == "http://s3:8333"
    assert backend["OPTIONS"]["bucket_name"] == "b"
    assert backend["OPTIONS"]["addressing_style"] == "path"
    # staticfiles НЕ должен переключаться вместе с файлами.
    assert base.STORAGES["staticfiles"]["BACKEND"] == "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"


def test_empty_bucket_and_region_get_defaults(reload_base):
    # Регресс (урок 5.6): пустая переменная в .env приоритетнее default django-environ.
    base = reload_base(S3_ENDPOINT="http://s3:8333", S3_BUCKET="", S3_REGION="")
    opts = base.STORAGES["default"]["OPTIONS"]
    assert opts["bucket_name"] == "mynotes"
    assert opts["region_name"] == "us-east-1"


def test_prod_keeps_inherited_default_backend():
    """Прод обязан сохранять default (локальный или S3) и только дополнять staticfiles."""
    import config.settings.prod as prod

    assert "default" in prod.STORAGES
    assert prod.STORAGES["staticfiles"]["BACKEND"].startswith("whitenoise")


def test_active_test_settings_are_hermetic_local():
    assert active_settings.STORAGES["default"]["BACKEND"] == "django.core.files.storage.FileSystemStorage"
