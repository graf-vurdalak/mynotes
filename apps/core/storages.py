from urllib.parse import quote

from django.conf import settings

from storages.backends.s3 import S3Storage


class PrivateS3Storage(S3Storage):
    """S3-хранилище с приватной выдачей: url() возвращает путь authorized-proxy (/media/…),
    а не presigned/provider-specific URL.

    В БД хранятся только относительные ключи; браузер не знает endpoint хранилища —
    перенос объектов на другой S3-совместимый backend не меняет ни ключи, ни шаблоны
    (План MinIO: переносимость без изменения моделей и ключей файлов).
    """

    def url(self, name):
        return settings.MEDIA_URL + quote(name)
