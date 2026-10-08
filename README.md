# Мои записи (MyNotes)

Единая платформа: Бортжурнал автомобиля + Записная книжка.

Бортжурнал — учёт расходов, событий и плановых работ, связанных с автомобилем.
Записная книжка — планировщик личных и рабочих событий/задач.

Данные вносятся через веб-интерфейс (mobile-first) и через Telegram-ботов.

## Стек

- **Backend:** Django 5.x + DRF
- **DB:** PostgreSQL 16
- **Frontend:** Django templates + HTMX 2.x + TailwindCSS 3.x + Alpine.js
- **Cache/Queues:** Redis 7 + Celery 5
- **Auth:** django-allauth (email + Яндекс OAuth) + django-otp (2FA)
- **Bots:** aiogram 3.x

## Быстрый старт

### 1. Клонирование

```bash
git clone <repo_url>
cd mynotes
```

### 2. Настройка окружения

```bash
cp .env.example .env
# Отредактируйте .env
```

### 3. Запуск через Docker (рекомендуется)

```bash
make docker-up
```

Откройте http://localhost:8000/accounts/login/

### 4. Локальный запуск (без Docker)

```bash
pip install -r requirements/dev.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Структура проекта

```
mynotes/
├── config/            # настройки, wsgi, asgi, celery
├── apps/              # Django-приложения
│   ├── accounts/      # auth, профили, токены, 2FA
│   ├── vehicles/      # бортжурнал
│   ├── planner/       # записная книжка
│   └── ...
├── telegram_bots/     # aiogram-боты
├── locale/            # локализация
├── templates/         # Django templates
├── static/
├── tests/
├── docker/
├── docs/              # ТЗ и документация
└── requirements/
```

## Документация

Полное техническое задание: [docs/TZ.md](docs/TZ.md)
Деплой, S3-хранилище файлов (SeaweedFS вместо недоступных образов MinIO), бэкап/откат: [docs/deployment.md](docs/deployment.md)

## Лицензия

MIT. См. файл [LICENSE](LICENSE).
