# Локальная разработка

## Docker Compose (рекомендуемый путь)

Нужны Docker Engine и Compose plugin. Скопируйте `.env.example` в `.env`, оставьте
только локальные значения и не используйте этот файл для production. Задайте для
разработки `SITE_DOMAIN=localhost`, локальные `SECRET_KEY` и `POSTGRES_PASSWORD`;
одинаковый пароль используется БД Compose и Django. Реальные SMTP/OAuth/Telegram
реквизиты для запуска сайта не нужны. `.env` игнорируется Git.

Из корня репозитория выполните:

```powershell
docker compose -f docker-compose.dev.yml up --build -d
docker compose -f docker-compose.dev.yml exec web python manage.py migrate
docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
```

Откройте `http://localhost:8001/` или `http://localhost:8001/accounts/login/`.
Почта разработки сохраняется в MailHog: `http://localhost:8025/`. Compose запускает
PostgreSQL, Redis, web, Celery worker/beat, MailHog и SeaweedFS; dev-файлы хранятся
в отдельном бакете SeaweedFS в volume `s3_data`. Порты S3 и filer наружу не
публикуются.

Остановить контейнеры, сохранив локальные данные:

```powershell
docker compose -f docker-compose.dev.yml down
```

Чтобы удалить также базу, файлы и состояние ботов, потребуется `down -v`; это
разрушительная операция.

### Telegram-боты

Запуск ботов необязателен. Поместите токены BotFather в игнорируемый `.env` и
включите только нужные процессы:

```powershell
docker compose -f docker-compose.dev.yml --profile bots up --build -d bot_vehicle bot_planner
```

Для работы с данными каждому пользователю нужен отдельный API-токен из личного
кабинета приложения `/accounts/tokens/`. Настройка серверов выполняется в боте через
`/addserver`; токены BotFather и API-токен приложения имеют разные назначения.
Не вставляйте их в документацию или общие логи. Дополнительные сведения: [README
ботов](../telegram_bots/README.md).

## Запуск без Docker

Для запуска приложения непосредственно на хосте нужны Python, GNU Make,
PostgreSQL и Redis, запущенные и настроенные через `.env` (стандартные адреса БД и
Redis — `localhost`). Из корня репозитория:

```sh
make install
make migrate
make run
```

Этот `runserver` слушает порт `8000`; он не использует порт Docker `8001`. Без
S3-переменной `S3_ENDPOINT` default storage локальный файловый. Для локальной
инфраструктуры можно запустить:

```sh
docker compose -f docker-compose.dev.yml up -d db redis mailhog
```

При запуске Django на хосте задайте `EMAIL_HOST=localhost` и `EMAIL_PORT=1025`,
чтобы доставлять письма в MailHog. Пустой `EMAIL_HOST` использует имя `mailhog`,
доступное внутри Compose-сети. Подробности по внешним зависимостям задаются в
`.env.example`. Makefile также содержит `make test` и `make lint`; CI использует
более полный набор команд ниже.

## Проверки и тесты

Полный набор проверок запускается в Docker. Сначала соберите web-образ, затем
образ E2E-runner, поскольку тот наследует dev image `mynotes-web`:

```powershell
docker compose -f docker-compose.dev.yml build web
docker compose -f docker-compose.dev.yml --profile testing build e2e
```

Quality gates, Django checks, миграции и полный pytest suite с coverage gate:

```powershell
docker compose -f docker-compose.dev.yml --profile testing run --rm e2e sh -c 'ruff check . && bandit -r apps telegram_bots config -ll && safety check -r requirements/prod.txt --no-prompt --short-report && python manage.py check && python manage.py makemigrations --check --dry-run && pytest --create-db --reuse-db -q --cov=apps --cov=telegram_bots --cov-report=term:skip-covered --cov-fail-under=70'
```

Только браузерные сценарии:

```powershell
docker compose -f docker-compose.dev.yml --profile testing run --rm e2e pytest -q --reuse-db tests/e2e
```

CI, локальные проверки в Docker, сетевые требования E2E и ручные мобильные
проверки описаны в [`testing-ci.md`](testing-ci.md). Ручные сценарии iOS Safari и
Android Chrome перечислены в [`manual-testing.md`](manual-testing.md).

## Production

Локальный запуск не является инструкцией production-деплоя. Используйте
[`INSTALL.md`](../INSTALL.md) для установки и обновления, а
[`deployment.md`](deployment.md) для reverse proxy, S3/SeaweedFS, резервного
копирования и восстановления. Не переносите dev-секреты или dev-тома в production.
