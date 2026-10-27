# Схема базы данных

Ниже описана схема, следующая из моделей и миграций репозитория, а не SQL-эскиз раздела 5 в [ТЗ](docs/TZ.md). Источники — `apps/*/models.py` и `apps/*/migrations/`; актуальные цепочки проекта завершаются, в частности, `accounts.0003`, `vehicles.0009`, `planner.0004`, `references.0002`, `notifications.0002`, `api.0001` и `search.0002`.

## Общие правила

- В собственных бизнес-моделях обычно UUID PK; исключения и встроенные таблицы Django описаны отдельно. PostgreSQL — backend из `config/settings/base.py`.
- Для основных моделей автомобиля и планировщика поля `user`, `created_at`, `updated_at`, `is_deleted` приходят из абстрактного `OwnedModel`. `OwnedModel.delete()` выполняет soft delete, а явный `hard_delete()` — физическое удаление.
- `OwnedModel` не является общей базой всех таблиц: у справочников, аккаунта, уведомлений, staging-загрузок, вложенных фотографий и истории статусов нет `is_deleted` по умолчанию.
- FK-поведение задаётся Django `on_delete`; проверки владения и исключение удалённых записей выполняются приложением. База не использует row-level security и не проверяет, что связанные FK принадлежат одному пользователю.
- Суммы представлены `DecimalField` и отдельным кодом валюты (обычно default `RUB`); отдельной таблицы валют нет. JSON-поля представлены Django `JSONField`; теги событий — PostgreSQL `ArrayField`.

## Аккаунты — `apps/accounts/models.py`

| Таблица | Модель и ключевые связи |
|---|---|
| `auth_user` | `accounts.User`: UUID, уникальный email, username/Yandex UID, профиль. Это пользовательская модель Django, назначенная через `AUTH_USER_MODEL`. |
| `user_settings` | `UserSettings.user` — OneToOne → `auth_user`, `CASCADE`; валюта, часовой пояс, язык и параметры напоминаний. |
| `auth_token` | `AuthToken.user` → `auth_user`, `CASCADE`; уникальный `token_hash`, срок действия, активность и сведения об использовании. |
| `auth_session_log` | `AuthSessionLog.user` → `auth_user`, `CASCADE`; IP, user-agent, провайдер и дата входа. |
| `audit_log` | `AuditLog.user` → `auth_user`, nullable `SET_NULL`; action, тип/ID сущности, старое/новое JSON-значение и контекст запроса. PK — UUID. |

TOTP-устройства и статические резервные коды реализуются моделями установленных `django_otp` приложений (`otp_totp`, `otp_static`), а не собственными моделями `apps/accounts`.

## Бортжурнал — `apps/vehicles/models.py`

Все перечисленные ниже модели, кроме `PurchaseCategory` и `ServicePhoto`, наследуют `vehicles.OwnedModel`; у них есть FK `user` → `auth_user` с `CASCADE`.

| Таблица | Модель и связи |
|---|---|
| `vehicle_vehicle` | `Vehicle`; `brand` → `ref_car_brand` и `model` → `ref_car_model`, оба nullable `SET_NULL`. VIN — `EncryptedCharField`; произвольные атрибуты — JSON. |
| `vehicle_fuel_entry` | `FuelEntry`; `vehicle` → `vehicle_vehicle`, `CASCADE`; `station` → `vehicle_fuel_station`, nullable `SET_NULL`. Даты, одометр, объём/цена/сумма, координаты и `receipt_photo`. |
| `vehicle_purchase_category` | `PurchaseCategory`; `user` → `auth_user`, nullable `CASCADE`; `NULL` используется для системных категорий. |
| `vehicle_purchase` | `Purchase`; `vehicle` → `vehicle_vehicle`, `CASCADE`; `category` → `vehicle_purchase_category`, nullable `SET_NULL`; состав покупки — JSON, фото — `ImageField`. |
| `vehicle_planned_event` | `PlannedEvent`; `vehicle` → `vehicle_vehicle`, `CASCADE`; `planner_event` → `planner_event`, nullable `SET_NULL`; дата, пробег, тип напоминания и `is_done`. |
| `vehicle_service` | `Service`; `vehicle` → `vehicle_vehicle`, `CASCADE`; `planned_event` → `vehicle_planned_event`, nullable `SET_NULL`; стоимость, работы и источник. |
| `vehicle_service_photo` | `ServicePhoto`; `service` → `vehicle_service`, `CASCADE`; изображение и порядок. Владелец определяется через Service, отдельного `user`/`is_deleted` нет. |
| `vehicle_fine` | `Fine`; `vehicle` → `vehicle_vehicle`, `CASCADE`; `purchase` → `vehicle_purchase`, nullable `SET_NULL`; статус, сумма и `link_purchase`. |
| `vehicle_insurance` | `Insurance`; `vehicle` → `vehicle_vehicle`, `CASCADE`; `renewed_by` → `vehicle_insurance`, nullable `SET_NULL`; сроки, стоимость и флаг созданного напоминания. |

Пользователь FK присутствует также в записях `FuelEntry`, `Purchase`, `Service`, `Fine`, `Insurance` и `PlannedEvent`, независимо от их FK на автомобиль. Сервисы и views должны связывать их с автомобилем того же пользователя.

## Справочники — `apps/references/models.py`

| Таблица | Модель и связи |
|---|---|
| `ref_car_brand` | `CarBrand`; уникальное имя, системный флаг; `created_by` → `auth_user`, nullable `SET_NULL`. |
| `ref_car_model` | `CarModel`; `brand` → `ref_car_brand`, `CASCADE`; уникальность пары `(brand, name)`; nullable `created_by` → пользователь, `SET_NULL`. |
| `vehicle_fuel_station` | `FuelStation`; справочник АЗС, координаты и `created_by` → пользователь, nullable `SET_NULL`. |

Связанные модели справочников и АЗС видны приложению по системному флагу или `created_by`; это не пользовательские бизнес-записи с soft delete.

## Планировщик — `apps/planner/models.py`

Модели `Scope`, `Project`, `Status`, `Event`, `EventAttachment` и `Comment` наследуют `planner.OwnedModel` и имеют FK `user` → `auth_user` (`CASCADE`).

| Таблица | Модель и связи |
|---|---|
| `planner_scope` | `Scope`; уникальность `(user, code)`; коды `personal` и `work`. |
| `planner_project` | `Project`; `scope` → `planner_scope`, `CASCADE`; название, цвет, описание и архивность. |
| `planner_status` | `Status`; пользовательские/system-строки; уникальность `(user, code)`. |
| `planner_event` | `Event`; `scope` → `planner_scope`, `CASCADE`; `project` → `planner_project` и `status` → `planner_status` nullable `SET_NULL`; `parent_event` → та же таблица, nullable `SET_NULL`. Содержит тип/приоритет, временные поля, массив тегов, повторение и настройки напоминаний. |
| `planner_event_attachment` | `EventAttachment`; `event` → `planner_event`, `CASCADE`; `comment` → `planner_comment`, nullable `CASCADE`; файл и его метаданные. Модель наследует `user` отдельно от FK события. |
| `planner_comment` | `Comment`; `event` → `planner_event`, `CASCADE`; есть `user` (владелец записи) и отдельный `author` → `auth_user`, оба `CASCADE`. |
| `planner_status_history` | `StatusHistory`; `event` → `planner_event`, `CASCADE`; `from_status`, `to_status` и `changed_by` nullable `SET_NULL`. Не наследует `OwnedModel`, собственных `user` и `is_deleted` нет. |

Проверки владения и soft-delete фильтры для планировщика сосредоточены в `apps/planner/services.py`. Связь `EventAttachment.comment` может быть пустой, но FK `event` обязателен.

## Уведомления и Bot API

| Таблица | Путь, модель и связи |
|---|---|
| `notification` | `apps/notifications/models.py`, `Notification.user` → `auth_user`, `CASCADE`; тип, текст, ссылка на сущность в виде пары type/UUID без FK, флаги прочтения и доставки. |
| `bot_chat_binding` | `BotChatBinding.user` → `auth_user`, `CASCADE`; уникальность `(user, bot)`, хранит последний chat ID для каждого из двух ботов. |
| `api_bot_upload` | `apps/api/models.py`, `BotUpload.user` → `auth_user`, `CASCADE`; временный файл до привязки к записи. Очистка старше 24 часов расписана в Celery Beat. |

## Поиск, отчёты и системные таблицы

`apps/search` не объявляет модель поискового индекса. Миграции `0001_trgm_search_indexes.py` и `0002_join_and_tags_indexes.py` включают PostgreSQL `pg_trgm` и GIN-индексы на текстовые поля/теги существующих таблиц. Поиск в `apps/planner/services.py` использует `icontains` и поиск по массиву тегов; в модели Event нет поля `search_vector`, а tsvector не описан как сохраняемая колонка. `apps/reports` вычисляет отчёты по доменным моделям, собственной таблицы отчётов нет.

Кроме таблиц выше миграции Django и сторонних приложений создают служебные таблицы, например `django_migrations`, группы/права Django, сессии, сайты, allauth и `django_otp`. Они управляются своими миграциями и не являются доменными моделями этого документа.

## Отличия схемы от SQL-эскиза ТЗ

- SQL в разделе 5 `docs/TZ.md` — план, а не источник актуальной схемы. В нём много имён таблиц без подчёркиваний/не совпадающих с реальными `db_table`: например, фактические `auth_user`, `vehicle_vehicle`, `vehicle_fuel_entry`, `planner_event`, `ref_car_brand`.
- ТЗ предполагает общие `created_at`, `updated_at`, `is_deleted` для всех таблиц. В коде эти поля наследуют только некоторые модели; например `Notification`, `AuthToken`, справочники, `ServicePhoto`, `StatusHistory` и `BotUpload` не имеют soft delete.
- ТЗ задаёт `BIGSERIAL` для `audit_log` и поля `old_value`/`new_value`; фактически `AuditLog` имеет UUID PK и JSONField-поля `old`/`new` (`apps/accounts/models.py`, `apps/accounts/migrations/0003_auditlog.py`). Аудит ограничен журналируемыми критичными действиями, а не является универсальным аудит-триггером каждой бизнес-таблицы.
- `Fine` имеет FK `purchase` и bool `link_purchase`; фото хранится как `ImageField`. У `Service` фотографии вынесены в `ServicePhoto`, а не в текстовые URL-поля SQL-эскиза.
- В `Event` теги — PostgreSQL-массив, правило повторения хранится строкой с дополнительными `recurrence_count` и self-FK `parent_event`; сохраняемого `TSVECTOR search_vector`, указанного в эскизе, нет. Поиск/индексы реализованы отдельно через `apps/search`.
- VIN сейчас — `EncryptedCharField(max_length=255)`; переход отражён миграциями `vehicles.0008`/`0009`. `Vehicle.engine_volume` — `DecimalField(4,1)`, изменённый `vehicles.0002`, а не integer.
- В моделях собственных приложений PK, включая `AuditLog`, в основном UUID, а не `BIGSERIAL`. Связи владения в основном дублируют FK на пользователя и FK на родительскую запись; согласованность пользователя между ними обеспечивается прикладным кодом, не ограничением БД.

Фактическое состояние развёрнутой БД этим документом не проверялось; оно зависит от применённых миграций. Ориентир для воспроизведения схемы — миграции в `apps/*/migrations/`.
