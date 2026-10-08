# -*- coding: utf-8 -*-
"""Интеграционный smoke: реальные операции с self-hosted S3 (План MinIO/S3, приёмка).

Opt-in: запускается только при полном наборе S3_* в окружении (dev-контейнер web/worker).
В CI (сервис e2e) S3 env отсутствует — skip. Настройки НЕ берём из config.settings.test
(он форсит local FS) — backend конструируется напрямую из env.
"""

import os
import uuid

import pytest
from django.core.files.base import ContentFile
from storages.backends.s3 import S3Storage

PREFIX = os.environ.get("S3_ENDPOINT", "")
BUCKET = os.environ.get("S3_BUCKET", "")
AK = os.environ.get("S3_ACCESS_KEY", "")
SK = os.environ.get("S3_SECRET_KEY", "")

requires_s3 = pytest.mark.skipif(
    not (PREFIX and BUCKET and AK and SK),
    reason="S3_* env не задан — интеграционный smoke пропускается",
)


def _storage():
    return S3Storage(
        endpoint_url=PREFIX,
        access_key=AK,
        secret_key=SK,
        bucket_name=BUCKET,
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        addressing_style="path",
    )


@requires_s3
class TestS3IntegrationSmoke:
    def test_upload_read_delete_roundtrip(self):
        storage = _storage()
        key = f"s3-smoke/{uuid.uuid4().hex}.bin"
        payload = b"integration-payload"
        assert storage.save(key, ContentFile(payload)) == key
        try:
            assert storage.exists(key)
            with storage.open(key, "rb") as f:
                assert f.read() == payload
        finally:
            storage.delete(key)
        assert not storage.exists(key)

    def test_staged_upload_keys_are_relative(self):
        """DB хранит относительные ключи — прокси-URL не содержит endpoint хранилища."""
        from apps.core.storages import PrivateS3Storage

        storage = PrivateS3Storage(
            endpoint_url=PREFIX,
            access_key=AK,
            secret_key=SK,
            bucket_name=BUCKET,
            region_name="us-east-1",
            addressing_style="path",
        )
        key = f"s3-smoke/{uuid.uuid4().hex}.txt"
        storage.save(key, ContentFile(b"u"))
        try:
            url = storage.url(key)
            assert url == f"/media/{key}"
            assert PREFIX not in url and BUCKET not in url.split("/media/")[1]
        finally:
            storage.delete(key)

    def test_provider_portability_keys_unchanged(self):
        """Переносимость: относительный ключ того же объекта одинаков у base-классов и proxy-класса."""
        base = _storage()
        from apps.core.storages import PrivateS3Storage

        proxy = PrivateS3Storage(
            endpoint_url=PREFIX, access_key=AK, secret_key=SK,
            bucket_name=BUCKET, region_name="us-east-1", addressing_style="path",
        )
        key = f"s3-smoke/{uuid.uuid4().hex}.bin"
        base.save(key, ContentFile(b"p"))
        try:
            assert proxy.exists(key)
            assert proxy.url(key).endswith(key)
        finally:
            base.delete(key)
