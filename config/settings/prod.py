from .base import *  # noqa: F401,F403

DEBUG = False

# Работа за reverse-proxy (хостовый nginx на сервере или bundled-proxy из compose):
# nginx передаёт X-Forwarded-Proto: $scheme — без этого SECURE_SSL_REDIRECT
# считает внутренний http-запрос незащищённым и даёт redirect-цикл.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# CSRF origin checks за HTTPS (Django 4+): домен прод-инсталляции. Список
# переопределяется env (несколько инсталляций/псевдонимов), по умолчанию —
# https://<SITE_DOMAIN>.
CSRF_TRUSTED_ORIGINS = env.list(  # noqa: F405
    "CSRF_TRUSTED_ORIGINS", default=[f"https://{SITE_DOMAIN}"]  # noqa: F405
)

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default=f"noreply@{SITE_DOMAIN}")  # noqa: F405

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"  # noqa: F405
EMAIL_HOST = env("EMAIL_HOST", default="")  # noqa: F405
EMAIL_PORT = env.int("EMAIL_PORT", default=587)  # noqa: F405
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")  # noqa: F405
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")  # noqa: F405
# 465 = SMTPS (EMAIL_USE_SSL=True, EMAIL_USE_TLS=False); 587 = STARTTLS (наоборот).
# Дефолт сохраняет прежнее поведение: TLS включён, если SSL явно не включён.
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)  # noqa: F405
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=not EMAIL_USE_SSL)  # noqa: F405

if env("SENTRY_DSN", default=""):  # noqa: F405
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=env("SENTRY_DSN"),  # noqa: F405
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.01,
        send_default_pii=True,
    )

# Только staticfiles: production-бэкенд статики (WhiteNoise). Ключ "default"
# (файлы: FileSystemStorage или S3 по S3_ENDPOINT) наследуется из base.py —
# полная перезапись STORAGES лишала Django default-backend (падение на загрузках).
STORAGES = {**STORAGES,  # noqa: F405
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
