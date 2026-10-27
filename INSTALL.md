# Установка

Инструкция описывает проверенную установку и обновление production за уже работающим
хостовым nginx. Внешние интеграции, не настроенные на сервере, перечислены отдельно.

## Подготовка VPS

1. Настройте DNS A-запись домена на публичный IPv4 VPS. Добавляйте AAAA, только
   если сервер доступен по публичному IPv6. Проверить через публичный резолвер,
   заменив пример домена:

   ```sh
   DOMAIN=app.example.org
   dig @1.1.1.1 +short A "$DOMAIN"
   dig @1.1.1.1 +short AAAA "$DOMAIN"
   ```

2. По SSH проверьте Docker Engine, Compose plugin, свободное место и порт `8001`:

   ```sh
   docker --version
   docker compose version
   df -h / /opt
   sudo ss -ltnp | grep -E '(^|:)8001[[:space:]]' || true
   ```

   Для установки с хостовым nginx порт `8001` должен быть свободен. Не включайте
   профиль `bundled-proxy`: порты 80/443 уже заняты хостовым nginx.

3. Клонируйте репозиторий в `/opt/mynotes` от имени пользователя, которому будет
   принадлежать каталог. Перед клонированием проверьте, что каталог отсутствует
   или пуст:

   ```sh
   sudo install -d -o "$USER" -g "$USER" /opt/mynotes
   git clone --branch main https://github.com/graf-vurdalak/mynotes.git /opt/mynotes
   cd /opt/mynotes
   ```

4. Создайте секретные файлы штатным генератором:

   ```sh
   python3 scripts/gen_prod_secrets.py
   vim .env
   chmod 600 .env s3-prod.json
   git check-ignore .env s3-prod.json
   ```

   Генератор синхронизирует S3 app-ключи между файлами и записывает JSON в UTF-8
   без BOM. В `.env` заполните домен, `ALLOWED_HOSTS` и образы:

   ```dotenv
   MYNOTES_WEB_IMAGE=ghcr.io/graf-vurdalak/mynotes-web
   MYNOTES_BOT_IMAGE=ghcr.io/graf-vurdalak/mynotes-bot
   IMAGE_TAG=latest
   ```

   Полный перечень параметров и плейсхолдеров приведён в tracked-шаблоне
   [`.env.prod.template`](.env.prod.template); скрипт генерации подставляет значения
   `<GEN:...>`, остальные поля задаются при настройке домена и внешних сервисов.
   Не публикуйте `.env`, `s3-prod.json` или значения секретов в логах и сообщениях.

   Перед запуском SeaweedFS предоставьте read-доступ к конфигу только группе
   процесса внутри контейнера. Образ запускает сервер от пользователя `seaweed`,
   поэтому оставлять `s3-prod.json` с режимом `600` и владельцем `deploy` нельзя:

   ```sh
   docker pull chrislusf/seaweedfs:4.48
   SEAWEED_GID=$(docker run --rm --entrypoint id chrislusf/seaweedfs:4.48 -g seaweed)
   sudo chgrp "$SEAWEED_GID" s3-prod.json
   sudo chmod 640 s3-prod.json
   stat -c '%U:%G %a %n' s3-prod.json
   ```

   Итоговый режим `640` оставляет запись владельцу `deploy`, чтение — только
   владельцу и группе SeaweedFS; `.env` сохраняет режим `600`.

5. Образы GHCR приватные. Выполните интерактивный вход GitHub PAT (classic) с
   разрешением `read:packages`; аккаунт токена должен иметь доступ к пакетам:

   ```sh
   docker login ghcr.io --username graf-vurdalak
   ```

   Введите PAT в приглашение пароля Docker, не передавайте его аргументом команды.
   Без credential helper Docker хранит токен в base64 в `~/.docker/config.json`,
   а не шифрует его. Ограничьте доступ к файлу (`chmod 600 ~/.docker/config.json`)
   либо настройте credential helper; используйте PAT с минимальным scope и сроком
   действия.
   После заполнения обязательных production-переменных проверьте настройки Django
   внутри web-образа:

   ```sh
   docker compose run --rm --no-deps web python manage.py check --deploy
   ```

   Django не установлен в системном Python VPS, поэтому эту проверку нельзя запускать
   непосредственно как `python3 manage.py ...` на хосте. Предупреждение
   `staticfiles.W004` о необязательном каталоге `/app/static` не является ошибкой;
   при первом деплое дополнительно проверьте успешный `collectstatic` и выдачу
   `/static/` через хостовый nginx.

## Первичная загрузка данных

После того как PostgreSQL, Redis и S3 перешли в `healthy`, создайте бакет и
инициализируйте базу:

```sh
docker compose run --rm --no-deps s3-init
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
docker compose run --rm web python manage.py seed_references
docker compose run --rm web python manage.py loaddata car_catalog
```

`apps/references/fixtures/car_catalog.json` — Django fixture, поэтому его нужно
загружать через `loaddata car_catalog`. Команда `import_car_catalog <JSON|URL>`
предназначена для отдельного каталога в формате списка объектов `brand/country/models`;
это не Django fixture.

Если переносится существующая локальная media-папка в S3, сделайте предварительную
копию и загрузите её в бакет **до переключения приложения**:

```sh
docker compose run --rm --no-deps web python scripts/s3_files.py push /app/media
```

Команда идемпотентна; сравните итоговые количества и размеры с источником, затем
сохраните исходную папку до проверки приложения. Для чистой production-установки,
которая изначально использует S3, этот перенос не нужен.

Запустите web и фоновые процессы; ботов поднимайте после настройки production-токенов
BotFather:

```sh
docker compose up -d web worker beat
SITE_DOMAIN=$(sed -n 's/^SITE_DOMAIN=//p' .env)
curl -i -H "Host: $SITE_DOMAIN" http://127.0.0.1:8001/
```

Для корневого URL ожидается redirect на страницу входа. Не проверяйте production
через простой `curl http://127.0.0.1:8001/`: он отправит `Host: 127.0.0.1`, который
обычно отсутствует в `ALLOWED_HOSTS`, и Django ответит `400 Bad Request`.

## Хостовый nginx и TLS

Перед включением проверьте, что конфиг `/etc/nginx/sites-available/mynotes` и
ссылка `/etc/nginx/sites-enabled/mynotes` ещё не существуют. Если не существуют,
установите пример, подставив домен из `.env`:

```sh
SITE_DOMAIN=$(sed -n 's/^SITE_DOMAIN=//p' .env)
sudo cp deploy/nginx/site.conf.example /etc/nginx/sites-available/mynotes
sudo sed -i "s|<ВАШ_ДОМЕН>|${SITE_DOMAIN}|g" /etc/nginx/sites-available/mynotes
sudo ln -s /etc/nginx/sites-available/mynotes /etc/nginx/sites-enabled/mynotes
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx --redirect -d "$SITE_DOMAIN"
```

Конфиг проксирует приложение на `127.0.0.1:8001`, передаёт `X-Forwarded-Proto` и
раздаёт `/static/`; приватные `/media/` запросы остаются на приложении. После
получения сертификата проверьте HTTPS:

```sh
curl -i "https://${SITE_DOMAIN}/"
curl -i "https://${SITE_DOMAIN}/static/admin/css/base.css"
```

Ожидается redirect на страницу входа и `200` для CSS-файла. Не проверяйте статику
запросом `/static/`: листинг каталогов nginx выключен, поэтому на корневой URL
директории он закономерно отвечает `403`.

### Вариант без хостового nginx: bundled-proxy

Этот режим предназначен для чистого VPS, где порты 80/443 свободны. Не запускайте
его одновременно с уже работающим хостовым nginx. DNS A-запись должна указывать на
VPS, а `.env` должен содержать правильный `SITE_DOMAIN` и `ALLOWED_HOSTS`. После
запуска базы, Redis, S3, `s3-init`, миграций и приложения (предыдущие разделы) сначала
получите сертификат standalone-контейнером; временно порт 80 должен быть свободен:

```sh
cd /opt/mynotes
SITE_DOMAIN=$(sed -n 's/^SITE_DOMAIN=//p' .env)
LE_EMAIL=admin@example.org
docker run --rm -p 80:80 \
  -v "$PWD/certbot/conf:/etc/letsencrypt" \
  -v "$PWD/certbot/www:/var/www/certbot" certbot/certbot \
  certonly --standalone --cert-name mynotes --agree-tos --no-eff-email \
  --email "$LE_EMAIL" -d "$SITE_DOMAIN"
```

Замените `LE_EMAIL` адресом владельца сертификата. Затем запустите встроенный nginx:

```sh
docker compose --profile bundled-proxy up -d nginx
curl -i "https://${SITE_DOMAIN}/"
```

Конфиг ожидает файлы сертификата в `certbot/conf/live/mynotes/`; каталог монтируется
в контейнер nginx, S3 API и приватная media-раздача наружу не открываются. Получение
и продление standalone-сертификата требует свободного порта 80. Перед `certbot renew`
остановите bundled nginx, после команды обязательно запустите его снова:

```sh
docker compose --profile bundled-proxy stop nginx
if docker run --rm -p 80:80 \
    -v "$PWD/certbot/conf:/etc/letsencrypt" \
    -v "$PWD/certbot/www:/var/www/certbot" certbot/certbot renew; then
  RENEW_STATUS=0
else
  RENEW_STATUS=$?
fi
docker compose --profile bundled-proxy start nginx
exit "$RENEW_STATUS"
```

Запланируйте эту проверку заранее до истечения TLS-сертификата; для полностью
автоматического обновления используйте хостовый nginx/certbot или отдельную проверенную
процедуру, которая гарантированно перезапускает nginx даже при ошибке Certbot.

## Резервная копия S3 media

Одноразовую копию для быстрого восстановления храните вне checkout репозитория:

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

Bind mount сохраняет файлы после удаления одноразового контейнера. Для production-
хранения дополнительно копируйте backup вне VPS. Проверенный Compose override и
порядок аварийного возврата на локальные файлы приведены ниже; пустой `S3_ENDPOINT`
только в `.env` недостаточен, поскольку production compose явно задаёт его для
`web` и `worker`.

## Автоматические резервные копии и проверка восстановления

На VPS от пользователя `deploy` (или другого владельца `/opt/mynotes`) создайте
каталоги с закрытыми правами:

```sh
umask 077
mkdir -p "$HOME/mynotes-backups/postgres" "$HOME/mynotes-backups/media"
chmod 700 "$HOME/mynotes-backups" "$HOME/mynotes-backups/postgres" "$HOME/mynotes-backups/media"
```

Добавьте через `crontab -e` две команды. Первый cron ежедневно сохраняет PostgreSQL
в custom-формате и оставляет последние 7 дней; второй каждую неделю выгружает S3
объекты и оставляет медиа-копии за 30 дней:

```cron
15 2 * * * cd /opt/mynotes && BACKUP_DIR="$HOME/mynotes-backups/postgres" && umask 077 && mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR" && docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$BACKUP_DIR/mynotes-$(date +\%F).dump" && test -s "$BACKUP_DIR/mynotes-$(date +\%F).dump" && find "$BACKUP_DIR" -type f -name 'mynotes-*.dump' -mtime +6 -delete
0 3 * * 1 cd /opt/mynotes && BACKUP_DIR="$HOME/mynotes-backups/media/$(date +\%F)" && umask 077 && mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR" && docker compose run --rm --no-deps --user "$(id -u):$(id -g)" -v "$BACKUP_DIR:/backup" web python scripts/s3_files.py pull /backup && find "$HOME/mynotes-backups/media" -mindepth 2 -type f -mtime +29 -delete && find "$HOME/mynotes-backups/media" -mindepth 1 -maxdepth 1 -type d -empty -delete
```

В cron символ `%` в `date` должен быть экранирован обратной косой чертой. Проверьте
расписание (`crontab -l`), журналы cron и появление непустого `.dump` после первого
запуска. Эти копии находятся на том же VPS и не заменяют off-site backup: регулярно
копируйте оба каталога во внешнее хранилище либо настройте snapshots у VPS-провайдера.
Ограничьте доступ и включите шифрование резервных копий на внешнем хранилище: дамп
содержит пользовательские данные. Не помещайте резервные файлы в `/opt/mynotes`.

Для пробного восстановления PostgreSQL используйте отдельную временную БД, а не
боевую `mynotes` (выполняйте в спокойное время; потребуется свободное место):

```sh
cd /opt/mynotes
BACKUP_FILE="$HOME/mynotes-backups/postgres/mynotes-YYYY-MM-DD.dump"
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" -T template0 mynotes_restore_test'
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d mynotes_restore_test --no-owner --no-privileges' < "$BACKUP_FILE"
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d mynotes_restore_test -c "SELECT count(*) FROM django_migrations"'
docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" mynotes_restore_test'
```

До запуска проверьте путь `BACKUP_FILE`. Если восстановление прервалось, удалите
только временную БД `mynotes_restore_test` после диагностики; никогда не подменяйте
production DB при проверке. Для медиа проверьте, что backup содержит ожидаемое число
файлов. Для полного теста загрузите их в изолированный staging S3/bucket с отдельными
`S3_ENDPOINT`/`S3_BUCKET`; `scripts/s3_files.py push` использует активную конфигурацию
и не должен запускаться с production bucket во время пробного восстановления.

Ежедневный `pg_dump` выполняется системным cron, а не Celery Beat: резервное копирование
БД не должно зависеть от доступности приложения/планировщика. Периодическое копирование
S3 media также запускается cron; Celery Beat остаётся для прикладных напоминаний.

### Аварийный возврат S3 → локальные файлы

Подготовлен `docker-compose.local-storage.yml`. До переключения скачайте объекты в
named volume `media_volume`, пока web ещё использует S3:

```sh
docker compose run --rm --no-deps web python scripts/s3_files.py pull /app/media
docker compose -f docker-compose.yml -f docker-compose.local-storage.yml config -q
docker compose -f docker-compose.yml -f docker-compose.local-storage.yml up -d --force-recreate web worker
```

Override очищает `S3_ENDPOINT` для `web` и `worker` и монтирует общий `media_volume`
в worker; `depends_on` сбрасывается, чтобы нездоровый S3 не блокировал перезапуск.
Для `!reset` в Compose-файле требуется Compose plugin 2.24.4 или новее. После
переключения проверьте несколько файлов в приложении, задачи Celery
с загрузками и логи сервисов. Чтобы вернуться на S3, повторно создайте `web` и
`worker` без override; не удаляйте `media_volume` и `s3_data` до подтверждения
восстановления. Этот путь не выполняется штатно, только при аварии.

Подробная схема S3, права SeaweedFS, проксирование и восстановление описаны в
[`docs/deployment.md`](docs/deployment.md).

## Внешние production-сервисы

### Яндекс OAuth

В production OAuth-приложении зарегистрируйте callback allauth:

```text
https://<SITE_DOMAIN>/accounts/yandex/login/callback/
```

Замените `<SITE_DOMAIN>` доменом из `.env` (без схемы). Разрешите права Yandex ID
на email и профиль: приложение запрашивает scopes `login:email` и `login:info`.
Внесите client ID и secret прямо на сервере, не передавайте их в чат:

```sh
vim .env
docker compose up -d --force-recreate web worker beat
```

Выйдите из текущей сессии и проверьте вход через кнопку Яндекса в браузере.
При ошибке проверяйте `docker compose logs --since=5m --tail=100 web`, не публикуя
секреты.

### Telegram-боты

Для production используйте отдельные токены BotFather, отличные от dev-токенов.
Укажите `TELEGRAM_VEHICLE_BOT_TOKEN` и `TELEGRAM_PLANNER_BOT_TOKEN` в серверном
`.env`, затем пересоздайте боты: `docker compose up -d --force-recreate bot_vehicle
bot_planner`. Боты используют long polling: перед запуском удалите ранее заданный
webhook через BotFather/API. В приложении создайте отдельный AuthToken в
`/accounts/tokens/`, привяжите production URL через `/addserver` и проверьте
`/ping`, `/quick` и запланированное напоминание. Секрет AuthToken показывается только
при выпуске; не копируйте его в Git, логи или сообщения.

### Sentry и SMTP

Для Sentry создайте проект Django и задайте его DSN в `SENTRY_DSN`; если пока не
подключаете Sentry, оставьте значение пустым осознанно. После перезапуска web/worker
отправьте безопасное тестовое событие из контейнера и подтвердите его появление в
проекте:

```sh
docker compose run --rm --no-deps web python manage.py shell -c "import sentry_sdk; sentry_sdk.capture_message('MyNotes production smoke test')"
```

Для почты задайте SMTP host, port, username/password, sender и TLS-параметры в `.env`.
`EMAIL_USE_SSL` и `EMAIL_USE_TLS` взаимоисключающие: SSL обычно используется с 465,
STARTTLS — с 587. Уточните у провайдера разрешённый порт (на некоторых VPS исходящий
SMTP ограничен), затем проверьте реальную отправку через регистрацию или сброс
пароля; тестовое письмо также можно отправить так:

```sh
docker compose run --rm --no-deps web python manage.py shell -c "from django.core.mail import send_mail; send_mail('MyNotes SMTP smoke test', 'SMTP delivery check', None, ['YOUR_EMAIL@example.org'])"
```

Замените адрес на свой и не передавайте пароль SMTP аргументом команды.

## Обновление production через GitHub

### Локально (PowerShell, каталог проекта)

Проверьте изменения и закоммитьте только файлы текущей задачи:

```powershell
git status --short
git add path/to/changed-file
git diff --cached --check
git commit -m "Краткое описание изменений"
git push -u origin main
```

Вместо `path/to/changed-file` укажите конкретные проверенные пути; не используйте
`git add -A`, если в рабочем дереве есть несвязанные файлы.

Push в `main` запускает CI, но сам по себе **не публикует** образы в GHCR.

### GitHub (веб-интерфейс)

После успешного CI создайте GitHub Release: **Releases → Draft a new release**,
выберите или создайте новый тег на `main` (для первого production-релиза — `v1.0.0`),
затем нажмите **Publish release**. Для следующих релизов увеличивайте версию по
SemVer. Workflow `Publish Docker Images` соберёт web/bot и опубликует образы с
тегами версии и `latest`. Перед продолжением дождитесь успешного завершения workflow.

### Production VPS (SSH)

В `.env` проекта задайте тег именно опубликованного релиза. Если одновременно
настраивается Яндекс OAuth, там же задайте `YANDEX_OAUTH_CLIENT_ID` и
`YANDEX_OAUTH_SECRET` после регистрации callback из раздела выше. Не выводите
содержимое `.env` в терминал и не добавляйте его в Git.

```sh
cd /opt/mynotes
git status --short
git pull --ff-only origin main
vim .env
# выставить IMAGE_TAG=latest; при необходимости добавить реквизиты Яндекс OAuth
docker compose pull web worker beat
docker compose pull bot_vehicle bot_planner
docker compose run --rm --no-deps web python manage.py check --deploy
docker compose run --rm --no-deps web python manage.py migrate --noinput
docker compose up -d --no-deps --force-recreate web worker beat bot_vehicle bot_planner
docker compose ps
docker compose logs --since=5m --tail=100 web worker beat bot_vehicle bot_planner
SITE_DOMAIN=$(sed -n 's/^SITE_DOMAIN=//p' .env)
curl -i "https://${SITE_DOMAIN}/"
```

Перед `git pull` убедитесь, что в рабочем дереве сервера нет собственных изменений;
`.env` и `s3-prod.json` должны оставаться игнорируемыми Git. Ожидаемый ответ корня —
redirect на страницу входа. После обновления проверьте вход через Яндекс в браузере.
На VPS не выполняйте `docker compose build`: production-образы уже собраны GitHub
Actions и загружаются из GHCR. БД, Redis, S3 и nginx при этом не пересоздаются.
