import os
from pathlib import Path

import environ
from celery.schedules import crontab

env = environ.Env(
    DEBUG=(bool, False),
    SITE_DOMAIN=(str, "<ваш_домен>"),
    SECRET_KEY=(str, "insecure-default-change-me"),
    BOT_TOKEN_PEPPER=(str, ""),
    FERNET_KEY=(str, ""),
    TELEGRAM_VEHICLE_BOT_TOKEN=(str, ""),
    TELEGRAM_PLANNER_BOT_TOKEN=(str, ""),
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
SITE_DOMAIN = env("SITE_DOMAIN")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
# Соль-пепр для хэширования токенов ботов (ТЗ 8.2); по умолчанию — SECRET_KEY.
BOT_TOKEN_PEPPER = env("BOT_TOKEN_PEPPER") or SECRET_KEY
# Ключ Fernet для шифрования чувствительных полей на уровне приложения (ТЗ 8.5).
# Пусто — производный от SECRET_KEY детерминированный ключ (dev); в прод — задать явно.
FERNET_KEY = env("FERNET_KEY")

# Токены Telegram-ботов для исходящей доставки уведомлений (ТЗ 4.2.8/4.3.5, вариант А):
# сервер шлёт sendMessage от имени того же бота, чат-привязка — BotChatBinding.
TELEGRAM_VEHICLE_BOT_TOKEN = env("TELEGRAM_VEHICLE_BOT_TOKEN")
TELEGRAM_PLANNER_BOT_TOKEN = env("TELEGRAM_PLANNER_BOT_TOKEN")

LANGUAGE_CODE = "ru-ru"
LANGUAGES = [
    ("ru", "Русский"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

#DEFAULT_AUTO_FIELD = "django.db.models.UUIDField"
#DEFAULT_UUID_VERSION = 4
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django_extensions",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.yandex",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "apps.accounts",
    "apps.core",
    "apps.vehicles",
    "apps.planner",
    "apps.references",
    "apps.notifications",
    "apps.reports",
    "apps.search",
    "apps.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "apps.accounts.middleware.UserTimezoneMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.LoginRequiredMiddleware",
    "apps.accounts.middleware.TwoFactorChallengeMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notifications.context_processors.unread_notifications",
            ],
            "builtins": [
                "apps.core.templatetags.i18n_lang",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# Argon2id первым (ТЗ 8.1); остальные — для чтения старых хэшей.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

# Минимальная длина 10 символов (ТЗ 8.1); Entropy-валидатора в Django нет —
# вместо него CommonPassword + NumericPassword.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
ACCOUNT_CHANGE_EMAIL = True
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_LOGIN_REDIRECT_URL = "/dashboard/"

SOCIALACCOUNT_PROVIDERS = {
    "yandex": {
        "APP": {
            "client_id": env("YANDEX_OAUTH_CLIENT_ID", default=""),
            "secret": env("YANDEX_OAUTH_SECRET", default=""),
        },
        "SCOPE": ["login:email", "login:info"],
    }
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@example.com")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="mynotes"),
        "USER": env("POSTGRES_USER", default="mynotes"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="mynotes"),
        "HOST": env("POSTGRES_HOST", default="db"),
        "PORT": env("POSTGRES_PORT", default="5432"),
    }
}

REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_CACHE_ALIAS = "default"
SESSION_COOKIE_AGE = 604800

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
    },
}

if env("S3_ENDPOINT", default=""):
    # Единственная точка выбора backend файлов (default): наличие S3_ENDPOINT включает S3.
    # staticfiles намеренно не трогаем — файлы и статика разделены (ТЗ: переносимость хранилища).
    STORAGES["default"] = {
        # PrivateS3Storage.url() = /media/<ключ> (authorized-proxy); presigned/provider URL браузеру не отдаём.
        "BACKEND": "apps.core.storages.PrivateS3Storage",
        "OPTIONS": {
            "endpoint_url": env("S3_ENDPOINT"),
            "access_key": env("S3_ACCESS_KEY", default=""),
            "secret_key": env("S3_SECRET_KEY", default=""),
            # django-environ: переменная, заданная пустой в .env (S3_REGION=), имеет
            # приоритет над default — фолбэк через `or` (урок пустого EMAIL_HOST, 5.6).
            "bucket_name": env("S3_BUCKET", default="") or "mynotes",
            # boto3 не определяет регион для self-hosted endpoint — явный дефолт.
            "region_name": env("S3_REGION", default="") or "us-east-1",
            # Self-hosted S3 (SeaweedFS и аналоги) без wildcard-DNS: только path-style.
            "addressing_style": "path",
        },
    }

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "MyNotes API",
    "DESCRIPTION": "Единая платформа Мои записи",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

# Периодические сканы напоминаний (ТЗ 4.2.8/4.3.5): минуты — события Записной
# книжки, ежедневно 09:30 — сущности Бортжурнала.
CELERY_BEAT_SCHEDULE = {
    "scan-event-reminders": {
        "task": "notifications.scan_event_reminders",
        "schedule": 60.0,
    },
    "scan-vehicle-reminders": {
        "task": "notifications.scan_vehicle_reminders",
        "schedule": crontab(hour=9, minute=30),
    },
    # План MinIO/S3: staged-файлы прерванных диалогов ботов не должны
    # накапливаться в хранилище (TTL 24ч, apps/api/tasks.py).
    "cleanup-staged-bot-uploads": {
        "task": "api.cleanup_staged_uploads",
        "schedule": crontab(minute=15),
    },
}

# Ревью №13: приложение `two_factor` (django-two-factor-auth) и его
# TWO_FACTOR_PATCH_ADMIN убраны — вся 2FA-логика реализована на django_otp
# (otp_totp/otp_static) + собственный TwoFactorChallengeMiddleware, который
# и так закрывает /admin/ (не в EXEMPT_PREFIXES) для верифицируемых юзеров.
# Патч админ-логина django-two-factor-auth был неиспользуемым и не покрыт тестами.

RATELIMIT_VIEW = "apps.accounts.views.rate_limited"
RATELIMIT_USE_CACHE = "default"
RATELIMIT_API = env("RATELIMIT_API", default="300/m")
RATELIMIT_LOGIN = env("RATELIMIT_LOGIN", default="100/m")
RATELIMIT_SIGNUP = env("RATELIMIT_SIGNUP", default="5/m")

# Content-Security-Policy (ТЗ 8.4). Allow-list CDNs, реально подключаемыми
# шаблонами: Tailwind/Alpine/HTMX (base.html), ApexCharts/SortableJS (отчёты,
# канбан), Google Fonts. Alpine и Tailwind CDN требуют unsafe-eval; inline-
# обработчики/@click и style-атрибуты — unsafe-inline.
# Ревью №12 (осознанный trade-off): пока UI живёт на Tailwind/Alpine CDN с
# инлайн-обработчиками, script-src 'unsafe-inline'/'unsafe-eval' убрать нельзя.
# Дорожная карта к полноценной XSS-защите (вне рамок Этапа 7): сборный CSS вместо
# cdn.tailwindcss.com, Alpine CSP-сборка или внешние обработчики, nonce
# ({% csp_nonce %}) для оставшихся инлайнов — затем снимать unsafe-* из script-src.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),
        "script-src": (
            "'self'",
            "'unsafe-inline'",
            "'unsafe-eval'",
            "https://cdn.tailwindcss.com",
            "https://unpkg.com",
            "https://cdn.jsdelivr.net",
        ),
        "style-src": (
            "'self'",
            "'unsafe-inline'",
            "https://cdn.tailwindcss.com",
            "https://fonts.googleapis.com",
        ),
        "font-src": ("'self'", "https://fonts.gstatic.com", "data:"),
        "img-src": ("'self'", "data:", "blob:"),
        "connect-src": ("'self'",),
        "object-src": ("'none'",),
        "frame-ancestors": ("'none'",),
        "base-uri": ("'self'",),
        "form-action": ("'self'",),
    },
}

SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "%(levelname)s %(asctime)s %(module)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

SITE_ID = 1

I18N_CACHE_KEY_PREFIX = "i18n:"
