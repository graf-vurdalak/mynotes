# Участие в разработке

## Локальная разработка

Для веб-приложения используйте Docker Compose: он поднимает PostgreSQL, Redis,
SeaweedFS и Django из `docker-compose.dev.yml`. Подготовьте локальный `.env` на
основе `.env.example`, затем выполните:

```sh
docker compose -f docker-compose.dev.yml up --build -d
docker compose -f docker-compose.dev.yml exec web python manage.py migrate
```

Приложение доступно на `http://localhost:8001/`. Для локальных Python-команд
установите зависимости разработки через `pip install -r requirements/dev.txt`.
Настройки разработки используют PostgreSQL и Redis; для них должны быть доступны
соответствующие сервисы. Не добавляйте `.env`, пароли, токены, пользовательские
данные и загруженные файлы в изменения.

## Проверки

Для быстрой проверки Python-кода выполните `ruff check .`; форматирование проекта
настроено через `ruff format .` (`make lint` и `make format` соответственно).
Перед отправкой изменений запускайте тесты:

```sh
python -m pytest
```

Полный CI-набор, включая проверки безопасности, Django checks, миграции,
coverage, браузерные E2E-тесты и axe-core, описан в
[`docs/testing-ci.md`](docs/testing-ci.md). Он запускается в GitHub Actions для
Pull Request и push в `main` или `master`; для E2E используйте Docker-инструкцию
из этого документа.

## Соглашения

- Держите изменения небольшими и относящимися к задаче; добавляйте или обновляйте
  тесты для изменённого поведения.
- Пользовательские строки веб-приложения берите из каталога локализации через
  `t()` или template-тег `{% t %}`. В `apps/**/views.py` и `apps/**/forms.py`
  проверка запрещает кириллические строковые литералы, кроме docstring и
  `verbose_name`/`help_text`.
- Сохраняйте ключи переводов при изменении текста и проверяйте локализацию тестом
  `tests/unit/test_localization.py`; формат каталога описан в
  [`LOCALIZATION.md`](LOCALIZATION.md).
- Не включайте секреты, локальные конфиги и данные пользователей в diff. Перед
  отправкой проверьте `git status` и убедитесь, что изменения содержат только
  относящиеся к задаче файлы.

## Публикация

Опубликованный GitHub Release запускает workflow публикации Docker-образов web и
bot в GHCR. Теги образов формируются из release tag, semver и `latest`; подробности
проверок и выпуска описаны в [`docs/testing-ci.md`](docs/testing-ci.md).
