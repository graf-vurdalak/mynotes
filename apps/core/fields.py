"""Модельные поля с шифрованием на уровне приложения (ТЗ 8.5)."""

from __future__ import annotations

from cryptography.fernet import InvalidToken
from django.db import models

from .crypto import decrypt_value, encrypt_value


class EncryptedCharField(models.CharField):
    """CharField с Fernet-шифрованием при записи в БД (расшифровка при чтении).

    Legacy-значения (не расшифровываются) возвращаются как есть — до_data-миграции
    и на случай смены ключа. max_length должен вмещать токен (~150 символов для
    17-символьного VIN).
    """

    def get_db_prep_value(self, value, connection, prepared=False):
        value = super().get_db_prep_value(value, connection, prepared)
        if value is None or value == "":
            return value
        return encrypt_value(str(value))

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return decrypt_value(value)
        except InvalidToken:
            return value
