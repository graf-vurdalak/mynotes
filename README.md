# Мои записи (MyNotes)

MyNotes — русскоязычное веб-приложение для автомобильного бортжурнала и личной /
рабочей записной книжки. Интерфейс адаптирован для мобильных устройств; данные
можно вносить в веб-приложении и через Telegram-ботов.

Проект создан с использованием ИИ-инструментов под руководством Дениса Соколова. Распространяется под лицензией MIT.

## Возможности

- Бортжурнал автомобилей: расходы, топливо, обслуживание, штрафы и страхование.
- Планировщик задач, событий и проектов.
- Telegram-боты для бортжурнала и планировщика, включая быстрый ввод.
- Напоминания и уведомления, отчёты, PDF и экспорт.
- Приватное хранение загружаемых файлов через приложение.

## Стек

- **Backend:** Django 5.x + DRF
- **DB:** PostgreSQL 16
- **Frontend:** Django templates + HTMX 2.x + TailwindCSS 3.x + Alpine.js
- **Cache/Queues:** Redis 7 + Celery 5
- **Auth:** django-allauth (email + Яндекс OAuth) + django-otp (2FA)
- **Bots:** aiogram 3.x

## Быстрый старт (Docker)

### 1. Клонирование

```powershell
git clone <repo_url>
cd mynotes
```

### 2. Настройка локальной среды

```powershell
Copy-Item .env.example .env
# Задайте SITE_DOMAIN=localhost и локальные SECRET_KEY и POSTGRES_PASSWORD.
# Не используйте секреты production.
```

### 3. Запуск dev Compose

```powershell
docker compose -f docker-compose.dev.yml up --build -d
docker compose -f docker-compose.dev.yml exec web python manage.py migrate
docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
```

Откройте http://localhost:8001/accounts/login/. Письма для локальной разработки
можно просматривать в MailHog: http://localhost:8025/. Остановить сервисы без
удаления данных: `docker compose -f docker-compose.dev.yml down`.

Compose запускает PostgreSQL, Redis, Django, Celery, MailHog и SeaweedFS для файлов.
Telegram-боты опциональны и запускаются с профилем `bots`; см.
[руководство разработки](docs/development.md). Не используйте dev Compose для
production.

## Локальный запуск без Docker

```bash
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Документация

- [Частые вопросы](FAQ.md)
- [Локальная разработка и тесты](docs/development.md)
- [Тестирование и CI/CD](docs/testing-ci.md)
- [Установка и обновление production](INSTALL.md)
- [Деплой, S3-хранилище и резервные копии](docs/deployment.md)
- [Архитектура](ARCHITECTURE.md) и [схема БД](DB_SCHEMA.md)
- [Участие в разработке](CONTRIBUTING.md) и [локализация](LOCALIZATION.md)
- [Инструкция по Telegram-ботам](telegram_bots/README.md)
- [Техническое задание](docs/TZ.md)

## Лицензия

MIT. См. файл [LICENSE](LICENSE).
