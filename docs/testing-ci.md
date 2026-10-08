# Тесты и CI/CD

## Локальные проверки в Docker

Playwright runner наследует dev image `mynotes-web`, поэтому собирайте его после
web image:

```powershell
docker compose -f docker-compose.dev.yml build web
docker compose -f docker-compose.dev.yml --profile testing build e2e
```

Полный набор quality gates и тестов, включая E2E и axe-core:

```powershell
docker compose -f docker-compose.dev.yml --profile testing run --rm e2e sh -c 'ruff check . && bandit -r apps telegram_bots config -ll && safety check -r requirements/prod.txt --no-prompt --short-report && python manage.py check && python manage.py makemigrations --check --dry-run && pytest --create-db --reuse-db -q --cov=apps --cov=telegram_bots --cov-report=term:skip-covered --cov-fail-under=70'
```

Только браузерные сценарии:

```powershell
docker compose -f docker-compose.dev.yml --profile testing run --rm e2e pytest -q --reuse-db tests/e2e
```

Первый build E2E-образа требует сетевого доступа: он устанавливает Chromium
Headless Shell и загружает pinned axe-core 4.10.3. Тесты блокируют внешние
ресурсы браузера, кроме локального приложения и локальной копии axe-core.
Физические проверки iOS Safari и Android Chrome выполняются вручную по
`docs/manual-testing.md`.

## GitHub Actions

- Pull Request запускает Docker quality gates, полный suite и coverage gate 70%.
- Push в `main` или `master` запускает те же проверки и дополнительно собирает production web/bot images.
- Публикация в GHCR запускается событием **published GitHub Release**. Теги образов: release tag, semver и `latest`.
- Workflow-ы используют минимальные permissions. Для публикации применяется `GITHUB_TOKEN` с `packages: write`; токены из pull request в build не передаются.
- В Safety CLI 3.x команда `safety check` пока работает с open-source базой без API key, но upstream помечает её deprecated. Новая `safety scan` требует Safety API key.

## Запуск production images

Создайте локальный `.env` по образцу `.env.example`, задайте опубликованные имена
образов и версию релиза:

```dotenv
MYNOTES_WEB_IMAGE=ghcr.io/<owner>/<repository>-web
MYNOTES_BOT_IMAGE=ghcr.io/<owner>/<repository>-bot
IMAGE_TAG=v1.2.3
```

Для приватных пакетов предварительно выполните `docker login ghcr.io` с токеном,
имеющим `read:packages`, затем запустите production Compose. `.env`, сертификаты,
пользовательские данные и тесты исключены из Docker build context через
`.dockerignore`; runtime-секреты передаются контейнерам только из `.env`.
