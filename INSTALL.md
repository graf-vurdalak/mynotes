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

   Остальные внешние реквизиты (SMTP, OAuth, Telegram, Sentry) задаются по мере
   настройки соответствующих сервисов. Не публикуйте `.env`, `s3-prod.json` или
   значения секретов в логах и сообщениях.

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
хранения дополнительно копируйте backup вне VPS. Откат S3 на локальные файлы требует
заранее проверенного Compose override; пустой `S3_ENDPOINT` только в `.env`
недостаточен, поскольку production compose явно задаёт его для `web` и `worker`.

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
выберите или создайте тег `v0.9.3` на `main`, затем нажмите **Publish release**.
Тег должен быть новым для репозитория; для следующих релизов увеличивайте patch
версию. Workflow `Publish Docker Images` соберёт web/bot и опубликует образы с
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
# выставить IMAGE_TAG=v0.9.3; при необходимости добавить реквизиты Яндекс OAuth
docker compose pull web worker beat
docker compose run --rm --no-deps web python manage.py check --deploy
docker compose run --rm --no-deps web python manage.py migrate --noinput
docker compose up -d --no-deps --force-recreate web worker beat
docker compose ps
docker compose logs --since=5m --tail=100 web worker beat
curl -i https://mynotes.sokol-off.ru/
```

Перед `git pull` убедитесь, что в рабочем дереве сервера нет собственных изменений;
`.env` и `s3-prod.json` должны оставаться игнорируемыми Git. Ожидаемый ответ корня —
redirect на страницу входа. После обновления проверьте вход через Яндекс в браузере.
На VPS не выполняйте `docker compose build`: production-образы уже собраны GitHub
Actions и загружаются из GHCR. БД, Redis, S3 и nginx при этом не пересоздаются.
