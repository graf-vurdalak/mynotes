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

### Подготовка VPS (Этап 9.3)

Для инсталляции `graf-vurdalak/mynotes` на сервере с уже работающим хостовым nginx
выполнить проверки до включения сайта и запуска production-стека.

1. Проверить DNS после создания A-записи; AAAA нужна, только если серверу назначен
   публичный IPv6-адрес. Проверить ответы у публичного резолвера:

   ```sh
   DOMAIN=app.example.org # замените на домен установки
   dig @1.1.1.1 +short A "$DOMAIN"
   dig @1.1.1.1 +short AAAA "$DOMAIN"
   ```

   A должна вернуть IPv4-адрес VPS, а настроенная AAAA — его IPv6-адрес. `ping`
   может быть заблокирован на сервере и сам по себе не подтверждает правильность
   DNS.

2. Подключившись по SSH, проверить Docker Engine, Compose plugin, место и порт
   приложения. Пустой вывод последней команды означает, что порт `8001` свободен:

   ```sh
   docker --version
   docker compose version
   df -h / /opt
   sudo ss -ltnp | grep -E '(^|:)8001[[:space:]]' || true
   ```

   Если Docker/Compose отсутствуют, сначала установить Docker Engine с официального
   репозитория для ОС сервера. Не запускать compose с профилем `bundled-proxy`:
   порты 80/443 уже обслуживаются хостовым nginx.

3. Убедившись, что `/opt/mynotes` отсутствует или пуст, клонировать публичный
   репозиторий в каталог, доступный текущему SSH-пользователю:

   ```sh
   sudo install -d -o "$USER" -g "$USER" /opt/mynotes
   git clone --branch main https://github.com/graf-vurdalak/mynotes.git /opt/mynotes
   cd /opt/mynotes
   ```

4. Сгенерировать `.env` и `s3-prod.json` штатным скриптом. Он создаёт случайные
   секреты, синхронизирует S3 app-ключи между файлами, записывает JSON в UTF-8 без
   BOM и изначально выставляет права `600`. Затем заполнить оставшиеся доменные и внешние
   настройки только в `.env` через `vim`; не копировать готовый JSON через Windows-
   редактор. Не выводить содержимое секретных файлов в терминал/чат:

   ```sh
   python3 scripts/gen_prod_secrets.py
   vim .env
   chmod 600 .env s3-prod.json
   git check-ignore .env s3-prod.json
   ```

   `git check-ignore` должен показать оба файла. На этом подготовительном шаге не
   запускать контейнеры; сервисы запускаются отдельно в процедуре первого деплоя.

   До запуска S3 предоставьте доступ к JSON конфигу группе SeaweedFS внутри
   контейнера. Образ запускает сервер от пользователя `seaweed`; с владельцем
   `deploy` и режимом `600` файл прочитать не сможет:

   ```sh
   docker pull chrislusf/seaweedfs:4.48
   SEAWEED_GID=$(docker run --rm --entrypoint id chrislusf/seaweedfs:4.48 -g seaweed)
   sudo chgrp "$SEAWEED_GID" s3-prod.json
   sudo chmod 640 s3-prod.json
   stat -c '%U:%G %a %n' s3-prod.json
   ```

   Режим `640` оставляет запись владельцу и чтение группе SeaweedFS; `.env`
   остаётся с правами `600`.

5. GHCR-пакеты приватные. На VPS выполнить интерактивный вход с GitHub PAT
   (classic) и правом `read:packages`; учётная запись токена должна иметь доступ
   к пакетам. Вводить PAT только в запрос пароля Docker, не аргументом команды и
   не сообщением:

   ```sh
   docker login ghcr.io --username ИМЯ_ПОЛЬЗОВАТЕЛЯ_GITHUB
   ```

   После заполнения обязательных пользовательских значений в `.env` и успешного
   входа в GHCR production-проверку Django запускать **в контейнере**, а не системным
   `python3` на VPS (Django установлен в web-образе):

   ```sh
   docker compose run --rm --no-deps web python manage.py check --deploy
   ```

   Compose загрузит приватный web-образ; успешная проверка не должна содержать
   `core.E001` или других deployment errors. Команда не запускает зависимости
   (PostgreSQL/Redis/S3) и не поднимает production-стек.

### Права SeaweedFS и проверка storage

Скрипт из подготовки VPS создаёт `s3-prod.json` из
`docker/s3-prod.json.example`: `app` имеет только `Read/List/Write` для бакета
`mynotes`, `admin` — административные права. `signingKey` обязателен для
SeaweedFS 4.x; действие `Write` также покрывает удаление объектов, отдельного
`Delete` нет. Бакет создаётся сервисом `s3-init`, поскольку app-identity не имеет
права `Admin`.

При staged-подъёме инфраструктуры (Этап 9.4) сначала запустить базу, Redis и S3,
дождаться `healthy` и отдельно выполнить одноразовый `s3-init`:

```sh
docker compose up -d db redis s3
docker compose ps
docker compose run --rm --no-deps s3-init
```

Последняя команда идемпотентно создаёт бакет PUT'ом filer-директории
`/buckets/<name>/`. Команда `docker compose exec web ...` ниже нужна только после
запуска постоянно работающего сервиса `web` (она не запускает его сама). Проверить
URL хранилища из web-контейнера:

```sh
docker compose exec web python manage.py shell -c "from django.core.files.storage import default_storage as d; print(d.url('x'))"
```

Ожидается `/media/x`; адрес S3-провайдера не должен попадать в URL браузера.

### Перенос существующих файлов (media volume → бакет)

```
docker compose run --rm web python scripts/s3_files.py push /app/media
```

Идемпотентен (совпадающие по размеру ключи пропускаются). После переноса и
проверки proxy-выдачи media_volume остаётся только целью отката.

### Бэкап и восстановление

`pull` запускается во временном web-контейнере, поэтому каталог назначения должен
быть bind-mounted в постоянное хранилище хоста. На сервере (не в каталоге репозитория):

```sh
BACKUP_DIR="$HOME/mynotes-backups/media/$(date +%F)"
umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$BACKUP_DIR:/backup" web python scripts/s3_files.py pull /backup
du -sh "$BACKUP_DIR"
find "$BACKUP_DIR" -type f | wc -l
```

Затем `tar`/копирование каталога во внешнее хранилище (по ТЗ: медиа — 30 дней,
еженедельно вместе с `pg_dump`). Для восстановления объектов в бакет запускается
`scripts/s3_files.py push` с тем же bind mount и аргументом `/backup`; ключи
относительные и совпадают.

Пример еженедельного cron на сервере (`deploy`), с постоянным каталогом и
bind mount (ротация и копирование вне VPS настраиваются отдельно):

```cron
0 3 * * 1 cd /opt/mynotes && BACKUP_DIR="$HOME/mynotes-backups/media/$(date +\%F)" && umask 077 && mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR" && docker compose run --rm --no-deps --user "$(id -u):$(id -g)" -v "$BACKUP_DIR:/backup" web python scripts/s3_files.py pull /backup
```

### Откат на локальные файлы

Откат на локальное хранилище для начальной чистой установки не выполнялся.
Важно: в текущем prod compose `S3_ENDPOINT` задан явно для `web` и `worker`, поэтому
пустое значение только в `.env` **не отключает** S3. Перед использованием такого
отката нужно подготовить и проверить Compose override, который задаёт пустой endpoint
для обоих сервисов, подключает `media_volume` к worker, и восстановить копию файлов
в этот volume. Смена backend не требует миграций БД: сохраняются относительные ключи.

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
