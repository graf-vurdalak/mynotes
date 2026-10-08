from .dev import *  # noqa: F401,F403

# Keep email tests independent of SMTP and local environment settings.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "noreply@example.com"

# Автотесты герметичны: local-бэкенд default принудительно, даже когда контейнер
# задал S3_* в os.environ (compose dev подаёт http://s3:8333 для web/worker).
# Выбор local/S3 в настройках покрывается tests/unit/test_storage_settings.py,
# интеграционный smoke к реальному S3 — tests/integration/test_s3_smoke.py (opt-in).
STORAGES = {  # noqa: F405
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": STORAGES["staticfiles"],  # noqa: F405
}
