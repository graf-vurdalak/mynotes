# Telegram-боты «Мои записи»

Два самостоятельных aiogram-3.x процесса (`vehicle_bot`, `planner_bot`) работают
**HTTP-клиентами** к API-гейтвею Django `/api/v1/bot/*` (ТЗ 6.2, 7.1–7.6). Боты не
знают про ORM и не трогают БД — только JSON поверх HTTPS с авторизацией по `X-Bot-Token`.

## Как включить ботов

### 1. На BotFather
Откройте `@BotFather` и получите токены для двух ботов:
- `@<название>_vehicle_bot` → `TELEGRAM_VEHICLE_BOT_TOKEN`;
- `@<название>_planner_bot` → `TELEGRAM_PLANNER_BOT_TOKEN`.

Для inline-режима (ТЗ 7.5) включите Inline Mode командой `/setinline` и подскажите
пользователю использовать префиксы `поиск:` / `задача:`.

### 2. Выдача токена доступа
Токен API (не путать с BotFather-токеном!) привязывается к учётке пользователя.
Через management-команду (ТЗ 4.1):
```
python manage.py create_bot_token user@example.com "Phone" [--expires-days 90]
python manage.py create_bot_token user@example.com --list
python manage.py create_bot_token user@example.com "Phone" --revoke
```
Сгенерированный 64-символьный токен показывается **один раз**, в БД хранится только
HMAC-SHA256+пепр (ТЗ 8.2). Тот же объект виден и редактируется в Django admin
(`AuthToken`). Пепр задаётся env `BOT_TOKEN_PEPPER`.

### 3. Контейнеры
Образ собран из `docker/Dockerfile.bot` (только `requirements/bots.txt`, без Django).
В продакшене сервисы `bot_vehicle` / `bot_planner` уже в `docker-compose.yml`:
```
docker compose up -d --build bot_vehicle bot_planner
```
В разработке (нужен реальный токен Telegram):
```
docker compose -f docker-compose.dev.yml --profile bots up -d bot_vehicle bot_planner
```
Конфигурация инсталляций (urls+токены, добавленные юзером через `/addserver`) хранится
в SQLite на стороне бота — volume `bot_state`, env `BOT_STATE_DB` (см. ТЗ 7.1/7.2).

## Что умеют боты

**Vehicle bot (Бортжурнал, ТЗ 7.3):**
`servers`-группа: `/start`, `/help`, `/servers`, `/addserver`, `/removeserver`
мастера: `/fuel`, `/purchase`, `/service` (с фото до 10), `/fine`
чтения: `/vehicles`, `/stats`, `/insurance`
быстрая запись: `/quick <текст>` по грамматике ТЗ 7.6 MVP (регулярки + ключевые слова)
inline: `@<bot> поиск:<запрос>` (ТЗ 7.5)

**Planner bot (Записная книжка, ТЗ 7.4):**
`servers`-группа общая; `/scope`, `/events`, `/tasks`, `/projects`, `/search`
мастера `/newtask`, `/newevent`; `/quick <текст>`; inline `@<bot> задача:<запрос>`.

Все тексты — через ключи `bot.*` в `locale/ru_ru.lang` (ТЗ 10). Локализация грузится
собственным лёгким загрузчиком `telegram_bots/common/texts.py` (не тянет Django).

## Контракт API (кратко)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/v1/bot/ping/` | Проверка токена |
| POST | `/api/v1/bot/ingest/` | `{module, action, payload}` — роутинг к сервис-слою |
| GET | `/api/v1/bot/references/{type}/` | Справочники: vehicles, fuel_stations, purchase_categories, statuses, projects, scopes |
| POST | `/api/v1/bot/upload/` | Staged-загрузка файла (MIME по сигнатуре, ≤10 МБ) |

Все запросы требуют заголовок `X-Bot-Token`. Ошибки — 400 (payload), 401 (токен),
429 (`RATELIMIT_API`). Схема OpenAPI доступна через `/api/v1/docs/swagger/`.

## Не реализовано на этом этапе (по ТЗ)

- Расширенный NLP через LLM (ТЗ 7.6, этап 2) — MVP остаётся на регулярках/ключах.
- Голосовой ввод через Whisper (ТЗ 7.7) — отложено.

## Тесты

`tests/unit/test_bot_tokens.py`, `test_bot_common.py`, `test_vehicle_bot.py`,
`test_planner_bot.py`, `test_inline.py`, `tests/integration/test_bot_api.py`
запускаются вместе с основным pytest-сьют (`python -m pytest` в контейнере `web`).
