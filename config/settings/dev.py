from .base import *  # noqa: F401,F403

DEBUG = True

#INSTALLED_APPS += [  # noqa: F405
#    "debug_toolbar",
#]
#
#MIDDLEWARE.insert(MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
#
#INTERNAL_IPS = ["127.0.0.1"]

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
# Реальный SMTP берётся из .env (EMAIL_HOST/PORT/USER/PASSWORD, EMAIL_USE_SSL|EMAIL_USE_TLS);
# пустой EMAIL_HOST — фолбэк на локальный MailHog без шифрования.
_email_host = env("EMAIL_HOST", default="")  # noqa: F405
EMAIL_HOST = _email_host or "mailhog"
if _email_host:
    EMAIL_PORT = env.int("EMAIL_PORT", default=465)  # noqa: F405
    EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)  # noqa: F405
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)  # noqa: F405
else:
    EMAIL_PORT = env.int("EMAIL_PORT", default=1025)  # noqa: F405
    EMAIL_USE_SSL = False
    EMAIL_USE_TLS = False

DATABASES = {  # noqa: F405
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="mynotes"),  # noqa: F405
        "USER": env("POSTGRES_USER", default="mynotes"),  # noqa: F405
        "PASSWORD": env("POSTGRES_PASSWORD", default="mynotes"),  # noqa: F405
        "HOST": env("POSTGRES_HOST", default="localhost"),  # noqa: F405
        "PORT": env("POSTGRES_PORT", default="5432"),  # noqa: F405
    }
}
