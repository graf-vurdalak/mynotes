"""System-checks hardening (фикс ревью №4)."""

from django.conf import settings
from django.core.checks import Error, register


@register("security")
def check_fernet_key(app_configs, **kwargs):
    """ТЗ 8.5: без FERNET_KEY в проде VIN шифруются ключом от SECRET_KEY —
    ротация SECRET_KEY делает данные нечитаемыми. Ловится на
    `manage.py check --deploy` до миграций/данных."""
    if not settings.DEBUG and not (getattr(settings, "FERNET_KEY", "") or "").strip():
        return [
            Error(
                "FERNET_KEY не задан (прод): чувствительные поля (VIN) будут "
                "шифроваться производным от SECRET_KEY ключом; смена SECRET_KEY "
                "сделает их нечитаемыми. Задайте FERNET_KEY в env до миграций.",
                id="core.E001",
            )
        ]
    return []
