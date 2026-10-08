# Деплой и хранилище файлов (S3)

## Хранилище файлов: почему не MinIO

План этапа назывался «MinIO для dev и production». По факту (2026-10):

- публичные образы `minio/minio` и `minio/mc` **удалены** с Docker Hub (404),
  quay.io отдаёт 401, `bitnami/minio` недоступен, `ghcr.io/minio/minio` — denied;
- репозиторий `github.com/minio/minio` **архивирован** (read-only) 25.04.2026.

Согласованная замена — **SeaweedFS S3-гейтвей** (`chrislusf/seaweedfs:4.48`):
та же S3-протокольная совместимость (экосистема boto3/django-storages не меняется),
один лёгкий процесс `master+volume+filer+s3`, публичный активный образ.
Приложение от провайдера не зависит: любой S3-совместимый endpoint
(SeaweedFS / Yandex Object Storage / AWS S3) подключается переменными `S3_*`.

## Механизм выдачи файлов (приватность)

- В БД хранятся **только относительные ключи** (`FileField`/`ImageField`),
  provider-specific URL в БД не пишутся → перенос на другое S3-хранилище
  не требует миграции ключей и правки шаблонов.
- Браузер получает файлы **через authorized-proxy приложения**
  `/media/<ключ>` (`apps/core/views.media_file`): чтение идёт через
  default-storage backend, доступ проверяется логином и реестром владельцев
  `apps/core/media.MEDIA_FILE_OWNERS` (чужой ключ → 404, аноним → 302 на login).
  Presigned-URL сознательно **не** используются: не нужен browser-reachable
  TLS-endpoint хранилища, ссылки не «стекают» из кэшей страниц.
- S3 API (8333) и filer (8888/9333) **не публикуются наружу** ни в dev, ни в
  production; nginx больше не раздаёт `/media/` (публичная раздача media volume
  убрана).

## Переменные окружения

`.env` (см. `.env.example`), согласованный набор имён (в ТЗ была опечатка
`S3ACCESSKEY`/`S3SECRETKEY` — синхронизировано):

```
S3_ENDPOINT=http://s3:8333   # пустой — локальное файловое хранилище (dev без S3)
S3_ACCESS_KEY=…              # app-пользователь (не admin/root)
S3_SECRET_KEY=…
S3_BUCKET=mynotes            # dev-состав hardcode'ит mynotes-dev в docker-compose.dev.yml
S3_REGION=us-east-1          # boto3 требует регион и для self-hosted
```

В prod-`docker-compose.yml` `S3_ENDPOINT` зафиксирован на внутренний сервис
`http://s3:8333` и перекрывает `env_file`; ключи и бакет берутся из `.env`.
Непустой `S3_ENDPOINT` — **единственный** переключатель default-storage backend
(`config/settings/base.py`); `staticfiles` backend от него не зависит
(WhiteNoise/Manifest — отдельно).

## Production-топология

Два режима reverse-proxy (Этап 9.0, шапка `docker-compose.yml`):

1. **Хостовый nginx** (когда на сервере уже есть nginx с другим сайтом):
   web публикуется только на `127.0.0.1:8001`, сервисы `nginx`/`certbot` из
   compose не поднимаются. На сервер добавляется site из
   `deploy/nginx/site.conf.example` (alias `/static/` → `./staticfiles`,
   proxy `/` → `127.0.0.1:8001`, **без** `location /media/`), TLS —
   `certbot --nginx -d <домен>`.
2. **Bundled-proxy**: `docker compose --profile bundled-proxy up -d` — свой
   nginx :80/:443 (`docker/nginx.conf`) + certbot; для чистых сторонних
   инсталляций (ТЗ 1.2).

```
nginx :80/:443 ──▶ web (gunicorn :8001) ──▶ s3:8333 (S3 API, только docker-сеть)
worker/beat ─────────────────────────────▶ s3:8333
s3-init: одноразовый curl — создаёт бакет PUT'ом filer-директории
s3: chrislusf/seaweedfs:4.48, данные в volume s3_data, healthcheck master :9333
```

1. Скопировать `docker/s3-prod.json.example` → `s3-prod.json` в корень проекта на
   сервере; заменить `REPLACE_*` на реальные ключи (файл в `.gitignore`, права 600).
   Идентичность `app` получает минимальные права `Read/List/Write` только на бакет
   `mynotes` (без `Admin`); `admin` — для обслуживания. Те же app-ключи — в `.env`
   (`S3_ACCESS_KEY/S3_SECRET_KEY`).
   Проверено на SeaweedFS 4.48:
   - `signingKey` в конфиге **обязателен** (STS-подпись; без него IAM не загружается);
   - удаление объектов покрывается действием `Write` (отдельного Delete нет);
   - app без `Admin` не создаёт бакеты — бакет создаёт `s3-init`;
   - файл должен быть UTF-8 **без BOM** (SeaweedS отваливает парсер; на сервере
     редактировать `vim`, не переносить из Windows-редакторов).
2. `docker compose up -d` — `s3` станет healthy, `s3-init` создаст бакет
   (идемпотентно: PUT filer-директории `/buckets/<name>/`).
3. Проверка из `web`: `python manage.py shell -c "from django.core.files.storage import default_storage as d; print(d.url('x'))"`
   → `/media/x` (эндпоинт провайдера в URL браузера отсутствовать не должен).

### Перенос существующих файлов (media volume → бакет)

```
docker compose run --rm web python scripts/s3_files.py push /app/media
```

Идемпотентен (совпадающие по размеру ключи пропускаются). После переноса и
проверки proxy-выдачи media_volume остаётся только целью отката.

### Бэкап и восстановление

```
docker compose run --rm web python scripts/s3_files.py pull /app/_s3_backup/<дата>
```

Затем `tar`/копирование каталога во внешнее хранилище (по ТЗ: медиа — 30 дней,
еженедельно вместе с `pg_dump`). Восстановление: `push` из каталога бэкапа
(или `aws s3 sync`/`mc mirror` при наличии) — ключи относительные, совпадают.

Cron на сервере: `0 3 * * 1 cd /srv/mynotes && docker compose run --rm web python scripts/s3_files.py pull /srv/backup/media/$(date +\%F)`

### Откат на локальные файлы

`S3_ENDPOINT=` (пусто) в `.env` + `docker compose up -d web worker` →
FileSystemStorage на `media_volume`; предварительно: `pull` бакета в `/app/media`
(тот же скрипт). Миграций БД откат не требует: хранятся относительные ключи.

### Обновление MinIO→SeaweedFS-хранилища и пина образа

`docker-compose*.yml` пинят `chrislusf/seaweedfs:4.48`. Обновление: проверить
changelog → поменять тег в обоих compose → `docker compose pull s3 &&
docker compose up -d s3` (s3-init идемпотентен). Откат — вернуть прежний тег
(формат данных volume совместим между минорными версиями 4.x; перед обновлением —
свежий `pull`-бэкап).

### Мониторинг

- healthcheck'и compose (s3 master :9333 внутри сети; внешний признак деградации —
  5xx на /media/… у приложения);
- `docker compose ps` / логи `s3` (`I… volume` сообщения) — штатно unhealthy-статус
  `s3` должен отсутствовать;
- Sentry покрывает исключения proxy-view (ошибки хранилища видны как события).

## Dev

`docker-compose.dev.yml` несёт сервис `s3` (teardown: `docker compose -f
docker-compose.dev.yml down`); web/worker получают dev-credentials
(`mynotes_dev`, переопределяются `.env`), бакет `mynotes-dev` фиксирован,
авто-создание при первой загрузке. Права pytest-изоляции: `pytest.ini` →
`config.settings.test` форсирует локальный FileSystemStorage даже при
S3-переменных в контейнере; интеграционный S3-smoke
(`tests/integration/test_s3_smoke.py`) запускается только с полным набором
`S3_*` и пропускается в CI.
