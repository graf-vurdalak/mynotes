"""Схемы запросов/ответов гейтвея ботов для drf-spectacular (ТЗ 14.2).

Используются только для документирования (OpenAPI); фактическая валидация
бизнес-полей выполняется в ``apps/api/handlers.py``.
"""

from rest_framework import serializers


class IngestRequestSerializer(serializers.Serializer):
    module = serializers.CharField(max_length=20)
    action = serializers.CharField(max_length=50)
    payload = serializers.DictField(required=False, default=dict, help_text="Данные действия")


class OkResponseSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True)
    entity_id = serializers.CharField(read_only=True, required=False, allow_null=True)


class ListResponseSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True)
    data = serializers.ListField(child=serializers.DictField(), read_only=True)


class UploadRequestSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="Фото/аудио, до 10 МБ (ТЗ 8.4)")


class UploadResponseSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True)
    upload_id = serializers.CharField(read_only=True)
    mime_type = serializers.CharField(read_only=True)
    size = serializers.IntegerField(read_only=True)


class ErrorSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True, default="error")
    detail = serializers.CharField(read_only=True)
