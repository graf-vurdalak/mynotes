# Архитектура

Документ описывает реализацию в репозитории, а не целевое состояние из [ТЗ](docs/TZ.md). Основные границы системы подтверждаются настройками `config/settings/`, маршрутами `config/urls.py`, приложениями `apps/` и Compose-файлами.

## Контур приложения

- **Django 5.2** — единое серверное приложение (версия закреплена в `requirements/base.txt`). Пользовательский интерфейс отрисовывается Django templates; URL веб-модулей подключены в `config/urls.py` для кабинета, автомобилей, планировщика, уведомлений, отчётов и поиска. Статика обслуживается отдельно.
- **PostgreSQL 16** — основная БД (`config/settings/base.py`, `docker-compose.yml`). Модели, связи и фактические имена таблиц описаны в [DB_SCHEMA.md](DB_SCHEMA.md).
- **Django REST Framework** используется для шлюза Telegram-ботов под `/api/v1/bot/`: `ping`, `ingest`, `upload`, `references` (`apps/api/urls.py`, `apps/api/views.py`). Это не общий REST CRUD API для веб-клиента.
- **Redis 7** используется как кэш, backend для кэшированных сессий (TTL 7 дней) и брокер/результат Celery (`config/settings/base.py`).

Поток веб-запроса: браузер → Django URL/view → формы и сервисы доменного приложения → ORM/PostgreSQL. Django формирует HTML и частичные ответы интерфейса. Корневой `/` перенаправляется на `/dashboard/`.

## Приложения и ответственность

| Путь | Назначение |
|---|---|
| `apps/accounts/` | Пользователь `accounts.User`, настройки, токены ботов, журнал входов и критичных действий, веб-аутентификация и 2FA. |
| `apps/vehicles/` | Автомобили и связанные записи: заправки, покупки, обслуживание, штрафы, страховки и плановые события. `services.py` содержит правила владения и доменные операции. |
| `apps/planner/` | Личные/рабочие скоупы, проекты, статусы, события/задачи, комментарии, вложения и история смен статусов. |
| `apps/references/` | Марки/модели авто, АЗС и справочные данные с разделением системных и пользовательских записей. |
| `apps/notifications/` | Уведомления, привязки Telegram-чатов и доставка по email/Telegram. |
| `apps/api/` | Авторизация ботов по токену, приём команд и временных загрузок; маршрутизация доменных операций в handlers/services. |
| `apps/reports/` | Сбор данных и экспорт отчётов; отдельной модели отчётов нет. |
| `apps/search/` | Поиск по существующим таблицам и PostgreSQL-индексы; отдельной модели поиска нет. |
| `apps/core/` | Общие middleware, шифрование VIN, приватное файловое хранилище и прокси выдачи медиа. |
| `telegram_bots/` | Два отдельных aiogram-клиента: `vehicle_bot` и `planner_bot`; общая клиентская конфигурация и команды в `telegram_bots/common/`. |

## Боты и фоновые задачи

Оба процесса ботов запускаются через `python -m telegram_bots.<bot>.main`, работают через aiogram long polling и обращаются к серверу по HTTP. Состояние конфигурации установок и чатов хранится локально в SQLite (`telegram_bots/common/config_store.py`, путь задаётся `BOT_STATE_DB`); токен установки хранится у бота-клиента. На сервере `AuthToken` содержит HMAC-SHA256 дайджест с pepper, оригинал показывается при создании один раз. Gateway проверяет `X-Bot-Token` (`apps/api/authentication.py`).

Celery worker выполняет напоминания и другие фоновые операции; Celery Beat задаёт расписание в `config/settings/base.py`:

- скан событий планировщика — раз в минуту;
- скан автомобильных напоминаний — ежедневно в 09:30 по часовому поясу Celery;
- очистка незавершённых staged-загрузок ботов — каждый час; срок хранения staging-записи 24 часа (`apps/api/tasks.py`).

Задачи уведомлений находятся в `apps/notifications/tasks.py`: они создают запись `Notification`, а доставка вызывается через `apps/notifications/services.py`. Для Telegram сервер использует чат, связанный с пользователем и именем бота (`BotChatBinding`).

## Файлы и приватность

Без `S3_ENDPOINT` Django использует `FileSystemStorage`; при заданном endpoint включается `apps.core.storages.PrivateS3Storage` (`config/settings/base.py`). В Compose dev/prod используется SeaweedFS с S3 API. В БД хранятся ключи файлов, а не адреса провайдера. `PrivateS3Storage.url()` возвращает локальный `/media/<key>`; `apps/core/views.py` отдаёт файл после входа и проверки владельца через реестр `apps/core/media.py`. Публичной раздачи приватного media-volume через nginx нет. Статика использует отдельный backend и не переносится в S3.

Загрузка из bot API проходит через `BotUpload`, проверку размера и сигнатуры MIME; после прикрепления к записи staging удаляется. Старые незавершённые загрузки удаляются периодической задачей.

## Аутентификация и границы доступа

- `AUTH_USER_MODEL = "accounts.User"`; вход по email, обязательная верификация email, allauth/Yandex и проверка пароля с Argon2 первым hasher-ом настроены в `config/settings/base.py`.
- TOTP/резервные коды основаны на `django_otp` и собственном `TwoFactorChallengeMiddleware` (`apps/accounts/middleware.py`); приложение не подключает `django-two-factor-auth`.
- `LoginRequiredMiddleware` закрывает анонимам веб-разделы; REST Framework по умолчанию требует `IsAuthenticated`. Bot API заменяет session auth на проверку токена и ограничивает частоту запросов.
- Бизнес-записи изолируются фильтрацией по `user` и `is_deleted=False` в сервисах/запросах приложений, например `apps/vehicles/services.py` и `apps/planner/services.py`. Это прикладные проверки, не PostgreSQL RLS. Межтабличное совпадение владельца FK на уровне БД не гарантируется.
- VIN шифруется на уровне приложения через `EncryptedCharField` (Fernet; `apps/core/fields.py`, миграция `apps/vehicles/migrations/0009_encrypt_vehicle_vin.py`). Токены ботов хранятся в виде keyed digest.

## Развёртывание и асинхронность

`docker-compose.yml` описывает PostgreSQL, Redis, Django/Gunicorn (3 worker-а), Celery worker/beat, SeaweedFS S3 и два bot-процесса. Reverse proxy может быть хостовым; встроенный nginx/certbot включается профилем `bundled-proxy`. Dev-конфигурация находится в `docker-compose.dev.yml` и `config/settings/dev.py`.

В репозитории есть `config/asgi.py`, но рабочая конфигурация и Compose запускают WSGI (`config.wsgi:application`); Channels, channel layers и WebSocket-маршрутизация не настроены. Асинхронная обработка выполняется Celery и отдельными процессами aiogram, а не Django Channels.

## Отличия от ТЗ

`docs/TZ.md` задаёт целевые требования; среди подтверждённых расхождений: общее REST CRUD API, Channels/WebSocket и Redis-сессии описаны в ТЗ, но текущая конфигурация использует веб-views/templates, только bot gateway API и `cached_db` sessions. Приватное S3-хранилище фактически реализовано, но локальный filesystem остаётся fallback вне Compose. См. также список различий схемы в [DB_SCHEMA.md](DB_SCHEMA.md).
