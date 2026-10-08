ТЕХНИЧЕСКОЕ ЗАДАНИЕ
Единая платформа «Мои записи» (MyNotes)
Бортжурнал автомобиля + Записная книжка

Версия документа: 1.0  
Дата: 01.08.2026  
Лицензия проекта: MIT  
Статус: Согласование

Содержание

Общие сведения о проекте
Термины и определения
Стек технологий
Требования к функциональности
Структура базы данных
Архитектура приложения
Telegram-боты
Требования к безопасности
Дизайн и UI
Локализация
Отчёты и аналитика
Тестирование
Развёртывание и CI/CD
Требования к документации
Этапы реализации
Приложения

Общие сведения о проекте

1.1. Назначение

Единый веб-ресурс, объединяющий два функциональных блока:

Бортжурнал — учёт расходов, событий и плановых работ, связанных с автомобилем (включая штрафы и страхование).
Записная книжка — планировщик личных и рабочих событий/задач с элементами Agile.

Данные вносятся двумя способами:
Через веб-интерфейс (адаптивный, mobile-first).
Через два Telegram-бота (один для Бортжурнала, второй для Записной книжки).

1.2. Целевая аудитория

Личное использование владельцем проекта. Возможность развёртывания сторонними разработчиками на собственных серверах.

1.3. Модель развёртывания

Публичный репозиторий на GitHub (исходный код открыт, лицензия MIT).
Доступ к данным — строго по авторизации. Гостевой доступ отсутствует.
Поддержка нескольких инсталляций (dev / prod / кастомные) через механизм токенов и конфигурируемых адресов сервера в ботах.
Хостинг: VPS (рекомендуется AdminVPS или аналог).
Доменное имя: настраивается администратором. В документации используется плейсхолдер .

1.4. Ограничения и допущения

Прямое упоминание конкретного доменного имени в коде и документации запрещено. Используется переменная окружения SITEDOMAIN со значением по умолчанию .
Платформа предназначена для личного использования, многопользовательский совместный доступ (шаринг задач между пользователями) не реализуется.
Валюта: любая, настраивается пользователем в ЛК (по умолчанию — рубли ₽).
Язык интерфейса: русский (с возможностью локализации силами сторонних разработчиков).

Термины и определения

| Термин | Определение |
|---|---|
| Бортжурнал | Модуль учёта автомобильных расходов и событий |
| Записная книжка | Модуль планирования личных и рабочих событий/задач |
| Скоуп (Scope) | Раздел Записной книжки: «Личное» или «Рабочее» |
| Инсталляция | Конкретный развёрнутый экземпляр платформы (dev, prod и т.п.) |
| Bot-токен | Криптографический ключ, выдаваемый в ЛК для привязки Telegram-бота |
| NLP-парсинг | Разбор естественного языка для быстрого ввода данных |
| Soft delete | Логическое удаление (флаг is_deleted вместо физического удаления записи) |

Стек технологий

3.1. Backend

| Компонент | Технология | Обоснование |
|---|---|---|
| Фреймворк | Django 5.x + Django REST Framework | Зрелая экосистема, встроенная админка, ORM, миграции, auth |
| СУБД | PostgreSQL 16 | JSONB для гибких полей, полнотекстовый поиск, надёжность |
| Кэш / очереди | Redis 7 | Кэш сессий, Celery broker, rate-limiting |
| Фоновые задачи | Celery 5 + Celery Beat | Напоминания, обработка фото, агрегация отчётов |
| Аутентификация | django-allauth | Email + Яндекс OAuth из коробки |
| 2FA | django-otp (TOTP) | Включено в первую версию (см. п. 8) |
| API-документация | drf-spectacular (OpenAPI 3.0) | Автогенерация Swagger/ReDoc |
| Валидация | pydantic (для NLP-парсинга) | Строгая типизация входных данных |

3.2. Telegram-боты

| Компонент | Технология |
|---|---|
| Фреймворк | aiogram 3.x (Python, async) |
| NLP (быстрый ввод) | Собственный парсинг на регулярных выражениях + ключевых словах (этап 1); интеграция с LLM — на этапе 2 |
| Распознавание голоса | OpenAI Whisper API (отложено на этап 2) |

3.3. Frontend

| Компонент | Технология | Обоснование |
|---|---|---|
| Рендеринг | Django templates + HTMX 2.x | Быстрый SSR, без тяжёлого SPA, mobile-first |
| Стили | TailwindCSS 3.x | Utility-first, адаптивность из коробки |
| Интерактив | Alpine.js | Лёгкая реактивность без фреймворка |
| Kanban drag-n-drop | SortableJS | Проверенная библиотека |
| Графики | ApexCharts | Красивые, адаптивные графики |
| Иконки | Lucide Icons | SVG, лёгкие, согласованный стиль |
| Календарь | FullCalendar | Поддержка повторяющихся событий |

3.4. Инфраструктура

| Компонент | Технология |
|---|---|
| Контейнеризация | Docker + docker-compose |
| Reverse proxy | Nginx |
| TLS | Let's Encrypt (certbot) |
| Хранилище файлов | S3-совместимое (SeaweedFS локально / Yandex Object Storage / AWS S3; публичные образы MinIO недоступны с 2025) |
| CI/CD | GitHub Actions |
| Мониторинг | Sentry (ошибки), UptimeRobot (доступность, опц.) |

Требования к функциональности

4.1. Аутентификация и профиль пользователя

4.1.1. Регистрация и вход

Email + пароль: обязательная верификация email (ссылка на почту).
Яндекс OAuth 2.0: подключение через django-allauth (код подключения — в разделе «Приложения»).
Двухфакторная аутентификация (2FA): TOTP через django-otp (включена в первую версию — трудозатраты ~2 дня, существенно повышает безопасность публичного проекта).
Восстановление пароля: ссылка на email.

4.1.2. Личный кабинет

Смена email (с повторной верификацией).
Смена пароля.
Настройка 2FA (включение/выключение, резервные коды).
Настройка валюты по умолчанию (список валют: RUB, USD, EUR, KZT, UAH, BYN и др.).
Настройка часового пояса.
Настройка языка интерфейса (пока только ru, структура готова к расширению).
Управление токенами для Telegram-ботов (создание, отзыв, история использования).
Просмотр журнала входов (IP, userAgent, провайдер, дата).

4.1.3. Управление токенами для ботов

Пользователь может создать неограниченное количество токенов.
Каждый токен имеет имя (например, «Бот на телефоне», «Dev-инсталляция»).
Токен показывается только один раз при создании.
Возможность отозвать токен.
Отображение даты последнего использования.

4.2. Бортжурнал

4.2.1. Автопарк

Пользователь может добавить несколько автомобилей.
Одно авто может быть назначено «по умолчанию» (для быстрого выбора в боте).
Поля автомобиля:
  - Марка (из справочника)
  - Модель (из справочника, зависит от марки)
  - Год выпуска
  - VIN (17 символов, опционально, с проверкой формата)
  - Гос. номер (опционально)
  - Тип топлива: бензин / дизель / электро / гибрид / газ
  - Объём двигателя (см³, опц.)
  - Мощность (л.с., опц.)
  - КПП: МКПП / АКПП / вариатор / робот
  - Привод: передний / задний / полный
  - Цвет (опц.)
  - Дата покупки (опц.)
  - Стоимость покупки (опц.)
  - Текущий пробег
  - Произвольные параметры (JSON — например, «размер шин», «масло»)
  - Фото автомобиля (1 основное, опц.)

Справочники марок и моделей: импортируются из открытого каталога (например, данные типа Auto.ru / каталог ГИБДД). Обновляются management-командой.

4.2.2. Заправки

Дата заправки
АЗС: выбор из справочника крупных сетей ИЛИ ввод произвольного названия
Тип топлива
Объём (литры)
Цена за литр
Сумма (авто-расчёт или ручной ввод)
Пробег на момент заправки
Полный бак (да/нет)
Геолокация (опц., определяется автоматически в боте)
Источник: web / telegram

Справочник крупных сетей АЗС (предзаполненный):
Лукойл, Роснефть, Газпромнефть, BP, Shell, Татнефть, Башнефть, ЕКА, Нефис, Трасса, Circle K, Optima, Магистраль, Русснефть, Сургутнефтегаз.

4.2.3. Покупки

Дата
Автомобиль
Категория (из предзаданного списка + пользовательские)
Название / описание
Сумма
Пробег (опц.)
Список товаров (опц., JSON: {name, qty, price})
Фото чека (опц.)

Стартовый набор категорий:
Запчасти
Расходники (масла, фильтры)
Шины / диски
Мойка / химия
Страховка (ОСАГО / КАСКО)
Транспортный налог
Парковка
Штрафы
Ремонт своими силами
Тюнинг / доп. оборудование
Эвакуатор / помощь на дороге
Прочее

4.2.4. Сервисное обслуживание

Дата
Автомобиль
Название сервиса (СТО)
Описание работ
Стоимость
Пробег
Текст заказ-наряда (опц.)
Фото заказ-наряда: до 10 фото на одну запись
Связь с плановым событием (опц.)

4.2.5. Штрафы ГИБДД (новый раздел)

Дата штрафа
Номер постановления (УИН)
Автомобиль
Статья КоАП
Описание нарушения
Сумма
Статус: оплачен / не оплачен / оспаривается
Дата оплаты (опц.)
Фото постановления (опц.)
Возможность привязать к покупке (категория «Штрафы»)

4.2.6. Страхование (отдельный раздел)

Тип: ОСАГО / КАСКО / ДСАГО / Зеленая карта
Страховая компания
Номер полиса
Автомобиль
Дата начала / дата окончания
Стоимость
Фото полиса
Напоминание: за 1 месяц до окончания полиса — уведомление в Записной книжке (создаётся автоматически как событие в разделе «Личное»).

4.2.7. Планирование событий (связь с Записной книжкой)

Дата и время планового события
Описание
Место (опц.)
Автомобиль
Предполагаемая стоимость (опц.)
Связь с событием в Записной книжке (автоматически создаётся в «Личном» скоупе)

Примеры: ТО, замена масла, техосмотр, запись на шиномонтаж.

4.2.8. Напоминания (Бортжурнал)

О приближающемся ТО (настраивается: по пробегу и/или дате).
Об окончании страховки (за 1 месяц, настраиваемо).
О необходимости уплаты транспортного налога (дата настраивается).
О неоплаченных штрафах.
Каналы уведомлений: email + Telegram (через бота).

4.2.9. Статистика и отчёты (Бортжурнал)

Расходы по месяцам (bar chart).
Расходы по категориям (pie chart).
Расход топлива (л/100 км) в динамике.
Стоимость 1 км пробега.
Прогноз следующего ТО.
Топ-5 самых затратных статей.
Экспорт отчётов: Excel (.xlsx), PDF.

4.3. Записная книжка

4.3.1. Структура

Два раздела (скоупа), изолированных друг от друга:
Личное — события, встречи, напоминания.
Рабочее — задачи со статусами (Agile-подобный workflow).

Внутри каждого скоупа — поддержка проектов (группировка событий/задач).

4.3.2. Личный раздел

Календарь (вид: месяц / неделя / день).
Список событий (лента).
Создание события:
  - Заголовок
  - Описание
  - Дата/время начала и окончания
  - Место (опц.)
  - Проект (опц.)
  - Приоритет: низкий / обычный / высокий / срочный
  - Теги (произвольные)
  - Повторение: не повторяется / ежедневно / еженедельно / ежемесячно / ежегодно / по дням недели / произвольный интервал
  - Напоминание: за N минут/часов/дней до события (настраивается пользователем глобально и для каждого события отдельно)
  - Вложения (файлы, опц.)
Цветовая маркировка по проектам.
Полнотекстовый поиск по событиям.

4.3.3. Рабочий раздел

Статусы задач (по умолчанию, настраиваемые):

| Код | Название | Цвет |
|---|---|---|
| new | Новый | серый |
| estimate | Оценка | синий |
| in_progress | В работе | жёлтый |
| testing | Тестирование | оранжевый |
| done | Готово | зелёный |

Пользователь может добавлять/удалять/переименовывать статусы.

Kanban-доска:
5 колонок по статусам.
Drag-n-drop карточек между колонками (через SortableJS + HTMX).
Фильтры: по проекту, приоритету, тегам, дате, исполнителю (когда появится).
Поиск по задачам.

Карточка задачи:
Заголовок
Описание (Markdown)
Проект
Статус
Приоритет
Даты: создания, начала, дедлайн, завершения
Оценка времени (часы, опц.)
Фактическое время (опц.)
Теги
Комментарии: неограниченное количество, с поддержкой вложений (файлы, включая аудиозаписи — до 10 МБ на файл).
История изменений статусов (автоматически).

Повторяющиеся задачи: поддерживаются по аналогии с личными событиями.

4.3.4. Проекты (в обоих скоупах)

Название
Описание
Цвет
Статус: активный / архивный
Связанные события/задачи
Прогресс (авто-расчёт для рабочих: % выполненных задач)

4.3.5. Напоминания (Записная книжка)

Глобальная настройка: «напоминать по умолчанию за N минут до события».
Индивидуальная настройка для каждого события.
Каналы: email + Telegram.

4.3.6. Отчёты (Рабочий раздел)

Количество задач по статусам за период.
Среднее время нахождения задачи в каждом статусе.
Выполнено vs просрочено.
Burndown-диаграмма по проекту.
Топ-5 самых долгих задач.
Экспорт: Excel, PDF.

4.4. Глобальный поиск

Полнотекстовый поиск по всем сущностям (автомобили, заправки, покупки, сервисы, события, задачи, проекты).
Фильтры по типу сущности, дате, проекту.
Использование pg_trgm + tsvector в PostgreSQL.

Структура базы данных

5.1. Общие принципы

Все таблицы имеют поля: createdat, updatedat, is_deleted (soft delete).
Первичные ключи — UUID v4 (безопасность, невозможно угадать ID).
Все бизнес-сущности привязаны к user_id (мультипользовательность).
Денежные суммы хранятся в DECIMAL(12,2) + currency_code (VARCHAR(3), ISO 4217).
Мягкие удаления + аудит (таблица audit_log).
Индексы на все внешние ключи и часто фильтруемые поля.
Полнотекстовые индексы GIN для поиска.

5.2. Таблицы аутентификации и профиля
sql
-- Пользователи (расширение Django User)
auth_user (
    id              UUID PK,
    email           VARCHAR(254) UNIQUE NOT NULL,
    username        VARCHAR(150) UNIQUE,
    password_hash   VARCHAR(255),          -- для email-авторизации
    yandex_uid      VARCHAR(128) UNIQUE,   -- для Яндекс OAuth
    display_name    VARCHAR(200),
    avatar_url      TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    is_staff        BOOLEAN DEFAULT FALSE,
    email_verified  BOOLEAN DEFAULT FALSE,
    date_joined     TIMESTAMPTZ,
    last_login      TIMESTAMPTZ
)

-- Настройки пользователя
user_settings (
    id              UUID PK,
    userid         FK -> authuser UNIQUE,
    default_currency VARCHAR(3) DEFAULT 'RUB',
    timezone        VARCHAR(50) DEFAULT 'Europe/Moscow',
    language        VARCHAR(5) DEFAULT 'ru',
    reminderdefaultminutes INT DEFAULT 30,  -- напоминание по умолчанию
    dark_theme      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ
)

-- Токены для Telegram-ботов
auth_token (
    id              UUID PK,
    userid         FK -> authuser,
    token_hash      VARCHAR(128) UNIQUE NOT NULL,  -- SHA-256 + соль
    name            VARCHAR(100),
    created_at      TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    lastusedat    TIMESTAMPTZ,
    lastusedip    INET
)

-- Журнал сессий
authsessionlog (
    id              UUID PK,
    userid         FK -> authuser,
    ip_address      INET,
    user_agent      TEXT,
    provider        VARCHAR(20),   -- 'email' | 'yandex'
    created_at      TIMESTAMPTZ
)

-- 2FA TOTP-устройства
authtotpdevice (
    id              UUID PK,
    userid         FK -> authuser,
    key             VARCHAR(64),
    name            VARCHAR(100),
    confirmed       BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ
)

-- Резервные коды 2FA
authtotpbackup_code (
    id              UUID PK,
    deviceid       FK -> authtotp_device,
    code_hash       VARCHAR(128),
    used_at         TIMESTAMPTZ
)

5.3. Таблицы Бортжурнала
sql
-- Автомобили
vehicle_vehicle (
    id              UUID PK,
    userid         FK -> authuser,
    brandid        FK -> refcar_brand,
    modelid        FK -> refcar_model,
    brand_custom    VARCHAR(100),      -- если не из справочника
    model_custom    VARCHAR(100),
    year            SMALLINT,
    vin             VARCHAR(17),       -- с проверкой формата
    license_plate   VARCHAR(20),
    fuel_type       VARCHAR(20),       -- petrol/diesel/electric/hybrid/gas
    engine_volume   INT,               -- см³
    power_hp        INT,
    transmission    VARCHAR(20),       -- mt/at/cvt/robot
    drive_type      VARCHAR(10),       -- fwd/rwd/awd
    color           VARCHAR(50),
    purchase_date   DATE,
    purchase_price  DECIMAL(12,2),
    purchase_currency VARCHAR(3),
    current_mileage INT,
    notes           TEXT,
    metadata        JSONB,             -- произвольные параметры
    photo_url       TEXT,
    is_default      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT FALSE
)

-- Справочник марок
refcarbrand (
    id              UUID PK,
    name            VARCHAR(100) NOT NULL,
    country         VARCHAR(50),
    logo_url        TEXT,
    is_active       BOOLEAN DEFAULT TRUE
)

-- Справочник моделей
refcarmodel (
    id              UUID PK,
    brandid        FK -> refcar_brand,
    name            VARCHAR(100) NOT NULL,
    year_from       SMALLINT,
    year_to         SMALLINT,
    body_type       VARCHAR(30)        -- sedan/suv/hatchback и т.п.
)

-- АЗС (справочник + пользовательские)
vehiclefuelstation (
    id              UUID PK,
    name            VARCHAR(200),
    brand           VARCHAR(100),
    is_system       BOOLEAN DEFAULT FALSE,  -- предзаполненные
    address         TEXT,
    latitude        DECIMAL(10,7),
    longitude       DECIMAL(10,7),
    createdbyid   FK -> auth_user
)

-- Заправки
vehiclefuelentry (
    id              UUID PK,
    userid         FK -> authuser,
    vehicleid      FK -> vehiclevehicle,
    stationid      FK -> vehiclefuel_station,
    stationcustomname TEXT,
    fuel_date       DATE NOT NULL,
    odometer        INT NOT NULL,
    fuel_type       VARCHAR(20),
    volume_liters   DECIMAL(6,2),
    priceperliter DECIMAL(8,3),
    total_cost      DECIMAL(12,2),
    currency_code   VARCHAR(3),
    full_tank       BOOLEAN,
    latitude        DECIMAL(10,7),
    longitude       DECIMAL(10,7),
    source          VARCHAR(10),       -- web/telegram
    created_at      TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT FALSE
)

-- Категории покупок
vehiclepurchasecategory (
    id              UUID PK,
    userid         FK -> authuser,   -- NULL = системная
    name            VARCHAR(100),
    icon            VARCHAR(50),
    color           VARCHAR(7),
    sort_order      INT,
    is_system       BOOLEAN DEFAULT FALSE
)

-- Покупки
vehicle_purchase (
    id              UUID PK,
    userid         FK -> authuser,
    vehicleid      FK -> vehiclevehicle,
    categoryid     FK -> vehiclepurchase_category,
    title           VARCHAR(255),
    description     TEXT,
    amount          DECIMAL(12,2),
    currency_code   VARCHAR(3),
    purchase_date   DATE,
    odometer        INT,
    items           JSONB,             -- [{name, qty, price}]
    source          VARCHAR(10),
    created_at      TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT FALSE
)

-- Сервисное обслуживание
vehicle_service (
    id              UUID PK,
    userid         FK -> authuser,
    vehicleid      FK -> vehiclevehicle,
    service_station VARCHAR(255),
    work_description TEXT,
    amount          DECIMAL(12,2),
    currency_code   VARCHAR(3),
    service_date    DATE,
    odometer        INT,
    order_document  TEXT,
    plannedeventid FK -> vehicleplannedevent,
    source          VARCHAR(10),
    created_at      TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT FALSE
)

-- Фото сервисов
vehicleservicephoto (
    id              UUID PK,
    serviceid      FK -> vehicleservice,
    file_url        TEXT,
    file_key        VARCHAR(255),
    thumbnail_url   TEXT,
    sort_order      INT,
    uploaded_at     TIMESTAMPTZ
)

-- Штрафы ГИБДД
vehicle_fine (
    id              UUID PK,
    userid         FK -> authuser,
    vehicleid      FK -> vehiclevehicle,
    fine_date       DATE,
    decision_number VARCHAR(50),       -- УИН
    article         VARCHAR(50),       -- статья КоАП
    description     TEXT,
    amount          DECIMAL(12,2),
    currency_code   VARCHAR(3),
    status          VARCHAR(20),       -- unpaid/paid/disputed
    paid_at         DATE,
    purchaseid     FK -> vehiclepurchase,  -- связь с оплатой
    photo_url       TEXT,
    source          VARCHAR(10),
    created_at      TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT FALSE
)

-- Страхование
vehicle_insurance (
    id              UUID PK,
    userid         FK -> authuser,
    vehicleid      FK -> vehiclevehicle,
    insurance_type  VARCHAR(20),       -- osago/kasko/dsago/greencard
    company         VARCHAR(200),
    policy_number   VARCHAR(50),
    start_date      DATE,
    end_date        DATE,
    cost            DECIMAL(12,2),
    currency_code   VARCHAR(3),
    photo_url       TEXT,
    reminder_created BOOLEAN DEFAULT FALSE,  -- создано ли напоминание
    created_at      TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT FALSE
)

-- Плановые события (связь с Записной книжкой)
vehicleplannedevent (
    id              UUID PK,
    userid         FK -> authuser,
    vehicleid      FK -> vehiclevehicle,
    plannereventid FK -> planner_event,   -- связь с календарём
    description     TEXT,
    planned_date    TIMESTAMPTZ,
    location        VARCHAR(255),
    estimated_cost  DECIMAL(12,2),
    currency_code   VARCHAR(3),
    reminder_type   VARCHAR(20),       -- mileage/date/both
    reminder_mileage INT,              -- для ТО по пробегу
    created_at      TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT FALSE
)

5.4. Таблицы Записной книжки
sql
-- Скоупы (Личное / Рабочее)
planner_scope (
    id              UUID PK,
    userid         FK -> authuser,
    code            VARCHAR(20),       -- 'personal' | 'work'
    name            VARCHAR(50),
    created_at      TIMESTAMPTZ
)

-- Проекты
planner_project (
    id              UUID PK,
    userid         FK -> authuser,
    scopeid        FK -> plannerscope,
    title           VARCHAR(200),
    description     TEXT,
    color           VARCHAR(7),
    is_archived     BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT FALSE
)

-- Статусы задач (настраиваемые)
planner_status (
    id              UUID PK,
    userid         FK -> authuser,   -- NULL = системный
    code            VARCHAR(30),
    name            VARCHAR(50),
    color           VARCHAR(7),
    sort_order      INT,
    is_system       BOOLEAN DEFAULT FALSE
)

-- События и задачи (универсальная сущность)
planner_event (
    id              UUID PK,
    userid         FK -> authuser,
    scopeid        FK -> plannerscope,
    projectid      FK -> plannerproject,
    title           VARCHAR(300),
    description     TEXT,
    event_type      VARCHAR(20),       -- task/meeting/reminder/milestone
    statusid       FK -> plannerstatus,
    priority        VARCHAR(10),       -- low/normal/high/urgent
    start_at        TIMESTAMPTZ,
    end_at          TIMESTAMPTZ,
    due_at          TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    location        VARCHAR(255),
    estimated_minutes INT,
    actual_minutes  INT,
    tags            TEXT[],
    -- Повторяемость
    recurrence_rule TEXT,              -- iCal RRULE формат
    recurrence_end  TIMESTAMPTZ,
    parenteventid UUID,              -- для экземпляров повторяющихся
    -- Напоминания
    reminderminutesbefore INT,
    reminder_sent   BOOLEAN DEFAULT FALSE,
    source          VARCHAR(10),       -- web/telegram
    search_vector   TSVECTOR,          -- для полнотекстового поиска
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT FALSE
)

-- Вложения к событиям/задачам
plannereventattachment (
    id              UUID PK,
    eventid        FK -> plannerevent,
    file_url        TEXT,
    file_key        VARCHAR(255),
    file_name       VARCHAR(255),
    mime_type       VARCHAR(100),
    size_bytes      INT,
    uploaded_at     TIMESTAMPTZ
)

-- Комментарии к задачам
planner_comment (
    id              UUID PK,
    eventid        FK -> plannerevent,
    userid         FK -> authuser,
    text            TEXT,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    is_deleted      BOOLEAN DEFAULT FALSE
)

-- Вложения к комментариям
plannercommentattachment (
    id              UUID PK,
    commentid      FK -> plannercomment,
    file_url        TEXT,
    file_key        VARCHAR(255),
    file_name       VARCHAR(255),
    mime_type       VARCHAR(100),
    size_bytes      INT,
    uploaded_at     TIMESTAMPTZ
)

-- История изменений статусов
plannerstatushistory (
    id              UUID PK,
    eventid        FK -> plannerevent,
    fromstatusid  FK -> planner_status,
    tostatusid    FK -> planner_status,
    changedbyid   FK -> auth_user,
    changed_at      TIMESTAMPTZ,
    comment         TEXT
)

5.5. Таблицы уведомлений и аудита
sql
-- Уведомления
notification (
    id              UUID PK,
    userid         FK -> authuser,
    type            VARCHAR(50),       -- insuranceexpiring/fineunpaid/event_reminder и т.п.
    title           VARCHAR(255),
    message         TEXT,
    entity_type     VARCHAR(50),
    entity_id       UUID,
    is_read         BOOLEAN DEFAULT FALSE,
    sentviaemail  BOOLEAN DEFAULT FALSE,
    sentviatelegram BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ
)

-- Аудит
audit_log (
    id              BIGSERIAL PK,
    userid         FK -> authuser,
    action          VARCHAR(50),
    entity_type     VARCHAR(50),
    entity_id       UUID,
    old_value       JSONB,
    new_value       JSONB,
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ
)

Архитектура приложения

6.1. Структура Django-проекта

my_notes/
├── config/                    # настройки, wsgi, asgi, celery
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   ├── celery.py
│   └── wsgi.py
├── apps/
│   ├── accounts/              # auth, профили, токены, 2FA
│   ├── vehicles/              # бортжурнал (авто, заправки, покупки, сервисы, штрафы, страховки)
│   ├── planner/               # записная книжка (события, задачи, проекты)
│   ├── references/            # справочники (марки, модели, АЗС, категории)
│   ├── notifications/         # уведомления, напоминания, Celery-задачи
│   ├── reports/               # генерация отчётов (Excel, PDF)
│   ├── search/                # полнотекстовый поиск
│   └── api/                   # DRF-эндпоинты для ботов
├── telegram_bots/
│   ├── vehicle_bot/           # aiogram-бот для бортжурнала
│   └── planner_bot/           # aiogram-бот для записной книжки
├── locale/                    # файлы локализации (.lang)
├── templates/                 # Django templates + HTMX
├── static/
├── media/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docker/
│   ├── Dockerfile.web
│   ├── Dockerfile.bot
│   └── nginx.conf
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── Makefile
└── README.md

6.2. API для Telegram-ботов

Единый gateway для обоих ботов:

POST /api/v1/bot/ingest
Headers:
  X-Bot-Token: 
  X-Client-Id: 
Body:
{
  "module": "vehicle" | "planner",
  "action": "createfuel" | "createpurchase" | "create_task" | ... ,
  "payload": { ... }
}

Ответы:
  200 OK { "status": "ok", "entity_id": "..." }
  401 Unauthorized (неверный токен)
  400 Bad Request (ошибка валидации)
  429 Too Many Requests (rate limit)

Дополнительные эндпоинты:
POST /api/v1/bot/ping — проверка валидности токена.
POST /api/v1/bot/upload — загрузка файлов (фото, аудио).
GET /api/v1/bot/references/{type} — получение справочников.

6.3. Внутренние API (для frontend)

REST API через DRF для всех CRUD-операций.
HTMX-эндпоинты для частичного обновления страниц.
WebSocket (опц., через Django Channels) — для real-time уведомлений в браузере.

Telegram-боты

7.1. Общие принципы

Два отдельных бота: @ и @.
Боты не привязаны к конкретному Telegram-аккаунту — авторизация происходит по токену, полученному в ЛК.
Поддержка нескольких инсталляций (серверов) в одном боте: пользователь может добавить dev, prod и другие серверы, переключаясь между ними.
Хранилище конфигурации бота — локальный JSON/SQLite на устройстве пользователя (бот работает как клиент).

7.2. Структура конфигурации бота
json
{
  "installations": [
    {
      "id": "prod",
      "name": "Продакшн",
      "url": "https://",
      "token": "abc...",
      "is_active": true
    },
    {
      "id": "dev",
      "name": "Разработка",
      "url": "http://localhost:8000",
      "token": "xyz...",
      "is_active": false
    }
  ]
}

7.3. Команды бота Бортжурнала

/start — приветствие, проверка наличия хотя бы одной инсталляции.
/servers — список серверов, переключение активного.
/addserver — добавить новый (URL + токен).
/removeserver — удалить сервер.
/vehicles — список авто, выбор активного.
/fuel — диалог добавления заправки (пошаговый мастер или быстрая запись).
/purchase — добавление покупки.
/service — добавление сервиса + фото.
/fine — добавление штрафа.
/insurance — список страховок.
/stats — краткая статистика.
/quick — быстрая запись: одно сообщение, бот парсит (например: «Заправил 40л 95го на Лукойле 2500р пробег 125000»).
/help — справка.

7.4. Команды бота Записной книжки

/start, /servers, /addserver, /removeserver — аналогично.
/scope — выбор скоупа (Личное / Рабочее).
/events — ближайшие события.
/tasks — список задач (по статусам).
/newtask — создание задачи (мастер).
/newevent — создание события.
/projects — список проектов.
/search  — поиск.
/quick — быстрая запись (например: «Завтра в 15:00 встреча в офисе #работа»).
/help — справка.

7.5. Inline-режим

Оба бота поддерживают inline-режим для быстрого поиска:
@vehicle_bot поиск:лукойл — список последних заправок на Лукойле.
@planner_bot задача:отчёт — поиск задач с таким названием.

7.6. NLP-парсинг (быстрая запись)

Этап 1 (MVP): парсинг по ключевым словам и регулярным выражениям.
Распознавание дат («завтра», «в понедельник», «15 августа»).
Распознавание чисел (суммы, объёмы, пробег).
Распознавание названий из справочников (марки АЗС, категории).

Этап 2 (будущее): интеграция с LLM для более точного разбора.

7.7. Голосовые сообщения

Отложено на этап 2. Плановая интеграция: OpenAI Whisper API.

Требования к безопасности

8.1. Аутентификация

Email + пароль: хэширование Argon2id, минимальная длина пароля — 10 символов.
Яндекс OAuth 2.0: подключение через django-allauth. Код подключения:
python
settings.py
INSTALLED_APPS = [
    ...
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.yandex',
]

SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

SOCIALACCOUNT_PROVIDERS = {
    'yandex': {
        'APP': {
            'clientid': os.environ.get('YANDEXOAUTHCLIENTID', ''),
            'secret': os.environ.get('YANDEXOAUTHSECRET', ''),
        },
        'SCOPE': ['login:email', 'login:info'],
    }
}

Обязательная верификация email
ACCOUNTEMAILREQUIRED = True
ACCOUNTEMAILVERIFICATION = "mandatory"
ACCOUNTLOGINONEMAILCONFIRMATION = True

2FA (TOTP): включено в первую версию. Реализация через django-otp + django-two-factor-auth. Трудозатраты — ~2 дня, значительное повышение безопасности.

8.2. Сессии и токены

Сессии хранятся в Redis, TTL — 7 дней (настраиваемо).
CSRF-токены на всех формах.
Bot-токены: 64-символьные случайные строки (secrets.token_urlsafe(48)). В БД хранится только SHA-256 хэш + соль. Оригинал показывается пользователю только один раз при создании.

8.3. Авторизация (права доступа)

Все view — под декоратором @login_required.
Глобальный middleware LoginRequiredMiddleware — редирект на /accounts/login/ для всех анонимных запросов.
В API — IsAuthenticated + фильтрация queryset по user_id (защита от IDOR).
Проверка принадлежности сущности пользователю на уровне сервиса, не только view.

8.4. Защита от атак

Rate limiting: django-ratelimit — 100 req/min на login, 300 req/min на API бота.
SQL-инъекции: только ORM, никаких raw SQL без параметризации.
XSS: шаблонизатор Django с авто-экранированием + Content-Security-Policy заголовки.
CORS: только для доменов из settings.ALLOWED_HOSTS.
File uploads:
  - Проверка MIME-типа по содержимому (не только по расширению).
  - Максимальный размер: 10 МБ на файл.
  - Имена файлов нормализуются (UUID + расширение).
  - Хранение — вне веб-доступа, выдача через presigned URLs.
HTTPS обязательно: HSTS, secure cookies, SECURESSLREDIRECT = True.
Secrets: только через .env + django-environ, никогда в коде.

8.5. Данные

Шифрование чувствительных полей (VIN, токены) на уровне приложения (Fernet).
Регулярные бэкапы PostgreSQL (pg_dump) + загрузка в S3.
Логирование всех входов и критичных действий в audit_log.
Soft delete — возможность восстановления данных.

8.6. Для публичного GitHub

Все секреты — только в .env.example с пустыми значениями.
.gitignore исключает .env, media/, *.sqlite3.
Pre-commit хуки для проверки на наличие секретов (detect-secrets).
GitHub Secrets для CI/CD.

Дизайн и UI

9.1. Общие принципы

Mobile-first: 80% трафика — с мобильных устройств.
Минимализм: чистый интерфейс, акцентные цвета — синий и зелёный.
Тёмная тема: задел реализован через CSS-переменные и класс dark на . Активация — на этапе 2.
Быстродействие: HTMX для точечных обновлений без перезагрузки страницы.
Доступность: соответствие WCAG 2.1 AA (контраст, навигация с клавиатуры, ARIA).

9.2. Цветовая палитра

| Элемент | Светлая тема | Тёмная тема |
|---|---|---|
| Фон | #F8FAFC | #0F172A |
| Карточки | #FFFFFF | #1E293B |
| Акцент 1 (Бортжурнал) | #2563EB | #3B82F6 |
| Акцент 2 (Записная книжка) | #10B981 | #34D399 |
| Текст основной | #0F172A | #F1F5F9 |
| Текст вторичный | #64748B | #94A3B8 |
| Успех | #10B981 | #34D399 |
| Предупреждение | #F59E0B | #FBBF24 |
| Ошибка | #EF4444 | #F87171 |

9.3. Структура страниц

/                              → редирект на /dashboard
/accounts/login/               → форма входа (email + Яндекс)
/accounts/register/            → регистрация
/accounts/verify-email//  → верификация email
/accounts/password/reset/      → восстановление пароля
/accounts/settings/            → профиль, настройки, 2FA
/accounts/tokens/              → управление токенами для ботов
/accounts/sessions/            → журнал входов

/dashboard/                    → главный дашборд

/vehicles/                     → список авто (карточки)
/vehicles//                → страница авто + вкладки:
    /vehicles//fuel/       → заправки
    /vehicles//purchases/  → покупки
    /vehicles//services/   → сервисы
    /vehicles//fines/      → штрафы
    /vehicles//insurance/  → страховки
    /vehicles//planned/    → плановые события
    /vehicles//stats/      → статистика

/planner/                      → выбор скоупа
/planner/personal/             → календарь + список событий
/planner/work/                 → Kanban-доска
/planner/projects/             → список проектов
/planner/search/               → глобальный поиск

/reports/                      → отчёты

9.4. Ключевые экраны

Дашборд:
Приветствие, текущая дата.
Две большие плитки: «Бортжурнал» и «Записная книжка».
В Бортжурнале: последнее авто, последние 3 события, расходы за месяц.
В Записной книжке: ближайшие 5 событий, количество открытых задач по статусам.
Блок уведомлений (истекающие страховки, неоплаченные штрафы, приближающиеся события).

Бортжурнал — страница авто:
Фото/иконка авто, основные характеристики.
Табы: Заправки | Покупки | Сервис | Штрафы | Страховки | План | Статистика.
FAB (floating action button) для быстрого добавления.

Записная книжка — Рабочий раздел:
Kanban-доска: 5 колонок по статусам.
Drag-n-drop карточек (SortableJS).
Фильтры по проекту, приоритету, тегам, дате.
Боковая панель с деталями задачи при клике.

Личный раздел:
Календарь (месяц/неделя) + список.
Цветовая маркировка по проектам.
Индикаторы повторяющихся событий.

9.5. Логотип и фирменный стиль

Будет сгенерирован отдельно. Предварительная концепция:
Минималистичный знак, сочетающий иконку автомобиля и блокнота.
Цвета: градиент синего (#2563EB → #3B82F6) и зелёного (#10B981 → #34D399).
Шрифт: Inter (основной), JetBrains Mono (для кода/цифр).

9.6. Иконки

Lucide Icons — согласованный набор SVG-иконок.

Локализация

10.1. Формат файлов локализации

Пользовательские файлы формата .lang (текстовый формат key=value), расположенные в locale/.lang.

Пример locale/ru_ru.lang:
Общие
app.name=Мои записи
app.tagline=Бортжурнал и записная книжка в одном месте

Аутентификация
auth.login=Войти
auth.register=Регистрация
auth.email=Email
auth.password=Пароль
auth.forgot_password=Забыли пароль?

Бортжурнал
vehicle.title=Бортжурнал
vehicle.add=Добавить автомобиль
vehicle.fuel=Заправки
vehicle.purchase=Покупки
...

10.2. Механизм загрузки

Собственный загрузчик, читающий .lang-файлы и кеширующий в Redis. API для использования в шаблонах и Python-коде:
python
from core.i18n import t

t('vehicle.title')  # → 'Бортжурнал'

В шаблонах:django
{% load i18n_lang %}
{% t 'vehicle.title' %}

10.3. Языки

По умолчанию: ru_ru.lang (русский).
Структура готова к добавлению других языков (enus.lang, dede.lang и т.п.).
Язык выбирается в настройках пользователя.

10.4. Требования к разработчикам

Все пользовательские тексты — только через t('key').
Запрещены хардкод-строки в шаблонах и views.
При добавлении новой функциональности — обязательно добавлять ключи в ru_ru.lang.

Отчёты и аналитика

11.1. Бортжурнал

Расходы по месяцам (bar chart).
Расходы по категориям (pie chart).
Расход топлива (л/100 км) в динамике (line chart).
Стоимость 1 км пробега.
Прогноз следующего ТО (на основе истории).
Топ-5 самых затратных статей.
Сводка по страховкам и штрафам.

11.2. Записная книжка (рабочий раздел)

Количество задач по статусам за период.
Среднее время нахождения в каждом статусе.
Выполнено vs просрочено.
Burndown-диаграмма по проекту.
Топ-5 самых долгих задач.
Производительность по неделям.

11.3. Экспорт

Excel (.xlsx): через библиотеку openpyxl.
PDF: через WeasyPrint (HTML → PDF) с фирменным стилем.
Экспорт доступен для всех отчётов и списков.

11.4. Библиотеки графиков

ApexCharts — красивые, адаптивные, с поддержкой тёмной темы.

Тестирование

12.1. Автотесты

Unit-тесты: покрытие бизнес-логики (сервисы, модели). Фреймворк — pytest + pytest-django.
Integration-тесты: тестирование API-эндпоинтов, взаимодействия с БД.
E2E-тесты: ключевые пользовательские сценарии через Playwright.
Целевое покрытие: ≥ 70% для бизнес-логики, 100% для критичных путей (аутентификация, платежи, токены).

12.2. Ручные тесты

Чек-листы для регрессионного тестирования.
Тестирование на мобильных устройствах (iOS Safari, Android Chrome).
Тестирование доступности (axe-core).

12.3. CI/CD

GitHub Actions: запуск тестов на каждый PR.
Линтеры: ruff (Python), eslint (JS), prettier.
Проверка миграций БД.
Проверка безопасности: safety, bandit.

Развёртывание и CI/CD

13.1. Docker-окружение

docker-compose.yml включает:
web — Django + gunicorn (3 воркера).
worker — Celery worker.
beat — Celery beat (периодические задачи: напоминания, бэкапы).
bot_vehicle — aiogram-бот бортжурнала.
bot_planner — aiogram-бот записной книжки.
db — PostgreSQL 16.
redis — Redis 7.
nginx — reverse proxy + TLS.
s3 — S3-хранилище SeaweedFS (опционально, можно использовать внешний S3-провайдер; MinIO заменён, т.к. его публичные образы удалены из реестров).

13.2. Переменные окружения (.env.example)
bash
Общие
DEBUG=False
SITEDOMAIN=
SECRET_KEY=
ALLOWED_HOSTS=

База данных
POSTGRES_DB=mynotes
POSTGRES_USER=mynotes
POSTGRES_PASSWORD=
POSTGRES_HOST=db
POSTGRES_PORT=5432

Redis
REDIS_URL=redis://redis:6379/0

S3
S3_ENDPOINT=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET=mynotes
S3_REGION=us-east-1

Email
EMAIL_HOST=
EMAIL_PORT=587
EMAILHOSTUSER=
EMAILHOSTPASSWORD=
DEFAULTFROMEMAIL=noreply@

Яндекс OAuth
YANDEXOAUTHCLIENT_ID=
YANDEXOAUTHSECRET=

Telegram-боты
TELEGRAMVEHICLEBOT_TOKEN=
TELEGRAMPLANNERBOT_TOKEN=

Sentry
SENTRY_DSN=

Безопасность
RATELIMITLOGIN=100/m
RATELIMITAPI=300/m

13.3. CI/CD (GitHub Actions)

Ветка main: авто-прогон тестов, линтеров, сборка Docker-образов.
Pull Request: прогон тестов, проверка покрытия.
Релизы: автоматическая сборка и публикация образов в GitHub Container Registry.
Деплой: опционально, через SSH на VPS (или вручную — docker-compose pull && docker-compose up -d).

13.4. Бэкапы

Ежедневный бэкап PostgreSQL (через Celery Beat).
Хранение: локально (7 дней) + S3 (30 дней).
Еженедельный бэкап S3 (медиа-файлы).

Требования к документации

14.1. Для пользователей

README.md: краткое описание, скриншоты, инструкции по развёртыванию.
INSTALL.md: пошаговая инструкция установки на VPS.
FAQ.md: часто задаваемые вопросы.

14.2. Для разработчиков

API-документация: автоматически генерируемая через drf-spectacular (Swagger UI + ReDoc).
ARCHITECTURE.md: описание архитектуры, диаграммы.
CONTRIBUTING.md: руководство для контрибьюторов.
DB_SCHEMA.md: описание структуры БД.
LOCALIZATION.md: как добавить новый язык.

14.3. Для сторонних разработчиков

Документация по механизму локализации (формат .lang, как добавить новый язык).
Документация по API ботов (для интеграции с другими клиентами).
Примеры кастомизации.

Этапы реализации

| Этап | Срок (оценка) | Результат |
|---|---|---|
| 1. Архитектура, БД, базовый auth | 1.5 недели | Регистрация, вход, верификация email, 2FA, профиль, токены, Яндекс OAuth |
| 2. Бортжурнал (веб) | 2 недели | Авто, заправки, покупки, сервисы, штрафы, страховки, фото |
| 3. Записная книжка (веб) | 2 недели | Личный календарь, рабочая Kanban, проекты, комментарии, теги, поиск |
| 4. Telegram-боты | 1.5 недели | Оба бота, мульти-серверность, быстрая запись, inline-режим |
| 5. Напоминания и уведомления | 1 неделя | Celery-задачи, email + Telegram уведомления |
| 6. Отчёты и экспорт | 1 неделя | Графики, Excel, PDF |
| 7. Безопасность, аудит, локализация | 1 неделя | Hardening, .lang-файлы, аудит-логи |
| 8. Тесты и CI/CD | 1 неделя | Автотесты, GitHub Actions, документация |
| 9. Деплой и релиз | 0.5 недели | Docker, README, публикация на GitHub |

Итого для MVP: ~11 недель.

15.1. Этап 2 (пост-MVP)

Тёмная тема.
Голосовые сообщения в ботах (Whisper).
Продвинутый NLP через LLM.
WebSocket для real-time уведомлений.
Мобильное приложение (PWA или React Native).

Приложения

16.1. Код подключения Яндекс OAuth

Предоставлен в разделе 8.1.

16.2. Полный список категорий покупок

См. раздел 4.2.3.

16.3. Полный список сетей АЗС

См. раздел 4.2.2.

16.4. Статусы рабочих задач

См. раздел 4.3.3.

16.5. Примеры .lang-файлов

См. раздел 10.1.

16.6. Лицензия MIT

MIT License

Copyright (c) 2026 MyNotes

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

